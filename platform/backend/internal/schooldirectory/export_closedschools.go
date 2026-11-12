package schooldirectory

// What the Closed Schools page (internal/closedschools) reads from the
// directory: the schools an analytics surface may aggregate over.

// AnalyticsReach is scoping.scoped_school_queryset(scope) as a condition on
// the schools aliased s: a country reader's country, a region reader's
// regions, the whole deployment for a summary reader with no geography (its
// regions otherwise), and the reader's own and team schools for anyone else.
// Deleted schools are left out, as that queryset leaves them out. Its
// numbered arguments are appended to args.
func AnalyticsReach(s Scope, args *[]any) string {
	b := &sqlb{args: *args}
	reach := "false"
	switch {
	case s.CountryScope:
		reach = "true"
		if s.Country != "" {
			reach = b.inCountry(s.Country)
		}
	case s.RegionScope:
		if len(s.RegionIDs) > 0 {
			reach = "s.region_id = ANY(" + b.arg(s.RegionIDs) + ")"
		}
	case s.SummaryOnly:
		reach = "true"
		if len(s.RegionIDs) > 0 {
			reach = "s.region_id = ANY(" + b.arg(s.RegionIDs) + ")"
		}
	case len(s.SchoolIDs) > 0:
		reach = "s.id = ANY(" + b.arg(s.SchoolIDs) + ")"
	}
	*args = b.args
	return "s.deleted_at IS NULL AND (" + reach + ")"
}
