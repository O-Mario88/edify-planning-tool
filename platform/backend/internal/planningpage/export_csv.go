package planningpage

import (
	"bytes"
	"context"
	"encoding/csv"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// The Planning page's CSV (planning_views.planning_view, export=csv): the
// filtered list, every page of it, with its planning readiness, its
// recommended action and, where the support rule is on, who is responsible
// and both planning indicators.

const (
	csvExportName  = "planning_export.csv"
	csvExportLimit = 5000
)

var csvHeader = []string{"School ID", "Name", "District", "Type", "SSA Status", "Weakest Intervention", "Planning Readiness",
	"Recommended Action", "Owner"}

var csvSupportHeader = []string{"Responsible", "Partner Workflow", "Visit Status", "Training Status"}

// csvSchool is what the CSV reads of a school beside the page's row.
type csvSchool struct {
	subCounty, ssaState string
	scheduled           bool
	assignment          string // the newest live hand-over's status, or "" for none
	hasAssignment       bool
	latestScore         *float64
	hasLatest           bool
	weakest             string
}

// ExportCSV answers the Planning page's export=csv. handled is false for a
// query Go does not take.
func (s *Service) ExportCSV(ctx context.Context, p auth.Principal, query url.Values) (string, []byte, bool, error) {
	if strings.TrimSpace(query.Get("export")) != "csv" {
		return "", nil, false, nil
	}
	doors, ok := rules.Doors[p.ActiveRole]
	if !ok || !doors.Page {
		return "", nil, true, pagegate.ErrNotAvailable
	}
	// require_export_permission, inside the page's own door.
	if !rbac.Grants(p.ActiveRole, "data.export") {
		return "", nil, true, workbook.Refusal("Your role does not include data export.")
	}
	if query.Get("priority_allocation") != "" {
		return "", nil, false, nil
	}
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return "", nil, true, err
	}
	operational := schooldirectory.OperationalFY(now)
	f, readable := readFilters(query, operational, scope.CountryScope, now)
	if !readable || !in([]string{"client", "core", "partner", "scheduled"}, f.tab) {
		return "", nil, false, nil
	}
	f.page, f.perPage = 1, csvExportLimit
	support := clusterpage.SupportRuleOn(p)
	owners := []string{}
	for _, id := range []string{p.UserID, p.StaffProfileID} {
		if id != "" {
			owners = append(owners, id)
		}
	}
	list, err := s.csvSchools(ctx, p.Country, scope, f, owners, support, operational, now)
	if err != nil {
		return "", nil, true, err
	}
	facts, err := s.csvFacts(ctx, list, f.dataFY, operational)
	if err != nil {
		return "", nil, true, err
	}
	var hasCatalogue bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM cost_catalogue WHERE country = $1 AND kind = $2 AND status = $3 AND is_active)`,
		registry.SettingsName(p.Country, rules.Catalogue.Country), rules.Catalogue.Kind, rules.Catalogue.Status).Scan(&hasCatalogue); err != nil {
		return "", nil, true, fmt.Errorf("planningpage: reading the cost catalogue: %w", err)
	}
	var responsible map[string]responsibility
	if support {
		if responsible, err = s.responsibilities(ctx, list, f.dataFY); err != nil {
			return "", nil, true, err
		}
	}
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	w.UseCRLF = true
	header := slices.Clone(csvHeader)
	if support {
		header = append(header, csvSupportHeader...)
	}
	write := func(values []string) error {
		cells := make([]workbook.Cell, len(values))
		for i, v := range values {
			cells[i] = workbook.Text(v)
		}
		return w.Write(workbook.SafeCSVRow(cells))
	}
	if err := write(header); err != nil {
		return "", nil, true, err
	}
	labels := rules.CSVExport
	for _, sc := range list {
		x := facts[sc.ID]
		district := "—"
		if sc.HasDistrictRow {
			district = sc.District
		}
		readiness, action := planningReadiness(sc, x, hasCatalogue)
		typeLabel, ok := labels.SchoolTypeLabels[sc.Type]
		if !ok {
			typeLabel = sc.Type
		}
		row := []string{sc.Code, sc.Name, district, typeLabel, x.ssaState, x.weakest, readiness, action, sc.ownerName}
		if r, ok := responsible[sc.ID]; ok && support {
			row = append(row, r.display(), r.workflow(), chipText(sc.badges.VisitChips()),
				chipText(sc.badges.TrainingChips(), sc.badges.ClusterMeetingChips()))
		}
		if err := write(row); err != nil {
			return "", nil, true, err
		}
	}
	w.Flush()
	return csvExportName, buf.Bytes(), true, w.Error()
}

// chipText is the CSV's join of a row's chips: their labels by " · ".
func chipText(lists ...[]schoolplanning.Chip) string {
	parts := []string{}
	for _, list := range lists {
		for _, c := range list {
			parts = append(parts, c.Label)
		}
	}
	return strings.Join(parts, " · ")
}

// csvSchools is the page's filtered schools in its order, every page.
func (s *Service) csvSchools(ctx context.Context, place *registry.Work, scope schooldirectory.Scope, f filterState, owners []string,
	support bool, operational string, now time.Time) ([]school, error) {
	b := &sqlb{}
	where := filtered(b, scope, f, owners, support) + " AND " + tableCondition(b, f, support)
	order := "s.name"
	if f.group == "owner" {
		args := slices.Clone(b.args)
		ids, err := distinctOwners(ctx, s.db, where, args)
		if err != nil {
			return nil, err
		}
		directory, err := ownerDirectory(ctx, s.db, ids)
		if err != nil {
			return nil, err
		}
		ranked := slices.Clone(ids)
		key := func(id string) [2]string {
			if o := directory[id]; o != nil {
				return o.sortKey()
			}
			return [2]string{"￿", "￿"}
		}
		slices.SortStableFunc(ranked, func(a, c string) int {
			ka, kc := key(a), key(c)
			if n := strings.Compare(ka[0], kc[0]); n != 0 {
				return n
			}
			return strings.Compare(ka[1], kc[1])
		})
		order = fmt.Sprintf("COALESCE(array_position(%s::varchar[], s.account_owner_id) - 1, %d), s.name", b.arg(ranked), len(ranked))
	}
	ids := []string{}
	if err := each(ctx, s.db, "the export's schools", fmt.Sprintf("SELECT s.id FROM school s WHERE %s ORDER BY %s LIMIT %d",
		where, order, f.perPage), func(rows pgx.Rows) error {
		var id string
		if err := rows.Scan(&id); err != nil {
			return err
		}
		ids = append(ids, id)
		return nil
	}, b.args...); err != nil {
		return nil, err
	}
	list, at, err := readSchools(ctx, s.db, ids)
	if err != nil {
		return nil, err
	}
	horizon, err := schoolplanning.Horizon(ctx, s.db, place, f.dataFY, atoi(operational), schooldirectory.FYOptions(now), now)
	if err != nil {
		return nil, err
	}
	return list, enrich(ctx, s.db, list, at, f.dataFY, operational, horizon, support, now)
}

// csvFacts reads what the CSV's readiness and SSA columns rest on.
func (s *Service) csvFacts(ctx context.Context, list []school, fy, operational string) (map[string]*csvSchool, error) {
	ids := make([]string, 0, len(list))
	out := map[string]*csvSchool{}
	for _, sc := range list {
		ids = append(ids, sc.ID)
		out[sc.ID] = &csvSchool{weakest: "—"}
	}
	if err := each(ctx, s.db, "the schools' readiness facts", `SELECT s.id, COALESCE(s.sub_county_id, ''),
  EXISTS (SELECT 1 FROM activity a WHERE a.school_id = s.id AND a.deleted_at IS NULL AND a.fy = $2
    AND NOT COALESCE(a.status = ANY($3), false)),
  r.id IS NOT NULL, COALESCE(r.verification_status, ''), COALESCE(r.fy, ''),
  c.id IS NOT NULL, COALESCE(c.delivery_type, ''), COALESCE(c.activity_type, '')
