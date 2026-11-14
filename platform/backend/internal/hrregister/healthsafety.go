package hrregister

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
)

// yearDays is the "last 12 months" the figures count back (365 days).
const yearDays = 365

// healthSafety is health_safety_view: the incidents of the reach's
// countries in the search (category, location, country or the injured
// person's name), the latest first, and the figures over them.
func healthSafety(ctx context.Context, in input) (register, error) {
	scopeSQL, args := in.reach.byCountry("i.country", nil)
	searchSQL, args := contains(in.search, args, "i.category", "i.location", "i.country", "u.name")
	args = append(args, in.today.AddDate(0, 0, -yearDays).Format(time.DateOnly))
	since := len(args)
	rows, err := in.db.Query(ctx, fmt.Sprintf(`
SELECT i.id, i.category, u.name, i.country, i.incident_date::text, i.severity, i.days_lost, i.status, i.incident_date >= $%d::date
FROM hr_safety_incident i LEFT JOIN staff_profile sp ON sp.id = i.affected_staff_id LEFT JOIN "user" u ON u.id = sp.user_id
WHERE %s AND %s ORDER BY i.incident_date DESC`, since, scopeSQL, searchSQL), args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the safety incidents: %w", err)
	}
	type incident struct {
		id, category, country, date, severity, status string
		injured                                       *string
		daysLost                                      int
		thisYear                                      bool
	}
	items, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (incident, error) {
		var i incident
		err := row.Scan(&i.id, &i.category, &i.injured, &i.country, &i.date, &i.severity, &i.daysLost, &i.status, &i.thisYear)
		return i, err
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the safety incidents: %w", err)
	}
	reg := register{
		path: "/health-safety", title: "Health & Safety", eyebrow: "Rewards and wellbeing",
		description: "Occupational health and safety across the countries you oversee: incidents, near misses and hazards, " +
			"and the corrective action taken.",
		columns:    []string{"Incident", "Country", "Date", "Severity", "Days lost", "Status"},
		actions:    []action{{label: "Report an incident", drawer: "/health-safety/new"}},
		emptyTitle: "No incidents recorded",
		emptyBody:  "Report injuries, road traffic incidents, near misses and hazards so their causes can be fixed.",
	}
	open, serious, nearMisses, daysLost := 0, 0, 0, 0
	for _, i := range items {
		if i.status != "closed" {
			open++
			if i.severity == "high" || i.severity == "critical" {
				serious++
			}
		}
		if i.thisYear {
			daysLost += i.daysLost
			if i.category == "near_miss" {
				nearMisses++
			}
		}
		who := "No one injured"
		if i.injured != nil {
			who = *i.injured
		}
		reg.rows = append(reg.rows, []string{
			labelOf(rules.SafetyCategories, i.category) + " · " + who, dash(i.country), dash(i.date),
			dash(labelOf(rules.Severities, i.severity)), count(i.daysLost), dash(labelOf(rules.SafetyStatuses, i.status)),
		})
		reg.rowActions = append(reg.rowActions, []action{{label: "Open", drawer: "/health-safety/" + i.id}})
	}
	reg.metrics = []metric{
		{"Open incidents", count(open), "not yet closed", "warning"},
		{"Serious incidents", count(serious), "high or critical, open", "danger"},
		{"Near misses", count(nearMisses), "reported in the last 12 months", "info"},
		{"Days lost", count(daysLost), "to incidents in the last 12 months", "warning"},
	}
	return reg, nil
}
