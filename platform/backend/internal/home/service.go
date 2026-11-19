package home

import (
	"context"
	"errors"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerassigned"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/todos"
)

// kampala is the project's timezone (settings.TIME_ZONE): Home's day, its
// greeting and an activity's time of day are read in it.
var kampala = time.FixedZone("EAT", 3*60*60)

// pageGlyphs are the icons Home's own headings and rows use (the feed's
// PAGE_GLYPHS).
var pageGlyphs = []string{"bolt", "grid", "calendar", "clock", "chevron", "arrow"}

// planFigure is one of PLAN_FIGURES: the My Plan state, the metric, the
// icon and the tone it reads.
type planFigure struct{ state, metric, icon, tone string }

var planFigures = []planFigure{
	{"upcoming", "home_plan_upcoming", "calendar", "brand"},
	{"under_way", "home_plan_under_way", "clock", "info"},
	{"overdue", "home_plan_overdue", "warning", "alert"},
}

// queueFigure is one of QUEUE_FIGURES: the queue's count, the metric, the
// icon and the tone it reads when it is not zero.
type queueFigure struct{ key, metric, icon, tone string }

var queueFigures = []queueFigure{
	{"waiting_me", "home_todo_waiting", "check", "caution"},
	{"due_today", "home_todo_due_today", "clock", "caution"},
	{"critical", "home_todo_critical", "warning", "alert"},
}

// Service builds Home.
type Service struct {
	db    schooldirectory.Querier
	now   func() time.Time
	todos *todos.Service
}

// NewService returns a Service reading db at the time now gives.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	if now == nil {
		now = time.Now
	}
	return &Service{db: db, now: now, todos: todos.NewService(db, now)}
}

// roleOf is the reader's Home rules, and whether Go answers their Home: a
// role it has rules for that may open Home, working in its own capacity.
func roleOf(p auth.Principal) (Role, bool) {
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Home || p.InActingAppointment {
		return Role{}, false
	}
	return role, true
}

// partnerSlug is the delivery partners' role slug: their plan is their
// organisation's.
const partnerSlug = "PARTNER"

// teamMember is whether p is a partner team member, whom the existing feed
// sends to their own schools instead of Home (it answers the redirect,
// which Go does not draw): the existing application answers them.
func (s *Service) teamMember(ctx context.Context, p auth.Principal, role Role) (bool, error) {
	if role.Slug != partnerSlug {
		return false, nil
	}
	return partnerassigned.IsTeamMember(ctx, s.db, p)
}

// planOf is my_plan_activities' owner: a partner login's organisation
// (resolve_partner_ids), else the reader's own two ids.
func (s *Service) planOf(ctx context.Context, p auth.Principal, role Role) (myplan.PlanOf, error) {
	plan := myplan.PlanOf{Owners: myplan.OwnerIDs(p)}
	if role.Slug != partnerSlug {
		return plan, nil
	}
	partners, err := partnerassigned.PartnerIDs(ctx, s.db, p)
	plan.Partners = partners
	return plan, err
}

// ErrForbidden is require_page's refusal: the reader's role may not open
// Home (the Cluster Leader, whose Home is the Cluster Leader Portal).
var ErrForbidden = errors.New("home: the role may not open Home")

// refused is whether Go answers p with the existing feed's refusal: a role
// it has rules for that may not open Home, in its own capacity.
func refused(p auth.Principal) bool {
	role, ok := rules.Roles[p.ActiveRole]
	return ok && !role.Home && !p.InActingAppointment
}

// refusal is ErrForbidden for a refused reader, else nil (handed on).
func refusal(p auth.Principal) error {
	if refused(p) {
		return ErrForbidden
	}
	return nil
}

// Served is whether Go answers this reader's Home.
func Served(p auth.Principal) bool {
	_, ok := roleOf(p)
	return ok
}

