// Package closurequality is Closure Quality (/analytics/closure-quality):
// which school closures should not yet be believed and why, as the existing
// Analytics section draws it (apps.frontend.views.closure_quality_views,
// apps.schools.closure_analytics and the closure-quality partials) and the
// app's feed reads it. The page is read-only.
//
// The door, the reasons, the thresholds and the page size are exported to
// rules.json by `manage.py export_closure_quality_rules`;
// apps/schools/test_closure_quality_rules_export.py fails when the two differ.
package closurequality

import (
	"context"
	_ "embed"
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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/analytics/closure-quality"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	PageRoles          []string          `json:"page_roles"`
	Reasons            map[string]string `json:"reasons"`
	WeakGroundReasons  []string          `json:"weak_ground_reasons"`
	UnresolvedDup      string            `json:"unresolved_duplicate"`
	StaleDays          int               `json:"stale_recording_days"`
	MaxRows            int               `json:"max_rows"`
	PageSize           int               `json:"page_size"`
	SchoolProfileRoles []string          `json:"school_profile_roles"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.PageRoles) == 0 || len(r.Reasons) == 0 || r.MaxRows == 0 || r.PageSize == 0 {
		panic(fmt.Sprintf("closurequality: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		panic(fmt.Sprintf("closurequality: loading the zone: %v", err))
	}
	return z
}()

// Service answers the page from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// summary is closure_analytics.closure_quality.
type summary struct {
	recorded, stranded, reopened, weak, missing, underReview, removed, stale int
	averageLag                                                               *int
}

type reasonRow struct {
	key                               string
	total, missing, reopened, learned int
}

// closureRow is one closure as the two lists read it.
type closureRow struct {
	schoolPK, code, name, district, reason, dupStatus string
	effective                                         time.Time
	createdDay                                        time.Time
	enrolment                                         *int
	underReview                                       int
	reopenedAt                                        *time.Time
}

// lagSQL is the recording lag as the summary annotates it:
// ExtractDay(created_at - effective_date), the date read as UTC midnight.
const lagSQL = `EXTRACT(DAY FROM (c.created_at - (c.effective_date::timestamp AT TIME ZONE 'UTC')))::int`

// Build answers Path.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	period := query.Get("period")
	if period == "" {
		period = "all"
	}
	fy := schooldirectory.OperationalFY(s.now())
	inPeriod, args := "TRUE", []any{}
	if period == "fy" {
		n, _ := strconv.Atoi(fy)
		args = append(args, time.Date(n-1, 10, 1, 0, 0, 0, 0, time.UTC), time.Date(n, 10, 1, 0, 0, 0, 0, time.UTC))
		inPeriod = "c.effective_date >= $1::date AND c.effective_date < $2::date"
	}
	sum, err := s.summary(ctx, inPeriod, args)
	if err != nil {
		return nil, true, err
	}
	var reasons []reasonRow
	var attention, reopened []closureRow
	if sum.recorded > 0 {
		if reasons, err = s.byReason(ctx, inPeriod, args); err != nil {
			return nil, true, err
		}
		if attention, err = s.closures(ctx, `(s.duplicate_status = $3 OR c.reason_category = ANY($1) OR c.enrollment_at_closure IS NULL
  OR c.locked_activities_for_review > 0 OR `+lagSQL+` > $2) AND c.reopened_at IS NULL`, `c.effective_date DESC`,
			rules.WeakGroundReasons, rules.StaleDays, rules.UnresolvedDup); err != nil {
			return nil, true, err
		}
		if reopened, err = s.closures(ctx, `c.reopened_at IS NOT NULL`, `c.reopened_at DESC`); err != nil {
			return nil, true, err
		}
	}
	return page(p, period, fy, sum, reasons, attention, reopened, query), true, nil
}

func (s *Service) summary(ctx context.Context, inPeriod string, args []any) (summary, error) {
	var out summary
	var avg *float64
	n := len(args)
	a := append(append([]any{}, args...), rules.UnresolvedDup, rules.WeakGroundReasons, rules.StaleDays)
	err := s.db.QueryRow(ctx, fmt.Sprintf(`
SELECT count(*), count(*) FILTER (WHERE s.duplicate_status = $%[2]d), count(*) FILTER (WHERE c.reopened_at IS NOT NULL),
  count(*) FILTER (WHERE c.reason_category = ANY($%[3]d)), count(*) FILTER (WHERE c.enrollment_at_closure IS NULL),
  COALESCE(sum(c.enrollment_at_closure) FILTER (WHERE c.reopened_at IS NULL), 0),
  count(*) FILTER (WHERE c.locked_activities_for_review > 0),
  avg(%[1]s)::float8, count(*) FILTER (WHERE %[1]s > $%[4]d)
FROM school_closure c JOIN school s ON s.id = c.school_id WHERE `+inPeriod, lagSQL, n+1, n+2, n+3), a...).Scan(
		&out.recorded, &out.stranded, &out.reopened, &out.weak, &out.missing, &out.removed, &out.underReview, &avg, &out.stale)
	if err != nil {
		return out, fmt.Errorf("closurequality: reading the summary: %w", err)
	}
	if avg != nil {
		v := int(math.RoundToEven(*avg))
		out.averageLag = &v
	}
	return out, nil
}

func (s *Service) byReason(ctx context.Context, inPeriod string, args []any) ([]reasonRow, error) {
	rows, err := s.db.Query(ctx, `
SELECT c.reason_category, count(*), count(*) FILTER (WHERE c.enrollment_at_closure IS NULL),
  count(*) FILTER (WHERE c.reopened_at IS NOT NULL), COALESCE(sum(c.enrollment_at_closure), 0)
FROM school_closure c WHERE `+inPeriod+` GROUP BY c.reason_category ORDER BY count(*) DESC`, args...)
	if err != nil {
		return nil, fmt.Errorf("closurequality: reading the reasons: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (reasonRow, error) {
		var x reasonRow
		return x, r.Scan(&x.key, &x.total, &x.missing, &x.reopened, &x.learned)
	})
}

// closures are needs_attention and reopenings: the closures where match
// holds, in order, the first MAX_ROWS.
func (s *Service) closures(ctx context.Context, match, order string, args ...any) ([]closureRow, error) {
	args = append(args, rules.MaxRows)
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT s.id, COALESCE(s.school_id, ''), s.name, COALESCE(d.name, ''), c.reason_category, COALESCE(s.duplicate_status, ''),
  c.effective_date, (c.created_at AT TIME ZONE 'UTC')::date, c.enrollment_at_closure, c.locked_activities_for_review, c.reopened_at
FROM school_closure c JOIN school s ON s.id = c.school_id LEFT JOIN district d ON d.id = s.district_id
WHERE %s ORDER BY %s LIMIT $%d`, match, order, len(args)), args...)
	if err != nil {
		return nil, fmt.Errorf("closurequality: reading the closures: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (closureRow, error) {
		var x closureRow
		return x, r.Scan(&x.schoolPK, &x.code, &x.name, &x.district, &x.reason, &x.dupStatus,
			&x.effective, &x.createdDay, &x.enrolment, &x.underReview, &x.reopenedAt)
	})
}

