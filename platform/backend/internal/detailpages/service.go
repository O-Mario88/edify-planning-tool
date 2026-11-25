// Package detailpages provides read-only Go page handlers for entity detail,
// analytics, document, and operational sub-pages across Edify so zero internal
// links fall through to a legacy "Not Moved Yet" placeholder.
package detailpages

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Service answers entity detail and sub-pages directly from PostgreSQL.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
	// annex is an impact report's evidence annex (internal/iareports), for
	// /ia/impact-reports/<id>/annex.csv.
	annex ReportAnnex
	// releaseFile is a released donor or school version's download, for
	// /ia/impact-reports/<id>/releases/<release>/download.
	releaseFile ReleaseDownload
	// workbooks are the workbook exports Go makes, by export path.
	workbooks map[string]WorkbookExport
	// workbookRoutes name the workbook exports at patterned paths.
	workbookRoutes []WorkbookRoute
	// files are the other file exports Go makes, by export path.
	files map[string]FileExport
}

// ReleaseDownload writes a report's released version for p.
type ReleaseDownload func(ctx context.Context, p auth.Principal, reportID, releaseID string) (string, []byte, error)

// WithReleaseDownload serves the impact report release download.
func (s *Service) WithReleaseDownload(d ReleaseDownload) *Service {
	s.releaseFile = d
	return s
}

// ReportAnnex writes a report's evidence annex for p: its file name and
// bytes, or an error the download answers with not found.
type ReportAnnex func(ctx context.Context, p auth.Principal, reportID string) (string, []byte, error)

// WithReportAnnex serves the impact report annex download.
func (s *Service) WithReportAnnex(a ReportAnnex) *Service {
	s.annex = a
	return s
}

// NewService wires the service to the PostgreSQL reader.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// Build dispatches entity detail, document, analytics, and fallback pages.
func (s *Service) Build(ctx context.Context, p auth.Principal, rawPath string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	path := strings.TrimSuffix(rawPath, "/")
	if path == "" {
		path = "/"
	}
	// These pages read records with no check of the reader's schools, team or
	// country yet. Until each has its scope, only Admin (who may read every
	// record) is served; everyone else is handed on to the existing rules.
	if needsRecordScope(ctx, path) && p.ActiveRole != rbac.Admin {
		return nil, true, pagegate.ErrNotAvailable
	}
	if id, ok := recordID(path, "/projects/"); ok {
		return s.projectDetail(ctx, p, id, query)
	}
	if id, ok := recordID(path, "/partners/"); ok {
		return s.partnerDetail(ctx, p, id, query)
	}
	if id, ok := recordID(path, "/activities/"); ok {
		return s.activityDetail(ctx, p, id, "/activities/"+id)
	}
	if id, ok := recordID(path, "/my-plan/"); ok {
		return s.activityDetail(ctx, p, id, "/my-plan/"+id)
	}
	switch {
	case path == "/projects/analytics":
		return s.projectAnalytics(ctx, p, query)
	case strings.HasPrefix(path, "/admin-ops/incidents/"):
		id := strings.TrimPrefix(path, "/admin-ops/incidents/")
		if id != "" && !strings.Contains(id, "/") {
			return s.incidentDetail(ctx, p, id)
		}
	case strings.HasPrefix(path, "/documents/"):
		rest := strings.TrimPrefix(path, "/documents/")
		if strings.HasSuffix(rest, "/manage") {
			slug := strings.TrimSuffix(rest, "/manage")
			if slug != "" && !strings.Contains(slug, "/") {
				return s.documentManage(ctx, p, slug)
			}
		} else if rest != "" && !strings.Contains(rest, "/") && rest != "new" && rest != "agreements" && rest != "restricted" {
			return s.documentDetail(ctx, p, rest)
		}
	case path == "/accounts/monthly-request":
		return s.monthlyFundRequest(ctx, p, query)
	case path == "/uploads/bulk-completion/visit":
		return s.bulkCompletionPage(ctx, p, "visit")
	case path == "/uploads/bulk-completion/training":
		return s.bulkCompletionPage(ctx, p, "training")
	case path == "/dashboard" && pagegate.DjangoAbsent(ctx):
		return s.executiveDashboard(ctx, p, query)
	}
	return nil, false, nil
}

// fixedRoutes are the pages that share a prefix with a record's address, so
// "/projects/capacity" is never read as a project whose id is "capacity".
var fixedRoutes = map[string][]string{
	"/projects/":   {"analytics", "capacity", "create", "export", "filter", "filters-drawer", "monitoring", "my-plan", "planning"},
	"/partners/":   {"create"},
	"/activities/": {"closure"},
	"/my-plan/":    {"day-package", "export-drawer", "readiness", "smart-route"},
}

// recordID is the id in a one-record address under prefix.
func recordID(path, prefix string) (string, bool) {
	id, found := strings.CutPrefix(path, prefix)
	if !found || id == "" || strings.Contains(id, "/") || slices.Contains(fixedRoutes[prefix], id) {
		return "", false
	}
	return id, true
}

// needsRecordScope is whether path is a page that does not yet limit what it
// reads to the reader's own scope.
func needsRecordScope(ctx context.Context, path string) bool {
	switch path {
	case "/projects/analytics", "/accounts/monthly-request":
		return true
	case "/dashboard":
		return pagegate.DjangoAbsent(ctx)
	}
	for prefix := range fixedRoutes {
		if _, ok := recordID(path, prefix); ok {
			return true
		}
	}
	if slug, found := strings.CutPrefix(path, "/documents/"); found {
		return slug != "" && !strings.Contains(slug, "/") && !slices.Contains([]string{"new", "agreements", "restricted"}, slug)
	}
	return false
}

func orDash(v string) string {
	v = strings.TrimSpace(v)
	if v == "" {
		return "—"
	}
	return v
}

func fmtUGX(n int64) string {
	if n == 0 {
		return "UGX 0"
	}
	return "UGX " + commaInt(n)
}

func commaInt(n int64) string {
	neg := n < 0
	if neg {
		n = -n
	}
	s := strconv.FormatInt(n, 10)
	if len(s) <= 3 {
		if neg {
			return "-" + s
		}
		return s
	}
	var b strings.Builder
	if neg {
		b.WriteByte('-')
	}
	rem := len(s) % 3
	if rem > 0 {
		b.WriteString(s[:rem])
		if len(s) > rem {
			b.WriteByte(',')
		}
	}
	for i := rem; i < len(s); i += 3 {
		if i > rem {
			b.WriteByte(',')
		}
		b.WriteString(s[i : i+3])
	}
	return b.String()
}

func hrefIf(cond bool, h string) string {
	if cond {
		return h
	}
	return ""
}

func makeCols(labels ...string) []*screensv1.PageColumn {
	out := make([]*screensv1.PageColumn, 0, len(labels))
	for _, lbl := range labels {
		out = append(out, &screensv1.PageColumn{Label: lbl})
	}
	return out
}

// ── 1. Project Profile (/projects/{id}) ─────────────────────────────────

