package dashboard

import (
	"context"
	"fmt"
	"slices"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
)

// The fixed part of the officer's Home: the header, the week at a glance
// and Do next, over cc_activities — the work the officer owns, and the
// partner work they monitor — of any year.

// agendaCard is one Do next card (components/mobile_agenda_card.html).
type agendaCard struct {
	date, title, place, status string
	actionLabel, actionURL     string
}

type home struct {
	counts          [4]int // completed, in progress, planned, overdue
	overdue, visits []agendaCard
	clusterWeek     []agendaCard
}

// ccWhere is cc_activities over owners $1.
const ccWhere = `a.deleted_at IS NULL AND (a.responsible_staff_id = ANY($1)
OR (a.monitored_by_staff_id = ANY($1) AND a.delivery_type = 'partner'))`

// agendaLimit is how many of each list the page reads ([:8]).
const agendaLimit = 8

func (s *Service) readHome(ctx context.Context, owners []string, today time.Time) (home, error) {
	var h home
	if len(owners) == 0 {
		return h, nil
	}
	o := rules.Officer
	day := today.Format(time.DateOnly)
	err := s.db.QueryRow(ctx, `SELECT
  count(*) FILTER (WHERE a.status = ANY($2)),
  count(*) FILTER (WHERE a.status = ANY($3)),
  count(*) FILTER (WHERE a.status = ANY($4) AND NOT COALESCE(a.planned_date < $5, false)),
  count(*) FILTER (WHERE a.status = ANY($4) AND a.planned_date < $5)
FROM activity a WHERE `+ccWhere, owners, o.CompletedStatuses, o.UnderWayStatuses, o.NotStartedStatuses, day).
		Scan(&h.counts[0], &h.counts[1], &h.counts[2], &h.counts[3])
	if err != nil {
		return h, fmt.Errorf("dashboard: week at a glance: %w", err)
	}
	from := today.AddDate(0, 0, -21).Format(time.DateOnly)
	weekEnd := myplan.MondayOf(today).AddDate(0, 0, 6).Format(time.DateOnly)
	if h.overdue, err = s.agenda(ctx, `a.planned_date < $3 AND a.planned_date >= $4`, owners, day, from, overdueCard); err != nil {
		return h, err
	}
	if h.visits, err = s.agenda(ctx, `a.planned_date BETWEEN $3 AND $4 AND a.activity_type = ANY($5) AND a.school_id IS NOT NULL`,
		owners, day, weekEnd, visitCard(today), o.VisitTypes); err != nil {
		return h, err
	}
	if h.clusterWeek, err = s.agenda(ctx, `a.planned_date BETWEEN $3 AND $4 AND a.activity_type = ANY($5) AND a.cluster_id IS NOT NULL`,
		owners, day, weekEnd, clusterCard(today), o.ClusterTypes); err != nil {
		return h, err
	}
	return h, nil
}

// agendaRow is what a Do next list reads of one activity.
type agendaRow struct {
	id, kind, status, purpose       string
	planned                         time.Time
	school, schoolDistrict, cluster *string
}

// agenda is one of the page's three lists: cc_activities matching where,
// not done, by planned date, the first eight.
func (s *Service) agenda(ctx context.Context, where string, owners []string, a3, a4 string,
	card func(agendaRow) agendaCard, extra ...any) ([]agendaCard, error) {
	args := append([]any{owners, rules.Officer.DoneStatuses, a3, a4}, extra...)
	rows, err := s.db.Query(ctx, `SELECT a.id, a.activity_type, COALESCE(a.status, ''), COALESCE(a.activity_purpose_text, ''),
  a.planned_date, s.name, sd.name, c.name
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN district sd ON sd.id = s.district_id
LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE `+ccWhere+` AND NOT COALESCE(a.status = ANY($2), false) AND `+where+`
ORDER BY a.planned_date ASC LIMIT `+fmt.Sprint(agendaLimit), args...)
	if err != nil {
		return nil, fmt.Errorf("dashboard: do next: %w", err)
	}
	defer rows.Close()
	var out []agendaCard
	for rows.Next() {
		var r agendaRow
		if err := rows.Scan(&r.id, &r.kind, &r.status, &r.purpose, &r.planned, &r.school, &r.schoolDistrict,
			&r.cluster); err != nil {
			return nil, fmt.Errorf("dashboard: do next: %w", err)
		}
		out = append(out, card(r))
	}
	return out, rows.Err()
}

// due is strftime("%b %-d, %Y (%a)").
func due(d time.Time) string {
	return fmt.Sprintf("%s %d, %d (%s)", d.Format("Jan"), d.Day(), d.Year(), d.Format("Mon"))
}

