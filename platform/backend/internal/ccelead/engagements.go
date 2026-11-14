package ccelead

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// EngagementsPath is the CCE Engagement Log.
const EngagementsPath = "/cce-leadership/engagements"

// rhythmShown is how many rhythm rows the log's card lists.
const rhythmShown = 12

// reach is services.lead_reach: the countries served (every country the
// regions name for Admin), whether any are assigned, and the Programme Leads
// in them.
type reach struct {
	countries []string
	assigned  bool
	leads     []leadInReach
}

func leadReach(ctx context.Context, db schooldirectory.Querier, p auth.Principal) (reach, error) {
	var r reach
	var err error
	switch {
	case p.ActiveRole == adminRole:
		r.countries, _, err = schooldirectory.RegionCountries(ctx, db, "")
	case p.ActiveRole == regionalLead:
		r.countries, r.assigned, err = schooldirectory.RegionCountries(ctx, db, p.StaffProfileID)
	}
	if err != nil {
		return r, fmt.Errorf("ccelead: reading the lead's countries: %w", err)
	}
	if len(r.countries) == 0 {
		return r, nil
	}
	rows, err := db.Query(ctx, `
SELECT sp.id, COALESCE(NULLIF(u.name, ''), u.email), COALESCE(sp.country, '')
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.deleted_at IS NULL AND u.status = 'active' AND sp.country = ANY($1)
  AND u.roles @> ARRAY['Program Lead']::varchar[]
ORDER BY sp.country, u.name`, r.countries)
	if err != nil {
		return r, fmt.Errorf("ccelead: reading the Programme Leads in reach: %w", err)
	}
	r.leads, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (leadInReach, error) {
		var l leadInReach
		err := row.Scan(&l.staffID, &l.name, &l.country)
		return l, err
	})
	if err != nil {
		return r, fmt.Errorf("ccelead: reading the Programme Leads in reach: %w", err)
	}
	return r, nil
}

func plural(n int, one, many string) string {
	if n == 1 {
		return one
	}
	return many
}

