package iapages

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// UploadHistoryPath is SSA Upload History (ssa_views.ssa_upload_history_view,
// pages/ssa/upload_history.html): the SSA import batches the reader may open
// (_visible_batches), with the rows each imported, left unmatched and
// refused, newest first, fifty a page.
const UploadHistoryPath = "/ssa/upload/history/"

type importBatch struct {
	id, file, uploaderName, status   string
	known                            bool
	total, ready, unmatched, blocked int
	created                          time.Time
}

// capitalize is str.capitalize: the first letter upper, the rest lower.
func capitalize(s string) string {
	r := []rune(strings.ToLower(s))
	if len(r) > 0 {
		r[0] = unicode.ToUpper(r[0])
	}
	return string(r)
}

func (s *Service) uploadHistory(ctx context.Context, p auth.Principal, role Role, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if !slices.Contains(rules.SSAUploadRoles, p.ActiveRole) {
		// _may_upload_ssa refuses with the existing access-denied page.
		return nil, false, nil
	}
	var args []any
	arg := func(v any) string { args = append(args, v); return "$" + strconv.Itoa(len(args)) }
	where := "TRUE"
	switch p.ActiveRole {
	case "Admin":
	case "ImpactAssessment":
		scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
		if err != nil {
			return nil, true, err
		}
		if countryBound(scope) {
			args = append(args, scope.CountryID)
			where = "(b.uploaded_by IN " + countryUsers(len(args)) + " OR b.uploaded_by = " + arg(p.UserID) + ")"
		}
	default:
		where = "b.uploaded_by = " + arg(p.UserID)
	}
	hasBlocked, mine := query.Get("has_blocked") == "1", query.Get("mine") == "1"
	if mine {
		where += " AND b.uploaded_by = " + arg(p.UserID)
	}
	having := ""
	if hasBlocked {
		having = " HAVING count(r.id) FILTER (WHERE r.status = 'blocked') > 0"
	}
	rows, err := s.db.Query(ctx, `
SELECT b.id, COALESCE(b.file_name, ''), u.id IS NOT NULL, COALESCE(u.name, ''), COALESCE(b.status, ''),
  COALESCE(b.total_rows, 0), b.created_at,
  count(r.id) FILTER (WHERE r.status = 'ready'), count(r.id) FILTER (WHERE r.status = 'unmatched'),
  count(r.id) FILTER (WHERE r.status = 'blocked')
FROM ssa_import_batch b LEFT JOIN ssa_import_row r ON r.batch_id = b.id LEFT JOIN "user" u ON u.id = b.uploaded_by
WHERE `+where+`
GROUP BY b.id, u.id, u.name`+having+`
ORDER BY b.created_at DESC, b.id DESC`, args...)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the SSA import batches: %w", err)
	}
	all, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (importBatch, error) {
		var b importBatch
		return b, r.Scan(&b.id, &b.file, &b.known, &b.uploaderName, &b.status, &b.total, &b.created,
			&b.ready, &b.unmatched, &b.blocked)
	})
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the SSA import batches: %w", err)
	}
	return uploadHistoryPage(role, query, all, hasBlocked, mine), true, nil
}

func uploadHistoryPage(role Role, query url.Values, all []importBatch, hasBlocked, mine bool) *screensv1.GetPageResponse {
	choice := func(name, caption string, on bool, options [2]string) *screensv1.PageFilter {
		f := &screensv1.PageFilter{Name: name, Caption: caption, Options: []*screensv1.PageFilterOption{
			{Value: "", Label: options[0]}, {Value: "1", Label: options[1]}}}
		if on {
			f.Value = "1"
		}
		return f
	}
	t := &screensv1.PageTable{}
	pg := tablepager.Paginate(len(all), rules.TablePageSize, query, "history_page")
	if len(all) == 0 {
		t.EmptyMessage = "No SSA imports yet"
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No SSA imports yet Batches appear here once an SSA file is uploaded."}}}}
	} else {
		for _, c := range []string{"File", "Uploaded by", "Uploaded", "Status", "Rows", "Imported", "Unmatched", "Refused", ""} {
			t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
		}
		for _, b := range all[pg.Start:pg.End] {
			name := b.uploaderName
			if !b.known {
				name = "Unknown user"
			}
			t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
				{Text: closedschools.Collapse(or(b.file, "SSA import"))}, {Text: closedschools.Collapse(name)},
				{Text: b.created.In(zone).Format("2 Jan 2006, 15:04")},
				{Text: capitalize(strings.ReplaceAll(b.status, "_", " "))},
				{Text: strconv.Itoa(b.total)}, {Text: strconv.Itoa(b.ready)}, {Text: strconv.Itoa(b.unmatched)},
				{Text: strconv.Itoa(b.blocked)},
				{Actions: []*screensv1.PageAction{{Key: "button", Label: "Open result", Primary: true, Enabled: true,
					Href: "/ssa/upload/" + b.id + "/result/"}}},
			}})
		}
	}
	blocks := workspaceStrip(role)
	blocks = append(blocks,
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Import batches",
			Badges: []*screensv1.PageBadge{}, Items: []*screensv1.PagePanelItem{}}}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{
			choice("has_blocked", "Batches", hasBlocked, [2]string{"All batches", "With refused rows"}),
			choice("mine", "Uploaded by", mine, [2]string{"Anyone", "Me"}),
		}}}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if panel := tablepager.Panel(len(all), rules.TablePageSize, query, "history_page"); panel != nil {
		blocks = append(blocks, panel)
	}
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{Eyebrow: "Baseline & Field Data", Title: "SSA Upload History",
			Description: "Every SSA import in your country and what it did. Imported records wait for a verifier other than the uploader; refused rows are listed on each batch's result page.",
			Badges:      []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{
				{Key: "upload_ssa_file", Label: "Upload SSA file", Enabled: true, Href: "/ssa/upload/"}}},
		Blocks: blocks, Tabs: []*screensv1.PageTab{}, Dialogs: []*screensv1.PageDialog{}, WebPath: UploadHistoryPath,
	}
}

// or is the value, or fallback when it is empty.
func or(v, fallback string) string {
	if v == "" {
		return fallback
	}
	return v
}
