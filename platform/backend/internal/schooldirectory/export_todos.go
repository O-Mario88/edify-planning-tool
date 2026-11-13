package schooldirectory

import (
	"context"
	"fmt"
)

// CountrySchoolIDs is scoping.scoped_school_queryset for a country-scoped
// reader: every school not deleted, in the country when one is named
// (school_in_country_q), for the To-Do page's Business Transformation rows
// (internal/todos, bt_services.scoped_loans).
func CountrySchoolIDs(ctx context.Context, q Querier, country string) ([]string, error) {
	b := &sqlb{}
	b.and("s.deleted_at IS NULL")
	if country != "" {
		b.and(b.inCountry(country))
	}
	ids, err := strings1(ctx, q, "SELECT s.id FROM school s WHERE "+b.where(), b.args...)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading the country's schools: %w", err)
	}
	return ids, nil
}
