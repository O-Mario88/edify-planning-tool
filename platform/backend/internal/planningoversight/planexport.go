package planningoversight

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// exportRefusal is require_export_permission's refusal.
const exportRefusal = "Your role does not include data export."

var fourDigits = regexp.MustCompile(`^\d{4}$`)

// inProgressStatuses are _filter_export_items' "In progress only".
var inProgressStatuses = []string{"in_progress", "completion_started", "evidence_uploaded", "evidence_accepted"}

// PlanExportFile is team_planning_export_view ("team") or
// country_planning_export_view ("country"): the work the page shows, as My
// Plan's tables with each activity's Planned Activity ID, as
// <page>-planning-oversight-<fy>.xlsx, or the same sheets as one CSV.
// handled is false for an export Go does not choose the work of yet.
func (s *Service) PlanExportFile(page string) func(ctx context.Context, p auth.Principal, query url.Values) (string, []byte, bool, error) {
	return func(ctx context.Context, p auth.Principal, query url.Values) (string, []byte, bool, error) {
		door := rules.Doors[p.ActiveRole][page]
		if !door.ExportPage {
			return "", nil, true, pagegate.ErrNotAvailable
		}
		if !door.Export {
			return "", nil, true, workbook.Refusal(exportRefusal)
		}
		ids, fy, ok, err := s.exportedWork(ctx, p, page, query)
		if err != nil || !ok {
			return "", nil, ok, err
		}
		now := s.now()
		sheets, ported, err := myplan.TableSheets(ctx, s.db, p.Country, ids, myplan.ReadKindOrTab(query), now, true)
		if errors.Is(err, myplan.ErrUnported) {
			return "", nil, false, nil
		}
		if err != nil || !ported {
			return "", nil, ported, err
		}
		stem := page + "-planning-oversight-" + fy
		if !wantsExcel(query) {
			body, err := myplan.TablesCSV(sheets)
			return stem + ".csv", body, true, err
		}
		var buf bytes.Buffer
		if err := workbook.Write(&buf, sheets); err != nil {
			return "", nil, true, err
		}
		return stem + ".xlsx", buf.Bytes(), true, nil
	}
}

// wantsExcel is _wants_excel: format=xlsx or excel, or the Export options
// drawer's period fields; otherwise (format=csv, or nothing) the CSV.
func wantsExcel(q url.Values) bool {
	switch strings.ToLower(last(q, "format")) {
	case "csv":
		return false
	case "xlsx", "excel":
		return true
	}
	for _, key := range []string{"from_month", "to_month", "start_date", "end_date", "period_type"} {
		if q.Has(key) {
			return true
		}
	}
	return false
}

func last(q url.Values, key string) string {
	vs := q[key]
	if len(vs) == 0 {
		return ""
	}
	return strings.TrimSpace(vs[len(vs)-1])
}

// exportedWork is the activities the export view lists, in its order: the
// lens's items for the period, the tab or Lead asked for, the drawer's
// period, Plan Status and Activity Type (_filter_export_items).
func (s *Service) exportedWork(ctx context.Context, p auth.Principal, page string, q url.Values) ([]string, string, bool, error) {
	reader, ok := rules.TeamPlan.Readers[p.ActiveRole]
	if !ok || p.Acting != nil || p.InActingAppointment || reader.Scope == "region" || hasAdvancedFilter(q) {
		return nil, "", false, nil
	}
	if page == "team" && last(q, "team_member") != "" {
		return nil, "", false, nil
	}
	now := s.now()
	fy := last(q, "fy")
	if fy == "" {
		fy = schooldirectory.OperationalFY(now)
	}
	if !fourDigits.MatchString(fy) {
		return nil, "", false, nil
	}
	fyN, _ := strconv.Atoi(fy)
	start, lastDay, custom := myplan.DrawerPeriod(q, fyN)
	var years []string
	var read periodRead
	if custom {
		years = []string{schooldirectory.OperationalFY(start)}
		if y := schooldirectory.OperationalFY(lastDay); y != years[0] {
			years = append(years, y)
			sort.Strings(years)
		}
		read = periodRead{start: start, end: lastDay.AddDate(0, 0, 1)}
	} else {
		per, ok := partneroversight.ReadPeriod(q, now)
		if !ok {
			return nil, "", false, nil
		}
		var err error
		if years, _, read, err = s.planPeriod(ctx, p.Country, per, schooldirectory.FYOptions(now), now); err != nil {
			return nil, "", true, err
		}
	}
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	items, ok, err := s.exportItems(ctx, p, reader, page, q, years, read, today, now)
	if err != nil || !ok {
		return nil, "", ok, err
	}
	kind := myplan.ReadKindOrTab(q)
	online, err := s.onlineIDs(ctx, items, kind)
	if err != nil {
		return nil, "", true, err
	}
	status := strings.ToLower(last(q, "status"))
	ids := []string{}
	for _, it := range items {
		if custom && (it.plannedDate == nil || it.plannedDate.Before(start) || it.plannedDate.After(lastDay)) {
			continue
		}
		done := it.completed()
		switch status {
		case "completed":
			if !done {
				continue
			}
		case "scheduled":
			if done {
				continue
			}
		case "in_progress":
			if !slices.Contains(inProgressStatuses, it.status) {
				continue
			}
		}
		if !myplan.KeepsKind(kind, it.activityType, online[it.a.id]) {
			continue
		}
		ids = append(ids, it.a.id)
	}
	return ids, fy, true, nil
}