func (s *Service) projectDetail(ctx context.Context, _ auth.Principal, id string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	var code, name, category, intervention, status, managerID, managerName, schoolFocus string
	var startFY, endFY string
	var ceiling int64
	err := s.db.QueryRow(ctx, `
SELECT COALESCE(pr.code, ''), pr.name, COALESCE(pr.category, ''), COALESCE(pr.intervention, ''),
       COALESCE(pr.status, 'active'), COALESCE(pr.manager_staff_id, ''), COALESCE(u.name, ''),
       COALESCE(pr.school_focus, ''), COALESCE(pr.measurement_start_fy, ''), COALESCE(pr.measurement_end_fy, ''),
       COALESCE(pr.budget_ceiling_ugx, 0)
FROM project pr
LEFT JOIN "user" u ON u.id = pr.manager_staff_id
WHERE pr.id = $1 AND pr.deleted_at IS NULL`, id).Scan(
		&code, &name, &category, &intervention, &status, &managerID, &managerName, &schoolFocus, &startFY, &endFY, &ceiling)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if err != nil {
		return nil, true, fmt.Errorf("detailpages: reading project %s: %w", id, err)
	}

	fy := strings.TrimSpace(query.Get("fy"))
	if fy == "" {
		fy = schooldirectory.OperationalFY(s.now())
	}

	// Participating schools
	sRows, err := s.db.Query(ctx, `
SELECT s.id, COALESCE(s.school_id, ''), s.name, COALESCE(d.name, ''), COALESCE(psa.participation_type, ''),
       COALESCE(psa.baseline_band, ''), psa.baseline_score, psa.follow_up_score
FROM project_school_assignment psa
JOIN school s ON s.id = psa.school_id AND s.deleted_at IS NULL
LEFT JOIN district d ON d.id = s.district_id
WHERE psa.project_id = $1
ORDER BY s.name LIMIT 100`, id)
	if err != nil {
		return nil, true, err
	}
	defer sRows.Close()
	var schoolRows []*screensv1.PageRow
	for sRows.Next() {
		var sid, scode, sname, dist, ptype, bband string
		var bscore, fscore *float64
		if err := sRows.Scan(&sid, &scode, &sname, &dist, &ptype, &bband, &bscore, &fscore); err != nil {
			return nil, true, err
		}
		ref := scode
		if ref == "" {
			ref = sid
		}
		bTxt, fTxt := "—", "—"
		if bscore != nil {
			bTxt = fmt.Sprintf("%.1f", *bscore)
		}
		if fscore != nil {
			fTxt = fmt.Sprintf("%.1f", *fscore)
		}
		schoolRows = append(schoolRows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: orDash(scode)},
			{Text: sname, Href: "/schools/" + url.PathEscape(ref)},
			{Text: orDash(dist)},
			{Text: orDash(ptype)},
			{Text: orDash(bband)},
			{Text: bTxt + " → " + fTxt},
		}})
	}

	// Partners
	pRows, err := s.db.Query(ctx, `
SELECT pt.id, pt.name, COALESCE(pt.contract_status, ''), COALESCE(pt.contact_person, ''), COALESCE(pt.email, '')
FROM project_partner_assignment ppa
JOIN partner pt ON pt.id = ppa.partner_id AND pt.deleted_at IS NULL
WHERE ppa.project_id = $1
ORDER BY pt.name`, id)
	if err != nil {
		return nil, true, err
	}
	defer pRows.Close()
	var partnerRows []*screensv1.PageRow
	for pRows.Next() {
		var pid, pname, cstat, contact, email string
		if err := pRows.Scan(&pid, &pname, &cstat, &contact, &email); err != nil {
			return nil, true, err
		}
		partnerRows = append(partnerRows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: pname, Href: "/partners/" + pid},
			{Text: orDash(cstat)},
			{Text: orDash(contact)},
			{Text: orDash(email)},
		}})
	}

	// Activities & budget
	var plannedActs, doneActs int
	var estCents int64
	_ = s.db.QueryRow(ctx, `
SELECT count(*),
       count(*) FILTER (WHERE status IN ('completed', 'verified', 'approved', 'submitted')),
       COALESCE(sum(est_cost_cents), 0)
FROM activity WHERE project_id = $1 AND deleted_at IS NULL`, id).Scan(&plannedActs, &doneActs, &estCents)

	aRows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(NULLIF(a.activity_name_snapshot, ''), NULLIF(a.purpose_intervention, ''), a.activity_type, 'Activity'),
       COALESCE(a.activity_type, ''), COALESCE(a.status, ''), COALESCE(a.planned_date, a.scheduled_date),
       COALESCE(s.name, ''), COALESCE(s.school_id, ''), COALESCE(u.name, '')
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN "user" u ON u.id = a.responsible_staff_id
WHERE a.project_id = $1 AND a.deleted_at IS NULL
ORDER BY COALESCE(a.planned_date, a.scheduled_date) DESC NULLS LAST LIMIT 50`, id)
	if err != nil {
		return nil, true, err
	}
	defer aRows.Close()
	var actRows []*screensv1.PageRow
	for aRows.Next() {
		var aid, title, atype, astat, sname, scode, owner string
		var dt *time.Time
		if err := aRows.Scan(&aid, &title, &atype, &astat, &dt, &sname, &scode, &owner); err != nil {
			return nil, true, err
		}
		dStr := "—"
		if dt != nil {
			dStr = dt.Format("02 Jan 2006")
		}
		scCell := &screensv1.PageCell{Text: "Project-wide"}
		if sname != "" {
			ref := scode
			if ref == "" {
				ref = sname
			}
			scCell = &screensv1.PageCell{Text: sname, Href: "/schools/" + url.PathEscape(ref)}
		}
		actRows = append(actRows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: dStr},
			{Text: title, Href: "/activities/" + aid},
			{Text: atype},
			scCell,
			{Text: astat},
			{Text: orDash(owner)},
		}})
	}

	header := &screensv1.PageHeader{
		Eyebrow:     "Projects",
		BackLabel:   "Back to Projects",
		BackHref:    "/projects",
		Title:       name,
		Description: fmt.Sprintf("Project %s · %s · FY %s", orDash(code), orDash(category), fy),
		Badges:      []*screensv1.PageBadge{{Text: strings.ToUpper(status), Tone: "positive"}},
		Actions: []*screensv1.PageAction{
			{Key: "plan", Label: "Project Planning", Enabled: true, Primary: true, Href: "/projects/planning?project=" + id},
			{Key: "monitor", Label: "Monitoring", Enabled: true, Href: "/projects/monitoring?project=" + id},
			{Key: "analytics", Label: "Analytics", Enabled: true, Href: "/projects/analytics?project=" + id},
			{Key: "export", Label: "Export CSV", Enabled: true, Download: true, Href: "/projects/" + id + "/export"},
		},
	}

	facts := []*screensv1.PageFact{
		{Label: "Project Code", Value: orDash(code)},
		{Label: "Category", Value: orDash(category)},
		{Label: "Intervention", Value: orDash(intervention)},
		{Label: "Project Manager", Value: orDash(managerName), Href: hrefIf(managerID != "", "/staff/"+managerID)},
		{Label: "School Focus", Value: orDash(schoolFocus)},
		{Label: "Measurement Window", Value: strings.TrimSpace(orDash(startFY) + " – " + orDash(endFY))},
	}

	strip := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
		Title: "Project Execution Snapshot",
		Metrics: []*screensv1.PageMetric{
			{Label: "Participating Schools", Value: commaInt(int64(len(schoolRows)))},
			{Label: "Assigned Partners", Value: commaInt(int64(len(partnerRows)))},
			{Label: "Activities", Value: fmt.Sprintf("%d / %d", doneActs, plannedActs), Note: "completed / total"},
			{Label: "Budget Ceiling", Value: fmtUGX(ceiling), Note: "Estimated spend " + fmtUGX(estCents/100)},
		},
	}}}

	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Facts{Facts: &screensv1.PageFacts{Facts: facts}}},
		strip,
		{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title:        "Participating Schools",
			Columns:      makeCols("School ID", "School Name", "District", "Participation", "Baseline Band", "Baseline → Follow-up"),
			Rows:         schoolRows,
			EmptyMessage: "No schools are currently assigned to this project.",
		}}},
		{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title:        "Assigned Implementation Partners",
			Columns:      makeCols("Partner", "Contract Status", "Primary Contact", "Email"),
			Rows:         partnerRows,
			EmptyMessage: "No external implementation partners are assigned to this project.",
		}}},
		{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title:        "Project Activities",
			Columns:      makeCols("Date", "Activity", "Type", "School", "Status", "Owner"),
			Rows:         actRows,
			EmptyMessage: "No activities have been scheduled under this project yet.",
		}}},
	}

	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: "/projects/" + id}, true, nil
}

// ── 2. Project Analytics (/projects/analytics) ──────────────────────────

func (s *Service) projectAnalytics(ctx context.Context, _ auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	fy := strings.TrimSpace(query.Get("fy"))
	if fy == "" {
		fy = schooldirectory.OperationalFY(s.now())
	}
	projectFilter := strings.TrimSpace(query.Get("project"))

	rows, err := s.db.Query(ctx, `
