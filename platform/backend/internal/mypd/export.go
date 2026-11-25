package mypd

import (
	"bytes"
	"context"
	"encoding/csv"
	"fmt"
	"math"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// exportPermission is Permission.EXPORT (require_export_permission).
const exportPermission = "data.export"

// Export is pd_export_view: the year's balances and courses as CSV
// (pd-report-fy<fy>.csv). It reads what the page reads, after the same
// writes when the page's writes are on (StaffPDService.get_page moves
// courses on and makes the year's allocation); otherwise it reads as the
// page does with the existing application absent. handled is false for a
// reader without a staff profile, whose export Go does not write.
func (s *Service) Export(ctx context.Context, p auth.Principal, query url.Values) (string, []byte, bool, error) {
	doors, known := rules.Doors[p.ActiveRole]
	if !known || !doors.Page || !rbac.Grants(p.ActiveRole, exportPermission) {
		return "", nil, true, pagegate.ErrNotAvailable
	}
	now := s.now()
	fy := strings.TrimSpace(query.Get("fy"))
	if fy == "" {
		fy = schooldirectory.OperationalFY(now)
	}
	if len(fy) > maxFY {
		return "", nil, false, nil
	}
	sp, ok, err := s.staffOf(ctx, p.UserID)
	if err != nil || !ok {
		return "", nil, err != nil, err
	}
	today := dateOf(now.In(zone))
	if s.writes {
		// The export reads balances and get_page, which make the year's
		// allocation; only the page's own view moves courses on.
		if err := s.allocateOnly(ctx, sp, fy); err != nil {
			return "", nil, true, err
		}
	}
	v, err := s.read(pagegate.WithDjangoAbsent(ctx, true), p, sp, fy, today)
	if err != nil {
		return "", nil, true, err
	}
	var name string
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(name, '') FROM "user" WHERE id = $1`, p.UserID).Scan(&name); err != nil {
		return "", nil, true, fmt.Errorf("mypd: reading the reader's name: %w", err)
	}
	body, err := v.exportCSV(name, now)
	return "pd-report-fy" + fy + ".csv", body, true, err
}

func (s *Service) allocateOnly(ctx context.Context, sp staff, fy string) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("mypd: opening the export's write: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := allocate(ctx, tx, sp, fy); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("mypd: committing the export's write: %w", err)
	}
	return nil
}

// exportCSV is the view's rows: the heading, the balances
// (StaffPDService.balances, each figure /100 as Python divides), then the
// courses as _course_row shows them.
func (v *view) exportCSV(name string, now time.Time) ([]byte, error) {
	var committed, accounted int64
	for _, c := range v.rows {
		if in(rules.CommittedStatuses, c.status) && c.accountedAmount() == 0 {
			committed += c.requested
		}
		accounted += c.accountedAmount()
	}
	remaining := max(0, v.allocation-committed-accounted)
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	w.UseCRLF = true
	write := func(cells ...string) {
		for i, c := range cells {
			cells[i] = workbook.SpreadsheetText(c)
		}
		_ = w.Write(cells)
	}
	write("My Professional Development — FY "+v.fy, "Generated "+now.UTC().Format("02 Jan 2006 15:04"), name)
	_ = w.Write(nil)
	write("Annual Allocation ("+v.currency+")", "Committed", "Used (Accounted)", "Remaining")
	write(pyHundredths(v.allocation), pyHundredths(committed), pyHundredths(accounted), pyHundredths(remaining))
	_ = w.Write(nil)
	write("Course", "Institution", "Type", "Start", "End", "Status", "Funding Used")
	for _, r := range v.rows {
		funding := money(r.currency, r.requested)
		if r.requested == 0 {
			funding = r.currency + " 0"
			if r.funding == rules.SelfFunded {
				funding = "Self-Funded"
			}
		}
		write(r.name, r.institution, courseType(r.kind), r.start.Format(time.DateOnly), r.end.Format(time.DateOnly),
			statusLabel(r.status), funding)
	}
	w.Flush()
	return buf.Bytes(), w.Error()
}

// pyHundredths is str(cents / 100): Python's float repr, "10000.0" for a
// whole figure.
func pyHundredths(cents int64) string {
	f := float64(cents) / 100
	switch abs := math.Abs(f); {
	case f == math.Trunc(f) && abs < 1e16:
		return strconv.FormatFloat(f, 'f', 1, 64)
	case abs >= 1e-4 && abs < 1e16:
		return strconv.FormatFloat(f, 'f', -1, 64)
	}
	return strconv.FormatFloat(f, 'g', -1, 64)
}
