package todos

// Impact Assessment's queue (docs/migration/56). IA reaches 23 builders
// (rules.Roles["ImpactAssessment"]): the field officer's ones that read the
// reader's own records answer the same for IA, those that branch on the role
// answer here, and builders whose records Go does not read yet are guards
// that pass the reader on whenever such a record exists anywhere in reach.

import (
	"context"
	"fmt"
	"net/url"
	"sort"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const roleIA = "ImpactAssessment"

// iaRules are the vocabularies IA's own builders read (rules.json "ia").
type iaRules struct {
	WaitingStatus string `json:"waiting_status"`
	Category      string `json:"category"`

	CollectionCategory          string   `json:"collection_category"`
	CollectionMaxOwnerRows      int      `json:"collection_max_owner_rows"`
	CollectionBlockedRowsDays   int      `json:"collection_blocked_rows_days"`
	CollectionBlockedStatus     string   `json:"collection_blocked_status"`
	CollectionOperatingStatuses []string `json:"collection_operating_statuses"`
	CollectionOpenStatuses      []string `json:"collection_open_statuses"`
	CollectionDeliveredStatuses []string `json:"collection_delivered_statuses"`
	CollectionRecordReturned    string   `json:"collection_record_returned"`
	CollectionRecordPending     string   `json:"collection_record_pending"`
	CollectionRecordConfirmed   string   `json:"collection_record_confirmed"`
	CollectionPartner           string   `json:"collection_partner"`

	CoverageRoles               []string `json:"coverage_roles"`
	CoverageURL                 string   `json:"coverage_url"`
	CoverageSessionTypes        []string `json:"coverage_session_types"`
	CoverageDeadStatuses        []string `json:"coverage_dead_statuses"`
	CoverageSchoolTrainingTypes []string `json:"coverage_school_training_types"`
	CoverageTrainedTypes        []string `json:"coverage_trained_types"`

	FrameworkCategory  string   `json:"framework_category"`
	FrameworkInReview  string   `json:"framework_in_review"`
	FrameworkDraft     string   `json:"framework_draft"`
	DefinitionInReview string   `json:"definition_in_review"`
	DefinitionReturned string   `json:"definition_returned"`
	EvidencePending    string   `json:"evidence_pending"`
	StorySubmitted     string   `json:"story_submitted"`
	QueueSSAPending    string   `json:"queue_ssa_pending"`
	QueueUnmatchedOpen []string `json:"queue_unmatched_open"`
	QueueDuplicateOpen string   `json:"queue_duplicate_open"`
	QueueSamplePending string   `json:"queue_sample_pending"`
}

type builder = func(context.Context, *Service, *reader) ([]todo, error)

// byRole answers with ia for an Impact Assessment reader and with base for
// everyone else: the builders that branch on the role.
func byRole(base, ia builder) builder {
	return func(ctx context.Context, s *Service, r *reader) ([]todo, error) {
		if r.role == roleIA {
			return ia(ctx, s, r)
		}
		return base(ctx, s, r)
	}
}

// onlyRole is a builder Go has for one role alone; any other role that
// reaches it is passed on.
func onlyRole(role string, b builder) builder {
	return func(ctx context.Context, s *Service, r *reader) ([]todo, error) {
		if r.role != role {
			return nil, errPassOn
		}
		return b(ctx, s, r)
	}
}

// onlyIA is a builder Go has for Impact Assessment alone; any other role
// that reaches it is passed on.
func onlyIA(ia builder) builder {
	return byRole(func(context.Context, *Service, *reader) ([]todo, error) { return nil, errPassOn }, ia)
}

func init() {
	for name, build := range map[string]builder{
		// The Admin reaches it too: plReviewGuard stands for it (admin.go).
		"_ia_todos": byRole(onlyRole(adminRole, plReviewGuard), iaVerificationTodos),
		"apps.activities.ia_todos:ia_queue_todos":     onlyIA(iaQueueGuard),
		"apps.impact.framework_todos:framework_todos": onlyIA(frameworkTodos),
		// A Business Transformation officer's conclusions are built (pcbt.go).
		"apps.impact.learning_todos:learning_todos": byRole(learningTodos, learningGuard),
		"apps.impact.report_todos:report_todos":     onlyIA(reportGuard),
		// A Programme Lead's portfolio passes them on (lead.go).
		"apps.planning.coverage_todos:missing_training_todos": byRole(portfolioGuard, missingTrainingTodos),
	} {
		Handled[name] = build
	}
}

// iaVerificationTodos is _ia_todos: work in the reader's country awaiting
// IA verification (partner work, or staff work with a Salesforce ID), never
// the reader's own, the twenty first submitted, each a row whose due day is
// a day after submission.
func iaVerificationTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	args := []any{rules.IA.WaitingStatus}
	where := `a.deleted_at IS NULL AND a.status = $1
  AND (a.delivery_type = 'partner' OR NOT (a.salesforce_activity_id IS NULL OR a.salesforce_activity_id = ''))`
	if r.scope.CountryScope && r.scope.Country != "" {
		args = append(args, r.scope.Country)
		where += " AND " + activityInCountry(len(args))
	}
	if len(r.owners) > 0 {
		args = append(args, r.owners)
		where += fmt.Sprintf(" AND NOT (a.responsible_staff_id = ANY($%d) AND a.responsible_staff_id IS NOT NULL)", len(args))
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, a.activity_type, a.delivery_type, a.submitted_to_ia_at,
  a.school_id IS NOT NULL, COALESCE(s.name, ''), a.cluster_id IS NOT NULL, COALESCE(cl.name, '')
FROM activity a LEFT OUTER JOIN school s ON s.id = a.school_id LEFT OUTER JOIN cluster cl ON cl.id = a.cluster_id
WHERE `+where+`
ORDER BY a.submitted_to_ia_at ASC NULLS LAST, a.updated_at ASC LIMIT 20`, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []todo
	for rows.Next() {
		var id, kind, delivery, school, cluster string
		var submitted *time.Time
		var hasSchool, hasCluster bool
		if err := rows.Scan(&id, &kind, &delivery, &submitted, &hasSchool, &school, &hasCluster, &cluster); err != nil {
			return nil, err
		}
		out = append(out, iaVerificationRow(r, id, kind, delivery, submitted, place(hasSchool, school, hasCluster, cluster)))
	}
	return out, rows.Err()
}

// activityInCountry is scoping.activity_country_q over an activity a with
// its school s and cluster cl, the country being argument n.
func activityInCountry(n int) string {
	c := "$" + strconv.Itoa(n)
	return `(EXISTS (SELECT 1 FROM region r WHERE r.id = s.region_id AND r.country = ` + c + `)
 OR (s.id IS NOT NULL AND s.region_id IS NULL AND (
   s.account_owner_id IN (SELECT id FROM staff_profile WHERE country = ` + c + ` AND deleted_at IS NULL)
   OR s.account_owner_id IS NULL OR s.account_owner_id = ''
   OR s.account_owner_id IN (SELECT id FROM staff_profile WHERE (country IS NULL OR country = '') AND deleted_at IS NULL)))
 OR EXISTS (SELECT 1 FROM region r WHERE r.id = cl.region_id AND r.country = ` + c + `)
 OR EXISTS (SELECT 1 FROM district d JOIN region r ON r.id = d.region_id WHERE d.id = cl.district_id AND r.country = ` + c + `)
 OR (a.school_id IS NULL AND a.cluster_id IS NULL
   AND a.responsible_staff_id IN (SELECT id FROM staff_profile WHERE country = ` + c + ` AND deleted_at IS NULL)))`
}

// place is the row's where: the school, else the cluster, else "—".
func place(hasSchool bool, school string, hasCluster bool, cluster string) string {
	switch {
	case hasSchool:
		return school
	case hasCluster:
		return cluster
	}
	return "—"
}

// iaVerificationRow is one _ia_todos row: late a day after submission.
func iaVerificationRow(r *reader, id, kind, delivery string, submitted *time.Time, where string) todo {
	partner := delivery == "partner"
	t := todo{Title: "Verify Activity", Category: rules.IA.Category, Priority: "high", StatusKey: "waiting_me",
		Actionable: true, Linked: where + " · " + typeLabel(kind), ActionLabel: "Verify",
		ActionURL: "/ia/verification/" + id + "/", Shape: "/ia/verification/{id}/"}
	if partner {
		t.Title, t.ActionLabel = "Review Partner Evidence and Confirm Salesforce", "Review"
		t.ActionURL, t.Shape = "/ia/partner-evidence/"+id+"/", "/ia/partner-evidence/{id}/"
	}
	if submitted != nil {
		t.Due = dateOf(submitted.Add(24 * time.Hour).In(zone))
		if r.now.Sub(*submitted) > 24*time.Hour {
			t.Priority, t.StatusKey = "critical", "overdue"
		}
	}
	return t
}

// iaQueueGuard is ia_queue_todos: any SSA record awaiting verification,
// unmatched import row, potential duplicate or pending verification sample
// passes the reader on.
func iaQueueGuard(ctx context.Context, s *Service, _ *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `
SELECT 1 FROM ssa_record WHERE deleted_at IS NULL AND verification_status = $1
UNION ALL SELECT 1 FROM unmatched_ssa_record WHERE status = ANY($2)
UNION ALL SELECT 1 FROM ia_duplicate_activity WHERE status = $3
UNION ALL SELECT 1 FROM ia_verification_sample WHERE status = $4`,
		rules.IA.QueueSSAPending, rules.IA.QueueUnmatchedOpen, rules.IA.QueueDuplicateOpen, rules.IA.QueueSamplePending))
}

// learningGuard is learning_todos: any loan (every lending queue is a
// loan's) or impact finding passes the reader on.
func learningGuard(ctx context.Context, s *Service, _ *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM bt_mfi_loan UNION ALL SELECT 1 FROM impact_finding`))
}