// Build answers GetHome for p, or served=false when the existing
// application answers it (Served).
func (s *Service) Build(ctx context.Context, p auth.Principal) (*screensv1.GetHomeResponse, bool, error) {
	role, ok := roleOf(p)
	if !ok {
		return nil, refused(p), refusal(p)
	}
	if member, err := s.teamMember(ctx, p, role); err != nil || member {
		return nil, false, err
	}
	now := s.now()
	local := now.In(kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	fy := operationalFY(now)
	out := &screensv1.GetHomeResponse{
		Greeting:   greeting(local),
		FirstName:  firstName(p.Name),
		RoleTitle:  role.Title,
		Today:      today.Format(time.DateOnly),
		TodayLabel: today.Format("Mon, Jan") + " " + strconv.Itoa(today.Day()),
		Fy:         fy,
		HasPlan:    role.HasPlan,
		Glyphs:     map[string]string{},
		Figures:    []*screensv1.HomeFigure{},
		Upcoming:   []*screensv1.HomeUpcoming{},
		Shortcuts:  []*screensv1.HomeShortcut{},
	}
	for _, name := range pageGlyphs {
		out.Glyphs[name] = rules.Icons[name]
	}
	if role.HasPlan {
		plan, err := s.planOf(ctx, p, role)
		if err != nil {
			return nil, false, err
		}
		counts, err := myplan.ReadHomeCounts(ctx, s.db, plan, fy, now)
		if err != nil {
			return nil, false, err
		}
		out.Figures = append(out.Figures, planFiguresOf(counts)...)
		upcoming, err := myplan.ReadHomeUpcoming(ctx, s.db, plan, fy, now, rules.UpcomingLimit)
		if err != nil {
			return nil, false, err
		}
		for _, a := range upcoming {
			out.Upcoming = append(out.Upcoming, upcomingOf(a, today))
		}
	}
	out.Figures = append(out.Figures, QueueFigures(nil, role.HasPlan)...)
	for _, sc := range role.Shortcuts {
		out.Shortcuts = append(out.Shortcuts, &screensv1.HomeShortcut{Label: sc.Label, Url: sc.URL, IconSvg: sc.Icon})
	}
	return out, true, nil
}

// greeting is greeting_for: the part of the local day.
func greeting(local time.Time) string {
	switch {
	case local.Hour() < 12:
		return "Good morning"
	case local.Hour() < 17:
		return "Good afternoon"
	}
	return "Good evening"
}

// firstName is the first word of the account's name.
func firstName(name string) string {
	words := strings.Fields(name)
	if len(words) == 0 {
		return ""
	}
	return words[0]
}

// operationalFY is get_operational_fy: the year an October starts, read on
// the UTC day.
func operationalFY(now time.Time) string {
	utc := now.UTC()
	if utc.Month() >= time.October {
		return strconv.Itoa(utc.Year() + 1)
	}
	return strconv.Itoa(utc.Year())
}

// figure is the feed's figure() over render_precomputed_metric_item.
func figure(metric, key, value, icon, tone, url string, loading bool) *screensv1.HomeFigure {
	words := rules.Figures[metric]
	return &screensv1.HomeFigure{
		Key: key, Label: words.Label, Value: value, IconSvg: rules.Icons[icon],
		Tone: tone, Url: url, Loading: loading, Description: words.Description,
	}
}

// planFiguresOf is plan_figures: Overdue reads as an alarm only when there
// is something overdue.
func planFiguresOf(c myplan.HomeCounts) []*screensv1.HomeFigure {
	values := map[string]int{"upcoming": c.Upcoming, "under_way": c.UnderWay, "overdue": c.Overdue}
	out := []*screensv1.HomeFigure{}
	for _, f := range planFigures {
		value := values[f.state]
		tone := f.tone
		if f.state == "overdue" && value == 0 {
			tone = "plain"
		}
		out = append(out, figure(f.metric, f.state, strconv.Itoa(value), f.icon, tone, "/my-plan?status="+f.state, false))
	}
	return out
}

// QueueFigures is todo_figures: a planner gets one (its plan figures carry
// the rest), anyone else the three that describe their queue. counts nil is
// the page before the queue has loaded: the same tiles, valueless.
func QueueFigures(counts map[string]int, withPlan bool) []*screensv1.HomeFigure {
	specs := queueFigures
	if withPlan {
		specs = specs[:1]
	}
	out := []*screensv1.HomeFigure{}
	for _, f := range specs {
		if counts == nil {
			out = append(out, figure(f.metric, f.key, "", f.icon, "plain", "/todos", true))
			continue
		}
		value := counts[f.key]
		tone := "plain"
		if value != 0 {
			tone = f.tone
		}
		out = append(out, figure(f.metric, f.key, strconv.Itoa(value), f.icon, tone, "/todos", false))
	}
	return out
}

// upcomingOf is one of upcoming_activities' rows.
func upcomingOf(a myplan.HomeActivity, today time.Time) *screensv1.HomeUpcoming {
	var day time.Time
	switch {
	case a.Planned != nil:
		day = time.Date(a.Planned.Year(), a.Planned.Month(), a.Planned.Day(), 0, 0, 0, 0, time.UTC)
	case a.Scheduled != nil:
		local := a.Scheduled.In(kampala)
		day = time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	}
	typeLabel := label(rules.TypeLabels, a.Type)
	title := a.Purpose
	if title == "" {
		title = typeLabel
	}
	where := a.SchoolName
	if a.SchoolID == "" {
		where = ""
		if a.ClusterID != "" {
			where = a.ClusterName
		}
	}
	return &screensv1.HomeUpcoming{
		Id:          a.ID,
		Month:       strings.ToUpper(day.Format("Jan")),
		Day:         int32(day.Day()),
		IsToday:     day.Equal(today),
		Title:       title,
		Where:       where,
		Time:        clock(a.Scheduled),
		TypeLabel:   typeLabel,
		StatusLabel: label(rules.StatusLabels, a.Status),
		Url:         "/my-plan/" + a.ID,
	}
}

// clock is local_clock: the time of day an instant carries, or "" for none
// (a plan dated in a drawer is saved at local midnight).
func clock(moment *time.Time) string {
	if moment == nil {
		return ""
	}
	local := moment.In(kampala)
	if local.Hour() == 0 && local.Minute() == 0 {
		return ""
	}
	return local.Format("3:04 PM")
}
