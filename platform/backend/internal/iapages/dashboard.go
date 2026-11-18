package iapages

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// DashboardPath is Impact Assessment's home (ia_dashboard_view).
const DashboardPath = "/ia/dashboard/"

// dashboardRules is the dashboard's vocabulary (export_ia_pages_rules
// _dashboard).
type dashboardRules struct {
	Tabs                    [][2]string     `json:"tabs"`
	DefaultView             string          `json:"default_view"`
	Metrics                 [][2]string     `json:"metrics"`
	ReviewOpenRoles         []string        `json:"review_open_roles"`
	QueueOpenRoles          []string        `json:"queue_open_roles"`
	DistrictSSATarget       float64         `json:"district_ssa_target"`
	ReturnOverdueDays       int             `json:"return_overdue_days"`
	FailedUploadStatuses    []string        `json:"failed_upload_statuses"`
	SchoolDuplicateStatuses []string        `json:"school_duplicate_statuses"`
	UnmatchedOpenStatuses   []string        `json:"unmatched_open_statuses"`
	DuplicateOpenStatus     string          `json:"duplicate_open_status"`
	OperatingStatuses       []string        `json:"operating_statuses"`
	Outcomes                outcomeRules    `json:"outcomes"`
	Collection              collectionRules `json:"collection"`
	// PerformanceExcludedStatuses and AchievedStatuses are the Map view's
	// roll-ups: the plans left out, and the done-states.
	PerformanceExcludedStatuses []string `json:"performance_excluded_statuses"`
	AchievedStatuses            []string `json:"achieved_statuses"`
}

// dashboardKeys are the query keys the dashboard reads.
var dashboardKeys = []string{"view", "project", "fy", "state", "district", "owner", "school_type", "collection_page"}

// queueCard is one of the oldest waiting records (the phone's queue).
type queueCard struct {
	id, school, district string
}

// header is _ia_header_context: the six tile figures and the oldest
// waiting records.
type header struct {
	waiting, overdue, missingSF, returnedOpen, unmatched int
	cards                                                []queueCard
}

// exception is one of the operations' Needs attention lines.
type exception struct {
	count      int
	text, href string
}

// operations is the part of _ia_operations_context the feed reads: the open
// queues' counts and the exceptions.
type operations struct {
	ssaPending, evidencePending, returnedOpen, duplicateRisk int
	exceptions                                               []exception
}

func (s *Service) dashboard(ctx context.Context, p auth.Principal, role Role, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	for key := range query {
		if !slices.Contains(dashboardKeys, key) && !slices.Contains(rules.QueryKeysNotPassed, key) {
			return nil, false, nil
		}
	}
	// resolve_dashboard_view: a view the page knows, else the default (the
	// app sends no remembered view).
	view := strings.ToLower(strings.TrimSpace(query.Get("view")))
	if !slices.ContainsFunc(rules.Dashboard.Tabs, func(t [2]string) bool { return t[0] == view }) {
		view = rules.Dashboard.DefaultView
	}
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: resolving the reader's scope: %w", err)
	}
	where, args, err := reach(ctx, s.db, p, now, nil)
	if err != nil {
		return nil, true, err
	}
	h, err := s.dashboardHeader(ctx, p, scope, where, args, now)
	if err != nil {
		return nil, true, err
	}
	viewBlocks := []*screensv1.PageBlock{panelOf("", textItem("Loading your day…"))}
	switch view {
	case "outcomes":
		blocks, served, err := s.outcomes(ctx, scope, query, now)
		if err != nil || !served {
			return nil, served, err
		}
		viewBlocks = blocks
	case "map":
		blocks, served, err := s.mapView(ctx, scope, where, args, now)
		if err != nil || !served {
			return nil, served, err
		}
		viewBlocks = blocks
	case "collection":
		blocks, served, err := s.collection(ctx, p, scope, query, now)
		if err != nil || !served {
			return nil, served, err
		}
		viewBlocks = blocks
	case "reports":
		blocks, served, err := s.reportsView(ctx, p, scope, query, now)
		if err != nil || !served {
			return nil, served, err
		}
		viewBlocks = blocks
	case "operations":
		ops, err := s.dashboardOperations(ctx, scope, where, args, h, now)
		if err != nil {
			return nil, true, err
		}
		if len(ops.exceptions) == 0 {
			// The quiet state's words are not ones the feed was seen
			// reading; hand on rather than guess them.
			return nil, false, nil
		}
		viewBlocks = []*screensv1.PageBlock{ops.block()}
	}
	return dashboardResponse(p, role, h, view, viewBlocks, now), true, nil
}

