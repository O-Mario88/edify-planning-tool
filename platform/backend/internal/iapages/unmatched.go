package iapages

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pynum"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// UnmatchedPath is the Unmatched SSA queue
// (extended_views.unmatched_ssa_queue_view over
// unmatched_service.get_unmatched_queue, pages/admin/unmatched_ssa_queue.html):
// the imported SSA rows no school matched, in the reader's country, by the
// filters asked, newest first, fifty a page. Linking, creating a school,
// holding and ignoring stay the existing page's.
const UnmatchedPath = "/ssa/unmatched"

// unmatchedFilters are the queue's filters, in the order its pager carries
// them.
var unmatchedFilters = []string{"status", "batch", "district", "school_id", "min_confidence", "date_from", "date_to"}

type unmatchedRow struct {
	schoolID, name, district, date, reason, status string
	suggestedID, suggested, suggestedCode          string
	confidence                                     *float64
	hasSuggestion                                  bool
}

// unmatchedReach is unmatched_rows_in_reach(statuses=None) over `u`: a
// country-bound reader's rows placed in their country by the batch's
// uploader or the suggested school.
func unmatchedReach(scope schooldirectory.Scope, args *[]any) string {
	if !countryBound(scope) {
		return "TRUE"
	}
	*args = append(*args, scope.CountryID)
	n := len(*args)
	return fmt.Sprintf(`(u.batch_id IN (SELECT id FROM ssa_import_batch WHERE uploaded_by IN %s)
  OR u.suggested_school_id IN (SELECT ss.id FROM school ss WHERE %s))`, countryUsers(n), registry.SchoolIn("ss", fmt.Sprintf("ARRAY[$%d::text]", n)))
}

func (s *Service) unmatched(ctx context.Context, p auth.Principal, role Role, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	f := map[string]string{}
	for _, k := range unmatchedFilters {
		f[k] = strings.TrimSpace(query.Get(k))
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return nil, true, err
	}
	var args []any
	arg := func(v any) string { args = append(args, v); return "$" + strconv.Itoa(len(args)) }
	where := unmatchedReach(scope, &args)
	if f["status"] != "" {
		where += " AND u.status = " + arg(f["status"])
	} else {
		where += " AND u.status = ANY(" + arg(rules.Unmatched.DefaultStatuses) + ")"
	}
	if f["batch"] != "" {
		where += " AND u.batch_id = " + arg(f["batch"])
	}
	if f["district"] != "" {
		where += " AND UPPER(u.district_raw::text) LIKE UPPER(" + arg(likeOf(f["district"])) + ")"
	}
	if f["school_id"] != "" {
		where += " AND UPPER(u.school_id::text) LIKE UPPER(" + arg(likeOf(f["school_id"])) + ")"
	}
	if raw := query.Get("min_confidence"); raw != "" {
		v, err := strconv.ParseFloat(strings.TrimSpace(raw), 64)
		if err != nil {
			// float() refuses it and the existing page fails.
			return nil, false, nil
		}
		where += " AND u.match_confidence >= " + arg(v)
	}
	for _, d := range [][2]string{{"date_from", ">="}, {"date_to", "<="}} {
		if f[d[0]] == "" {
			continue
		}
		if !plainDate(f[d[0]]) {
			return nil, false, nil
		}
		where += " AND (u.created_at AT TIME ZONE '" + zone.String() + "')::date " + d[1] + " " + arg(f[d[0]]) + "::date"
	}
	rows, err := s.db.Query(ctx, `
SELECT u.school_id, COALESCE(u.school_name_raw, ''), COALESCE(u.district_raw, ''), COALESCE(u.date_of_ssa, 'None'),
  COALESCE(u.reason, 'None'), u.status, ss.id IS NOT NULL, COALESCE(ss.id, ''), COALESCE(ss.name, ''),
  COALESCE(ss.school_id, 'None'), u.match_confidence
FROM unmatched_ssa_record u LEFT JOIN school ss ON ss.id = u.suggested_school_id
WHERE `+where+` ORDER BY u.created_at DESC`, args...)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the unmatched SSA rows: %w", err)
	}
	all, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (unmatchedRow, error) {
		var u unmatchedRow
		return u, r.Scan(&u.schoolID, &u.name, &u.district, &u.date, &u.reason, &u.status, &u.hasSuggestion,
			&u.suggestedID, &u.suggested, &u.suggestedCode, &u.confidence)
	})
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the unmatched SSA rows: %w", err)
	}
	batches, err := s.unmatchedBatches(ctx, scope)
	if err != nil {
		return nil, true, err
	}
	return unmatchedPage(p, role, f, query, all, batches), true, nil
}

// plainDate is a value the date filters take (a date the queryset reads).
func plainDate(v string) bool {
	if len(v) != 10 || v[4] != '-' || v[7] != '-' {
		return false
	}
	for i, c := range v {
		if i != 4 && i != 7 && (c < '0' || c > '9') {
			return false
		}
	}
	return true
}