SELECT pr.id, COALESCE(pr.code, ''), pr.name, COALESCE(pr.category, ''), COALESCE(pr.status, 'active'),
       COALESCE(pr.budget_ceiling_ugx, 0),
       (SELECT count(*) FROM project_school_assignment psa WHERE psa.project_id = pr.id),
       (SELECT count(*) FROM project_partner_assignment ppa WHERE ppa.project_id = pr.id),
       (SELECT count(*) FROM activity a WHERE a.project_id = pr.id AND a.deleted_at IS NULL AND ($1 = '' OR a.fy = $1)),
       (SELECT count(*) FROM activity a WHERE a.project_id = pr.id AND a.deleted_at IS NULL AND ($1 = '' OR a.fy = $1)
         AND a.status IN ('completed', 'verified', 'approved', 'submitted')),
       COALESCE((SELECT sum(a.est_cost_cents) FROM activity a WHERE a.project_id = pr.id AND a.deleted_at IS NULL AND ($1 = '' OR a.fy = $1)), 0)
FROM project pr
WHERE pr.deleted_at IS NULL AND ($2 = '' OR pr.id = $2)
ORDER BY pr.name`, fy, projectFilter)
	if err != nil {
		return nil, true, fmt.Errorf("detailpages: project analytics query: %w", err)
	}
	defer rows.Close()

	var tableRows []*screensv1.PageRow
	var totalProjects, totalSchools, totalActs, totalDone int64
	var totalCeiling, totalEstCents int64
	for rows.Next() {
		var id, code, name, cat, status string
		var ceiling, schools, partners, acts, done, estCents int64
		if err := rows.Scan(&id, &code, &name, &cat, &status, &ceiling, &schools, &partners, &acts, &done, &estCents); err != nil {
			return nil, true, err
		}
		totalProjects++
		totalSchools += schools
		totalActs += acts
		totalDone += done
		totalCeiling += ceiling
		totalEstCents += estCents
		pct := "0%"
		if acts > 0 {
			pct = fmt.Sprintf("%d%%", (done*100)/acts)
		}
		tableRows = append(tableRows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: name, Href: "/projects/" + id},
			{Text: orDash(cat)},
			{Text: strings.ToUpper(status)},
			{Text: commaInt(schools)},
			{Text: commaInt(partners)},
			{Text: fmt.Sprintf("%d / %d (%s)", done, acts, pct)},
			{Text: fmtUGX(ceiling)},
		}})
	}

	overallPct := "0%"
	if totalActs > 0 {
		overallPct = fmt.Sprintf("%d%%", (totalDone*100)/totalActs)
	}

	header := &screensv1.PageHeader{
		Eyebrow:     "Projects & Impact",
		BackLabel:   "Back to Projects",
		BackHref:    "/projects",
		Title:       "Project Analytics",
		Description: fmt.Sprintf("Portfolio delivery, school participation, and budget execution across FY %s.", fy),
		Actions: []*screensv1.PageAction{
			{Key: "export", Label: "Export CSV", Enabled: true, Download: true, Href: "/projects/export?fy=" + url.QueryEscape(fy)},
		},
	}

	strip := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
		Title: "Portfolio Delivery Metrics (FY " + fy + ")",
		Metrics: []*screensv1.PageMetric{
			{Label: "Active Projects", Value: commaInt(totalProjects)},
			{Label: "Schools Enrolled", Value: commaInt(totalSchools)},
			{Label: "Activity Completion", Value: overallPct, Note: fmt.Sprintf("%d / %d done", totalDone, totalActs)},
			{Label: "Combined Budget Ceiling", Value: fmtUGX(totalCeiling), Note: "Est. spend " + fmtUGX(totalEstCents/100)},
		},
	}}}

	table := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title:        "Project Delivery Comparison",
		Columns:      makeCols("Project", "Category", "Status", "Schools", "Partners", "Completion", "Budget Ceiling"),
		Rows:         tableRows,
		EmptyMessage: "No projects match the current filter.",
	}}}

	return &screensv1.GetPageResponse{
		Header:  header,
		Blocks:  []*screensv1.PageBlock{strip, table},
		WebPath: "/projects/analytics",
	}, true, nil
}

// ── 3. Partner Profile (/partners/{id}) ─────────────────────────────────

func (s *Service) partnerDetail(ctx context.Context, _ auth.Principal, id string, _ url.Values) (*screensv1.GetPageResponse, bool, error) {
	var name, regionName, trainsOn, contact, email, phone, contractStatus, certStatus, activeStatus, partnerRole, notes string
	err := s.db.QueryRow(ctx, `
SELECT name, COALESCE(region_name, ''), COALESCE(array_to_string(trains_on, ', '), ''), COALESCE(contact_person, ''),
       COALESCE(email, ''), COALESCE(phone, ''), COALESCE(contract_status, ''), COALESCE(certification_status, ''),
       CASE WHEN active_status IS FALSE THEN 'inactive' ELSE 'active' END, COALESCE(partner_role, ''), COALESCE(notes, '')
