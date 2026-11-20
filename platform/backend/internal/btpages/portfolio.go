package btpages

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/btportfolio"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The two school-level portfolios.
const (
	FinancePath    = "/business-transformation/business-accounting-finance"
	GovernmentPath = "/business-transformation/government-requirements"
)

const defaultPortfolioPageSize = 50

// portfolioKind is one portfolio's words.
type portfolioKind struct {
	path, intervention, title, description, listTitle, listHelper, stripTitle string
	finance                                                                   bool
}

func kindOf(path string) portfolioKind {
	p := btportfolio.Rules.Portfolio
	if path == FinancePath {
		return portfolioKind{path: path, intervention: p.FinancialHealth, finance: true, title: "Business Accounting & Finance",
			description: "A school-centred view of BAFF and Financial Health support, verified practice adoption and SSA performance.",
			listTitle:   "Financial Health portfolio", stripTitle: "Financial health headline",
			listHelper: "Performance compares the first and latest confirmed Financial Health SSA; training and verified practice adoption remain separate."}
	}
	return portfolioKind{path: path, intervention: p.GovernmentRequirement, title: "Government Requirements",
		description: "A school-centred view of registration, taxation and NSSF support, evidence verification and SSA performance.",
		listTitle:   "Government Requirements portfolio", stripTitle: "Government requirements headline",
		listHelper: "Schools supported for Government Requirements, with verified compliance evidence kept distinct from SSA improvement."}
}

// performance is _portfolio_performance for one school.
type performance struct {
	baseline, latest     float64
	baseDate, latestDate time.Time
	movement             float64
	label, tone          string
	assessed             bool
}

// portfolioSchool is one listed school.
type portfolioSchool struct {
	id, code, name, district, region, owner, schoolType string
	enrollment                                          *int
}

func (s *Service) portfolio(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if !btportfolio.Opens(p.ActiveRole, path) {
		return nil, true, pagegate.ErrNotAvailable
	}
	k := kindOf(path)
	now := s.now()
	keys := append(slices.Clone(btportfolio.FilterKeys), "per_page")
	f := btportfolio.ReadFilters(query, keys)
	fy, ok := fyOf(f, now)
	if !ok {
		return nil, false, nil
	}
	today := now.In(btportfolio.Zone()).Format(time.DateOnly)
	where, a, err := s.portfolioWhere(ctx, p, k, f, today, now)
	if err != nil {
		return nil, true, err
	}
	rows, err := s.db.Query(ctx, `SELECT s.id FROM school s LEFT JOIN district d ON d.id = s.district_id LEFT JOIN region g ON g.id = s.region_id
WHERE `+where+` ORDER BY s.name, s.school_id`, *a...)
	if err != nil {
		return nil, true, fmt.Errorf("btpages: reading the portfolio: %w", err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, true, fmt.Errorf("btpages: reading the portfolio: %w", err)
	}
	if ids == nil {
		ids = []string{}
	}
	perf, err := s.performances(ctx, ids, fy, k.intervention)
	if err != nil {
		return nil, true, err
	}
	size := defaultPortfolioPageSize
	if n, err := strconv.Atoi(f["per_page"]); err == nil && slices.Contains(btportfolio.Rules.Portfolio.PageSizes, n) {
		size = n
	}
	number, _ := djangoPage(f["page"], len(ids), size)
	pageIDs := ids[min((number-1)*size, len(ids)):min(number*size, len(ids))]
	records, err := s.portfolioRecords(ctx, p, k, pageIDs, perf, fy, today)
	if err != nil {
		return nil, true, err
	}
	strip, err := s.portfolioStrip(ctx, k, ids, perf)
	if err != nil {
		return nil, true, err
	}
	filters, err := s.portfolioFilters(ctx, k, ids, f, number, size)
	if err != nil {
		return nil, true, err
	}
	header := &screensv1.PageHeader{Eyebrow: "Uganda Business Transformation", Title: k.title, Description: k.description}
	blocks := append(nav(p.ActiveRole), filters, strip)
	count := strconv.Itoa(len(ids)) + " school"
	if len(ids) != 1 {
		count += "s"
	}
	blocks = append(blocks, panel(k.listTitle+" ("+count+")", k.listHelper, text("Select a school to inspect its full support journey")))
	blocks = append(blocks, records...)
	if len(ids) == 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: "No schools match this support portfolio Schools appear after a relevant partner assignment, support activity or confirmed SSA recommendation."}})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Pager{Pager: &screensv1.PagePager{}}})
	aside, err := s.portfolioAside(ctx, k)
	if err != nil {
		return nil, true, err
	}
	blocks = append(blocks, aside)
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: path}, true, nil
}

