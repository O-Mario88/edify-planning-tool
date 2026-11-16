package pricing

import (
	"context"
	"errors"
	"math"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing"
)

// ErrUnknownProfile is an activity whose Activity Catalogue costing profile
// the recipe does not know; the existing writer refuses to price it.
var ErrUnknownProfile = errors.New("pricing: unknown Activity Catalogue costing profile")

// Dual is calculate_dual's result.
type Dual struct {
	Operational, Reference costing.Cost
	HasReference           bool
	OperationalCard        *Card
	ReferenceCard          *Card
	Warnings               []string
	MissingOperational     []string
	MissingReference       []string
	Viability              string
	CanSchedule            bool
}

// Profiled is _profiled_input: the catalogue item's costing profile decides
// the recipe's activity type and kind.
func Profiled(in Input) (costing.Activity, error) {
	a := in.Activity
	if in.Profile == "" {
		return a, nil
	}
	resolved, ok := rules.CostingProfiles[in.Profile]
	if !ok {
		return a, ErrUnknownProfile
	}
	a.ActivityType = resolved[0]
	if resolved[1] != "" {
		a.CostingKind = resolved[1]
	}
	return a, nil
}

// Price is calculate_dual for the input: the recipe on the operational card
// and the reference card in force on the activity's day.
func Price(ctx context.Context, db Querier, in Input) (Dual, error) {
	a, err := Profiled(in)
	if err != nil {
		return Dual{}, err
	}
	operational, err := ReadCard(ctx, db, rules.OperationalKind, in.PlannedDate)
	if err != nil {
		return Dual{}, err
	}
	reference, err := ReadCard(ctx, db, rules.ReferenceKind, in.PlannedDate)
	if err != nil {
		return Dual{}, err
	}
	return dual(a, in.CatalogueItemID, operational, reference), nil
}

func ratesOf(c *Card) map[string]int64 {
	if c == nil {
		return map[string]int64{}
	}
	return c.Rates
}

func dual(a costing.Activity, itemID string, operational, reference *Card) Dual {
	a.LinkedRates = operational.LinkedRates(itemID)
	d := Dual{OperationalCard: operational, ReferenceCard: reference, Warnings: []string{}}
	d.Operational = costing.CostForActivity(a, ratesOf(operational))
	if reference != nil {
		d.Reference, d.HasReference = costing.CostForActivity(a, reference.Rates), true
	}
	d.MissingOperational = append([]string{}, d.Operational.MissingItems...)
	belowMinimum := false
	if operational != nil {
		for _, line := range d.Operational.Lines {
			s, ok := operational.Settings[line.Key]
			if ok && s.ApprovedMinimum != nil && s.UnitCost < *s.ApprovedMinimum {
				belowMinimum = true
			}
		}
	}
	if belowMinimum {
		d.Warnings = append(d.Warnings, "One or more operational rates are below an approved minimum.")
	}
	switch {
	case reference == nil:
		d.Warnings = append(d.Warnings, "Regional Standard Funding Rate Card has not been configured.")
	case d.Reference.CostMissing:
		d.Warnings = append(d.Warnings, "Regional Standard Funding Rate Card configuration is incomplete.")
	case d.Reference.Amount != 0 && operational != nil && operational.ThresholdBps != nil:
		// round((reference - operational) * 10_000 / reference), as Python
		// divides and rounds (half to even).
		difference := math.RoundToEven(float64((d.Reference.Amount-d.Operational.Amount)*10_000) / float64(d.Reference.Amount))
		if difference >= float64(*operational.ThresholdBps) {
			d.Warnings = append(d.Warnings, "The Country Operational Cost is materially below the Regional Standard Funding Cost. "+
				"Confirm that the approved activity scope remains executable.")
		}
	}
	switch {
	case operational == nil || d.Operational.CostMissing:
		d.Viability = "configuration_missing"
	case belowMinimum:
		d.Viability = "below_approved_minimum"
	case len(d.Warnings) > 0 && reference != nil:
		d.Viability = "review_recommended"
	default:
		d.Viability = "viable"
	}
	if reference != nil {
		d.MissingReference = append([]string{}, d.Reference.MissingItems...)
	} else {
		d.MissingReference = []string{"rate_card"}
	}
	d.CanSchedule = operational != nil && !d.Operational.CostMissing
	return d
}