FROM partner WHERE id = $1 AND deleted_at IS NULL`, id).Scan(
		&name, &regionName, &trainsOn, &contact, &email, &phone, &contractStatus, &certStatus, &activeStatus, &partnerRole, &notes)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if err != nil {
		return nil, true, fmt.Errorf("detailpages: reading partner %s: %w", id, err)
	}

	// Team members
	mRows, err := s.db.Query(ctx, `
SELECT name, COALESCE(role, ''), COALESCE(title, ''), COALESCE(email, ''), COALESCE(phone, ''), active
FROM partner_member WHERE partner_id = $1 ORDER BY name`, id)
	if err != nil {
		return nil, true, err
	}
	defer mRows.Close()
	var memberRows []*screensv1.PageRow
	for mRows.Next() {
		var mn, mr, mt, me, mp string
		var active bool
		if err := mRows.Scan(&mn, &mr, &mt, &me, &mp, &active); err != nil {
			return nil, true, err
		}
		st := "Active"
		if !active {
			st = "Inactive"
		}
		memberRows = append(memberRows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: mn}, {Text: orDash(mr)}, {Text: orDash(mt)}, {Text: orDash(me)}, {Text: orDash(mp)}, {Text: st},
		}})
	}

	// Partner assignments / hand-overs
	aRows, err := s.db.Query(ctx, `
SELECT COALESCE(pa.expected_activity_type, 'Assignment'), COALESCE(pa.focus_intervention, ''),
       COALESCE(pa.status, ''), pa.scheduled_date, COALESCE(s.name, ''), COALESCE(s.school_id, ''),
       COALESCE(c.name, ''), COALESCE(c.id, '')
FROM partner_assignment pa
LEFT JOIN school s ON s.id = pa.school_id
LEFT JOIN cluster c ON c.id = pa.cluster_id
WHERE pa.partner_id = $1
ORDER BY pa.scheduled_date DESC NULLS LAST, pa.created_at DESC LIMIT 60`, id)
	if err != nil {
		return nil, true, err
	}
	defer aRows.Close()
	var assignRows []*screensv1.PageRow
	for aRows.Next() {
		var atype, focus, status, sname, scode, cname, cid string
		var dt *time.Time
		if err := aRows.Scan(&atype, &focus, &status, &dt, &sname, &scode, &cname, &cid); err != nil {
			return nil, true, err
		}
		dStr := "—"
		if dt != nil {
			dStr = dt.Format("02 Jan 2006")
		}
		whereCell := &screensv1.PageCell{Text: "—"}
		if sname != "" {
			ref := scode
			if ref == "" {
				ref = sname
			}
			whereCell = &screensv1.PageCell{Text: sname, Href: "/schools/" + url.PathEscape(ref)}
		} else if cname != "" {
			whereCell = &screensv1.PageCell{Text: cname, Href: "/clusters/" + cid}
		}
		assignRows = append(assignRows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: dStr}, {Text: atype}, {Text: orDash(focus)}, whereCell, {Text: orDash(status)},
		}})
	}

	var projectCount int
	_ = s.db.QueryRow(ctx, `SELECT count(*) FROM project_partner_assignment WHERE partner_id = $1`, id).Scan(&projectCount)

	header := &screensv1.PageHeader{
		Eyebrow:     "Partners",
		BackLabel:   "Back to Partner Oversight",
		BackHref:    "/partner-oversight/",
		Title:       name,
		Description: fmt.Sprintf("Implementation Partner · %s", orDash(regionName)),
		Badges:      []*screensv1.PageBadge{{Text: strings.ToUpper(activeStatus), Tone: "positive"}},
	}

	facts := []*screensv1.PageFact{
		{Label: "Primary Contact", Value: orDash(contact)},
		{Label: "Email", Value: orDash(email)},
		{Label: "Phone", Value: orDash(phone)},
		{Label: "Contract Status", Value: orDash(contractStatus)},
		{Label: "Certification", Value: orDash(certStatus)},
		{Label: "Trains On", Value: orDash(trainsOn)},
		{Label: "Role", Value: orDash(partnerRole)},
	}

	strip := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
		Title: "Partner Operations Overview",
		Metrics: []*screensv1.PageMetric{
			{Label: "Team Members", Value: commaInt(int64(len(memberRows)))},
			{Label: "Projects", Value: commaInt(int64(projectCount))},
			{Label: "Hand-over Assignments", Value: commaInt(int64(len(assignRows)))},
		},
	}}}

	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Facts{Facts: &screensv1.PageFacts{Facts: facts}}},
		strip,
	}
	if notes != "" {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Title: "Partner Notes",
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: notes}}},
		}}})
	}
	blocks = append(blocks,
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title:        "Partner Team Members",
			Columns:      makeCols("Name", "Role", "Title", "Email", "Phone", "Status"),
			Rows:         memberRows,
			EmptyMessage: "No partner team members registered yet.",
		}}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title:        "Recent Assignments & Hand-overs",
			Columns:      makeCols("Scheduled Date", "Activity Type", "Focus Intervention", "School / Cluster", "Status"),
			Rows:         assignRows,
			EmptyMessage: "No assignments recorded for this partner.",
		}}},
	)

	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: "/partners/" + id}, true, nil
}

// ── 4. Activity Detail (/activities/{id} and /my-plan/{id}) ─────────────

func (s *Service) activityDetail(ctx context.Context, _ auth.Principal, id, webPath string) (*screensv1.GetPageResponse, bool, error) {
	var title, actType, status, evidenceStatus, iaStatus, sfID, fy, quarter, purpose, outcome, obs, venue string
	var schoolID, schoolCode, schoolName, clusterID, clusterName, projectID, projectName string
	var ownerID, ownerName, partnerID, partnerName string
	var plannedDate, actualDate *time.Time
	var teachers, leaders, other int
	var estCents int64

	err := s.db.QueryRow(ctx, `
