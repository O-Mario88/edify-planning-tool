package activities

import "context"

// StandalonePricing implements the Pricing, MoveChecker, CancelChecker,
// Announcer and HandedInNotifier hooks without calling the existing Django
// application. It is used for Django-absent vertical-slice acceptance tests
// and isolated rehearsals until Go owns day-pool costing (M12) and
// notifications (M11) directly.
type StandalonePricing struct{}

// DayCheck approves the day locally without calling Django.
func (StandalonePricing) DayCheck(context.Context, map[string]any) (DayVerdict, error) {
	return DayVerdict{Pooled: true}, nil
}

// Settle is a no-op when Django is absent.
func (StandalonePricing) Settle(context.Context, []int64, string) error { return nil }

// MoveCheck approves a single-visit move locally without calling Django.
func (StandalonePricing) MoveCheck(context.Context, string, string, string) (MoveVerdict, error) {
	return MoveVerdict{Pooled: true}, nil
}

// CancelCheck approves a visit cancellation locally without calling Django.
func (StandalonePricing) CancelCheck(context.Context, string, string) (CancelVerdict, error) {
	return CancelVerdict{Found: true}, nil
}

// Announce is a no-op when Django is absent.
func (StandalonePricing) Announce(context.Context, string) error { return nil }

// HandedIn is a no-op when Django is absent.
func (StandalonePricing) HandedIn(context.Context, string, string, string) error { return nil }