// dashboardHeader reads the tiles' figures and the oldest waiting records.
func (s *Service) dashboardHeader(ctx context.Context, p auth.Principal, scope schooldirectory.Scope, where string, args []any, now time.Time) (header, error) {
	var h header
	queue, qargs := staffQueue(p, where, args)
	overdueBefore := now.Add(-verificationSLAHours * time.Hour)
	n := len(qargs)
	if err := s.db.QueryRow(ctx, fmt.Sprintf(`
SELECT count(*), count(*) FILTER (WHERE a.submitted_to_ia_at IS NOT NULL AND a.submitted_to_ia_at <= $%d)
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id WHERE %s`, n+1, queue),
		append(qargs, overdueBefore)...).Scan(&h.waiting, &h.overdue); err != nil {
		return h, fmt.Errorf("iapages: counting the waiting work: %w", err)
	}
	n = len(args)
	if err := s.db.QueryRow(ctx, fmt.Sprintf(`
SELECT count(*) FILTER (WHERE a.status = ANY($%d) AND COALESCE(a.salesforce_activity_id, '') = ''),
       count(*) FILTER (WHERE a.status = 'returned_by_ia')
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
WHERE a.deleted_at IS NULL AND %s`, n+1, where), append(slices.Clone(args), reviewable)...).Scan(&h.missingSF, &h.returnedOpen); err != nil {
		return h, fmt.Errorf("iapages: counting the ledger: %w", err)
	}
	unmatched, uargs := unmatchedSSA(scope)
	if err := s.db.QueryRow(ctx, "SELECT count(*) FROM unmatched_ssa_record u WHERE "+unmatched, uargs...).Scan(&h.unmatched); err != nil {
		return h, fmt.Errorf("iapages: counting the unmatched SSA rows: %w", err)
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, s.name, d.name FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
LEFT JOIN district d ON d.id = s.district_id
WHERE `+queue+` ORDER BY a.submitted_to_ia_at ASC NULLS LAST, a.updated_at LIMIT 3`, qargs...)
	if err != nil {
		return h, fmt.Errorf("iapages: reading the oldest waiting records: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var c queueCard
		var school, district *string
		if err := rows.Scan(&c.id, &school, &district); err != nil {
			return h, fmt.Errorf("iapages: reading a waiting record: %w", err)
		}
		c.school, c.district = "Cluster-wide", "No district"
		if school != nil {
			c.school = *school
			if district != nil {
				c.district = *district
			}
		}
		h.cards = append(h.cards, c)
	}
	return h, rows.Err()
}

// staffQueue is _ia_staff_queue over activity `a` (school `s`, cluster
// `cl`): staff submissions waiting with their Salesforce ID, not a lead's to
// verify, never the reader's own.
func staffQueue(p auth.Principal, where string, args []any) (string, []any) {
	args = slices.Clone(args)
	args = append(args, rules.LeadVerifiedRoles, rules.LeadRole)
	lead := leadVerifiedSQL(len(args) - 1)
	own := []string{p.UserID}
	if p.StaffProfileID != "" {
		own = append(own, p.StaffProfileID)
	}
	args = append(args, own)
	return fmt.Sprintf(`a.deleted_at IS NULL AND (%s) AND a.status = 'awaiting_ia_verification'
AND a.delivery_type IS DISTINCT FROM 'partner' AND COALESCE(a.salesforce_activity_id, '') <> ''
AND NOT COALESCE(%s, FALSE) AND (a.responsible_staff_id IS NULL OR NOT a.responsible_staff_id = ANY($%d))`,
		where, lead, len(args)), args
}

// countryBound is scoping.country_bound.
func countryBound(scope schooldirectory.Scope) bool {
	return scope.CountryScope && scope.Country != ""
}

// countryUsers is country_user_ids as a sub-select, read through the
// registry (country.UsersIn, docs/migration/80 §14): the argument numbered n
// is the country's registry id (Scope.CountryID).
func countryUsers(n int) string {
	return registry.UsersIn(fmt.Sprintf("$%d::text", n))
}

// unmatchedSSA is unmatched_ssa_for_scope over `u`: rows still pending or on
// hold, placed in the country by their batch's uploader or the school the
// importer suggested.
func unmatchedSSA(scope schooldirectory.Scope) (string, []any) {
	args := []any{rules.Dashboard.UnmatchedOpenStatuses}
	where := "u.status = ANY($1)"
	if countryBound(scope) {
		args = append(args, scope.CountryID)
		where += fmt.Sprintf(` AND (u.batch_id IN (SELECT id FROM ssa_import_batch WHERE uploaded_by IN %s)
  OR u.suggested_school_id IN (SELECT ss.id FROM school ss WHERE %s))`, countryUsers(2), registry.SchoolIn("ss", "ARRAY[$2::text]"))
	}
	return where, args
}

// dashboardOperations reads the open queues and the exceptions.
func (s *Service) dashboardOperations(ctx context.Context, scope schooldirectory.Scope, where string, args []any, h header, now time.Time) (operations, error) {
	d := rules.Dashboard
	ops := operations{returnedOpen: h.returnedOpen}
	inReach := "SELECT a.id FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id WHERE a.deleted_at IS NULL AND " + where
	n := len(args)
	var overdueReturns int
	if err := s.db.QueryRow(ctx, fmt.Sprintf(`
SELECT (SELECT count(*) FROM ia_duplicate_activity WHERE status = $%[1]d AND activity_id IN (%[3]s)),
       (SELECT count(*) FROM evidence_record WHERE NOT quarantined AND status = 'uploaded' AND activity_id IN (%[3]s)),
       (SELECT count(*) FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
        WHERE a.deleted_at IS NULL AND %[4]s AND a.status = 'returned_by_ia' AND a.updated_at < $%[2]d)`,
		n+1, n+2, inReach, where),
		append(slices.Clone(args), d.DuplicateOpenStatus, now.AddDate(0, 0, -d.ReturnOverdueDays))...).Scan(
		&ops.duplicateRisk, &ops.evidencePending, &overdueReturns); err != nil {
		return ops, fmt.Errorf("iapages: counting the open queues: %w", err)
	}
	sargs := []any{}
	schools := schooldirectory.AnalyticsReach(scope, &sargs)
	sargs = append(sargs, d.OperatingStatuses)
	schools += fmt.Sprintf(" AND s.operational_status = ANY($%d)", len(sargs))
	sargs = append(sargs, d.SchoolDuplicateStatuses)
	var dupSchools int
	if err := s.db.QueryRow(ctx, fmt.Sprintf(`
SELECT count(*) FILTER (WHERE s.duplicate_status = ANY($%d)),
       (SELECT count(*) FROM ssa_record r WHERE r.deleted_at IS NULL AND r.verification_status = 'pending'
        AND r.school_id IN (SELECT s.id FROM school s WHERE %s))
FROM school s WHERE %s`, len(sargs), schools, schools), sargs...).Scan(&dupSchools, &ops.ssaPending); err != nil {
		return ops, fmt.Errorf("iapages: counting the schools' records: %w", err)
	}
	below, err := s.districtsBelowTarget(ctx, scope, schools, sargs[:len(sargs)-1])
	if err != nil {
		return ops, err
	}
	failed, err := s.failedUploads(ctx, scope)
	if err != nil {
		return ops, err
	}
	for _, e := range []exception{
		{h.missingSF, "completed/verified activities missing Salesforce IDs", "/ia/verification/?sf_id=missing"},
		{ops.duplicateRisk, "activities flagged as potential duplicates", "/ia/duplicates/"},
		{dupSchools, "schools flagged as potential duplicates", "/data-quality/duplicates"},
		{below, "districts below 50% SSA completion", "/country-profile?tab=ssa"},
		{overdueReturns, "activities returned for correction over 7 days ago", "/ia/returned/"},
		{failed, "bulk uploads failed validation", "/uploads?tab=imports"},
	} {
		if e.count > 0 {
			ops.exceptions = append(ops.exceptions, e)
		}
	}
	return ops, nil
}

// districtsBelowTarget counts the reader's districts (_ia_districts) whose
// open schools in scope have fewer than the target share with this year's
// SSA done.
func (s *Service) districtsBelowTarget(ctx context.Context, scope schooldirectory.Scope, schools string, args []any) (int, error) {
	args = slices.Clone(args)
	districts := "TRUE"
	if countryBound(scope) {
		args = append(args, scope.CountryIDs())
		districts = "d.region_id IN " + registry.RegionsIn(fmt.Sprintf("$%d", len(args)))
	}
	// A reader without the country sees the districts of their schools, which
	// are the districts the schools below sit in already.
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT count(*), count(*) FILTER (WHERE s.current_fy_ssa_status = 'done')
FROM school s JOIN district d ON d.id = s.district_id WHERE %s AND %s GROUP BY d.id`, schools, districts), args...)
	if err != nil {
		return 0, fmt.Errorf("iapages: reading the districts' SSA completion: %w", err)
	}
	defer rows.Close()
	below := 0
	for rows.Next() {
		var total, done int
		if err := rows.Scan(&total, &done); err != nil {
			return 0, fmt.Errorf("iapages: reading a district's SSA completion: %w", err)
		}
		if float64(done)/float64(total) < rules.Dashboard.DistrictSSATarget {
			below++
		}
	}
	return below, rows.Err()
}

