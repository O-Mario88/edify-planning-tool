package planningpage

import (
	"context"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
)

// sqlb gathers a statement's numbered arguments.
type sqlb struct{ args []any }

func (b *sqlb) arg(v any) string {
	b.args = append(b.args, v)
	return fmt.Sprintf("$%d", len(b.args))
}

// filterState is the page's query as the view reads it (each value as
// given, its defaults filled).
type filterState struct {
	fy, quarter, district, subCounty, staff, schoolType, readiness, ssaStatus string
	clusterStatus, partner, support, q, tab, group                            string
	page, perPage                                                             int
	// dataFY is the year the service reads ("fy" or the operational year).
	dataFY string
}

// quarterOf is core.fy.get_quarter_for_date for a day.
func quarterOf(day time.Time) string {
	switch m := day.Month(); {
	case m >= time.October:
		return "Q1"
	case m <= time.March:
		return "Q2"
	case m <= time.June:
		return "Q3"
	}
	return "Q4"
}

// readFilters is planning_dashboard_view's filters; ok is false where the
// view would fail (a page or page size that is not a number).
func readFilters(query url.Values, operational string, countryScope bool, now time.Time) (filterState, bool) {
	get := func(key, fallback string) string {
		if values, ok := query[key]; ok && len(values) > 0 {
			return values[len(values)-1]
		}
		return fallback
	}
	local := now.In(schoolplanning.Nairobi)
	f := filterState{
		fy:            get("fy", operational),
		quarter:       get("quarter", quarterOf(local)),
		district:      get("district", "All"),
		subCounty:     get("sub_county", "All"),
		staff:         get("staff", "All"),
		schoolType:    get("school_type", "All"),
		readiness:     get("planning_readiness", "All"),
		ssaStatus:     get("ssa_status", "All"),
		clusterStatus: get("cluster_status", "All"),
		partner:       get("partner", "All"),
		q:             get("q", ""),
		tab:           get("tab", "client"),
	}
	f.support = strings.TrimSpace(get("support", "all"))
	if f.support == "" {
		f.support = "all"
	}
	known := false
	for _, pair := range rules.SupportFilters {
		known = known || pair[0] == f.support
	}
	if !known {
		f.support = "all"
	}
	group, given := query["group"]
	switch {
	case !given:
		f.group = "name"
		if countryScope {
			f.group = "owner"
		}
	case len(group) > 0 && group[len(group)-1] == "owner":
		f.group = "owner"
	default:
		f.group = "name"
	}
	var err1, err2 error
	f.page, err1 = strconv.Atoi(strings.TrimSpace(get("page", "1")))
	f.perPage, err2 = strconv.Atoi(strings.TrimSpace(get("per_page", "15")))
	f.dataFY = f.fy
	if f.dataFY == "" {
		f.dataFY = operational
	}
	return f, err1 == nil && err2 == nil && f.page >= 1 && f.perPage >= 1
}

func set(value string) bool { return value != "" && value != "All" }

// filtered is get_dashboard_data's schools_qs: the direct portfolio and the
// page's filters, over the schools aliased s.
func filtered(b *sqlb, scope schooldirectory.Scope, f filterState, owners []string, support bool) string {
	parts := []string{schooldirectory.DirectPortfolio(scope, b.arg)}
	if set(f.district) {
		parts = append(parts, "s.district_id = "+b.arg(f.district))
	}
	if set(f.subCounty) {
		parts = append(parts, "s.sub_county_id = "+b.arg(f.subCounty))
	}
	if set(f.staff) {
		// owner_id_variants: the chosen id and the other id space's.
		v := b.arg(f.staff) + "::varchar"
		parts = append(parts, fmt.Sprintf(`s.account_owner_id IN (SELECT %[1]s UNION SELECT id FROM staff_profile
  WHERE deleted_at IS NULL AND (id = %[1]s OR user_id = %[1]s)
  UNION SELECT user_id FROM staff_profile WHERE deleted_at IS NULL AND user_id IS NOT NULL AND (id = %[1]s OR user_id = %[1]s))`, v))
	}
	if set(f.schoolType) {
		parts = append(parts, "s.school_type = "+b.arg(f.schoolType))
	}
	switch {
	case f.readiness == "data_cleanup_required":
		parts = append(parts, "s.cluster_id IS NOT NULL AND s.cluster_id <> '' AND "+schooldirectory.PlanningBlockers())
	case set(f.readiness):
		parts = append(parts, "s.planning_readiness = "+b.arg(f.readiness))
	}
	switch {
	case f.ssaStatus == "not_done":
		parts = append(parts, schooldirectory.NoSSA(f.dataFY, b.arg))
	case f.ssaStatus == "done":
		parts = append(parts, "NOT "+schooldirectory.NoSSA(f.dataFY, b.arg))
	case set(f.ssaStatus):
		parts = append(parts, "s.current_fy_ssa_status = "+b.arg(f.ssaStatus))
	}
	if set(f.clusterStatus) {
		parts = append(parts, "s.cluster_status = "+b.arg(f.clusterStatus))
	}
	if set(f.partner) {
		parts = append(parts, fmt.Sprintf(`EXISTS (SELECT 1 FROM activity pa WHERE pa.school_id = s.id
  AND pa.assigned_partner_id = %s AND pa.deleted_at IS NULL)`, b.arg(f.partner)))
	}
	if f.q != "" {
		p := b.arg(likeContains(f.q))
		parts = append(parts, fmt.Sprintf(`(UPPER(s.name::text) LIKE UPPER(%[1]s) OR UPPER(s.school_id::text) LIKE UPPER(%[1]s)
  OR EXISTS (SELECT 1 FROM district d WHERE d.id = s.district_id AND UPPER(d.name::text) LIKE UPPER(%[1]s))
  OR EXISTS (SELECT 1 FROM sub_county sc WHERE sc.id = s.sub_county_id AND UPPER(sc.name::text) LIKE UPPER(%[1]s))
  OR UPPER(s.uploaded_district_text::text) LIKE UPPER(%[1]s) OR UPPER(s.uploaded_sub_county_text::text) LIKE UPPER(%[1]s)
  OR UPPER(s.account_owner_name_raw::text) LIKE UPPER(%[1]s))`, p))
	}
	if support && f.support != "all" {
		if c := supportCondition(b, f, owners); c != "" {
			parts = append(parts, c)
		}
	}
	return "(" + strings.Join(parts, ") AND (") + ")"
}

