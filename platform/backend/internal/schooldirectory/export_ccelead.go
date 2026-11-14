package schooldirectory

import (
	"context"
	"fmt"
)

// RegionCountries is scoping._regional_reach's countries for a region role
// with this People record: the countries of the regions assigned to them
// (directly, or through a district when no region is), and whether any are
// assigned; with none, every country the platform's regions name. For the
// CCE leadership registers (internal/ccelead).
func RegionCountries(ctx context.Context, q Querier, staffID string) ([]string, bool, error) {
	assigned := []string{}
	if staffID != "" {
		var err error
		if assigned, err = assignedRegions(ctx, q, staffID); err != nil {
			return nil, false, err
		}
	}
	countries, err := strings1(ctx, q, `SELECT country FROM region WHERE id = ANY($1) AND country <> '' ORDER BY country`, assigned)
	if err != nil {
		return nil, false, fmt.Errorf("schooldirectory: reading the assigned countries: %w", err)
	}
	if countries = uniq(countries); len(countries) > 0 {
		return countries, true, nil
	}
	if countries, err = strings1(ctx, q, `SELECT country FROM region WHERE country <> '' ORDER BY country`); err != nil {
		return nil, false, fmt.Errorf("schooldirectory: reading the countries: %w", err)
	}
	return uniq(countries), false, nil
}
