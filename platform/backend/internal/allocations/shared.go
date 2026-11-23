package allocations

import (
	"context"
	"fmt"
	"slices"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The counting bases' unit families (apps.hr.milestone_progress), in the order
// _aggregate_credits asks them.
const (
	BasisSchools  = "schools"
	BasisTeachers = "teachers"
	BasisLeaders  = "leaders"
	BasisCredits  = "credited_value"
)

// OwnerIDs is contribution_scope.owner_ids: every id a person's work may be
// filed under, with their team's when asked.
func OwnerIDs(ctx context.Context, db schooldirectory.Querier, staffID string, team bool) ([]string, error) {
	return ownerIDs(ctx, db, staffID, team)
}

// IsRateMeasurement is whether a measurement type's achievement is a rate.
func IsRateMeasurement(measurement string) bool {
	return slices.Contains(rules.RateTypes, measurement)
}

// BasisFamily is the unit _aggregate_credits counts these bases in.
func BasisFamily(bases []string) string {
	has := func(set []string) bool {
		return slices.ContainsFunc(bases, func(b string) bool { return slices.Contains(set, b) })
	}
	switch {
	case has(rules.SchoolBases):
		return BasisSchools
	case has(rules.TeacherBases):
		return BasisTeachers
	case has(rules.LeaderBases):
		return BasisLeaders
	}
	return BasisCredits
}

// CountryActivityClause is scope_activities(country=…) as a condition on
// activity `a`, with the country at the placeholder given.
func CountryActivityClause(placeholder string) string {
	return fmt.Sprintf(`(
  EXISTS (SELECT 1 FROM school s JOIN region r ON r.id = s.region_id WHERE s.id = a.school_id AND r.country = %[1]s)
  OR EXISTS (SELECT 1 FROM school s WHERE s.id = a.school_id AND s.region_id IS NULL AND (
       s.account_owner_id IN (SELECT id FROM staff_profile WHERE country = %[1]s AND deleted_at IS NULL)
       OR s.account_owner_id IS NULL OR s.account_owner_id = ''
       OR s.account_owner_id IN (SELECT id FROM staff_profile WHERE (country IS NULL OR country = '') AND deleted_at IS NULL)))
  OR (a.school_id IS NULL AND EXISTS (SELECT 1 FROM cluster cl JOIN district d ON d.id = cl.district_id JOIN region r ON r.id = d.region_id
                                       WHERE cl.id = a.cluster_id AND r.country = %[1]s))
  OR (a.school_id IS NULL AND a.cluster_id IS NULL AND (
       a.responsible_staff_id IN (SELECT id FROM staff_profile WHERE country = %[1]s UNION SELECT user_id FROM staff_profile WHERE country = %[1]s AND user_id IS NOT NULL)
       OR a.monitored_by_staff_id IN (SELECT id FROM staff_profile WHERE country = %[1]s UNION SELECT user_id FROM staff_profile WHERE country = %[1]s AND user_id IS NOT NULL))))`, placeholder)
}