// djangoPage is Paginator.get_page: anything not a whole number is the
// first page, a number outside the pages the last.
func djangoPage(raw string, total, size int) (int, int) {
	pages := max(1, (total+size-1)/size)
	n, err := strconv.Atoi(strings.TrimSpace(raw))
	switch {
	case raw == "" || err != nil:
		return 1, pages
	case n < 1 || n > pages:
		return pages, pages
	}
	return n, pages
}

// portfolioWhere is _intervention_school_queryset and the filters, on
// school s (district d, region g).
func (s *Service) portfolioWhere(ctx context.Context, p auth.Principal, k portfolioKind, f btportfolio.Filters, today string, now time.Time) (string, *btportfolio.Args, error) {
	a := &btportfolio.Args{}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return "", nil, fmt.Errorf("btpages: resolving the reader's scope: %w", err)
	}
	if btportfolio.SummaryOnly(p.ActiveRole) || scope.SummaryOnly {
		return "FALSE", a, nil
	}
	in := a.Add(k.intervention)
	live := a.Add([]string{"assigned", "pending_scheduling", "scheduled"})
	where := `s.deleted_at IS NULL AND (
  EXISTS (SELECT 1 FROM partner_assignment pa WHERE pa.school_id = s.id AND pa.focus_intervention = ` + in + ` AND pa.status = ANY(` + live + `))
  OR EXISTS (SELECT 1 FROM activity v WHERE v.school_id = s.id AND v.focus_intervention = ` + in + ` AND v.deleted_at IS NULL)
  OR EXISTS (SELECT 1 FROM bt_case c JOIN bt_case_recommendation r ON r.case_id = c.id
    WHERE c.school_id = s.id AND c.deleted_at IS NULL AND r.source_intervention = ` + in + `))`
	if !btportfolio.UgandaWide(p.ActiveRole) {
		ids := scope.SchoolIDs
		if ids == nil {
			ids = []string{}
		}
		where += " AND s.id = ANY(" + a.Add(ids) + ")"
	}
	if q := f["q"]; q != "" {
		like := a.Add("%" + strings.NewReplacer(`\`, `\\`, "%", `\%`, "_", `\_`).Replace(q) + "%")
		where += " AND (UPPER(s.name::text) LIKE UPPER(" + like + ") OR UPPER(s.school_id::text) LIKE UPPER(" + like +
			") OR UPPER(d.name::text) LIKE UPPER(" + like + ") OR UPPER(g.name::text) LIKE UPPER(" + like +
			") OR UPPER(s.account_owner_name_raw::text) LIKE UPPER(" + like + "))"
	}
	if f["region"] != "" {
		where += " AND s.region_id = " + a.Add(f["region"])
	}
	if f["district"] != "" {
		where += " AND s.district_id = " + a.Add(f["district"])
	}
	if f["partner"] != "" {
		where += " AND EXISTS (SELECT 1 FROM partner_assignment pa WHERE pa.school_id = s.id AND pa.partner_id = " + a.Add(f["partner"]) +
			" AND pa.focus_intervention = " + in + ")"
	}
	rules := btportfolio.Rules.Portfolio
	switch f["support_status"] {
	case "assigned":
		where += " AND EXISTS (SELECT 1 FROM partner_assignment pa WHERE pa.school_id = s.id AND pa.focus_intervention = " + in +
			" AND pa.status = ANY(" + live + "))"
	case "delivered":
		where += " AND EXISTS (SELECT 1 FROM activity v WHERE v.school_id = s.id AND v.focus_intervention = " + in +
			" AND v.status = ANY(" + a.Add(rules.DeliveredStatuses) + "))"
	case "follow_up_due":
		where += " AND EXISTS (SELECT 1 FROM activity v WHERE v.school_id = s.id AND v.focus_intervention = " + in +
			" AND v.status = ANY(" + a.Add(rules.OpenSupportStatuses) + ") AND v.planned_date < " + a.Add(today) + "::date)"
	}
	return where, a, nil
}

// performances is _portfolio_performance over the confirmed SSA scores of
// the year before and this year.
func (s *Service) performances(ctx context.Context, ids []string, fy, intervention string) (map[string]performance, error) {
	n, _ := strconv.Atoi(fy)
	rows, err := s.db.Query(ctx, `SELECT r.school_id, sc.score::float8, r.date_of_ssa FROM ssa_score sc JOIN ssa_record r ON r.id = sc.ssa_record_id
WHERE r.school_id = ANY($1) AND r.verification_status = 'confirmed' AND r.deleted_at IS NULL AND r.fy = ANY($2) AND sc.intervention = $3
ORDER BY r.school_id, r.date_of_ssa`, ids, []string{strconv.Itoa(n - 1), fy}, intervention)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the SSA scores: %w", err)
	}
	defer rows.Close()
	out := map[string]performance{}
	for rows.Next() {
		var id string
		var score float64
		var at time.Time
		if err := rows.Scan(&id, &score, &at); err != nil {
			return nil, fmt.Errorf("btpages: reading the SSA scores: %w", err)
		}
		x, ok := out[id]
		if !ok {
			x = performance{baseline: score, baseDate: at, assessed: true}
		}
		x.latest, x.latestDate = score, at
		out[id] = x
	}
	for id, x := range out {
		x.movement = math.RoundToEven((x.latest-x.baseline)*10) / 10
		switch {
		case x.baseDate.Equal(x.latestDate):
			x.label, x.tone = "Baseline only", "neutral"
		case x.movement >= 1:
			x.label, x.tone = "Improving", "success"
		case x.movement <= -1:
			x.label, x.tone = "Declining", "danger"
		default:
			x.label, x.tone = "Stable", "info"
		}
		out[id] = x
	}
	return out, rows.Err()
}

// signed is |stringformat:'+g'.
func signed(v float64) string {
	t := strconv.FormatFloat(v, 'g', -1, 64)
	if v >= 0 && !strings.HasPrefix(t, "-") {
		return "+" + t
	}
	return t
}

// floatformatOne is |floatformat:"-1": one decimal, dropped when it is 0.
func floatformatOne(v float64) string {
	t := strconv.FormatFloat(math.Round(v*10)/10, 'f', 1, 64)
	return strings.TrimSuffix(t, ".0")
}

func fact(label, value, tone string) *screensv1.PageFact {
	return &screensv1.PageFact{Label: label, Value: closedschools.Collapse(value), Tone: tone}
}

func goodOrCaution(ok bool) string {
	if ok {
		return "good"
	}
	return "caution"
}

func dmy(t *time.Time, none string) string {
	if t == nil {
		return none
	}
	return t.Format("02 Jan 2006")
}

// portfolioRecords is each school's row on the page shown.
func (s *Service) portfolioRecords(ctx context.Context, p auth.Principal, k portfolioKind, ids []string, perf map[string]performance, fy, today string) ([]*screensv1.PageBlock, error) {
	if len(ids) == 0 {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `SELECT s.id, COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(d.name, '—'), COALESCE(g.name, '—'),
  COALESCE(NULLIF(s.account_owner_name_raw, ''), 'Unassigned'), COALESCE(s.school_type, ''), s.enrollment
FROM school s LEFT JOIN district d ON d.id = s.district_id LEFT JOIN region g ON g.id = s.region_id WHERE s.id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the portfolio schools: %w", err)
	}
	schools, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (portfolioSchool, error) {
		var x portfolioSchool
		return x, r.Scan(&x.id, &x.code, &x.name, &x.district, &x.region, &x.owner, &x.schoolType, &x.enrollment)
	})
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the portfolio schools: %w", err)
	}
	byID := map[string]portfolioSchool{}
	for _, x := range schools {
		byID[x.id] = x
	}
	partners, err := s.assignments(ctx, ids, k.intervention)
	if err != nil {
		return nil, err
	}
	work, err := s.support(ctx, ids, k.intervention, fy, today)
	if err != nil {
		return nil, err
	}
	extra, err := s.evidence(ctx, k, ids)
	if err != nil {
		return nil, err
	}
	rules := btportfolio.Rules.Portfolio
	blocks := []*screensv1.PageBlock{}
	for _, id := range ids {
		sc := byID[id]
		w, pa, pf := work[id], partners[id], perf[id]
		partnerName, partnerState := "Not assigned", "—"
		if pa.name != "" || pa.status != "" {
			partnerName = pa.name
			partnerState = btportfolio.Label(rules.AssignmentStatuses, pa.status)
		}
		performanceText, performanceTone := "Not assessed", "caution"
		if pf.assessed {
			performanceText = pf.label + " (" + signed(pf.movement) + ")"
			performanceTone = map[string]string{"success": "good", "danger": "caution"}[pf.tone]
		}
		delivered := strconv.Itoa(w.delivered) + " support action"
		if w.delivered != 1 {
			delivered += "s"
		}
		facts := []*screensv1.PageFact{fact("District", sc.district, ""), fact("Owner", sc.owner, ""), fact("Partner", partnerName, ""),
			fact("Delivered", delivered, goodOrCaution(w.delivered > 0)), fact("IA verified", strconv.Itoa(w.verified), goodOrCaution(w.verified > 0)),
			extra[id].summary, fact("Performance", performanceText, performanceTone)}
		enrollment := "—"
		if sc.enrollment != nil {
			enrollment = strconv.Itoa(*sc.enrollment)
		}
		next := dmy(w.next, "Not scheduled")
		if w.overdue {
			next += " · overdue"
		}
		baseline, latest := "—", "—"
		if pf.assessed {
			baseline, latest = floatformatOne(pf.baseline), floatformatOne(pf.latest)
		}
		details := []*screensv1.PageFact{fact("Region:", sc.region, ""), fact("School type:", btportfolio.Label(rules.SchoolTypes, sc.schoolType), ""),
			fact("Enrollment:", enrollment, ""), fact("Partner state:", partnerState, ""), fact("Latest support:", dmy(w.last, "Not delivered"), ""),
			fact("Next support:", next, ""), fact("Baseline SSA:", baseline, ""), fact("Latest SSA:", latest, "")}
		details = append(details, extra[id].details...)
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Record{Record: &screensv1.PageRecord{
			Title: closedschools.Collapse(sc.name), Href: "/schools/" + sc.code, Facts: facts,
			Details: []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Facts{Facts: &screensv1.PageFacts{Facts: details}}}}}}})
	}
	return blocks, nil
}