func likeOf(v string) string {
	return "%" + strings.NewReplacer(`\`, `\\`, "%", `\%`, "_", `\_`).Replace(v) + "%"
}

// unmatchedBatches is batch_options: the batches with rows in reach, newest
// first.
func (s *Service) unmatchedBatches(ctx context.Context, scope schooldirectory.Scope) ([][2]string, error) {
	var args []any
	reach := unmatchedReach(scope, &args)
	rows, err := s.db.Query(ctx, `SELECT b.id, b.file_name FROM ssa_import_batch b
WHERE b.id IN (SELECT u.batch_id FROM unmatched_ssa_record u WHERE `+reach+`)
ORDER BY b.created_at DESC`, args...)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the upload batches: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) ([2]string, error) {
		var b [2]string
		return b, r.Scan(&b[0], &b[1])
	})
}

func unmatchedPage(p auth.Principal, role Role, f map[string]string, query url.Values, all []unmatchedRow, batches [][2]string) *screensv1.GetPageResponse {
	size := rules.Unmatched.PageSize
	pages := max(1, (len(all)+size-1)/size)
	number := 1
	if n, ok := pynum.Int(query.Get("page")); ok && n > 0 {
		number = n
	}
	number = min(number, pages)
	start := (number - 1) * size
	shown := all[start:min(start+size, len(all))]

	status := &screensv1.PageFilter{Name: "status", Label: "Status", Options: []*screensv1.PageFilterOption{{Value: "", Label: "Pending + Hold"}}}
	for _, c := range rules.Unmatched.Statuses {
		status.Options = append(status.Options, &screensv1.PageFilterOption{Value: c[0], Label: c[1]})
		if c[0] == f["status"] {
			status.Value = c[0]
		}
	}
	batch := &screensv1.PageFilter{Name: "batch", Label: "Batch", Options: []*screensv1.PageFilterOption{{Value: "", Label: "All batches"}}}
	for _, b := range batches {
		batch.Options = append(batch.Options, &screensv1.PageFilterOption{Value: b[0], Label: closedschools.Collapse(b[1])})
		if b[0] == f["batch"] {
			batch.Value = b[0]
		}
	}
	t := &screensv1.PageTable{}
	for i, c := range []string{"SSA School ID", "School Name from SSA", "District", "Assessment Date", "Reason", "Suggested Match", "Status", "Actions"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c, Numeric: i == 7})
	}
	links := slices.Contains(rules.SchoolProfileRoles, p.ActiveRole)
	for _, u := range shown {
		suggested := &screensv1.PageCell{Text: "None found"}
		if u.hasSuggestion {
			confidence := "None"
			if u.confidence != nil {
				confidence = strconv.FormatFloat(*u.confidence, 'f', 2, 64)
			}
			suggested.Text = closedschools.Collapse(u.suggested + " ID: " + u.suggestedCode + " · confidence " + confidence)
			if links {
				suggested.Href = "/schools/" + u.suggestedID
			}
		}
		state := "Pending"
		if u.status == "hold" {
			state = "Held"
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: closedschools.Collapse("ID: " + u.schoolID)}, {Text: closedschools.Collapse(orDash(u.name))},
			{Text: closedschools.Collapse(orDash(u.district))}, {Text: closedschools.Collapse(u.date)},
			{Text: closedschools.Collapse(u.reason)}, suggested, {Text: state, Tone: "primary", Badge: true},
			{Actions: []*screensv1.PageAction{}},
		}})
	}
	if len(all) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No unmatched SSA records match this filter."}}}}
	}
	blocks := workspaceStrip(role)
	blocks = append(blocks,
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{status, batch}}}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		carried := ""
		for _, k := range unmatchedFilters {
			if f[k] != "" {
				carried += "&" + k + "=" + f[k]
			}
		}
		pager := &screensv1.PagePager{Pages: []*screensv1.PagePagerPage{
			{Label: "Page " + strconv.Itoa(number) + " of " + strconv.Itoa(pages) + " · " + strconv.Itoa(len(all)) + " total"}}}
		if number > 1 {
			pager.Pages = append(pager.Pages, &screensv1.PagePagerPage{Label: "← Prev", Href: "?page=" + strconv.Itoa(number-1) + carried})
		}
		if number < pages {
			pager.Pages = append(pager.Pages, &screensv1.PagePagerPage{Label: "Next →", Href: "?page=" + strconv.Itoa(number+1) + carried})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Pager{Pager: pager}})
	}
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{Eyebrow: "SSA assurance", Title: "Unmatched SSA",
			BackLabel: "Back to Quality Center", BackHref: "/admin-panel/data-quality-center",
			Description: "Manually link SSA records that were uploaded with unknown School IDs — " + strconv.Itoa(len(all)) + " matching this filter.",
			Badges:      []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}},
		Blocks: blocks, Tabs: []*screensv1.PageTab{}, Dialogs: []*screensv1.PageDialog{}, WebPath: UnmatchedPath,
	}
}
