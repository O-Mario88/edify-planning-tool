package planningmonitor

import (
	"context"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// The Execution & Completion tab as a workbook (country_execution_views
// .export_view): one row per level, per Partner, per activity (not for a
// reader who sees the country's figures only) and per follow-up.

var cexPartnerHeaders = []string{"Partner", "Assigned", "Scheduled", "Started", "Evidence submitted", "Verified",
	"Awaiting verification", "Paid", "Awaiting payment", "Overdue", "Returned by IA", "Assigned, unscheduled", "Schools served"}

var cexActivityHeaders = []string{"Activity", "School ID", "School / cluster", "Owner", "Programme Lead", "Channel", "Partner",
	"Due", "Stage", "Overdue stage", "Days overdue", "Waiting on", "Last action"}

var cexFollowUpHeaders = []string{"Sent", "Programme Lead", "CCEO", "Partner", "Issue", "Status", "Open when sent", "Open now",
	"Due", "Priority"}

// CountryExecutionExport is the workbook export at /country-planning-oversight/execution/export.
func CountryExecutionExport(db schooldirectory.Querier, now func() time.Time) func(context.Context, auth.Principal, url.Values) (string, []workbook.Sheet, bool, error) {
	return func(ctx context.Context, p auth.Principal, query url.Values) (string, []workbook.Sheet, bool, error) {
		return cexExport(ctx, db, p, query, now())
	}
}

func dayCell(t *time.Time) workbook.Cell {
	if t == nil {
		return workbook.Empty()
	}
	return workbook.Date(*t)
}

func cexExport(ctx context.Context, db schooldirectory.Querier, p auth.Principal, query url.Values, now time.Time) (string, []workbook.Sheet, bool, error) {
	if !pageaccess.CanOpen(p.ActiveRole, false, cexBase+"/export") {
		return "", nil, true, pagegate.ErrNotAvailable
	}
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return "", nil, true, err
	}
	q := map[string]string{}
	for k, v := range query {
		if len(v) > 0 {
			q[k] = v[len(v)-1]
		}
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	f := cexReadFilters(q, today)
	s, err := buildCEXSnapshot(ctx, db, scope, f, today)
	if err != nil {
		return "", nil, true, err
	}
	reminders, err := cexOpenCounts(ctx, db, f.fy)
	if err != nil {
		return "", nil, true, err
	}
	country := strings.TrimSpace(scope.Country)
	if country == "" || country == schooldirectory.NoCountry {
		country = "Country"
	}
	txt, num := workbook.Text, func(n int) workbook.Cell { return workbook.Int(int64(n)) }
	figures := func(c cexCells) []workbook.Cell {
		onTime := txt("")
		if c.onTime != nil {
			onTime = txt(fmt.Sprintf("%d%%", *c.onTime))
		}
		remaining := txt("")
		if c.remaining != nil {
			remaining = num(*c.remaining)
		}
		return []workbook.Cell{num(c.due), num(c.inProgress), num(c.complete), onTime, num(c.overdue), num(c.carried),
			num(c.returned), remaining, txt(c.forecast.label), num(c.reminders)}
	}
	hierarchy := [][]workbook.Cell{append([]workbook.Cell{txt("Country"), txt(country), txt("")},
		figures(s.cells(s.tree.country, s.remainingOf("country", ""), reminders[[2]string{"country", ""}], false))...)}
	for _, lead := range s.tree.leads {
		hierarchy = append(hierarchy, append([]workbook.Cell{txt("Programme Lead"), txt(lead.name), txt("")},
			figures(s.cells(lead.tally, s.remainingOf("lead", lead.key), reminders[[2]string{"lead", lead.key}], !lead.noLead))...))
		for _, o := range lead.owners {
			level := "CCEO"
			if o.kind == "pl_personal" {
				level = "PL personal"
			}
			hierarchy = append(hierarchy, append([]workbook.Cell{txt(level), txt(o.name), txt(lead.name)},
				figures(s.cells(o.tally, s.remainingOf("owner", o.key), reminders[[2]string{"owner", o.key}], !lead.noLead))...))
		}
	}
	partners, err := s.partnerRows(ctx, db)
	if err != nil {
		return "", nil, true, err
	}
	partnerRows := [][]workbook.Cell{}
	for _, r := range partners {
		partnerRows = append(partnerRows, []workbook.Cell{txt(r.name), num(r.assigned), num(r.due), num(r.started), num(r.executed),
			num(r.verified), num(r.awaiting), num(r.paid), num(r.unpaid), num(r.late), num(r.returned), num(r.unscheduled), num(r.schools)})
	}
	sheets := []workbook.Sheet{
		{Title: "Hierarchy (one row per level)", Headers: append([]string{"Level", "Name", "Programme Lead"}, rules.CountryExecution.Page.TableColumns...), Rows: hierarchy},
		{Title: "Partners (one row each)", Headers: cexPartnerHeaders, Rows: partnerRows},
	}
	if !scope.SummaryOnly {
		rows, err := s.activityExportRows(ctx, db)
		if err != nil {
			return "", nil, true, err
		}
		sheets = append(sheets, workbook.Sheet{Title: "Activities (one row each)", Headers: cexActivityHeaders, Rows: rows})
	}
	followUps, err := cexFollowUpRows(ctx, db, f.fy)
	if err != nil {
		return "", nil, true, err
	}
	sheets = append(sheets, workbook.Sheet{Title: "Follow-ups (one row each)", Headers: cexFollowUpHeaders, Rows: followUps})
	return "country-execution-" + f.fy + "-" + today.Format(time.DateOnly), sheets, true, nil
}

// activityExportRows is _describe over filtered_records: each activity's
// type, school or cluster, owner, Lead, channel and Partner, its due day,
// stage, overdue stage, days overdue, whom it waits on and its last action.
func (s *cexSnapshot) activityExportRows(ctx context.Context, db schooldirectory.Querier) ([][]workbook.Cell, error) {
	records := s.records()
	schoolIDs, clusterIDs := []string{}, []string{}
	for _, r := range records {
		schoolIDs = append(schoolIDs, r.schoolID)
		clusterIDs = append(clusterIDs, r.clusterID)
	}
	names, codes := map[string]string{}, map[string]string{}
	rs, err := db.Query(ctx, `SELECT id, COALESCE(name, ''), COALESCE(school_id, '') FROM school WHERE id = ANY($1)`, schoolIDs)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the activities' schools: %w", err)
	}
	for rs.Next() {
		var id, name, code string
		if err := rs.Scan(&id, &name, &code); err != nil {
			rs.Close()
			return nil, err
		}
		names[id], codes[id] = name, code
	}
	rs.Close()
	clusters, err := cpoNames(ctx, db, "cluster", clusterIDs)
	if err != nil {
		return nil, err
	}
	clusterName := map[string]string{}
	for _, o := range clusters {
		clusterName[o.value] = o.label
	}
	st := rules.CountryExecution.Stages
	stageLabel, ownerLabel := map[string]string{}, map[string]string{}
	for _, p := range st.StageLabels {
		stageLabel[p[0]] = p[1]
	}
	for _, p := range st.OwnerLabels {
		ownerLabel[p[0]] = p[1]
	}
	txt := workbook.Text
	out := [][]workbook.Cell{}
	for _, r := range records {
		kind := rules.CountryOversight.Page.TableWords.Types[r.activityType]
		if kind == "" {
			kind = pyTitleWords(strings.ReplaceAll(r.activityType, "_", " "))
		}
		where := orElse(orElse(names[r.schoolID], clusterName[r.clusterID]), "—")
		owner, lead := rules.CountryOversight.NoOwner[1], rules.CountryOversight.NoLead[1]
		if o := s.data.owners[r.ownerKey]; o != nil {
			owner, lead = o.name, o.leadName
		}
		channel, partner := "Staff", ""
		if r.channel == "partner" {
			channel, partner = "Partner", s.data.partnerName[r.partnerKey]
		}
		stage, ok := stageLabel[r.stage]
		if !ok {
			stage = r.stage
		}
		out = append(out, []workbook.Cell{txt(kind), txt(codes[r.schoolID]), txt(where), txt(owner), txt(lead), txt(channel),
			txt(partner), dayCell(r.due), txt(stage), txt(st.OverdueLabels[r.overdue]), workbook.Int(int64(r.age)),
			txt(ownerLabel[r.owner]), dayCell(r.lastAction)})
	}
	return out, nil
}