// intcomma is |intcomma.
func intcomma(n int) string {
	s := strconv.Itoa(n)
	neg := strings.HasPrefix(s, "-")
	s = strings.TrimPrefix(s, "-")
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	if neg {
		return "-" + s
	}
	return s
}

func dashOr(n int) string {
	if n == 0 {
		return "—"
	}
	return intcomma(n)
}

func reasonLabel(key string) string {
	if l, ok := rules.Reasons[key]; ok {
		return l
	}
	return key
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func panel(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
}

func columns(numeric []bool, labels ...string) []*screensv1.PageColumn {
	out := make([]*screensv1.PageColumn, len(labels))
	for i, l := range labels {
		out[i] = &screensv1.PageColumn{Label: l, Numeric: numeric != nil && numeric[i]}
	}
	return out
}

// paged is a table's rows a page at a time, with its pager past one page.
func paged(t *screensv1.PageTable, rows []*screensv1.PageRow, param string, query url.Values) []*screensv1.PageBlock {
	number, pages := closedschools.PageOf(query.Get(param), len(rows), rules.PageSize)
	t.Rows = rows[min((number-1)*rules.PageSize, len(rows)):min(number*rules.PageSize, len(rows))]
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		out = append(out, closedschools.PagerPanel(param, number, pages, len(rows), rules.PageSize, query, nil))
	}
	return out
}
