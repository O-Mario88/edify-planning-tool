package hrregister

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
)

// citationShown is how much of a citation the register shows
// (item.citation[:90] + "…").
const citationShown = 90

// quarterDays is the "last quarter" the figures count back (91 days).
const quarterDays = 91

// cutCitation is the view's citation cell: the first 90 characters, and an
// ellipsis when there is more.
func cutCitation(text string) string {
	runes := []rune(text)
	if len(runes) <= citationShown {
		return text
	}
	return string(runes[:citationShown]) + "…"
}

// recognition is recognition_view: the recognitions of the reach's
// countries in the search (name, category or citation), the latest first;
// those of the last quarter counted, and the people they named against the
// live, not exited People records in reach.
func recognition(ctx context.Context, in input) (register, error) {
	scopeSQL, args := in.reach.byCountry("r.country", nil)
	searchSQL, args := contains(in.search, args, "u.name", "r.category", "r.citation")
	args = append(args, in.today.AddDate(0, 0, -quarterDays).Format(time.DateOnly))
	since := len(args)
	rows, err := in.db.Query(ctx, fmt.Sprintf(`
SELECT u.name, r.country, r.category, r.citation, r.awarded_on::text, r.staff_id, r.awarded_on >= $%d::date
FROM hr_staff_recognition r JOIN staff_profile sp ON sp.id = r.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE %s AND %s ORDER BY r.awarded_on DESC`, since, scopeSQL, searchSQL), args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the recognitions: %w", err)
	}
	type given struct {
		name, country, category, citation, awarded, staff string
		recent                                            bool
	}
	items, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (given, error) {
		var g given
		err := row.Scan(&g.name, &g.country, &g.category, &g.citation, &g.awarded, &g.staff, &g.recent)
		return g, err
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the recognitions: %w", err)
	}
	staff, err := peopleInScope(ctx, in)
	if err != nil {
		return register{}, err
	}
	reg := register{
		path: "/recognition", primary: &action{label: "Staff Pulse Surveys", href: "/pulse-surveys"}, title: "Recognition", eyebrow: "Rewards and wellbeing",
		description: "Recognition given to staff across the countries you oversee, so good work is named and nobody goes a year unrecognised.",
		columns:     []string{"Team member", "Country", "Recognised for", "Citation", "Awarded"},
		actions:     []action{{label: "Recognise someone", drawer: "/recognition/new"}},
		emptyTitle:  "No recognition recorded yet",
		emptyBody:   "Recognise someone to record what they did and why it mattered.",
	}
	recent, people := 0, map[string]bool{}
	for _, g := range items {
		if g.recent {
			recent++
			people[g.staff] = true
		}
		reg.rows = append(reg.rows, []string{
			dash(g.name), dash(g.country), dash(labelOf(rules.RecognitionCategories, g.category)), dash(cutCitation(g.citation)), dash(g.awarded),
		})
	}
	reg.metrics = []metric{
		{"Recognitions", count(recent), "given in the last quarter", "success"},
		{"People recognised", count(len(people)), fmt.Sprintf("of %d staff, last quarter", staff), "info"},
	}
	return reg, nil
}

// peopleInScope is _profile_scope(request).exclude(onboarding_state="exited")
// counted: the live People records of live accounts in reach, not exited.
func peopleInScope(ctx context.Context, in input) (int, error) {
	reachSQL, args := in.reach.profiles(nil)
	var n int
	err := in.db.QueryRow(ctx, fmt.Sprintf(`
SELECT count(*) FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.deleted_at IS NULL AND %s AND NOT (sp.onboarding_state = 'exited')`, reachSQL), args...).Scan(&n)
	if err != nil {
		return 0, fmt.Errorf("hrregister: counting the people in scope: %w", err)
	}
	return n, nil
}