// reportGuard is report_todos: any impact report passes the reader on.
func reportGuard(ctx context.Context, s *Service, _ *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM impact_report`))
}

// loanGuardIA is _business_transformation_todos for IA: every row it adds
// is a loan's, so any loan passes the reader on.
func loanGuardIA(ctx context.Context, s *Service, _ *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM bt_mfi_loan`))
}

// evidenceGuardIA is evidence_todos for IA: school evidence awaiting a
// verifier, evidence returned to the reader, or a submitted change story
// passes the reader on.
func evidenceGuardIA(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	sql := `SELECT 1 FROM mscs_story WHERE status = $3`
	for _, table := range rules.EvidenceTables {
		sql += ` UNION ALL SELECT 1 FROM ` + pgx.Identifier{table}.Sanitize() +
			` WHERE verification_status = $1 OR (verification_status = $2 AND recorded_by_user_id = $4)`
	}
	return passOnIf(s.exists(ctx, sql, rules.IA.EvidencePending, rules.EvidenceReturned, rules.IA.StorySubmitted, r.p.UserID))
}

// frameworkTodos is framework_todos for IA: rules or definitions awaiting a
// reviewer, or returned to their author, pass the reader on; otherwise the
// one row is the school-outcome catalogue items with no live primary rule.
func frameworkTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	found, err := s.exists(ctx, `
SELECT 1 FROM activity_intervention_mapping WHERE active = false
  AND (status = $1 OR (status = $2 AND reviewed_at IS NOT NULL))
UNION ALL SELECT 1 FROM impact_outcome_area WHERE status = ANY($3)
UNION ALL SELECT 1 FROM impact_indicator_definition WHERE status = ANY($3)`,
		rules.IA.FrameworkInReview, rules.IA.FrameworkDraft, []string{rules.IA.DefinitionInReview, rules.IA.DefinitionReturned})
	if err != nil || found {
		return passOnIf(found, err)
	}
	var unmapped int
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM activity_catalogue_item ci
WHERE ci.status = 'active' AND (ci.requires_school OR ci.cluster_delivery_allowed OR ci.is_training_course)
  AND NOT (ci.id IN (SELECT m.catalogue_item_id FROM activity_intervention_mapping m WHERE m.active AND m.is_primary))`).Scan(&unmapped); err != nil {
		return nil, err
	}
	if unmapped == 0 {
		return nil, nil
	}
	word := "activities"
	if unmapped == 1 {
		word = "activity"
	}
	return []todo{{Title: "Set measurement rules for " + strconv.Itoa(unmapped) + " " + word,
		Category: rules.IA.FrameworkCategory, Priority: "medium", StatusKey: "waiting_me", Actionable: true,
		Linked: strconv.Itoa(unmapped) + " waiting", ActionLabel: "Open Measurement Rules",
		ActionURL: "/ia/framework/?tab=rules&status=required", Shape: "/ia/framework/?tab=rules&status=required",
		Due: &r.today}}, nil
}

// localFY is get_operational_fy(today) for the local day.
func localFY(today time.Time) string {
	if today.Month() >= time.October {
		return strconv.Itoa(today.Year() + 1)
	}
	return strconv.Itoa(today.Year())
}

// missingTrainingTodos is missing_training_todos for IA: one row counting
// the operating Core, Client, Core Trained and Core Graduate schools in
// reach with no cluster session they are invited to or attend, and no
// in-school training, planned in this year (coverage_service.training_coverage).
func missingTrainingTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if !contains(rules.IA.CoverageRoles, r.role) {
		return nil, nil
	}
	fy := localFY(r.today)
	year, _ := strconv.Atoi(fy)
	start := time.Date(year-1, time.October, 1, 0, 0, 0, 0, time.UTC).Format(time.DateOnly)
	end := time.Date(year, time.October, 1, 0, 0, 0, 0, time.UTC).AddDate(0, 0, -1).Format(time.DateOnly)
	var args []any
	reach := schooldirectory.AnalyticsReach(r.scope, &args)
	arg := func(v any) string { args = append(args, v); return "$" + strconv.Itoa(len(args)) }
	ops, trained, fyArg, dead := arg(rules.OperatingStatuses), arg(rules.IA.CoverageTrainedTypes), arg(fy), arg(rules.IA.CoverageDeadStatuses)
	from, to := arg(start), arg(end)
	sessions, inSchool := arg(rules.IA.CoverageSessionTypes), arg(rules.IA.CoverageSchoolTrainingTypes)
	inPeriod := `(a.planned_date BETWEEN ` + from + `::date AND ` + to + `::date
    OR (a.planned_date IS NULL AND (a.scheduled_date AT TIME ZONE 'Africa/Nairobi')::date BETWEEN ` + from + `::date AND ` + to + `::date))`
	var missing int
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM school s
WHERE `+reach+` AND s.operational_status = ANY(`+ops+`) AND s.school_type = ANY(`+trained+`)
  AND NOT EXISTS (SELECT 1 FROM cluster_activity_attendance caa
    WHERE caa.school_id = s.id AND (caa.invited = true OR caa.attended = true)
      AND caa.activity_id IN (SELECT a.id FROM activity a WHERE a.activity_type = ANY(`+sessions+`)
        AND a.deleted_at IS NULL AND a.fy = `+fyArg+` AND NOT (a.status = ANY(`+dead+`)) AND `+inPeriod+`))
  AND NOT EXISTS (SELECT 1 FROM activity a WHERE a.activity_type = ANY(`+inSchool+`) AND a.cluster_id IS NULL
    AND a.school_id = s.id AND a.deleted_at IS NULL AND a.fy = `+fyArg+` AND NOT (a.status = ANY(`+dead+`)) AND `+inPeriod+`)`,
		args...).Scan(&missing); err != nil {
		return nil, err
	}
	if missing == 0 {
		return nil, nil
	}
	return []todo{{Title: "Review Schools with No Cluster Training or Meeting Planned", Category: "School Progress",
		Priority: "high", StatusKey: "waiting_me", Actionable: true, Linked: plural(missing, "school"),
		ActionLabel: "Open Schools & Coverage", ActionURL: rules.IA.CoverageURL, Shape: rules.IA.CoverageURL,
		Due: &r.today}}, nil
}

