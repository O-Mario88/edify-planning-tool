// Package acting is acting leadership, owned by Go: appointing an acting
// leader for one calendar month, changing or cancelling the appointment, and
// the appointee's switch between the acting capacity and their own role
// (apps/acting/services.py, one for one, on the existing acting_assignment
// rows).
//
// What each appointment delegates and withholds is the existing policy
// (apps/acting/policy.py), exported to acting_policy.json by
// `manage.py export_acting_policy`; apps/acting/tests/test_policy_export.py
// fails when the two differ.
package acting

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"time"
	_ "time/tzdata" // the platform's day is Kampala's wherever the gateway runs
)

// Scope types (apps.core.acting).
const (
	ScopePLTeam  = "pl_team"
	ScopeCountry = "country"
)

// Roles the rules name.
const (
	roleAdmin           = "Admin"
	roleCountryDirector = "CountryDirector"
	roleHumanResources  = "HumanResources"
)

//go:embed acting_policy.json
var policyJSON []byte

// Role is one kind of acting appointment (policy.ActingRole).
type Role struct {
	Key           string         `json:"key"`
	ActingRole    string         `json:"acting_role"`
	AppointeeRole string         `json:"appointee_role"`
	AppointerRole string         `json:"appointer_role"`
	ScopeType     string         `json:"scope_type"`
	Label         string         `json:"label"`
	ShortLabel    string         `json:"short_label"`
	ScopeLabel    string         `json:"scope_label"`
	Granted       map[string]any `json:"granted"`
}

var roles = mustLoad(policyJSON)

func mustLoad(raw []byte) []Role {
	var document struct {
		Roles []Role `json:"roles"`
	}
	if err := json.Unmarshal(raw, &document); err != nil || len(document.Roles) == 0 {
		panic(fmt.Sprintf("acting: the embedded policy is unreadable: %v", err))
	}
	return document.Roles
}

// ByKey is the entry for a policy key ("acting_pl").
func ByKey(key string) (Role, bool) {
	for _, entry := range roles {
		if entry.Key == key {
			return entry, true
		}
	}
	return Role{}, false
}

// offeredBy is the appointment a permanent holder of role may make.
func offeredBy(role string) (Role, bool) {
	for _, entry := range roles {
		if entry.AppointerRole == role {
			return entry, true
		}
	}
	return Role{}, false
}

// ── Days and months ────────────────────────────────────────────────────────

// platformZone is the existing TIME_ZONE: an appointment for October begins
// at midnight in Kampala, not three hours later.
var platformZone = mustZone("Africa/Nairobi")

func mustZone(name string) *time.Location {
	zone, err := time.LoadLocation(name)
	if err != nil {
		panic(fmt.Sprintf("acting: loading %s: %v", name, err))
	}
	return zone
}

// Today is the calendar day in the platform's time zone, at midnight UTC.
func Today(now time.Time) time.Time {
	local := now.In(platformZone)
	return time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
}

// monthsAhead is MONTHS_AHEAD: this month and the next eleven.
const monthsAhead = 12

func monthBounds(year int, month time.Month) (time.Time, time.Time) {
	start := time.Date(year, month, 1, 0, 0, 0, 0, time.UTC)
	return start, start.AddDate(0, 1, -1)
}

// parseMonth is parse_month: "2026-10" to that month's first and last day.
func parseMonth(value string) (time.Time, time.Time, error) {
	var year, month int
	if _, err := fmt.Sscanf(value, "%d-%d", &year, &month); err != nil || month < 1 || month > 12 || year < 1 {
		return time.Time{}, time.Time{}, refuse("Choose the month the appointment is for.")
	}
	start, end := monthBounds(year, time.Month(month))
	return start, end, nil
}

// appointableMonth is _appointable_month: not ended, and no further ahead
// than the eleventh month after this one.
func appointableMonth(value string, today time.Time) (time.Time, time.Time, error) {
	start, end, err := parseMonth(value)
	if err != nil {
		return start, end, err
	}
	if end.Before(today) {
		return start, end, refuse("That month has ended. Choose this month or a later one.")
	}
	last, _ := monthBounds(today.Year(), today.Month())
	if start.After(last.AddDate(0, monthsAhead-1, 0)) {
		return start, end, refuse(fmt.Sprintf("Appointments can be made up to %d months ahead.", monthsAhead))
	}
	return start, end, nil
}

// Month is one month an appointment may be made for.
type Month struct{ Value, Label, Effective string }

// monthOptions is month_options: this month and the next eleven.
func monthOptions(today time.Time) []Month {
	options := make([]Month, 0, monthsAhead)
	first, _ := monthBounds(today.Year(), today.Month())
	for i := 0; i < monthsAhead; i++ {
		start := first.AddDate(0, i, 0)
		_, end := monthBounds(start.Year(), start.Month())
		options = append(options, Month{Value: monthValue(start), Label: monthLabel(start), Effective: effectiveLabel(start, end)})
	}
	return options
}

func monthValue(start time.Time) string { return start.Format("2006-01") }

// monthLabel is period_label: "October 2026".
func monthLabel(start time.Time) string { return start.Format("January 2006") }

// effectiveLabel is effective_label: "October 1 – October 31, 2026".
func effectiveLabel(start, end time.Time) string {
	return fmt.Sprintf("%s %d – %s %d, %d", start.Format("January"), start.Day(), end.Format("January"), end.Day(), end.Year())
}

// ── States ─────────────────────────────────────────────────────────────────

const (
	stateUpcoming  = "upcoming"
	stateActive    = "active"
	stateExpired   = "expired"
	stateCancelled = "cancelled"
)

var stateLabels = map[string]string{
	stateUpcoming: "Upcoming", stateActive: "Active", stateExpired: "Expired", stateCancelled: "Cancelled",
}

// state is ActingAssignment.state: the dates, or the cancellation.
func state(start, end time.Time, cancelled bool, today time.Time) string {
	switch {
	case cancelled:
		return stateCancelled
	case today.Before(start):
		return stateUpcoming
	case today.After(end):
		return stateExpired
	}
	return stateActive
}

// ── Refusals ───────────────────────────────────────────────────────────────

// Refused is a rule saying no, in the existing words.
type Refused struct {
	Message   string
	NotFound  bool
	Forbidden bool
	Conflict  bool
}

func (r *Refused) Error() string { return r.Message }

func refuse(message string) error    { return &Refused{Message: message} }
func notFound(message string) error  { return &Refused{Message: message, NotFound: true} }
func forbidden(message string) error { return &Refused{Message: message, Forbidden: true} }
func conflict(message string) error  { return &Refused{Message: message, Conflict: true} }