type assignment struct{ name, status string }

// assignments is each school's latest live assignment for the intervention.
func (s *Service) assignments(ctx context.Context, ids []string, intervention string) (map[string]assignment, error) {
	rows, err := s.db.Query(ctx, `SELECT DISTINCT ON (pa.school_id) pa.school_id, COALESCE(pr.name, ''), pa.status
FROM partner_assignment pa LEFT JOIN partner pr ON pr.id = pa.partner_id
WHERE pa.school_id = ANY($1) AND pa.focus_intervention = $2 AND pa.status IS DISTINCT FROM 'returned_to_staff'
ORDER BY pa.school_id, pa.created_at DESC`, ids, intervention)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the partner assignments: %w", err)
	}
	defer rows.Close()
	out := map[string]assignment{}
	for rows.Next() {
		var id string
		var x assignment
		if err := rows.Scan(&id, &x.name, &x.status); err != nil {
			return nil, fmt.Errorf("btpages: reading the partner assignments: %w", err)
		}
		out[id] = x
	}
	return out, rows.Err()
}

type supportWork struct {
	delivered, verified int
	last, next          *time.Time
	overdue             bool
}

// support is each school's support activity this year.
func (s *Service) support(ctx context.Context, ids []string, intervention, fy, today string) (map[string]supportWork, error) {
	rules := btportfolio.Rules.Portfolio
	rows, err := s.db.Query(ctx, `SELECT school_id, COALESCE(status, ''), COALESCE(ia_verification_status, ''), planned_date FROM activity
WHERE school_id = ANY($1) AND focus_intervention = $2 AND fy = $3 AND deleted_at IS NULL AND NOT COALESCE(status IN ('cancelled', 'rejected'), FALSE)
ORDER BY school_id, planned_date DESC NULLS FIRST, created_at DESC`, ids, intervention, fy)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the support work: %w", err)
	}
	defer rows.Close()
	out := map[string]supportWork{}
	todayDay, _ := time.Parse(time.DateOnly, today)
	for rows.Next() {
		var id, status, ia string
		var planned *time.Time
		if err := rows.Scan(&id, &status, &ia, &planned); err != nil {
			return nil, fmt.Errorf("btpages: reading the support work: %w", err)
		}
		w := out[id]
		if slices.Contains(rules.DeliveredStatuses, status) {
			if w.delivered == 0 {
				w.last = planned
			}
			w.delivered++
		}
		if status == "ia_verified" || ia == "confirmed" {
			w.verified++
		}
		if slices.Contains(rules.OpenSupportStatuses, status) && planned != nil {
			if planned.Before(todayDay) {
				w.overdue = true
			}
			if w.next == nil || planned.Before(*w.next) {
				w.next = planned
			}
		}
		out[id] = w
	}
	return out, rows.Err()
}

