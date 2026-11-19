package adminpanel

import (
	"context"
	"fmt"
	"strconv"
	"time"
	"unicode"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// UploadHistoryPath is School Upload History
// (extended_views.admin_school_upload_history_view,
// pages/admin/school_upload_history.html): the newest fifty upload batches
// the reader may see (the Admin every batch, anyone else their country's
// uploaders' and their own), each with its file, type, row breakdown and
// state. Marking a batch failed stays the existing page's.
const UploadHistoryPath = "/admin-panel/school-upload-history"

const uploadHistoryLimit = 50

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("adminpanel: " + err.Error())
	}
	return z
}()

type uploadBatch struct {
	file, uploader, kind, source, status, errorSummary string
	known                                              bool
	total, created, updated, failed                    int
	at                                                 time.Time
}

// capfirst is |capfirst: the first letter upper, the rest as they are.
func capfirst(s string) string {
	r := []rune(s)
	if len(r) > 0 {
		r[0] = unicode.ToUpper(r[0])
	}
	return string(r)
}

func (s *Service) uploadHistory(ctx context.Context, p auth.Principal) (*screensv1.GetPageResponse, bool, error) {
	var args []any
	where := "TRUE"
	if p.ActiveRole != "Admin" {
		scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
		if err != nil {
			return nil, true, err
		}
		args = append(args, p.UserID)
		where = "b.uploaded_by = $1"
		if scope.CountryScope && scope.Country != "" {
			args = append(args, scope.CountryID)
			where = "(b.uploaded_by IN " + registry.UsersIn("$2::text") + " OR b.uploaded_by = $1)"
		} else if scope.CountryScope {
			where = "TRUE"
		}
	}
	args = append(args, uploadHistoryLimit)
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(NULLIF(b.file_name, ''), b.original_file_name, ''), COALESCE(u.name, ''), u.id IS NOT NULL,
  COALESCE(b.upload_type, ''), COALESCE(b.source, ''), COALESCE(b.status, ''), COALESCE(b.error_summary, ''),
  b.total_rows, b.created_rows, b.updated_rows, b.failed_rows, b.created_at
FROM upload_batch b LEFT JOIN "user" u ON u.id = b.uploaded_by
WHERE `+where+` ORDER BY b.created_at DESC LIMIT $`+strconv.Itoa(len(args)), args...)
	if err != nil {
		return nil, true, fmt.Errorf("adminpanel: reading the upload batches: %w", err)
	}
	batches, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (uploadBatch, error) {
		var b uploadBatch
		return b, r.Scan(&b.file, &b.uploader, &b.known, &b.kind, &b.source, &b.status, &b.errorSummary,
			&b.total, &b.created, &b.updated, &b.failed, &b.at)
	})
	if err != nil {
		return nil, true, fmt.Errorf("adminpanel: reading the upload batches: %w", err)
	}
	t := &screensv1.PageTable{}
	for i, c := range []string{"File Metadata", "Type / Source", "Row Breakdown", "Status", "Action"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c, Numeric: i == 4})
	}
	for _, b := range batches {
		uploader := b.uploader
		if !b.known || uploader == "" {
			uploader = "Unknown user"
		}
		state := capfirst(b.status)
		if b.status == "completed" || b.status == "imported" {
			state = "Imported"
		} else if b.status == "failed" {
			state = "Failed"
		}
		// The state reads as a badge alone; with an error under it, the cell
		// reads as one line of text.
		status := &screensv1.PageCell{Text: state, Tone: "primary", Badge: true}
		if b.errorSummary != "" {
			status = &screensv1.PageCell{Text: closedschools.Collapse(state + " " + b.errorSummary)}
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: closedschools.Collapse(b.file + " Uploaded at " + b.at.In(zone).Format("Jan 02, 2006 15:04") + " by " + uploader)},
			{Text: closedschools.Collapse(b.kind + " Source: " + b.source)},
			{Text: "Total: " + strconv.Itoa(b.total) + " Created: " + strconv.Itoa(b.created) +
				" Updated: " + strconv.Itoa(b.updated) + " Failed: " + strconv.Itoa(b.failed)},
			status,
			{Actions: []*screensv1.PageAction{}},
		}})
	}
	if len(batches) == 0 {
		t.EmptyMessage = "School data files imported through the Upload Center will be logged here."
		t.EmptyAction = &screensv1.PageAction{Key: "empty", Label: "Open Upload Center", Enabled: true, Href: "/uploads?tab=imports"}
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{
			Text: "No uploads yet School data files imported through the Upload Center will be logged here. Open Upload Center",
			Href: "/uploads?tab=imports"}}}}
	}
	return page(header("Administration", "School Upload History",
		`Audit uploaded school files, successful records, and row breakdowns. "Mark Failed" flags a batch record only — it does not revert school data.`),
		UploadHistoryPath, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}), true, nil
}