// failedUploads counts the reader's upload batches (_ia_uploads) that
// failed validation.
func (s *Service) failedUploads(ctx context.Context, scope schooldirectory.Scope) (int, error) {
	args := []any{rules.Dashboard.FailedUploadStatuses}
	where := "status = ANY($1)"
	if countryBound(scope) {
		args = append(args, scope.CountryID)
		where += " AND uploaded_by IN " + countryUsers(2)
	}
	var n int
	if err := s.db.QueryRow(ctx, "SELECT count(*) FROM upload_batch WHERE "+where, args...).Scan(&n); err != nil {
		return 0, fmt.Errorf("iapages: counting the failed uploads: %w", err)
	}
	return n, nil
}

func textItem(s string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: s}}
}

func headingItem(s string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: s}}
}

func linksItem(links ...*screensv1.PageLink) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}}
}

func panelOf(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
}

// block is partials/ia/operations.html as the feed reads it: the open
// queues and the exceptions (the rest of the view is hidden on a phone).
func (o operations) block() *screensv1.PageBlock {
	queues := linksItem(
		&screensv1.PageLink{Text: "SSA reviewConfirm assessment records", Href: "/ssa/verification/", Caption: strconv.Itoa(o.ssaPending)},
		&screensv1.PageLink{Text: "Evidence reviewUploaded files awaiting a decision", Href: "/evidence/", Caption: strconv.Itoa(o.evidencePending)},
		&screensv1.PageLink{Text: "Returned workCorrections still outstanding", Href: "/ia/returned/", Caption: strconv.Itoa(o.returnedOpen)},
		&screensv1.PageLink{Text: "Duplicate reviewPotential duplicate activities", Href: "/ia/duplicates/", Caption: strconv.Itoa(o.duplicateRisk)},
	)
	lines := []*screensv1.PageLink{}
	for i, e := range o.exceptions {
		if i == 5 {
			break
		}
		lines = append(lines, &screensv1.PageLink{Text: fmt.Sprintf("%d %s →", e.count, e.text), Href: e.href})
	}
	block := panelOf("Open queues", queues, textItem("Exceptions"), headingItem("Needs attention"),
		textItem(strconv.Itoa(len(o.exceptions))), linksItem(lines...))
	block.GetPanel().Subtitle = "Work lanes"
	return block
}

