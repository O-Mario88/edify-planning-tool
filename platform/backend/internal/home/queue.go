package home

import (
	"context"
	"log/slog"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningmonitor"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/plreview"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/todos"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trainingsummary"
)

// leadRole is the Programme Lead, whose rows count their own and their
// team's work; every other role with rows (the CCEO) counts their own.
const leadRole = "Program Lead"

// BuildQueue answers GetHomeQueue for p: the Priority actions the owner set
// for a CCEO and a Programme Lead (apps.command_center.home_priorities),
// each count read from the service behind the table it opens; the To-Do
// figures follow (GetHomeTodoFigures). Every other role's Priority actions
// are their To-Do queue's first entries (buildTodoQueue). served is false
// for an acting appointment and where Go does not build the queue: the
// existing application answers them.
func (s *Service) BuildQueue(ctx context.Context, p auth.Principal) (*screensv1.GetHomeQueueResponse, bool, error) {
	role, ok := roleOf(p)
	if !ok {
		return nil, refused(p), refusal(p)
	}
	specs, set := rules.Priorities.Roles[p.ActiveRole]
	if !set {
		return s.buildTodoQueue(ctx, p, role)
	}
	now := s.now()
	fy := operationalFY(now)
	counts := s.priorityCounts(ctx, p, specs, fy)
	out := &screensv1.GetHomeQueueResponse{HasPlan: role.HasPlan, TodoFiguresLater: true,
		PriorityRows: []*screensv1.HomePriorityRow{}, QueueFigures: []*screensv1.HomeFigure{}}
	for _, spec := range specs {
		count, read := counts[spec.Key]
		out.PriorityRows = append(out.PriorityRows, priorityRow(spec, count, read, fy))
	}
	return out, true, nil
}

// buildTodoQueue is build_home_queue for a role without the owner's rows:
// its Priority actions are its To-Do queue's first entries, identical To-Dos
// one row, the To-Do figures alongside. served is false where the existing
// application answers the queue (todos.Service.HomeQueue).
func (s *Service) buildTodoQueue(ctx context.Context, p auth.Principal, role Role) (*screensv1.GetHomeQueueResponse, bool, error) {
	q, served, err := s.todos.HomeQueue(ctx, p)
	if !served || err != nil {
		return nil, served, err
	}
	total := int32(q.Total)
	out := &screensv1.GetHomeQueueResponse{HasPlan: role.HasPlan, PriorityTotal: &total,
		QueueFigures: QueueFigures(q.Counts, role.HasPlan), PriorityRows: []*screensv1.HomePriorityRow{}}
	for _, e := range q.Entries[:min(rules.PriorityLimit, len(q.Entries))] {
		if e.Group {
			out.PriorityRows = append(out.PriorityRows, groupRow(e.Rows))
		} else {
			out.PriorityRows = append(out.PriorityRows, todoRow(e.Rows[0]))
		}
	}
	return out, true, nil
}

// queueTone is home_service.tone: the queue's tone as Home names it.
func queueTone(value string) string {
	if t, ok := rules.QueueRows.Tones[value]; ok {
		return t
	}
	return "plain"
}

func categoryIcon(category string) string {
	name, ok := rules.QueueRows.CategoryIcons[category]
	if !ok {
		name = "flag"
	}
	return rules.Icons[name]
}

// todoRow is home_service._todo_row through the feed's priority_row.
func todoRow(t todos.Row) *screensv1.HomePriorityRow {
	line := t.Description
	if t.Linked != "" {
		line = todos.ContextLine(t.Title, t.Linked)
	}
	due := t.DueLabel
	if due == "—" || due == t.StatusLabel {
		due = ""
	}
	action := t.ActionLabel
	if action == "" {
		action = "Open"
	}
	link := t.ActionURL
	if link == "" {
		link = "/todos"
	}
	return &screensv1.HomePriorityRow{Title: t.Title, Context: line, DueLabel: due, DueTone: queueTone(t.DueTone),
		StatusLabel: t.StatusLabel, StatusTone: queueTone(t.StatusTone), ActionLabel: action, Url: link,
		IconSvg: categoryIcon(t.Category)}
}

// groupRow is home_service._group_row: identical To-Dos as one row.
func groupRow(rows []todos.Row) *screensv1.HomePriorityRow {
	first := rows[0]
	label, ok := rules.QueueRows.PriorityLabels[first.Priority]
	if !ok {
		label = "—"
	}
	tone, ok := rules.QueueRows.PriorityTones[first.Priority]
	if !ok {
		tone = "plain"
	}
	return &screensv1.HomePriorityRow{Title: first.Title, Context: strconv.Itoa(len(rows)) + " like this",
		DueLabel: first.DueLabel, DueTone: queueTone(first.DueTone), StatusLabel: label, StatusTone: tone,
		ActionLabel: "Review", Url: "/todos", IconSvg: categoryIcon(first.Category), Count: int32(len(rows))}
}