SELECT COALESCE(NULLIF(a.activity_name_snapshot, ''), NULLIF(a.purpose_intervention, ''), a.activity_type, 'Activity'),
       COALESCE(a.activity_type, ''), COALESCE(a.status, ''), COALESCE(a.evidence_status, ''),
       COALESCE(a.ia_verification_status, ''), COALESCE(a.salesforce_activity_id, ''),
       COALESCE(a.fy, ''), COALESCE(a.quarter, ''),
       COALESCE(a.activity_purpose_text, a.purpose_intervention, ''),
       COALESCE(a.actual_outcome, a.expected_outcome, ''),
       COALESCE(a.actual_observations, a.follow_up_note, ''),
       COALESCE(a.venue, ''),
       COALESCE(a.school_id, ''), COALESCE(s.school_id, ''), COALESCE(s.name, ''),
       COALESCE(a.cluster_id, ''), COALESCE(c.name, ''),
       COALESCE(a.project_id, ''), COALESCE(pr.name, ''),
       COALESCE(a.responsible_staff_id, ''), COALESCE(u.name, ''),
       COALESCE(a.assigned_partner_id, a.facilitating_partner_id, ''), COALESCE(pt.name, ''),
       COALESCE(a.planned_date, a.scheduled_date), a.actual_delivery_date,
       COALESCE(a.teachers_attended, 0), COALESCE(a.leaders_attended, 0), COALESCE(a.other_participants, 0),
       COALESCE(a.est_cost_cents, 0)
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN cluster c ON c.id = a.cluster_id
LEFT JOIN project pr ON pr.id = a.project_id
LEFT JOIN "user" u ON u.id = a.responsible_staff_id
LEFT JOIN partner pt ON pt.id = COALESCE(a.assigned_partner_id, a.facilitating_partner_id)
WHERE a.id = $1 AND a.deleted_at IS NULL`, id).Scan(
		&title, &actType, &status, &evidenceStatus, &iaStatus, &sfID, &fy, &quarter, &purpose, &outcome, &obs, &venue,
		&schoolID, &schoolCode, &schoolName, &clusterID, &clusterName, &projectID, &projectName,
		&ownerID, &ownerName, &partnerID, &partnerName, &plannedDate, &actualDate,
		&teachers, &leaders, &other, &estCents)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if err != nil {
		return nil, true, fmt.Errorf("detailpages: reading activity %s: %w", id, err)
	}

	pDate, aDate := "—", "—"
	if plannedDate != nil {
		pDate = plannedDate.Format("02 Jan 2006")
	}
	if actualDate != nil {
		aDate = actualDate.Format("02 Jan 2006")
	}
	schoolRef := schoolCode
	if schoolRef == "" {
		schoolRef = schoolID
	}

	header := &screensv1.PageHeader{
		Eyebrow:     "Activity Record",
		BackLabel:   "Back to My Plan",
		BackHref:    "/my-plan",
		Title:       title,
		Description: fmt.Sprintf("%s · FY %s %s · Planned %s", orDash(actType), orDash(fy), quarter, pDate),
		Badges: []*screensv1.PageBadge{
			{Text: strings.ToUpper(orDash(status)), Tone: "info"},
		},
		Actions: []*screensv1.PageAction{},
	}
	if schoolRef != "" {
		header.Actions = append(header.Actions,
			&screensv1.PageAction{Key: "school", Label: "Open School Profile", Enabled: true, Primary: true, Href: "/schools/" + url.PathEscape(schoolRef)},
			&screensv1.PageAction{Key: "directions", Label: "Get Directions (In-App)", Enabled: true, Href: "/my-plan/smart-route?navigate=" + url.QueryEscape(schoolID)},
		)
	}

	facts := []*screensv1.PageFact{
		{Label: "Activity Type", Value: orDash(actType)},
		{Label: "Status", Value: orDash(status)},
		{Label: "Evidence Status", Value: orDash(evidenceStatus)},
		{Label: "IA Verification", Value: orDash(iaStatus)},
		{Label: "Planned Date", Value: pDate},
		{Label: "Actual Delivery Date", Value: aDate},
		{Label: "Responsible Staff", Value: orDash(ownerName), Href: hrefIf(ownerID != "", "/staff/"+ownerID)},
		{Label: "School", Value: orDash(schoolName), Href: hrefIf(schoolRef != "", "/schools/"+url.PathEscape(schoolRef))},
		{Label: "Cluster", Value: orDash(clusterName), Href: hrefIf(clusterID != "", "/clusters/"+clusterID)},
		{Label: "Project", Value: orDash(projectName), Href: hrefIf(projectID != "", "/projects/"+projectID)},
		{Label: "Partner", Value: orDash(partnerName), Href: hrefIf(partnerID != "", "/partners/"+partnerID)},
		{Label: "Salesforce ID", Value: orDash(sfID)},
		{Label: "Venue", Value: orDash(venue)},
		{Label: "Estimated Cost", Value: fmtUGX(estCents / 100)},
	}

	strip := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
		Title: "Participation Summary",
		Metrics: []*screensv1.PageMetric{
			{Label: "Teachers Attended", Value: strconv.Itoa(teachers)},
			{Label: "School Leaders", Value: strconv.Itoa(leaders)},
			{Label: "Other Participants", Value: strconv.Itoa(other)},
			{Label: "Total Participants", Value: strconv.Itoa(teachers + leaders + other)},
		},
	}}}

	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Facts{Facts: &screensv1.PageFacts{Facts: facts}}},
		strip,
	}
	var notesItems []*screensv1.PagePanelItem
	if purpose != "" {
		notesItems = append(notesItems, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: "Purpose: " + purpose}})
	}
	if outcome != "" {
		notesItems = append(notesItems, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: "Outcome: " + outcome}})
	}
	if obs != "" {
		notesItems = append(notesItems, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: "Field Observations: " + obs}})
	}
	if len(notesItems) > 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Title: "Activity Narrative & Observations",
			Items: notesItems,
		}}})
	}

	// Attendance rows if any
	attRows, err := s.db.Query(ctx, `
SELECT s.name, COALESCE(s.school_id, ''), caa.invited, caa.attended, COALESCE(caa.teachers, 0), COALESCE(caa.leaders, 0), COALESCE(caa.other, 0)
FROM cluster_activity_attendance caa
JOIN school s ON s.id = caa.school_id
WHERE caa.activity_id = $1 ORDER BY s.name`, id)
	if err == nil {
		defer attRows.Close()
		var rows []*screensv1.PageRow
		for attRows.Next() {
			var sn, sc string
			var inv, att bool
			var t, l, o int
			if err := attRows.Scan(&sn, &sc, &inv, &att, &t, &l, &o); err == nil {
				st := "Invited"
				if att {
					st = "Attended"
				}
				ref := sc
				if ref == "" {
					ref = sn
				}
				rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
					{Text: sn, Href: "/schools/" + url.PathEscape(ref)},
					{Text: st},
					{Text: strconv.Itoa(t)},
					{Text: strconv.Itoa(l)},
					{Text: strconv.Itoa(o)},
				}})
			}
		}
		if len(rows) > 0 {
			blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
				Title:   "Cluster Session Attendance Roster",
				Columns: makeCols("School", "Status", "Teachers", "Leaders", "Other"),
				Rows:    rows,
			}}})
		}
	}

	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: webPath}, true, nil
}

// ── 5. Incident Detail (/admin-ops/incidents/{id}) ──────────────────────

func (s *Service) incidentDetail(ctx context.Context, p auth.Principal, id string) (*screensv1.GetPageResponse, bool, error) {
	if p.ActiveRole != "Admin" && p.ActiveRole != "CountryDirector" && p.ActiveRole != "RegionalVicePresident" {
		return nil, true, pagegate.ErrNotAvailable
	}
	var ref, title, cat, sev, status, route, comp, detail, ownerID, ownerName string
	var occurrences, reopened int
	var firstAt, lastAt, ackAt, resAt *time.Time

	err := s.db.QueryRow(ctx, `
