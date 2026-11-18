package schoolprofile

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// The Activities tab of a profile of many schools: the year's work by kind
// (engine._execution with _expected), training by channel and the cluster
// meetings (profile_records.channels and meetings), then the list.

// scopeExecutionFigures is engine._execution over the scope, with what the
// year asks of its schools (_expected): the visits and trainings each
// school's type is due, the schools due any, and those with one in the plan
// or completed.
func (s *Service) scopeExecutionFigures(ctx context.Context, pr *scopeProfile, l lens, today time.Time) (executionFigures, error) {
	var ex executionFigures
	args := []any{}
	where := scopeWork(idsOf(pr.schools), clusterIDsOf(pr.schools), l.fy, l.window, &args)
	args = append(args, rules.Engine.CompletedWorkStatuses, rules.Engine.NotStartedStatuses, today)
	k := len(args)
	done := fmt.Sprintf("a.status = ANY($%d)", k-2)
	waiting := fmt.Sprintf("a.status = ANY($%d)", k-1)
	past := fmt.Sprintf(`(a.planned_date < $%[1]d::date OR (a.planned_date IS NULL AND (a.scheduled_date AT TIME ZONE 'Africa/Nairobi')::date < $%[1]d::date))`, k)
	cols := []string{}
	targets := []any{}
	for _, kind := range []struct {
		f     *kindFigures
		types []string
	}{{&ex.visits, rules.Engine.VisitTypes}, {&ex.trainings, rules.Engine.TrainingTypes}, {&ex.meetings, rules.Engine.MeetingTypes}} {
		args = append(args, kind.types)
		of := fmt.Sprintf("a.activity_type = ANY($%d)", len(args))
		count := func(filter string) string { return "COUNT(a.id) FILTER (WHERE " + of + " AND " + filter + ")" }
		cols = append(cols, count("true"), count(done), count(waiting), count(waiting+" AND "+past),
			count("a.delivery_type = 'partner'"),
			"COUNT(DISTINCT a.school_id) FILTER (WHERE "+of+")",
			"COUNT(DISTINCT a.school_id) FILTER (WHERE "+of+" AND "+done+")")
		f := kind.f
		targets = append(targets, &f.planned, &f.completed, &f.notStarted, &f.overdue, &f.byPartner, &f.schools, &f.schoolsDone)
	}
	if err := s.db.QueryRow(ctx, "SELECT "+strings.Join(cols, ", ")+" FROM activity a WHERE "+where, args...).Scan(targets...); err != nil {
		return ex, fmt.Errorf("schoolprofile: counting the profile's work by kind: %w", err)
	}
	for _, e := range []struct {
		f      *kindFigures
		visits bool
	}{{&ex.visits, true}, {&ex.trainings, false}} {
		expected, due, reached, inPlan := 0, 0, 0, 0
		for _, x := range pr.schools {
			need := rules.Engine.Requirements[x.kind]
			ask := need.Trainings
			if e.visits {
				ask = need.Visits
			}
			if ask == 0 {
				continue
			}
			expected += ask
			due++
			at := pr.schoolWork[x.id]
			if at == nil {
				continue
			}
			planned, completed := at.trainings, at.trainingsDone
			if e.visits {
				planned, completed = at.visits, at.visitsDone
			}
			if completed > 0 {
				reached++
			}
			if planned > 0 {
				inPlan++
			}
		}
		e.f.expected, e.f.schoolsDue = &expected, &due
		if due > 0 {
			c, pc := pyRoundInt(float64(reached*100)/float64(due)), pyRoundInt(float64(inPlan*100)/float64(due))
			e.f.coverage, e.f.planCoverage = &c, &pc
		}
	}
	return ex, nil
}

// scopeList is profile_activities over a profile's own work: the planned
// and the completed, fifty a page each, decorated with the reader's menus.
type scopeList struct {
	planned, completed       []activityRow
	plannedAll, completedAll int
	overdue                  int
	param                    string
	plannedPager, donePager  *screensv1.PageBlock
	active                   string
}

func (s *Service) scopeActivityList(ctx context.Context, p auth.Principal, scope schooldirectory.Scope, d doors,
	source func(args *[]any) string, param string, query url.Values, today time.Time) (scopeList, error) {
	out := scopeList{param: param, active: "planned"}
	pr := rules.Participation
	planned, err := s.listedWhere(ctx, scope, pr.OpenStatuses, "a.planned_date ASC NULLS LAST, a.created_at, a.id", source)
	if err != nil {
		return out, err
	}
	completed, err := s.listedWhere(ctx, scope, pr.DeliveredStatuses,
		"COALESCE(a.actual_delivery_date, a.planned_date) DESC NULLS LAST, a.created_at DESC, a.id", source)
	if err != nil {
		return out, err
	}
	out.plannedAll, out.completedAll = len(planned), len(completed)
	for _, a := range planned {
		if a.planned != nil && a.planned.Before(today) && slices.Contains(pr.PlannedStatuses, a.status) {
			out.overdue++
		}
	}
	requested := strings.TrimSpace(query.Get(param + "_tab"))
	switch {
	case requested == "planned" || requested == "completed":
		out.active = requested
	case len(planned) == 0 && len(completed) > 0:
		out.active = "completed"
	}
	plannedPage := tablepager.Paginate(len(planned), pr.PageSize, query, param+"_planned_page")
	donePage := tablepager.Paginate(len(completed), pr.PageSize, query, param+"_done_page")
	out.plannedPager = tablepager.Panel(len(planned), pr.PageSize, query, param+"_planned_page")
	out.donePager = tablepager.Panel(len(completed), pr.PageSize, query, param+"_done_page")
	shown := append(append([]listedActivity{}, planned[plannedPage.Start:plannedPage.End]...), completed[donePage.Start:donePage.End]...)
	names, err := s.executors(ctx, shown)
	if err != nil {
		return out, err
	}
	r := reader{p: p, scope: scope, s: s}
	n := plannedPage.End - plannedPage.Start
	for i, a := range shown {
		row, err := r.decorate(ctx, d, a, names, today)
		if err != nil {
			return out, err
		}
		if i < n {
			out.planned = append(out.planned, row)
		} else {
			out.completed = append(out.completed, row)
		}
	}
	return out, nil
}

// block is partials/components/profile_activities.html for the list.
func (l scopeList) block(caption string) *screensv1.PageBlock {
	subtitle := fmt.Sprintf("%d planned · %d completed", l.plannedAll, l.completedAll)
	if l.overdue != 0 {
		subtitle += fmt.Sprintf(" · %d overdue", l.overdue)
	}
	segment := func(label string, rows []activityRow, all int, done bool, pager *screensv1.PageBlock) *screensv1.PageSegment {
		blocks := []*screensv1.PageBlock{activityTable(rows, done)}
		if pager != nil {
			blocks = append(blocks, pager)
		}
		return &screensv1.PageSegment{Label: label, Count: fmt.Sprint(all), Active: l.active == strings.ToLower(label), Blocks: blocks}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Segments{Segments: &screensv1.PageSegments{
		Title: "Planned & Completed Activities", Subtitle: subtitle, Caption: caption,
		Segments: []*screensv1.PageSegment{
			segment("Planned", l.planned, l.plannedAll, false, l.plannedPager),
			segment("Completed", l.completed, l.completedAll, true, l.donePager),
		},
	}}}
}

// selection is the bar for ticked activities, drawn where a planned row
// on the page can be ticked.
func (l scopeList) selection() *screensv1.PageSelection {
	return activityList{planned: l.planned}.selection()
}