// collectionIA is collection_todos for IA: the schools in reach with no
// confirmed SSA this year, a row per account owner (eight, then one for the
// rest) and per district for unowned schools; the reader's blocked import
// rows of the last thirty days; then the records returned to them.
func collectionIA(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	out, err := collectionOwnerRows(ctx, s, r)
	if err != nil {
		return nil, err
	}
	blocked, err := collectionBlockedRows(ctx, s, r)
	if err != nil {
		return nil, err
	}
	out = append(out, blocked...)
	returned, err := returnedSSARows(ctx, s, r)
	return append(out, returned...), err
}

// collectionGroup is one (owner, district) count of schools needing
// collection, in the order the statement returned it.
type collectionGroup struct {
	owner, district, districtName string
	hasDistrict, hasName          bool
	n                             int
}

func collectionOwnerRows(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	groups, err := collectionGroups(ctx, s, r)
	if err != nil {
		return nil, err
	}
	owners := map[string]int{}
	for _, g := range groups {
		if g.owner != "" {
			owners[g.owner] += g.n
		}
	}
	names, err := ownerNames(ctx, s, owners)
	if err != nil {
		return nil, err
	}
	return collectionRows(r, groups, names), nil
}

// collectionRows is _owner_rows over the counted groups: owners by count
// (then id), eight a row and the rest one row, then unowned schools by
// district, most first (equal counts in the order the groups came).
func collectionRows(r *reader, groups []collectionGroup, names map[string]string) []todo {
	byOwner := map[string]int{}
	type place struct{ id, name string }
	var unownedOrder []place
	unowned := map[place]int{}
	for _, g := range groups {
		if g.owner != "" {
			byOwner[g.owner] += g.n
			continue
		}
		key := place{"", "No district"}
		if g.hasDistrict {
			key.id = g.district
		}
		if g.hasName && g.districtName != "" {
			key.name = g.districtName
		}
		if _, seen := unowned[key]; !seen {
			unownedOrder = append(unownedOrder, key)
		}
		unowned[key] += g.n
	}
	type ranked struct {
		owner string
		n     int
	}
	var owners []ranked
	for owner, n := range byOwner {
		owners = append(owners, ranked{owner, n})
	}
	sort.Slice(owners, func(i, j int) bool {
		if owners[i].n != owners[j].n {
			return owners[i].n > owners[j].n
		}
		return owners[i].owner < owners[j].owner
	})
	max := rules.IA.CollectionMaxOwnerRows
	var rows []todo
	for i, o := range owners {
		if i >= max {
			break
		}
		name, ok := names[o.owner]
		if !ok {
			name = "an unmatched owner"
		}
		// urlencode keeps the dict's order: view, then owner.
		u := "/ia/dashboard/?view=collection&owner=" + url.QueryEscape(o.owner)
		rows = append(rows, collectionRow(r, plural(o.n, "school")+" without this year's SSA · "+name,
			u, "/ia/dashboard/?view=collection&owner={id}", plural(o.n, "school"), "medium"))
	}
	rest := 0
	for i, o := range owners {
		if i >= max {
			rest += o.n
		}
	}
	if rest > 0 {
		rows = append(rows, collectionRow(r, strconv.Itoa(rest)+" more "+schoolWord(rest)+" without this year's SSA",
			"/ia/dashboard/?view=collection", "/ia/dashboard/?view=collection", plural(rest, "school"), "low"))
	}
	sort.SliceStable(unownedOrder, func(i, j int) bool { return unowned[unownedOrder[i]] > unowned[unownedOrder[j]] })
	for i, key := range unownedOrder {
		if i >= max {
			break
		}
		n := unowned[key]
		u, shape := "/ia/dashboard/?view=collection", "/ia/dashboard/?view=collection"
		if key.id != "" {
			// urlencode keeps the dict's order: view, then district.
			u = "/ia/dashboard/?view=collection&district=" + url.QueryEscape(key.id)
			shape = "/ia/dashboard/?view=collection&district={id}"
		}
		rows = append(rows, collectionRow(r, strconv.Itoa(n)+" unowned "+schoolWord(n)+" without this year's SSA · "+key.name,
			u, shape, plural(n, "school"), "low"))
	}
	return rows
}