// weekRange is _ia_week_window's dates as the header words them: the
// server's (UTC) week, Monday to Sunday.
func weekRange(now time.Time) string {
	now = now.UTC()
	start := now.AddDate(0, 0, -((int(now.Weekday()) + 6) % 7))
	end := start.AddDate(0, 0, 6)
	return fmt.Sprintf("%s %d – %s %d, %d", start.Format("Jan"), start.Day(), end.Format("Jan"), end.Day(), end.Year())
}

// dashboardResponse is the page: the role home's header, the workspace
// strip, the tiles, the oldest waiting records, and the view rail with the
// chosen view under each tab (the feed reads the one panel the page holds).
func dashboardResponse(p auth.Principal, role Role, h header, view string, viewBlocks []*screensv1.PageBlock, now time.Time) *screensv1.GetPageResponse {
	d := rules.Dashboard
	action := &screensv1.PageAction{Key: "primary-action", Label: "Open verification queue", Primary: true, Enabled: true, Href: VerificationPath}
	openRoles := d.QueueOpenRoles
	if len(h.cards) > 0 {
		action.Label, action.Href = "Review oldest record", VerificationPath+h.cards[0].id+"/"
		openRoles = d.ReviewOpenRoles
	}
	hdr := &screensv1.PageHeader{
		Eyebrow:     "School transformation",
		Title:       "Impact Assessment",
		Description: "Review school outcomes, coordinate assessments and turn evidence into programme decisions.",
		Badges: []*screensv1.PageBadge{
			{Text: weekRange(now), Tone: "plain"},
			{Text: fmt.Sprintf("%d waiting", h.waiting), Tone: "plain"},
		},
	}
	if slices.Contains(openRoles, p.ActiveRole) {
		hdr.Actions = []*screensv1.PageAction{action}
	}
	values := []int{h.waiting, h.waiting, h.missingSF, h.returnedOpen, h.unmatched, h.overdue}
	metrics := []*screensv1.PageMetric{}
	for i, m := range d.Metrics {
		metrics = append(metrics, &screensv1.PageMetric{Label: m[0], Value: strconv.Itoa(values[i]), Href: m[1]})
	}
	blocks := workspaceStrip(role)
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Verification workload", Metrics: metrics}}})
	if len(h.cards) == 0 {
		blocks = append(blocks, panelOf("Oldest waiting records", linksItem(&screensv1.PageLink{Text: "Full queue", Href: VerificationPath})),
			&screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: "Verification queue is clearNew submissions will appear here automatically."}})
	} else {
		items := []*screensv1.PagePanelItem{}
		for _, c := range h.cards {
			items = append(items, headingItem(c.school), textItem(c.district))
		}
		blocks = append(blocks, panelOf("Oldest waiting records", items...))
	}
	segments := &screensv1.PageSegments{}
	for _, t := range d.Tabs {
		segments.Segments = append(segments.Segments, &screensv1.PageSegment{Label: t[1], Active: t[0] == view, Blocks: viewBlocks})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Segments{Segments: segments}})
	return &screensv1.GetPageResponse{Header: hdr, Blocks: blocks, WebPath: DashboardPath}
}