// hasAdvancedFilter is whether export_filters reads any filter: the
// drawer's kind of work and the Plan Status are the export's own.
func hasAdvancedFilter(q url.Values) bool {
	for _, key := range rules.TeamPlan.FilterKeys {
		v := last(q, key)
		switch {
		case v == "", key == "status", key == "activity_type" && myplan.IsExportKind(v):
		default:
			return true
		}
	}
	return false
}

// exportItems is build_items for the export's lens with every Partner's
// work kept, narrowed as the view narrows it: the team's owner tab, the
// country's Lead tab, or the Lead the country export asks for.
func (s *Service) exportItems(ctx context.Context, p auth.Principal, reader Reader, page string, q url.Values,
	years []string, read periodRead, today, now time.Time) ([]*item, bool, error) {
	if reader.Scope == "pl" {
		if page != "team" {
			return nil, false, nil
		}
		scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
		if err != nil {
			return nil, true, err
		}
		own, err := partneroversight.BothIDSpaces(ctx, s.db, []string{p.UserID, p.StaffProfileID})
		if err != nil {
			return nil, true, err
		}
		supervised, err := partneroversight.BothIDSpaces(ctx, s.db, scope.SupervisedStaffIDs)
		if err != nil {
			return nil, true, err
		}
		supervised = slices.DeleteFunc(supervised, func(id string) bool { return slices.Contains(own, id) })
		team := append(append([]string{}, own...), supervised...)
		if len(team) == 0 {
			return nil, false, nil
		}
		items, err := s.buildItemsKeeping(ctx, team, nil, years, read, today, true)
		if err != nil {
			return nil, true, err
		}
		members, err := s.members(ctx, supervised)
		if err != nil {
			return nil, true, err
		}
		_, owner := ownerTabs(members, last(q, "owner"))
		switch owner {
		case wholeTeamKey:
			return items, true, nil
		case myWorkKey:
			return ownedBy(items, own), true, nil
		}
		for _, m := range members {
			if m.id == owner {
				return ownedBy(items, m.ids), true, nil
			}
		}
		return nil, false, nil
	}
	items, err := s.buildItemsKeeping(ctx, nil, nil, years, read, today, true)
	if err != nil {
		return nil, true, err
	}
	if err := s.stampLeads(ctx, items); err != nil {
		return nil, true, err
	}
	lead := last(q, "program_lead")
	if lead == "" || lead == "all" {
		return items, true, nil
	}
	if page == "country" {
		// build_items(program_lead_id=): the items whose Lead is that one,
		// under either id.
		ids, err := partneroversight.BothIDSpaces(ctx, s.db, []string{lead})
		if err != nil {
			return nil, true, err
		}
		return slices.DeleteFunc(items, func(it *item) bool { return it.lead == "" || !slices.Contains(ids, it.lead) }), true, nil
	}
	leads, err := partneroversight.SystemProgramLeads(ctx, s.db)
	if err != nil {
		return nil, true, err
	}
	tabs, filed := leadTabs(leads, items)
	if len(tabs) == 0 {
		return nil, false, nil
	}
	key := tabs[0].Key
	for _, t := range tabs {
		if t.Key == lead {
			key = lead
		}
	}
	return filed[key], true, nil
}

// onlineIDs is export_kinds.online_activity_ids, read only for the online
// kind.
func (s *Service) onlineIDs(ctx context.Context, items []*item, kind string) (map[string]bool, error) {
	out := map[string]bool{}
	if kind != "online" || len(items) == 0 {
		return out, nil
	}
	ids := make([]string, 0, len(items))
	for _, it := range items {
		ids = append(ids, it.a.id)
	}
	r := rules.TeamPlan.Items
	rows, err := s.db.Query(ctx, `SELECT id FROM activity WHERE id = ANY($1) AND activity_type = ANY($2) AND programme_delivery_mode = $3`,
		ids, r.OnlineTrainingTypes, r.Online)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the online trainings: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		out[id] = true
	}
	return out, rows.Err()
}