// engagements is engagements_view.
func engagements(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time, query url.Values) (register, error) {
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	lead := p.ActiveRole == regionalLead
	r, err := leadReach(ctx, db, p)
	if err != nil {
		return register{}, err
	}
	// engagements_visible_to: Admin every one, the Regional Lead their own.
	mine := "FALSE"
	args := []any{}
	switch p.ActiveRole {
	case adminRole:
		mine = "TRUE"
	case regionalLead:
		mine, args = "e.author_id = $1", []any{p.UserID}
	}
	kind, country := query.Get("kind"), query.Get("country")
	known := false
	for _, k := range rules.EngagementKinds {
		known = known || k[0] == kind
	}
	where := mine
	if kind != "" && known {
		args = append(args, kind)
		where += fmt.Sprintf(" AND e.kind = $%d", len(args))
	} else {
		kind = ""
	}
	if country != "" && slices.Contains(r.countries, country) {
		args = append(args, country)
		where += fmt.Sprintf(" AND e.country = $%d", len(args))
	} else {
		country = ""
	}
	rows, err := db.Query(ctx, fmt.Sprintf(`
SELECT e.id, e.author_id, e.kind, e.subject, e.country, e.held_on, e.program_lead_ids, e.feedback_shared_at, e.acknowledged_at
FROM cce_regional_engagement e WHERE %s ORDER BY e.held_on DESC, e.created_at DESC LIMIT %d`, where, feedbackLimit), args...)
	if err != nil {
		return register{}, fmt.Errorf("ccelead: reading the engagements: %w", err)
	}
	type engagement struct {
		id, author, kind, subject, country string
		held                               time.Time
		leads                              []string
		shared, acknowledged               *time.Time
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (engagement, error) {
		var e engagement
		err := row.Scan(&e.id, &e.author, &e.kind, &e.subject, &e.country, &e.held, &e.leads, &e.shared, &e.acknowledged)
		return e, err
	})
	if err != nil {
		return register{}, fmt.Errorf("ccelead: reading the engagements: %w", err)
	}
	names := map[string]string{}
	for _, l := range r.leads {
		names[l.staffID] = l.name
	}
	kinds := map[string]string{}
	for _, k := range rules.EngagementKinds {
		kinds[k[0]] = k[1]
	}
	reg := register{
		path: EngagementsPath, title: "CCE Engagement Log", eyebrow: "Regional CCE leadership", registerTitle: "Engagements",
		description: "Coaching conversations with Programme Leads, meetings with Country Directors, the RVP and the VP of CCE, " +
			"school visits, partner and network meetings, and the trainings you observe.",
		emptyTitle: "Nothing recorded yet",
		emptyBody: "Log a coaching conversation or observe a training; each one keeps your rhythm with Programme Leads and " +
			"Country Directors up to date.",
		columns: []string{"Engagement", "Kind", "Held", "With", "Shared with the lead"},
	}
	if lead {
		reg.actions = []action{
			{label: "Log an engagement", drawer: EngagementsPath + "/new"},
			{label: "Observe a training", drawer: EngagementsPath + "/new?kind=training_observation"},
		}
		if !r.assigned {
			reg.notice = "No countries are assigned to your account yet, so every country is in reach. An administrator narrows it " +
				"to your region on your staff record."
		}
	}
	for _, e := range list {
		with := []string{}
		for _, id := range e.leads {
			name, ok := names[id]
			if !ok {
				name = "Programme Lead"
			}
			with = append(with, name)
		}
		withText := strings.Join(with, ", ")
		if withText == "" {
			withText = e.country
		}
		state := ""
		shareable := slices.Contains(rules.ShareableKinds, e.kind)
		if shareable {
			switch {
			case e.acknowledged != nil:
				state = "Acknowledged"
			case e.shared != nil:
				state = "Awaiting the Programme Lead"
			default:
				state = "Not shared yet"
			}
		}
		label, ok := kinds[e.kind]
		if !ok {
			label = e.kind
		}
		reg.rows = append(reg.rows, []string{dash(e.subject), dash(label), dash(e.held.Format("2 Jan 2006")), dash(withText), dash(state)})
		acts := []action{{label: "Open", drawer: EngagementsPath + "/" + e.id}}
		if lead && e.author == p.UserID && shareable && e.shared == nil && len(e.leads) > 0 {
			acts = append(acts, action{label: "Share", drawer: EngagementsPath + "/" + e.id + "/share"})
		}
		reg.rowActions = append(reg.rowActions, acts)
	}
	// A select is drawn only when it has options (a reader with no
	// countries gets no country select).
	reg.filters = []*screensv1.PageFilter{filter("kind", "Kind", kind, "Every kind", rules.EngagementKinds)}
	if len(r.countries) > 0 {
		reg.filters = append(reg.filters, filter("country", "Country", country, "Every country", pairs(r.countries)))
	}
	counts, err := figuresOf(ctx, db, mine, args[:min(len(args), boolInt(lead))], today)
	if err != nil {
		return register{}, err
	}
	attention := 0
	if lead {
		rhythm, err := leadRhythm(ctx, db, p, today, r)
		if err != nil {
			return register{}, err
		}
		attention = countState(rhythm, "overdue") + countState(rhythm, "missed")
		reg.after = []*screensv1.PageBlock{rhythmCard(rhythm)}
	}
	overdueTone := "info"
	if attention > 0 {
		overdueTone = "danger"
	}
	reg.metrics = []metric{
		{"Coaching Conversations (30 Days)", strconv.Itoa(counts[0]),
			fmt.Sprintf("with %d Programme Lead%s in reach", len(r.leads), plural(len(r.leads), "", "s")), "info"},
		{"Trainings Observed This Quarter", strconv.Itoa(counts[1]), "observations recorded", "info"},
		{"Country Reviews This Quarter", strconv.Itoa(counts[2]),
			fmt.Sprintf("of %d countr%s", len(r.countries), plural(len(r.countries), "y", "ies")), "info"},
		{"Engagements Overdue", strconv.Itoa(attention), "in the rhythm the role sets", overdueTone},
	}
	return reg, nil
}

func boolInt(b bool) int {
	if b {
		return 1
	}
	return 0
}

func pairs(values []string) [][2]string {
	out := [][2]string{}
	for _, v := range values {
		out = append(out, [2]string{v, v})
	}
	return out
}

// filter is one of the register's selects as the feed reads it: its blank
// option first, the value selected only when it is one of the options.
func filter(name, caption, value, blank string, options [][2]string) *screensv1.PageFilter {
	f := &screensv1.PageFilter{Name: name, Value: value, Caption: caption,
		Options: []*screensv1.PageFilterOption{{Value: "", Label: blank}}}
	for _, o := range options {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
	}
	return f
}