SELECT COALESCE(i.reference, ''), i.title, COALESCE(i.category, ''), COALESCE(i.severity, ''),
       COALESCE(i.status, ''), COALESCE(i.affected_route, ''), COALESCE(i.affected_component, ''),
       COALESCE(NULLIF(i.detail #>> '{}', '{}'), ''), COALESCE(i.owner_id, ''), COALESCE(u.name, ''),
       COALESCE(i.occurrence_count, 0), COALESCE(i.reopened_count, 0),
       i.first_detected_at, i.last_detected_at, i.acknowledged_at, i.resolved_at
FROM admin_system_incident i
LEFT JOIN "user" u ON u.id = i.owner_id
WHERE i.id = $1`, id).Scan(
		&ref, &title, &cat, &sev, &status, &route, &comp, &detail, &ownerID, &ownerName,
		&occurrences, &reopened, &firstAt, &lastAt, &ackAt, &resAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if err != nil {
		return nil, true, fmt.Errorf("detailpages: reading incident %s: %w", id, err)
	}
	fmtTime := func(t *time.Time) string {
		if t == nil {
			return "—"
		}
		return t.Format("02 Jan 2006 15:04")
	}

	header := &screensv1.PageHeader{
		Eyebrow:     "Admin Ops · System Incidents",
		BackLabel:   "Back to Incidents",
		BackHref:    "/admin-ops/incidents",
		Title:       title,
		Description: fmt.Sprintf("Incident %s · %s · %s", orDash(ref), orDash(cat), orDash(sev)),
		Badges: []*screensv1.PageBadge{
			{Text: strings.ToUpper(orDash(sev)), Tone: "attention"},
			{Text: strings.ToUpper(orDash(status)), Tone: "info"},
		},
	}

	facts := []*screensv1.PageFact{
		{Label: "Reference", Value: orDash(ref)},
		{Label: "Category", Value: orDash(cat)},
		{Label: "Affected Route", Value: orDash(route)},
		{Label: "Component", Value: orDash(comp)},
		{Label: "Owner", Value: orDash(ownerName), Href: hrefIf(ownerID != "", "/staff/"+ownerID)},
		{Label: "Occurrences", Value: strconv.Itoa(occurrences)},
		{Label: "Reopened", Value: strconv.Itoa(reopened)},
		{Label: "First Detected", Value: fmtTime(firstAt)},
		{Label: "Last Detected", Value: fmtTime(lastAt)},
		{Label: "Acknowledged", Value: fmtTime(ackAt)},
		{Label: "Resolved", Value: fmtTime(resAt)},
	}

	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Facts{Facts: &screensv1.PageFacts{Facts: facts}}},
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Title: "Diagnostic Detail",
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: orDash(detail)}}},
		}}},
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: "/admin-ops/incidents/" + id}, true, nil
}

// ── 6. Policy & Governance Documents (/documents/{slug} & /manage) ──────

func (s *Service) documentDetail(ctx context.Context, p auth.Principal, slug string) (*screensv1.GetPageResponse, bool, error) {
	var id, title, desc, docType, cat, conf, status, stmt string
	var ackReq, agreeReq bool
	var verNum int
	var filename, changeSummary string
	var effectiveDate *time.Time

	err := s.db.QueryRow(ctx, `
SELECT d.id, d.title, COALESCE(d.description, ''), COALESCE(d.document_type, ''),
       COALESCE(d.category, ''), COALESCE(d.confidentiality, ''), COALESCE(d.status, ''),
       COALESCE(d.agreement_statement, ''), COALESCE(d.acknowledgement_required, false), COALESCE(d.agreement_required, false),
       COALESCE(v.version_number, 1), COALESCE(v.original_filename, ''), COALESCE(v.change_summary, ''), v.effective_date
FROM document_asset d
LEFT JOIN document_version v ON v.id = d.current_version_id
WHERE d.slug = $1`, slug).Scan(
		&id, &title, &desc, &docType, &cat, &conf, &status, &stmt, &ackReq, &agreeReq,
		&verNum, &filename, &changeSummary, &effectiveDate)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if err != nil {
		return nil, true, fmt.Errorf("detailpages: reading document %s: %w", slug, err)
	}

	var myState string
	var respondedAt *time.Time
	_ = s.db.QueryRow(ctx, `
SELECT COALESCE(state, ''), responded_at FROM document_acknowledgement
WHERE document_id = $1 AND user_id = $2 ORDER BY updated_at DESC LIMIT 1`, id, p.UserID).Scan(&myState, &respondedAt)

	effStr := "—"
	if effectiveDate != nil {
		effStr = effectiveDate.Format("02 Jan 2006")
	}
	ackText := "Not required"
	if ackReq || agreeReq {
		if myState != "" {
			ackText = myState
			if respondedAt != nil {
				ackText += " (" + respondedAt.Format("02 Jan 2006") + ")"
			}
		} else {
			ackText = "Pending your acknowledgement"
		}
	}

	header := &screensv1.PageHeader{
		Eyebrow:     "Policies & Documents",
		BackLabel:   "Back to Upload Center",
		BackHref:    "/uploads?tab=documents",
		Title:       title,
		Description: fmt.Sprintf("%s · Version %d · Effective %s", orDash(cat), verNum, effStr),
		Badges:      []*screensv1.PageBadge{{Text: strings.ToUpper(orDash(status)), Tone: "positive"}},
		Actions: []*screensv1.PageAction{
			{Key: "agreements", Label: "Policy Agreement Center", Enabled: true, Href: "/policy-agreement"},
		},
	}
	if p.ActiveRole == "Admin" || p.ActiveRole == "HR" || p.ActiveRole == "CountryDirector" {
		header.Actions = append(header.Actions, &screensv1.PageAction{
			Key: "manage", Label: "Manage Compliance", Enabled: true, Primary: true, Href: "/documents/" + slug + "/manage",
		})
	}

	facts := []*screensv1.PageFact{
		{Label: "Document Type", Value: orDash(docType)},
		{Label: "Category", Value: orDash(cat)},
		{Label: "Confidentiality", Value: orDash(conf)},
		{Label: "Active Version", Value: fmt.Sprintf("v%d", verNum)},
		{Label: "Effective Date", Value: effStr},
		{Label: "Original File", Value: orDash(filename)},
		{Label: "Your Compliance Status", Value: ackText},
	}

	var items []*screensv1.PagePanelItem
	if desc != "" {
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: desc}})
	}
	if changeSummary != "" {
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: "Version Change Summary: " + changeSummary}})
	}
	if stmt != "" {
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: "Attestation Statement: " + stmt}})
	}
	if len(items) == 0 {
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: "Policy document active in Edify governance repository."}})
	}

	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Facts{Facts: &screensv1.PageFacts{Facts: facts}}},
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Document Overview", Items: items}}},
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: "/documents/" + slug}, true, nil
}

func (s *Service) documentManage(ctx context.Context, p auth.Principal, slug string) (*screensv1.GetPageResponse, bool, error) {
	if p.ActiveRole != "Admin" && p.ActiveRole != "HR" && p.ActiveRole != "CountryDirector" && p.ActiveRole != "RegionalVicePresident" {
		return nil, true, pagegate.ErrNotAvailable
	}
	var id, title, status, cat string
	var verNum int
	err := s.db.QueryRow(ctx, `
SELECT d.id, d.title, COALESCE(d.status, ''), COALESCE(d.category, ''), COALESCE(v.version_number, 1)
FROM document_asset d
LEFT JOIN document_version v ON v.id = d.current_version_id
WHERE d.slug = $1`, slug).Scan(&id, &title, &status, &cat, &verNum)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if err != nil {
		return nil, true, err
	}

	rows, err := s.db.Query(ctx, `
SELECT u.id, COALESCE(u.name, u.email), COALESCE(da.role_at_acknowledgement, ''), COALESCE(da.state, ''), da.responded_at
FROM document_acknowledgement da
JOIN "user" u ON u.id = da.user_id
WHERE da.document_id = $1
ORDER BY da.responded_at DESC NULLS LAST, u.name LIMIT 100`, id)
	if err != nil {
		return nil, true, err
	}
	defer rows.Close()
	var ackRows []*screensv1.PageRow
	var doneCount, pendingCount int
	for rows.Next() {
		var uid, uname, role, state string
		var at *time.Time
		if err := rows.Scan(&uid, &uname, &role, &state, &at); err != nil {
			return nil, true, err
		}
		if strings.EqualFold(state, "acknowledged") || strings.EqualFold(state, "agreed") || strings.EqualFold(state, "completed") {
			doneCount++
		} else {
			pendingCount++
		}
		atStr := "Pending"
		if at != nil {
			atStr = at.Format("02 Jan 2006")
		}
		ackRows = append(ackRows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: uname, Href: "/staff/" + uid},
			{Text: orDash(role)},
			{Text: orDash(state)},
			{Text: atStr},
		}})
	}

	header := &screensv1.PageHeader{
		Eyebrow:     "Governance & Compliance",
		BackLabel:   "Back to Document",
		BackHref:    "/documents/" + slug,
		Title:       "Manage: " + title,
		Description: fmt.Sprintf("%s · Version %d · Status: %s", orDash(cat), verNum, strings.ToUpper(status)),
	}
	strip := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
		Title: "Acknowledgement Tracking",
		Metrics: []*screensv1.PageMetric{
			{Label: "Total Tracked", Value: strconv.Itoa(len(ackRows))},
			{Label: "Completed", Value: strconv.Itoa(doneCount)},
			{Label: "Pending", Value: strconv.Itoa(pendingCount)},
		},
	}}}
	table := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title:        "Staff Acknowledgement Register",
		Columns:      makeCols("Staff Member", "Role", "State", "Responded Date"),
		Rows:         ackRows,
		EmptyMessage: "No staff acknowledgement records have been created for this document yet.",
	}}}

	return &screensv1.GetPageResponse{
		Header:  header,
		Blocks:  []*screensv1.PageBlock{strip, table},
		WebPath: "/documents/" + slug + "/manage",
	}, true, nil
}

// ── 7. Accounts Monthly Request (/accounts/monthly-request) ─────────────

func (s *Service) monthlyFundRequest(ctx context.Context, _ auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	fy := strings.TrimSpace(query.Get("fy"))
	if fy == "" {
		fy = schooldirectory.OperationalFY(s.now())
	}
	rows, err := s.db.Query(ctx, `
SELECT m.month, COALESCE(u.name, m.staff_id), COALESCE(u.id, ''), COALESCE(m.amount, 0), COALESCE(m.status, '')
FROM monthly_fund_request m
LEFT JOIN "user" u ON u.id = m.staff_id
WHERE m.fy = $1
ORDER BY m.month DESC, u.name LIMIT 100`, fy)
	if err != nil {
		return nil, true, fmt.Errorf("detailpages: reading monthly_fund_request: %w", err)
	}
	defer rows.Close()
	var mRows []*screensv1.PageRow
	var totalAmt int64
	for rows.Next() {
		var month, staffName, uid, status string
		var amt int64
		if err := rows.Scan(&month, &staffName, &uid, &amt, &status); err != nil {
			return nil, true, err
		}
		totalAmt += amt
		mRows = append(mRows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: month},
			{Text: staffName, Href: hrefIf(uid != "", "/staff/"+uid)},
			{Text: fmtUGX(amt)},
			{Text: strings.ToUpper(orDash(status))},
		}})
	}

	// Weekly roll-up by month for comparison
	wRows, err := s.db.Query(ctx, `
SELECT to_char(week_start_date, 'YYYY-MM') AS ym, count(*),
       COALESCE(sum(total_amount), 0), COALESCE(sum(disbursed_amount), 0)
FROM weekly_fund_request
WHERE fy = $1
GROUP BY 1 ORDER BY 1 DESC LIMIT 12`, fy)
	if err != nil {
		return nil, true, err
	}
	defer wRows.Close()
	var rollupRows []*screensv1.PageRow
	var weeklyTotal, disbursedTotal int64
	for wRows.Next() {
		var ym string
		var cnt int
		var tot, disb int64
		if err := wRows.Scan(&ym, &cnt, &tot, &disb); err != nil {
			return nil, true, err
		}
		weeklyTotal += tot
		disbursedTotal += disb
		rollupRows = append(rollupRows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: ym},
			{Text: strconv.Itoa(cnt)},
			{Text: fmtUGX(tot)},
			{Text: fmtUGX(disb)},
		}})
	}

	header := &screensv1.PageHeader{
		Eyebrow:     "Finance & Accounts",
		BackLabel:   "Back to Weekly Fund Requests",
		BackHref:    "/fund-requests/weekly",
		Title:       "Monthly Fund Requests",
		Description: fmt.Sprintf("Consolidated monthly field funding requests and weekly disbursement roll-up for FY %s.", fy),
		Actions: []*screensv1.PageAction{
			{Key: "weekly", Label: "Weekly Requests", Enabled: true, Primary: true, Href: "/fund-requests/weekly"},
			{Key: "disb", Label: "Disbursements", Enabled: true, Href: "/disbursements"},
		},
	}

	strip := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
		Title: "FY " + fy + " Monthly Funding Summary",
		Metrics: []*screensv1.PageMetric{
			{Label: "Monthly Requests", Value: strconv.Itoa(len(mRows)), Note: fmtUGX(totalAmt)},
			{Label: "Weekly Requests Total", Value: fmtUGX(weeklyTotal)},
			{Label: "Disbursed Total", Value: fmtUGX(disbursedTotal)},
		},
	}}}

	blocks := []*screensv1.PageBlock{
		strip,
		{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title:        "Monthly Fund Requests (FY " + fy + ")",
			Columns:      makeCols("Month", "Staff", "Requested Amount", "Status"),
			Rows:         mRows,
			EmptyMessage: "No standalone monthly fund requests recorded for FY " + fy + ".",
		}}},
		{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title:        "Weekly Request Roll-up by Month",
			Columns:      makeCols("Month", "Weekly Requests", "Total Requested", "Total Disbursed"),
			Rows:         rollupRows,
			EmptyMessage: "No weekly fund requests submitted in FY " + fy + ".",
		}}},
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: "/accounts/monthly-request"}, true, nil
}

// Country Planning Oversight's Project Schools table is planningoversight's
// (country_oversight.tables), handed on until it is ported; the analytics
// page this package once drew under its address is gone (docs/migration/189).

// ── 9. Bulk Completion Upload Guide Pages ───────────────────────────────

func (s *Service) bulkCompletionPage(_ context.Context, _ auth.Principal, kind string) (*screensv1.GetPageResponse, bool, error) {
	label := "School Visits"
	if kind == "training" {
		label = "Trainings"
	}
	header := &screensv1.PageHeader{
		Eyebrow:     "Upload Center · Bulk Completion",
		BackLabel:   "Back to Upload Center",
		BackHref:    "/uploads?tab=imports",
		Title:       "Bulk Completion Upload — " + label,
		Description: fmt.Sprintf("Import verified %s completions in batch using the Upload Center structured import workflow.", strings.ToLower(label)),
		Actions: []*screensv1.PageAction{
			{Key: "open", Label: "Open Upload Center", Enabled: true, Primary: true, Href: "/uploads?tab=imports"},
			{Key: "template", Label: "Download School Template CSV", Enabled: true, Download: true, Href: "/schools/upload/template"},
		},
	}
	panel := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: "Bulk Import Checklist",
		Items: []*screensv1.PagePanelItem{
			{Kind: &screensv1.PagePanelItem_Text{Text: "1. Ensure each row includes a valid School ID, Activity Date (YYYY-MM-DD), Salesforce Activity ID, and Responsible Staff email."}},
			{Kind: &screensv1.PagePanelItem_Text{Text: "2. Upload your validated CSV or Excel workbook in the Upload Center under Structured Imports to preview validation errors before committing."}},
			{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
				{Text: "Go to Upload Center (Structured Imports)", Href: "/uploads?tab=imports"},
				{Text: "View SSA Upload Center", Href: "/ssa/upload"},
			}}}},
		},
	}}}
	return &screensv1.GetPageResponse{
		Header:  header,
		Blocks:  []*screensv1.PageBlock{panel},
		WebPath: "/uploads/bulk-completion/" + kind,
	}, true, nil
}

// ── 10. Executive Operations Dashboard (/dashboard fallback) ──────────────

func (s *Service) executiveDashboard(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	fy := strings.TrimSpace(query.Get("fy"))
	if fy == "" {
		fy = schooldirectory.OperationalFY(s.now())
	}
	var schools, coreSchools, clusters, gpsPlaced, actsPlanned, actsDone, openIncidents int64
	_ = s.db.QueryRow(ctx, `
SELECT
  (SELECT count(*) FROM school WHERE deleted_at IS NULL AND COALESCE(operational_status, 'active') NOT IN ('closed', 'inactive', 'merged')),
  (SELECT count(*) FROM school WHERE deleted_at IS NULL AND lower(COALESCE(school_type, '')) LIKE '%core%'),
  (SELECT count(*) FROM cluster WHERE deleted_at IS NULL),
  (SELECT count(*) FROM school s
   LEFT JOIN field_routes.school_location sl ON sl.school_id = s.id AND sl.target = 'school'
   LEFT JOIN field_routes.verified_location vl ON vl.school_id = s.id
   LEFT JOIN school_geo_point gp ON gp.school_id = s.id
   WHERE s.deleted_at IS NULL AND COALESCE(sl.lat, vl.lat, gp.latitude, s.latitude) IS NOT NULL),
  (SELECT count(*) FROM activity WHERE deleted_at IS NULL AND fy = $1 AND status <> 'cancelled'),
  (SELECT count(*) FROM activity WHERE deleted_at IS NULL AND fy = $1 AND status IN ('completed', 'verified', 'approved', 'submitted')),
  (SELECT count(*) FROM admin_system_incident WHERE status NOT IN ('resolved', 'closed'))
`, fy).Scan(&schools, &coreSchools, &clusters, &gpsPlaced, &actsPlanned, &actsDone, &openIncidents)

	compPct := "0%"
	if actsPlanned > 0 {
		compPct = fmt.Sprintf("%d%%", (actsDone*100)/actsPlanned)
	}
	gpsPct := "0%"
	if schools > 0 {
		gpsPct = fmt.Sprintf("%d%%", (gpsPlaced*100)/schools)
	}

	header := &screensv1.PageHeader{
		Eyebrow:     "Operations Dashboard",
		Title:       fmt.Sprintf("%s Dashboard", orDash(p.ActiveRole)),
		Description: fmt.Sprintf("Live PostgreSQL operational health across Uganda · FY %s", fy),
		Actions: []*screensv1.PageAction{
			{Key: "map", Label: "Open Interactive Map", Enabled: true, Primary: true, Href: "/dashboard?view=map&fy=" + url.QueryEscape(fy)},
			{Key: "route", Label: "Smart Route Planner", Enabled: true, Href: "/my-plan/smart-route"},
			{Key: "country", Label: "Country Profile", Enabled: true, Href: "/country-profile?fy=" + url.QueryEscape(fy)},
		},
	}

	strip := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
		Title: "Executive Operations Snapshot (FY " + fy + ")",
		Metrics: []*screensv1.PageMetric{
			{Label: "Operating Schools", Value: commaInt(schools), Note: fmt.Sprintf("%s Core · %s GPS", commaInt(coreSchools), gpsPct), Href: "/schools"},
			{Label: "Active Clusters", Value: commaInt(clusters), Href: "/clusters"},
			{Label: "FY Activities", Value: fmt.Sprintf("%s / %s", commaInt(actsDone), commaInt(actsPlanned)), Note: compPct + " delivered", Href: "/planning-monitor"},
			{Label: "Open System Incidents", Value: commaInt(openIncidents), Href: "/admin-ops/incidents"},
		},
	}}}

	quickLinks := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: "Core Workspaces",
		Items: []*screensv1.PagePanelItem{
			{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
				{Text: "Country Map & Coverage", Href: "/country-map"},
				{Text: "School Directory", Href: "/schools"},
				{Text: "Clusters & Cluster Profiles", Href: "/clusters"},
				{Text: "Projects & Analytics", Href: "/projects"},
				{Text: "Core Schools Oversight", Href: "/core-schools-oversight"},
				{Text: "Planning Monitor", Href: "/planning-monitor"},
				{Text: "Upload Center", Href: "/uploads"},
				{Text: "Reports", Href: "/reports"},
			}}}},
		},
	}}}

	return &screensv1.GetPageResponse{
		Header:  header,
		Blocks:  []*screensv1.PageBlock{strip, quickLinks},
		WebPath: "/dashboard",
	}, true, nil
}