// priorityCounts is home_priorities._counts: each row's figure, a figure
// that could not be read left out (its row shows no number, never a zero).
func (s *Service) priorityCounts(ctx context.Context, p auth.Principal, specs []PriorityRow, fy string) map[string]int {
	now := s.now()
	wanted := map[string]bool{}
	for _, spec := range specs {
		wanted[spec.Key] = true
	}
	lead := p.ActiveRole == leadRole
	counts := map[string]int{}
	read := func(name string, compute func() error) {
		if err := compute(); err != nil {
			// Home is never the reason a page fails (home_priorities._read).
			slog.Default().Error("home: a priority figure could not be read", "figure", name, "error", err)
		}
	}
	read("overdue", func() error {
		if lead {
			team, err := teamIDs(ctx, s.db, p, now)
			if err != nil {
				return err
			}
			past, err := myplan.ReadTeamPastDue(ctx, s.db, myplan.OwnerIDs(p), team, now, "")
			if err != nil {
				return err
			}
			counts["my_overdue"], counts["team_overdue"] = past.Owned(), past.Team()
			return nil
		}
		past, err := myplan.ReadPastDue(ctx, s.db, myplan.OwnerIDs(p), now)
		if err != nil {
			return err
		}
		counts["my_overdue"] = past.Total()
		return nil
	})
	read("school_rows", func() error {
		var schools []*planningmonitor.School
		if lead {
			m, err := planningmonitor.Read(ctx, s.db, p, fy, now)
			if err != nil {
				return err
			}
			schools = m.Schools()
		} else {
			own, err := planningmonitor.ReadOwnSchools(ctx, s.db, p, fy, now)
			if err != nil {
				return err
			}
			schools = own
		}
		lists := planningmonitor.HomeListCounts(schools)
		for key, list := range rules.Priorities.SchoolLists {
			// A CCEO's no SSA is the School Directory's (below).
			if wanted[key] && (lead || key != "no_ssa") {
				counts[key] = lists[list]
			}
		}
		return nil
	})
	if wanted["verify"] {
		read("verify", func() error {
			n, err := plreview.NewService(s.db, s.now).Waiting(ctx, p)
			if err == nil {
				counts["verify"] = n
			}
			return err
		})
	}
	if wanted["no_ssa"] && !lead {
		read("no_ssa", func() error {
			scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
			if err != nil {
				return err
			}
			n, err := schooldirectory.CountNoSSA(ctx, s.db, scope, fy)
			if err == nil {
				counts["no_ssa"] = n
			}
			return err
		})
	}
	return counts
}

// teamIDs is every id a Lead's line-managed team's work is filed under, as
// the dashboard's past-due list reads it.
func teamIDs(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) ([]string, error) {
	members, err := trainingsummary.TeamMembers(ctx, db, p.StaffProfileID, now)
	if err != nil {
		return nil, err
	}
	var team []string
	for _, m := range members {
		team = append(team, m.StaffID)
		if m.UserID != "" {
			team = append(team, m.UserID)
		}
	}
	return team, nil
}

// priorityRow is home_priorities._row through the feed's priority_row.
func priorityRow(spec PriorityRow, count int, read bool, fy string) *screensv1.HomePriorityRow {
	row := &screensv1.HomePriorityRow{
		Key: spec.Key, Title: spec.Title, DueTone: "plain", ActionLabel: spec.Action,
		Url: strings.ReplaceAll(spec.URL, rules.Priorities.FYMark, fy), IconSvg: rules.Icons[spec.Icon],
	}
	switch {
	case spec.Counts == "":
		row.Context, row.StatusTone, row.MarkTone = spec.Line, "plain", "info"
	case !read:
		row.Context, row.StatusTone, row.MarkTone = rules.Priorities.UnreadLine, "plain", "info"
	default:
		figure := thousands(count)
		if spec.One != "" {
			title := spec.Title
			if count == 1 {
				title = spec.One
			}
			row.Title, row.Context = figure+" "+title, spec.Counts
		} else {
			row.Context = figure + " " + spec.Counts
		}
		row.StatusLabel, row.StatusTone, row.MarkTone = "All clear", "good", "info"
		if count != 0 {
			row.StatusLabel, row.StatusTone, row.MarkTone = "Critical", "alert", "alert"
		}
		row.Count = int32(count)
	}
	return row
}

// thousands is Python's f"{n:,}".
func thousands(n int) string {
	digits := strconv.Itoa(n)
	sign := ""
	if strings.HasPrefix(digits, "-") {
		sign, digits = "-", digits[1:]
	}
	for i := len(digits) - 3; i > 0; i -= 3 {
		digits = digits[:i] + "," + digits[i:]
	}
	return sign + digits
}

// BuildTodoFigures answers GetHomeTodoFigures for p: the To-Do figures and
// the To-Do count, from the reader's queue (build_home_todo_figures).
// served is false where the existing application answers Home or the
// queue (todos.Service.QueueCounts).
func (s *Service) BuildTodoFigures(ctx context.Context, p auth.Principal) (*screensv1.GetHomeTodoFiguresResponse, bool, error) {
	role, ok := roleOf(p)
	if !ok {
		return nil, refused(p), refusal(p)
	}
	counts, total, served, err := s.todos.QueueCounts(ctx, p)
	if !served || err != nil {
		return nil, served, err
	}
	return &screensv1.GetHomeTodoFiguresResponse{QueueFigures: QueueFigures(counts, role.HasPlan), PriorityTotal: int32(total)}, true, nil
}