func overdueCard(r agendaRow) agendaCard {
	c := agendaCard{date: due(r.planned), title: myplan.TypeLabel(r.kind), place: "—"}
	switch {
	case r.school != nil:
		c.place = *r.school
	case r.cluster != nil:
		c.place = *r.cluster
	}
	switch {
	case r.status == "in_progress":
		c.status, c.actionLabel, c.actionURL = "Unsuccessful", "Complete", "/activities/"+r.id+"/complete"
	case slices.Contains(rules.Officer.ReturnedStatuses, r.status):
		c.status, c.actionLabel, c.actionURL = "Returned", "Complete", "/activities/"+r.id+"/complete"
	default:
		c.status, c.actionLabel, c.actionURL = "Not Completed", "Reschedule", "/my-plan/"+r.id
	}
	return c
}

// startsToday is a plan due today and still to be started.
func startsToday(r agendaRow, today time.Time) bool {
	d := time.Date(r.planned.Year(), r.planned.Month(), r.planned.Day(), 0, 0, 0, 0, time.UTC)
	return d.Equal(today) && (r.status == "scheduled" || r.status == "rescheduled")
}

func visitCard(today time.Time) func(agendaRow) agendaCard {
	return func(r agendaRow) agendaCard {
		c := agendaCard{date: due(r.planned), title: deref(r.school), place: "—", actionLabel: "View Details",
			actionURL: "/my-plan/" + r.id}
		if r.schoolDistrict != nil {
			c.place = *r.schoolDistrict
		}
		if startsToday(r, today) {
			c.actionLabel, c.actionURL = "Start Visit", "/activities/"+r.id+"/start"
		}
		return c
	}
}

func clusterCard(today time.Time) func(agendaRow) agendaCard {
	return func(r agendaRow) agendaCard {
		c := agendaCard{title: deref(r.cluster), actionLabel: "View Details", actionURL: "/my-plan/" + r.id}
		if startsToday(r, today) {
			c.actionLabel, c.actionURL = "Start", "/activities/"+r.id+"/start"
		}
		return c
	}
}

func deref(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}

// primary is mobile_primary_action: the first card's action, else plan the
// week.
func (h home) primary() (label, href string) {
	for _, list := range [][]agendaCard{h.overdue, h.visits, h.clusterWeek} {
		if len(list) > 0 {
			return list[0].actionLabel, list[0].actionURL
		}
	}
	return "Plan this week", "/planning"
}

// opens is whether the officer may open a link the page draws, by its shape.
func opens(href string) bool {
	o := rules.Officer.Opens
	switch {
	case href == "/planning":
		return o["planning"]
	case len(href) > len("/complete") && href[len(href)-len("/complete"):] == "/complete":
		return o["complete"]
	case len(href) > len("/start") && href[len(href)-len("/start"):] == "/start":
		return o["start"]
	}
	return o["details"]
}

func (h home) header(today time.Time) *screensv1.PageHeader {
	planned := len(h.overdue) + len(h.visits) + len(h.clusterWeek)
	out := &screensv1.PageHeader{
		Eyebrow:     "Field execution",
		Title:       "Your day, in priority order",
		Description: "Finish overdue work first, then move into today's visits and cluster activities.",
		Badges: []*screensv1.PageBadge{
			{Text: fmt.Sprintf("%s, %d %s", today.Format("Mon"), today.Day(), today.Format("Jan")), Tone: "plain"},
			{Text: fmt.Sprintf("%d planned this week", planned), Tone: "plain"},
		},
	}
	if label, href := h.primary(); opens(href) {
		out.Actions = []*screensv1.PageAction{{Key: "primary-action", Label: label, Primary: true, Enabled: true, Href: href}}
	}
	return out
}

func (h home) strip() *screensv1.PageBlock {
	strip := &screensv1.PageStrip{Title: "Week at a glance"}
	for i, m := range rules.Officer.Metrics {
		strip.Metrics = append(strip.Metrics, &screensv1.PageMetric{Label: m.Label, Value: fmt.Sprint(h.counts[i]), Note: m.Helper})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: strip}}
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

// doNext is the phone's Do next band: the first three of last weeks'
// overdue work, else of this week's school visits, each card's lines read
// into the band; with none, the link to the plan and a line pointing at
// "What needs you now" or saying nothing is urgent.
func (h home) doNext(pastDue int) []*screensv1.PageBlock {
	cards := h.overdue
	if len(cards) == 0 {
		cards = h.visits
	}
	band := &screensv1.PagePanel{Title: "Do next"}
	if len(cards) > 0 {
		for _, c := range cards[:min(3, len(cards))] {
			band.Items = append(band.Items, text(c.date),
				&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: orActivity(c.title)}})
			if c.place != "" {
				band.Items = append(band.Items, text(c.place))
			}
			if c.status != "" {
				band.Items = append(band.Items, text(c.status))
			}
		}
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: band}}}
	}
	band.Items = []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{
		Links: []*screensv1.PageLink{{Text: "Open full plan", Href: "/my-plan"}}}}}}
	empty := "No urgent field workYour next scheduled activity will appear here."
	if pastDue > 0 {
		empty = fmt.Sprintf("%d past dueFinish, reschedule or cancel them in What needs you now.", pastDue)
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: band}},
		{Kind: &screensv1.PageBlock_Empty{Empty: empty}},
	}
}

func orActivity(title string) string {
	if title == "" {
		return "Activity"
	}
	return title
}
