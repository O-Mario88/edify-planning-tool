package planningmonitor

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ErrSchoolGapUnread is a school with no owner: the existing check reads
// that one school alone, which Go's dataset does not narrow to.
var ErrSchoolGapUnread = errors.New("planningmonitor: a school with no owner's gap is not read in Go")

// SchoolGapOpen is followups.school_gap_open: whether one school still has
// the planning gap a school action names (figure is SCHOOL_GAP_FIGURE's),
// read over the school owner's whole portfolio for the year, as the
// country reads it on today. A school that is gone has no gap; with no year
// the gap is taken as still open.
func SchoolGapOpen(ctx context.Context, db schooldirectory.Querier, schoolID, fy, figure string, today time.Time) (bool, error) {
	var owner string
	err := db.QueryRow(ctx, `SELECT COALESCE(account_owner_id, '') FROM school WHERE id = $1`, schoolID).Scan(&owner)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("planningmonitor: the school: %w", err)
	}
	if fy == "" {
		return true, nil
	}
	if owner == "" {
		return false, ErrSchoolGapUnread
	}
	scope := schooldirectory.Scope{Role: "CountryDirector", UserID: "system", CountryScope: true}
	d, err := buildCPODatasetOn(ctx, db, scope, cpoWindowFor(fy, "fy", "", 0, nil), today, []string{owner})
	if err != nil {
		return false, err
	}
	s := d.byID[schoolID]
	if s == nil || !s.governed() {
		return false, nil
	}
	i, ok := cpoIdx[figure]
	if !ok {
		return false, fmt.Errorf("planningmonitor: %q is no school figure", figure)
	}
	return schoolValues(s, d.claims[s.id])[i] > 0, nil
}
