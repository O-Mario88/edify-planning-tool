package myplan

import (
	"context"
	"net/url"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// MealRates is costing_service.planned_meal_rates without its fallback, for
// Planning Oversight's cluster-training rows: one participant's meal at each
// session, from its own snapshot's meals line. ErrUnported where a meals
// component is one Go does not price.
func MealRates(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]int64, error) {
	return mealRates(ctx, db, ids)
}

// CatalogueRate is costing_service.catalogue_rate: the live published
// card's rate for key (nil when it carries none), planned_meal_rates'
// fallback.
func CatalogueRate(ctx context.Context, db schooldirectory.Querier, place *registry.Work, key string) (*int64, error) {
	return catalogueRate(ctx, db, place, key)
}

// Opens is My Plan's own door for a role (the page permission my_plan_view
// is decorated with), for the partner's My Plan (internal/partnerassigned),
// which the same view draws.
func Opens(role string) bool {
	door, ok := rules.Doors[role]
	return ok && door.Page
}

// AsksExport is whether the query carries the Export drawer's period
// fields, which my_plan_view answers with a file (handed on).
func AsksExport(query url.Values) bool {
	for _, key := range rules.ExportPeriodKeys {
		if query.Has(key) {
			return true
		}
	}
	return false
}