// supportCondition is planning_support.filter_queryset for one filter.
func supportCondition(b *sqlb, f filterState, owners []string) string {
	fy := f.dataFY
	counted := func(kind, bucket string) string {
		return schoolplanning.CountedCondition(kind, schoolplanning.Buckets(bucket), fy, b.arg)
	}
	switch f.support {
	case "partner_support":
		return schoolplanning.PartnerSupportCondition(fy, b.arg)
	case "staff_managed":
		return "NOT " + schoolplanning.PartnerSupportCondition(fy, b.arg)
	case "my_scheduled_visits":
		return fmt.Sprintf(`EXISTS (SELECT 1 FROM activity a WHERE a.school_id = s.id AND a.fy = %s AND a.deleted_at IS NULL
  AND a.activity_type = ANY(%s) AND a.status = ANY(%s) AND a.responsible_staff_id = ANY(%s) AND a.delivery_type = 'staff')`,
			b.arg(fy), b.arg(schoolplanning.VisitTypes()), b.arg(schoolplanning.Buckets("planned")), b.arg(nonNil(owners)))
	case "visit_not_planned":
		return "NOT " + counted(schoolplanning.KindVisits, "counted")
	case "training_not_planned":
		return "NOT " + counted(schoolplanning.KindTrainings, "counted") + " AND NOT " + counted(schoolplanning.KindClusterMeetings, "counted")
	case "both_planned":
		return counted(schoolplanning.KindVisits, "counted") + " AND (" + counted(schoolplanning.KindTrainings, "counted") +
			" OR " + counted(schoolplanning.KindClusterMeetings, "counted") + ")"
	case "awaiting_verification":
		return counted("", "awaiting_verification")
	case "completed":
		return counted("", "verified")
	case "needs_replanning":
		return counted("", "needs_replanning")
	}
	return ""
}

func nonNil(ids []string) []string {
	if ids == nil {
		return []string{}
	}
	return ids
}

