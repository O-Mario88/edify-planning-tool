package schooldirectory

import (
	"context"
	"fmt"
)

// What Home's Priority actions read from the directory (internal/home).

// CountNoSSA is a CCEO's "Schools With No SSA" on Home
// (home_priorities._ssa_gap_count): the schools of the reader's direct
// portfolio with no confirmed SSA in the year fy, as /schools?gap=no_ssa
// counts them.
func CountNoSSA(ctx context.Context, db Querier, s Scope, fy string) (int, error) {
	b := scopeBase(s)
	b.and("s.deleted_at IS NULL")
	b.and(b.noSSA(fy))
	var n int
	if err := db.QueryRow(ctx, `SELECT count(*) FROM school s WHERE `+b.where(), b.args...).Scan(&n); err != nil {
		return 0, fmt.Errorf("schooldirectory: counting the schools with no SSA: %w", err)
	}
	return n, nil
}