// figuresOf counts the reader's own engagements (unfiltered): coaching
// conversations of the last 30 days, and the trainings observed and country
// reviews held this quarter.
func figuresOf(ctx context.Context, db schooldirectory.Querier, mine string, args []any, today time.Time) ([3]int, error) {
	start, end := quarterRange(today)
	n := len(args)
	args = append(args, today.AddDate(0, 0, -30).Format(time.DateOnly), start.Format(time.DateOnly), end.Format(time.DateOnly))
	var out [3]int
	err := db.QueryRow(ctx, fmt.Sprintf(`
SELECT count(*) FILTER (WHERE e.kind = 'pl_coaching' AND e.held_on >= $%d::date),
       count(*) FILTER (WHERE e.kind = 'training_observation' AND e.held_on >= $%d::date AND e.held_on < $%d::date),
       count(*) FILTER (WHERE e.kind = 'cd_quarterly_review' AND e.held_on >= $%d::date AND e.held_on < $%d::date)
FROM cce_regional_engagement e WHERE %s`, n+1, n+2, n+3, n+2, n+3, mine), args...).Scan(&out[0], &out[1], &out[2])
	if err != nil {
		return out, fmt.Errorf("ccelead: counting the engagements: %w", err)
	}
	return out, nil
}

// leadRhythm is services.rhythm: the lead's last 400 days of engagements
// against the role's rules, with the countries whose next-year budget has
// gone to the RVP.
func leadRhythm(ctx context.Context, db schooldirectory.Querier, p auth.Principal, today time.Time, r reach) ([]rhythmRow, error) {
	rows, err := db.Query(ctx, `
SELECT kind, held_on, country, program_lead_ids FROM cce_regional_engagement WHERE author_id = $1 AND held_on >= $2::date`,
		p.UserID, today.AddDate(0, 0, -400).Format(time.DateOnly))
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the lead's rhythm: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (held, error) {
		var h held
		err := row.Scan(&h.kind, &h.on, &h.country, &h.leads)
		return h, err
	})
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the lead's rhythm: %w", err)
	}
	sent := map[string]bool{}
	budgets, err := db.Query(ctx, `
SELECT country_id FROM country_annual_budget WHERE fy = $1 AND country_id = ANY($2) AND status IN ('submitted_to_rvp', 'approved_by_rvp')`,
		strconv.Itoa(opFY(today)+1), r.countries)
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading next year's budgets: %w", err)
	}
	for budgets.Next() {
		var c string
		if err := budgets.Scan(&c); err != nil {
			budgets.Close()
			return nil, fmt.Errorf("ccelead: reading next year's budgets: %w", err)
		}
		sent[c] = true
	}
	budgets.Close()
	return evaluate(list, today, r.leads, r.countries, sent), budgets.Err()
}

func countState(rows []rhythmRow, state string) int {
	n := 0
	for _, r := range rows {
		if r.state == state {
			n++
		}
	}
	return n
}

// rhythmCard is partials/dashboards/rpl/rhythm.html as the feed reads it:
// the link to the log, the overdue count, then the three counts read one
// place off (each label beside the next count; OWNER_DEFECTS), the most
// urgent twelve rows and, past them, the footnote.
func rhythmCard(rows []rhythmRow) *screensv1.PageBlock {
	c := rules.Cadence
	attention := countState(rows, "overdue") + countState(rows, "missed")
	items := []*screensv1.PagePanelItem{
		{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{{Text: "Engagement log →", Href: EngagementsPath}}}}},
		text(strconv.Itoa(attention)),
		{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{
			{Label: "Overdue or missed", Value: strconv.Itoa(countState(rows, "due_soon"))},
			{Label: "Due soon", Value: strconv.Itoa(countState(rows, "done"))},
		}}}},
		text("On rhythm"),
	}
	for i, r := range rows {
		if i >= rhythmShown {
			break
		}
		what := r.expectation
		if r.lastHeld != nil {
			what += " · last held " + r.lastHeld.Format("2 Jan 2006")
		} else {
			what += " · not held yet"
		}
		if r.dueBy != nil && r.state != "done" {
			what += " · due by " + r.dueBy.Format("2 Jan")
		}
		if r.note != "" && r.lastHeld != nil {
			what += " · " + r.note
		}
		state := text(c.StateLabels[r.state])
		state.Tone = c.StateTones[r.state]
		items = append(items, text(r.label+" · "+r.subject), state, text(what))
	}
	if len(rows) > rhythmShown {
		items = append(items, text(fmt.Sprintf("Showing the %d most urgent of %d. The engagement log lists every one.", rhythmShown, len(rows))))
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Engagement rhythm", Items: items}}}
}