func schoolWord(n int) string {
	if n == 1 {
		return "school"
	}
	return "schools"
}

// collectionRow is collection_todos._row with no due day.
func collectionRow(r *reader, title, link, shape, linked, priority string) todo {
	return todo{Title: title, Category: rules.IA.CollectionCategory, Priority: priority, StatusKey: "waiting_me",
		Actionable: true, Linked: linked, ActionLabel: "Open Collection", ActionURL: link, Shape: shape, Due: &r.today}
}

// collectionGroups is ia_collection.annotate_states(collection_schools())
// narrowed to the states that need collection (never assessed, follow-up
// due, visit completed without scores), counted per owner and district.
// Those three are every state after the first five (returned, partner
// pending, pending verification, up to date, collection scheduled), so the
// schools are those none of the five holds for.
func collectionGroups(ctx context.Context, s *Service, r *reader) ([]collectionGroup, error) {
	var args []any
	reach := schooldirectory.AnalyticsReach(r.scope, &args)
	arg := func(v any) string { args = append(args, v); return "$" + strconv.Itoa(len(args)) }
	c := rules.IA
	ops, fy := arg(c.CollectionOperatingStatuses), arg(r.fy)
	returned, pending, confirmed, partner := arg(c.CollectionRecordReturned), arg(c.CollectionRecordPending), arg(c.CollectionRecordConfirmed), arg(c.CollectionPartner)
	open := arg(c.CollectionOpenStatuses)
	collection := `SELECT 1 FROM activity a WHERE a.school_id = s.id AND a.deleted_at IS NULL AND a.ssa_collection_expected = true`
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(s.account_owner_id, ''), s.district_id, d.name, COUNT(s.id)
FROM school s LEFT OUTER JOIN district d ON d.id = s.district_id
LEFT JOIN LATERAL (SELECT r.verification_status AS st, r.collector_type AS ct FROM ssa_record r
  WHERE r.school_id = s.id AND r.deleted_at IS NULL ORDER BY r.date_of_ssa DESC, r.created_at DESC LIMIT 1) lt ON true
WHERE `+reach+` AND s.operational_status = ANY(`+ops+`)
  AND lt.st IS DISTINCT FROM `+returned+` AND lt.st IS DISTINCT FROM `+pending+`
  AND NOT EXISTS (SELECT 1 FROM ssa_record r WHERE r.school_id = s.id AND r.deleted_at IS NULL AND r.verification_status = `+confirmed+` AND r.fy = `+fy+`)
  AND NOT EXISTS (`+collection+` AND a.delivery_type = `+partner+` AND a.status = ANY(`+open+`))
  AND NOT EXISTS (`+collection+` AND a.delivery_type <> `+partner+` AND a.status = ANY(`+open+`) AND a.ssa_not_collected_reason IS NULL)
GROUP BY 1, 2, 3`, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []collectionGroup
	for rows.Next() {
		var g collectionGroup
		var district, name *string
		if err := rows.Scan(&g.owner, &district, &name, &g.n); err != nil {
			return nil, err
		}
		if district != nil {
			g.hasDistrict, g.district = true, *district
		}
		if name != nil {
			g.hasName, g.districtName = true, *name
		}
		out = append(out, g)
	}
	return out, rows.Err()
}

// ownerNames is ia_collection._owner_names: account owners recorded by
// staff profile or by user id, named by the account ("Staff member" when it
// has no name).
func ownerNames(ctx context.Context, s *Service, owners map[string]int) (map[string]string, error) {
	names := map[string]string{}
	if len(owners) == 0 {
		return names, nil
	}
	ids := make([]string, 0, len(owners))
	for id := range owners {
		ids = append(ids, id)
	}
	rows, err := s.db.Query(ctx, `SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(u.name, '')
FROM staff_profile sp LEFT OUTER JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1))`, ids)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var profile, user, name string
		if err := rows.Scan(&profile, &user, &name); err != nil {
			return nil, err
		}
		if name == "" {
			name = "Staff member"
		}
		for _, key := range []string{profile, user} {
			if _, ok := owners[key]; ok && key != "" {
				names[key] = name
			}
		}
	}
	return names, rows.Err()
}

// collectionBlockedRows is _blocked_rows: the reader's import rows that
// could not be imported, from batches of the last thirty days.
func collectionBlockedRows(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.p.UserID == "" {
		return nil, nil
	}
	since := r.now.Add(-time.Duration(rules.IA.CollectionBlockedRowsDays) * 24 * time.Hour)
	var n, batches int
	var oldest *time.Time
	if err := s.db.QueryRow(ctx, `SELECT COUNT(r.id), COUNT(DISTINCT r.batch_id), MIN(b.created_at)
FROM ssa_import_row r INNER JOIN ssa_import_batch b ON b.id = r.batch_id
WHERE r.status = $1 AND b.uploaded_by = $2 AND b.created_at >= $3`,
		rules.IA.CollectionBlockedStatus, r.p.UserID, since).Scan(&n, &batches, &oldest); err != nil {
		return nil, err
	}
	if n == 0 {
		return nil, nil
	}
	word := "batches"
	if batches == 1 {
		word = "batch"
	}
	t := todo{Title: "Re-file " + plural(n, "blocked SSA row") + " from your uploads", Category: rules.IA.CollectionCategory,
		Priority: "medium", StatusKey: "waiting_me", Actionable: true, Linked: strconv.Itoa(batches) + " " + word,
		ActionLabel: "Open Upload History", ActionURL: "/ssa/upload/history/?has_blocked=1",
		Shape: "/ssa/upload/history/?has_blocked=1", Due: &r.today}
	if oldest != nil {
		t.Due = dateOf(oldest.In(zone))
		if t.Due.Before(r.today) {
			t.Priority, t.StatusKey = "high", "overdue"
		}
	}
	return []todo{t}, nil
}