FROM school s
LEFT JOIN LATERAL (SELECT id, verification_status, fy FROM ssa_record WHERE school_id = s.id AND deleted_at IS NULL
  ORDER BY date_of_ssa DESC LIMIT 1) r ON true
LEFT JOIN LATERAL (SELECT id, delivery_type, activity_type FROM activity WHERE school_id = s.id AND deleted_at IS NULL
  AND ssa_collection_expected AND NOT COALESCE(status = ANY($4), false) ORDER BY scheduled_date LIMIT 1) c ON true
WHERE s.id = ANY($1)`, func(rows pgx.Rows) error {
		var id, verification, recordFY, delivery, kind string
		var hasRecord, hasCollection bool
		x := &csvSchool{weakest: "—"}
		if err := rows.Scan(&id, &x.subCounty, &x.scheduled, &hasRecord, &verification, &recordFY, &hasCollection, &delivery, &kind); err != nil {
			return err
		}
		x.ssaState = ssaReadiness(hasRecord, verification, recordFY, operational, hasCollection, delivery, kind)
		out[id] = x
		return nil
	}, ids, fy, rules.NotScheduledStatuses, rules.CSVExport.SSACollectionDone); err != nil {
		return nil, err
	}
	// The newest hand-over not given back to staff (assignment_map).
	if err := each(ctx, s.db, "the schools' hand-overs", `SELECT DISTINCT ON (school_id) school_id, COALESCE(status, '')