// likeContains is Django's icontains pattern: the value escaped and wrapped.
func likeContains(value string) string {
	r := strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`)
	return "%" + r.Replace(value) + "%"
}

// tableCondition is the tab's rows of filtered: the client rule's types or
// Core, less the schools with work (only while the support rule is off),
// clustered, and never a Champion school.
func tableCondition(b *sqlb, f filterState, support bool) string {
	parts := []string{}
	switch f.tab {
	case "client":
		parts = append(parts, "s.school_type = ANY("+b.arg(rules.ClientTabTypes)+")")
	case "core":
		parts = append(parts, "s.school_type = 'core'")
	case "partner":
		// The live-support rule the Responsible column reads, or, with the
		// rule off, a hand-over in a live status.
		if support {
			parts = append(parts, schoolplanning.PartnerSupportCondition(f.dataFY, b.arg))
		} else {
			parts = append(parts, "s.id IN (SELECT pa.school_id FROM partner_assignment pa WHERE pa.status = ANY("+b.arg(rules.PartnerLiveStatuses)+"))")
		}
	case "scheduled":
		parts = append(parts, fmt.Sprintf(`s.id IN (SELECT a.school_id FROM activity a WHERE a.deleted_at IS NULL AND a.fy = %s
  AND NOT (a.status = ANY(%s)))`, b.arg(f.dataFY), b.arg(rules.NotInThePlan)))
	}
	if !support && (f.tab == "client" || f.tab == "core") {
		parts = append(parts, fmt.Sprintf(`s.id NOT IN (SELECT a.school_id FROM activity a WHERE a.deleted_at IS NULL AND a.fy = %s
  AND a.school_id IS NOT NULL AND NOT (a.status = ANY(%s)))`, b.arg(f.dataFY), b.arg(rules.NotActiveWorkStatuses)),
			fmt.Sprintf(`s.id NOT IN (SELECT pa.school_id FROM partner_assignment pa WHERE pa.school_id IS NOT NULL
  AND pa.status = ANY(%s))`, b.arg(rules.PartnerLiveStatuses)))
	}
	parts = append(parts, "s.cluster_status = 'clustered' AND s.cluster_id IS NOT NULL AND s.cluster_id <> ''",
		"NOT (s.school_type = ANY("+b.arg(rules.OwnTableSchoolTypes)+") AND s.school_type IS NOT NULL)")
	return strings.Join(parts, " AND ")
}

// ── The people who hold the schools (owner_groups) ───────────────────────

// owner is owner_groups.owner_directory's entry.
type owner struct {
	profileID, name, plName string
}

func (o owner) sortKey() [2]string {
	pl := o.plName
	if pl == "" {
		pl = "￿"
	}
	return [2]string{pl, o.name}
}

// groupLabel is owner_groups.group_label.
func groupLabel(o *owner) string {
	if o == nil {
		return "Unassigned"
	}
	pl := o.plName
	if pl == "" {
		pl = "No Program Lead"
	}
	return pl + " · " + o.name
}

// ownerDirectory is owner_groups.owner_directory: each live profile held
// under either id space, named, with the Program Lead it reports to.
func ownerDirectory(ctx context.Context, q schooldirectory.Querier, ids []string) (map[string]*owner, error) {
	out := map[string]*owner{}
	if len(ids) == 0 {
		return out, nil
	}
	type profile struct{ id, userID, name, role string }
	profiles := []profile{}
	rows, err := q.Query(ctx, `
SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(u.name, ''), COALESCE(u.active_role, '')
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE (sp.id = ANY($1) OR sp.user_id = ANY($1)) AND sp.deleted_at IS NULL`, ids)
	if err != nil {
		return nil, fmt.Errorf("planningpage: reading owners: %w", err)
	}
	for rows.Next() {
		var p profile
		if err := rows.Scan(&p.id, &p.userID, &p.name, &p.role); err != nil {
			rows.Close()
			return nil, err
		}
		profiles = append(profiles, p)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	profileIDs := make([]string, len(profiles))
	for i, p := range profiles {
		profileIDs[i] = p.id
	}
	leads := map[string]string{}
	rows, err = q.Query(ctx, `
SELECT a.supervisee_id, COALESCE(u.name, ''), COALESCE(u.active_role, '')
FROM staff_supervisor_assignment a JOIN staff_profile sup ON sup.id = a.supervisor_id
LEFT JOIN "user" u ON u.id = sup.user_id
WHERE a.supervisee_id = ANY($1) AND sup.deleted_at IS NULL
ORDER BY u.name ASC`, profileIDs)
	if err != nil {
		return nil, fmt.Errorf("planningpage: reading leads: %w", err)
	}
	for rows.Next() {
		var supervisee, name, role string
		if err := rows.Scan(&supervisee, &name, &role); err != nil {
			rows.Close()
			return nil, err
		}
		if _, ok := leads[supervisee]; !ok && role == "Program Lead" {
			leads[supervisee] = name
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	for _, p := range profiles {
		// (profile.user.name if profile.user_id else "") or profile.id
		name := p.name
		if p.userID == "" || name == "" {
			name = p.id
		}
		pl := leads[p.id]
		if pl == "" && p.role == "Program Lead" {
			pl = name
		}
		entry := &owner{profileID: p.id, name: name, plName: pl}
		out[p.id] = entry
		if p.userID != "" {
			out[p.userID] = entry
		}
	}
	return out, nil
}

// distinctOwners are the owner ids held by the schools of a condition.
func distinctOwners(ctx context.Context, q schooldirectory.Querier, where string, args []any) ([]string, error) {
	ids := []string{}
	rows, err := q.Query(ctx, `SELECT DISTINCT s.account_owner_id FROM school s WHERE `+where+`
  AND s.account_owner_id IS NOT NULL AND s.account_owner_id <> ''`, args...)
	if err != nil {
		return nil, fmt.Errorf("planningpage: reading owner ids: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	return ids, rows.Err()
}

func strings1(ctx context.Context, q schooldirectory.Querier, sql string, args ...any) ([]string, error) {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, pgx.RowTo[string])
}