// cexFollowUpRows are the year's execution follow-ups, newest first.
func cexFollowUpRows(ctx context.Context, db schooldirectory.Querier, fy string) ([][]workbook.Cell, error) {
	page := rules.CountryOversight.Page
	rs, err := db.Query(ctx, `SELECT assigned_at, COALESCE(program_lead_name, ''), COALESCE(cceo_name, ''), COALESCE(partner_name, ''),
  COALESCE(issue_type, ''), COALESCE(status, ''), remaining_value, live_remaining, due_date, COALESCE(priority, '')
FROM planning_oversight_follow_up WHERE fy = $1 AND module = 'execution' ORDER BY assigned_at DESC`, fy)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the execution follow-ups: %w", err)
	}
	defer rs.Close()
	txt := workbook.Text
	out := [][]workbook.Cell{}
	for rs.Next() {
		var sent, due time.Time
		var lead, cceo, partner, issue, status, priority string
		var remaining, live *int64
		if err := rs.Scan(&sent, &lead, &cceo, &partner, &issue, &status, &remaining, &live, &due, &priority); err != nil {
			return nil, err
		}
		label, ok := page.FollowUpIssueLabels[issue]
		if !ok {
			label = issue
		}
		local := sent.In(cpoLocation)
		sentDay := date(local.Year(), local.Month(), local.Day())
		open, now := workbook.Empty(), txt("")
		if remaining != nil {
			open = workbook.Int(*remaining)
		}
		if live != nil {
			now = workbook.Int(*live)
		}
		out = append(out, []workbook.Cell{workbook.Date(sentDay), txt(lead), txt(cceo), txt(partner), txt(label),
			txt(orElse(page.FollowUpStatusLabels[status], status)), open, now, workbook.Date(due),
			txt(orElse(page.FollowUpPriorityLabels[priority], priority))})
	}
	return out, rs.Err()
}