FROM partner_assignment WHERE school_id = ANY($1) AND status IS DISTINCT FROM 'returned_to_staff'
ORDER BY school_id, created_at DESC, id DESC`, func(rows pgx.Rows) error {
		var id, status string
		if err := rows.Scan(&id, &status); err != nil {
			return err
		}
		out[id].assignment, out[id].hasAssignment = status, true
		return nil
	}, ids); err != nil {
		return nil, err
	}
	// latest_applicable_record: the newest confirmed record, its average or
	// its scores' mean, or 0.
	if err := each(ctx, s.db, "the schools' latest SSA", `SELECT DISTINCT ON (r.school_id) r.school_id,
  COALESCE(r.average_score, (SELECT AVG(sc.score) FROM ssa_score sc WHERE sc.ssa_record_id = r.id), 0)::float8
FROM ssa_record r WHERE r.school_id = ANY($1) AND r.deleted_at IS NULL AND r.verification_status = 'confirmed'
ORDER BY r.school_id, r.date_of_ssa DESC, r.created_at DESC`, func(rows pgx.Rows) error {
		var id string
		var score float64
		if err := rows.Scan(&id, &score); err != nil {
			return err
		}
		out[id].latestScore, out[id].hasLatest = &score, true
		return nil
	}, ids); err != nil {
		return nil, err
	}
	// The weakest intervention of the year's latest confirmed record.
	if err := each(ctx, s.db, "the schools' weakest intervention", `SELECT DISTINCT ON (r.school_id) r.school_id, sc.intervention
FROM ssa_record r JOIN ssa_score sc ON sc.ssa_record_id = r.id
WHERE r.school_id = ANY($1) AND r.fy = $2 AND r.verification_status = 'confirmed' AND r.deleted_at IS NULL
  AND r.id = (SELECT r2.id FROM ssa_record r2 WHERE r2.school_id = r.school_id AND r2.fy = $2
    AND r2.verification_status = 'confirmed' AND r2.deleted_at IS NULL ORDER BY r2.date_of_ssa DESC LIMIT 1)
ORDER BY r.school_id, sc.score, sc.id`, func(rows pgx.Rows) error {
		var id, code string
		if err := rows.Scan(&id, &code); err != nil {
			return err
		}
		label, ok := rules.CSVExport.InterventionLabels[code]
		if !ok {
			label = code
		}
		out[id].weakest = label
		return nil
	}, ids, fy); err != nil {
		return nil, err
	}
	return out, nil
}

// planningReadiness is PlanningReadinessService.get_school_readiness and
// PlanningRecommendationService.get_recommendation: the readiness and the
// recommended action.
func planningReadiness(sc school, x *csvSchool, hasCatalogue bool) (string, string) {
	if sc.ClusterID == "" {
		return "Cluster Required", "Add to Cluster"
	}
	blocked := []string{}
	if sc.DistrictID == "" {
		blocked = append(blocked, "District")
	}
	if x.subCounty == "" {
		blocked = append(blocked, "Sub-county")
	}
	if sc.OwnerID == "" {
		blocked = append(blocked, "Responsible staff")
	}
	if sc.Code == "" {
		blocked = append(blocked, "School ID")
	}
	switch {
	case len(blocked) > 0:
		return "Data Cleanup Required", "Complete operational details: " + strings.Join(blocked, ", ") + "."
	case !hasCatalogue:
		return "Cost Catalogue Required", "Ask CD/Admin to activate Cost Catalogue"
	case x.scheduled:
		return "In My Plan", "Open My Plan"
	case x.hasAssignment && x.assignment == "partner_scheduled":
		return "In My Plan", "Open My Plan"
	case x.hasAssignment && in(rules.PartnerPendingStatuses, x.assignment):
		return "Partner Pending Schedule", "Monitor Partner Scheduling"
	case !x.hasLatest:
		return "SSA Required", "Complete SSA"
	}
	switch score := *x.latestScore; {
	case score < 5:
		return "Ready for Support", "Recommend Partner (In-school coaching)"
	case score < 8:
		return "Ready for Support", "Recommend Staff (Visit/training support)"
	}
	return "Ready for Support", "Maintain/consider champion pathway"
}

// ssaReadiness is School.ssa_readiness_state (models.readiness_from): a
// collection still to come first, else where the latest record stands.
func ssaReadiness(hasRecord bool, verification, recordFY, operational string, hasCollection bool, delivery, kind string) string {
	if hasCollection {
		switch {
		case delivery == "partner":
			return "Partner Collection Pending"
		case kind == "school_visit_ssa_collection":
			return "Collected During Visit"
		case kind == "cluster_training_ssa_collection":
			return "Collected During Training"
		case kind == "cluster_meeting_ssa_review":
			return "Collected During Cluster Activity"
		}
		return "Scheduled for Collection"
	}
	switch {
	case !hasRecord:
		return "No SSA"
	case verification == "pending":
		return "Pending IA Verification"
	case verification == "returned":
		return "Returned for Correction"
	case verification == "confirmed" && recordFY != operational:
		return "Expired / Needs Refresh"
	case verification == "confirmed":
		return "Verified"
	}
	return "No SSA"
}