type evidenceCells struct {
	summary *screensv1.PageFact
	details []*screensv1.PageFact
}

// evidence is the practice adoption (finance) or compliance (government)
// each school's case records.
func (s *Service) evidence(ctx context.Context, k portfolioKind, ids []string) (map[string]evidenceCells, error) {
	out := map[string]evidenceCells{}
	if k.finance {
		rows, err := s.db.Query(ctx, `SELECT DISTINCT ON (c.school_id) c.school_id, a.practices, a.verification_status
FROM bt_financial_practice_assessment a JOIN bt_case c ON c.id = a.case_id WHERE c.school_id = ANY($1)
ORDER BY c.school_id, a.assessed_on DESC, a.created_at DESC`, ids)
		if err != nil {
			return nil, fmt.Errorf("btpages: reading the practice assessments: %w", err)
		}
		found := map[string][2]any{}
		for rows.Next() {
			var id, status string
			var raw []byte
			if err := rows.Scan(&id, &raw, &status); err != nil {
				rows.Close()
				return nil, fmt.Errorf("btpages: reading the practice assessments: %w", err)
			}
			var practices map[string]any
			_ = json.Unmarshal(raw, &practices)
			found[id] = [2]any{practices, status == "verified"}
		}
		rows.Close()
		for _, id := range ids {
			practices, _ := found[id][0].(map[string]any)
			verified, _ := found[id][1].(bool)
			adopted := 0
			for _, v := range practices {
				if v == true {
					adopted++
				}
			}
			summary, evidence := "Not assessed", "Not assessed"
			if len(practices) > 0 {
				summary = strconv.Itoa(adopted) + "/" + strconv.Itoa(len(practices)) + " adopted"
				evidence = "Awaiting IA verification"
			}
			if verified {
				evidence = "IA verified"
			}
			out[id] = evidenceCells{summary: fact("Practices", summary, goodOrCaution(verified)),
				details: []*screensv1.PageFact{fact("Practice evidence:", evidence, "")}}
		}
		return out, nil
	}
	rows, err := s.db.Query(ctx, `SELECT c.school_id, a.status, a.ia_status, a.expiry_date FROM bt_school_compliance_assessment a
JOIN bt_case c ON c.id = a.case_id WHERE c.school_id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the compliance assessments: %w", err)
	}
	type tally struct {
		compliant, action, awaiting, unknown int
		nearest                              *time.Time
	}
	found := map[string]tally{}
	for rows.Next() {
		var id, status, ia string
		var expiry *time.Time
		if err := rows.Scan(&id, &status, &ia, &expiry); err != nil {
			rows.Close()
			return nil, fmt.Errorf("btpages: reading the compliance assessments: %w", err)
		}
		t := found[id]
		if ia == "verified" {
			switch status {
			case "compliant":
				t.compliant++
			case "action_required", "expired":
				t.action++
			}
			if expiry != nil && (t.nearest == nil || expiry.Before(*t.nearest)) {
				t.nearest = expiry
			}
		}
		if ia == "pending" {
			t.awaiting++
		}
		if status == "not_assessed" || status == "unknown" {
			t.unknown++
		}
		found[id] = t
	}
	rows.Close()
	for _, id := range ids {
		t := found[id]
		tone := ""
		switch {
		case t.action > 0:
			tone = "caution"
		case t.compliant > 0:
			tone = "good"
		}
		out[id] = evidenceCells{summary: fact("Compliance", strconv.Itoa(t.compliant)+" verified · "+strconv.Itoa(t.action)+" action", tone),
			details: []*screensv1.PageFact{fact("Awaiting evidence review:", strconv.Itoa(t.awaiting), ""),
				fact("Unknown / not assessed:", strconv.Itoa(t.unknown), ""), fact("Nearest expiry:", dmy(t.nearest, "—"), "")}}
	}
	return out, nil
}

// portfolioStrip is the four headline tiles over the whole portfolio.
func (s *Service) portfolioStrip(ctx context.Context, k portfolioKind, ids []string, perf map[string]performance) (*screensv1.PageBlock, error) {
	tile := func(label string, n int, note string) *screensv1.PageMetric {
		return &screensv1.PageMetric{Label: label, Value: strconv.Itoa(n), Note: note}
	}
	metrics := []*screensv1.PageMetric{tile("Portfolio schools", len(ids), "Assigned, supported or SSA-referred")}
	if k.finance {
		var assigned, verified int
		if err := s.db.QueryRow(ctx, `SELECT
  (SELECT count(DISTINCT school_id) FROM partner_assignment WHERE school_id = ANY($1) AND focus_intervention = $2 AND status IS DISTINCT FROM 'returned_to_staff'),
  (SELECT count(DISTINCT c.school_id) FROM bt_financial_practice_assessment a JOIN bt_case c ON c.id = a.case_id
     WHERE c.school_id = ANY($1) AND a.verification_status = 'verified')`, ids, k.intervention).Scan(&assigned, &verified); err != nil {
			return nil, fmt.Errorf("btpages: counting the finance portfolio: %w", err)
		}
		declining := 0
		for _, x := range perf {
			if x.label == "Declining" {
				declining++
			}
		}
		metrics = append(metrics, tile("Partner assigned", assigned, "Active BAFF assignments"),
			tile("Practice verified", verified, "IA-verified adoption"), tile("Declining", declining, "Needs follow-up"))
	} else {
		var compliant, action, awaiting int
		if err := s.db.QueryRow(ctx, `SELECT
  count(DISTINCT c.school_id) FILTER (WHERE a.status = 'compliant' AND a.ia_status = 'verified'),
  count(DISTINCT c.school_id) FILTER (WHERE a.status IN ('action_required', 'expired') AND a.ia_status = 'verified'),
  count(*) FILTER (WHERE a.ia_status = 'pending')
FROM bt_school_compliance_assessment a JOIN bt_case c ON c.id = a.case_id WHERE c.school_id = ANY($1)`, ids).Scan(&compliant, &action, &awaiting); err != nil {
			return nil, fmt.Errorf("btpages: counting the compliance portfolio: %w", err)
		}
		metrics = append(metrics, tile("Compliance verified", compliant, "At least one verified requirement"),
			tile("Action required", action, "Verified gap or expiry"), tile("Awaiting verification", awaiting, "Evidence pending IA review"))
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: k.stripTitle, Metrics: metrics}}}, nil
}

// portfolioFilters is school_portfolio_filters.html as the feed reads it.
func (s *Service) portfolioFilters(ctx context.Context, k portfolioKind, ids []string, f btportfolio.Filters, number, size int) (*screensv1.PageBlock, error) {
	options := func(sql, blank, chosen string, args ...any) (*screensv1.PageFilter, error) {
		rows, err := s.db.Query(ctx, sql, args...)
		if err != nil {
			return nil, fmt.Errorf("btpages: reading the filter choices: %w", err)
		}
		defer rows.Close()
		out := &screensv1.PageFilter{Options: []*screensv1.PageFilterOption{{Label: blank}}}
		for rows.Next() {
			var id, name string
			if err := rows.Scan(&id, &name); err != nil {
				return nil, fmt.Errorf("btpages: reading the filter choices: %w", err)
			}
			out.Options = append(out.Options, &screensv1.PageFilterOption{Value: id, Label: name})
			if id == chosen {
				out.Value = id
			}
		}
		return out, rows.Err()
	}
	region, err := options(`SELECT id, name FROM region WHERE id IN (SELECT region_id FROM school WHERE id = ANY($1)) ORDER BY name`, "All regions", f["region"], ids)
	if err != nil {
		return nil, err
	}
	district, err := options(`SELECT id, name FROM district WHERE id IN (SELECT district_id FROM school WHERE id = ANY($1)) ORDER BY name`, "All districts", f["district"], ids)
	if err != nil {
		return nil, err
	}
	partner, err := options(`SELECT id, name FROM partner WHERE id IN (SELECT partner_id FROM partner_assignment
  WHERE school_id = ANY($1) AND focus_intervention = $2 AND NOT (status = ANY($3))) ORDER BY name`, "All partners", f["partner"],
		ids, k.intervention, btportfolio.Rules.Portfolio.ReleasedStatuses)
	if err != nil {
		return nil, err
	}
	region.Name, region.Label = "region", "Region"
	district.Name, district.Label = "district", "District"
	partner.Name, partner.Label = "partner", "Partner"
	support := &screensv1.PageFilter{Name: "support_status", Label: "Support", Options: []*screensv1.PageFilterOption{{Label: "All support states"},
		{Value: "assigned", Label: "Partner assigned"}, {Value: "delivered", Label: "Support delivered"}, {Value: "follow_up_due", Label: "Follow-up overdue"}}}
	if slices.Contains([]string{"assigned", "delivered", "follow_up_due"}, f["support_status"]) {
		support.Value = f["support_status"]
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{region, district, partner, support},
		Hidden:  map[string]string{"page": strconv.Itoa(number), "per_page": strconv.Itoa(size)}}}}, nil
}

// portfolioAside is the card beside the list.
func (s *Service) portfolioAside(ctx context.Context, k portfolioKind) (*screensv1.PageBlock, error) {
	if k.finance {
		return panel("What this portfolio measures", "Attendance is an output. Practice adoption and SSA movement show whether support is changing school performance.",
			text("Partner assigned"), text("The school has live BAFF or Financial Health work with a delivery partner."),
			text("Practice adoption"), text("Budgeting, cashbook, reconciliations and controls recorded separately from training."),
			text("Performance"), text("Movement between confirmed Financial Health SSA assessments."),
			text("BT reads this portfolio and only writes the Salesforce Loan ID confirmation on the Loans page. The responsible CCEO or PL plans every training and visit.")), nil
	}
	rows, err := s.db.Query(ctx, `SELECT label, COALESCE(NULLIF(responsible_authority, ''), 'Uganda authority') FROM bt_compliance_requirement
WHERE country_code = 'UG' AND active ORDER BY label`)
	if err != nil {
		return nil, fmt.Errorf("btpages: reading the requirements: %w", err)
	}
	defer rows.Close()
	links := []*screensv1.PageLink{}
	for rows.Next() {
		var label, authority string
		if err := rows.Scan(&label, &authority); err != nil {
			return nil, fmt.Errorf("btpages: reading the requirements: %w", err)
		}
		// The requirement and its authority are two lines: read apart.
		links = append(links, &screensv1.PageLink{Text: closedschools.Collapse(feeddom.JoinParts(label, authority))})
	}
	items := []*screensv1.PagePanelItem{}
	if len(links) > 0 {
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}})
	} else {
		items = append(items, text("No active Uganda requirements are configured."))
	}
	items = append(items, text("BT reads this portfolio and only writes the Salesforce Loan ID confirmation on the Loans page. The responsible CCEO or PL plans every training and visit; IA verifies evidence."))
	return panel("Uganda requirements", "Missing evidence remains Unknown or Not Assessed; it is never silently presented as non-compliance.", items...), rows.Err()
}
