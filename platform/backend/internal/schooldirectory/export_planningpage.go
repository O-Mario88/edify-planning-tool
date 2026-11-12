package schooldirectory

import "strings"

// What the Planning page (internal/planningpage) reads from the directory:
// the direct portfolio's condition and the data gaps', each over the
// schools aliased s, numbering its parameters through arg.

// DirectPortfolio is school_queryset(scope, direct_only=True).
func DirectPortfolio(s Scope, arg func(any) string) string {
	b := scopeBase(s)
	return renumber(b, arg)
}

// renumber writes b's clause with its parameters handed to arg in order.
func renumber(b *sqlb, arg func(any) string) string {
	where := b.where()
	// Replace from the highest number down so $1 does not eat $10.
	for i := len(b.args); i >= 1; i-- {
		where = strings.ReplaceAll(where, "$"+itoa(i), "\x00"+itoa(i)+"\x00")
	}
	for i, v := range b.args {
		where = strings.ReplaceAll(where, "\x00"+itoa(i+1)+"\x00", arg(v))
	}
	return where
}

func itoa(n int) string {
	if n == 0 {
		return "0"
	}
	digits := []byte{}
	for n > 0 {
		digits = append([]byte{byte('0' + n%10)}, digits...)
		n /= 10
	}
	return string(digits)
}

// PlanningBlockers is data_gaps.planning_blockers_q: a school missing a
// detail a visit or a training cannot be planned without.
func PlanningBlockers() string {
	parts := []string{}
	for _, key := range []string{"no_district", "no_sub_county", "no_owner", "no_school_id"} {
		for _, g := range gapConditions {
			if g.key == key {
				parts = append(parts, g.condition)
			}
		}
	}
	return "(" + strings.Join(parts, " OR ") + ")"
}

// NoSSA is data_gaps.no_ssa_q(fy).
func NoSSA(fy string, arg func(any) string) string {
	b := &sqlb{}
	clause := b.noSSA(fy)
	b.and(clause)
	return renumber(b, arg)
}
