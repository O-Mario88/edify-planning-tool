package dashboard

import (
	"context"
	"fmt"
	"net/url"
	"sort"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trainingsummary"
)

// A Programme Lead's This Week (partials/dashboards/pl/week_view.html): the
// week across the lead and their team (apps.analytics.pl_week_service), then
// every overdue plan of any age ("What needs you now" for a lead).

// officer is one supervised staff profile as resolve_pl_scope lists it.
type officer struct{ staffID, userID, name string }

// supervisedOfficers is resolve_pl_scope's cceos: every staff profile with a
// reporting line to the lead, by name.
func supervisedOfficers(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) ([]officer, error) {
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	if len(scope.SupervisedStaffIDs) == 0 {
		return nil, nil
	}
	rows, err := db.Query(ctx, `SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(NULLIF(u.name, ''), NULLIF(sp.title, ''), 'CCEO')
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id WHERE sp.id = ANY($1)`, scope.SupervisedStaffIDs)
	if err != nil {
		return nil, fmt.Errorf("dashboard: the lead's officers: %w", err)
	}
	defer rows.Close()
	var out []officer
	for rows.Next() {
		var o officer
		if err := rows.Scan(&o.staffID, &o.userID, &o.name); err != nil {
			return nil, fmt.Errorf("dashboard: the lead's officers: %w", err)
		}
		out = append(out, o)
	}
	sort.SliceStable(out, func(i, j int) bool { return strings.ToLower(out[i].name) < strings.ToLower(out[j].name) })
	return out, rows.Err()
}

func (o officer) ids() []string {
	if o.userID == "" {
		return []string{o.staffID}
	}
	return []string{o.staffID, o.userID}
}

// leadPeople is PLWeek._people: the lead first, then the line-managed team,
// then anyone else reporting to the lead who holds work in the two weeks the
// page reads (_others_with_work). team is every id the team's work is filed
// under, for the past-due list.
func leadPeople(ctx context.Context, db schooldirectory.Querier, p auth.Principal, start, now time.Time) (people []myplan.TeamPerson, team []string, err error) {
	people = []myplan.TeamPerson{{Key: "me", Name: "You", StaffID: p.StaffProfileID, IDs: myplan.OwnerIDs(p), Me: true}}
	supervised, err := supervisedOfficers(ctx, db, p, now)
	if err != nil {
		return nil, nil, err
	}
	members, err := trainingsummary.TeamMembers(ctx, db, p.StaffProfileID, now)
	if err != nil {
		return nil, nil, err
	}
	onTeam := map[string]bool{}
	for _, m := range members {
		onTeam[m.StaffID] = true
		team = append(team, m.StaffID)
		if m.UserID != "" {
			team = append(team, m.UserID)
		}
	}
	busy, err := othersWithWork(ctx, db, supervised, onTeam, start)
	if err != nil {
		return nil, nil, err
	}
	for _, pass := range []func(officer) bool{
		func(o officer) bool { return onTeam[o.staffID] },
		func(o officer) bool { return !onTeam[o.staffID] && busy[o.staffID] },
	} {
		for _, o := range supervised {
			if pass(o) {
				people = append(people, myplan.TeamPerson{Key: o.staffID, Name: o.name, StaffID: o.staffID, IDs: o.ids()})
			}
		}
	}
	return people, team, nil
}

// othersWithWork is which officers off the team hold their own work dated in
// the week or the one before it.
func othersWithWork(ctx context.Context, db schooldirectory.Querier, supervised []officer, onTeam map[string]bool,
	start time.Time) (map[string]bool, error) {
	byID := map[string]string{}
	var ids []string
	for _, o := range supervised {
		if onTeam[o.staffID] {
			continue
		}
		for _, id := range o.ids() {
			byID[id] = o.staffID
			ids = append(ids, id)
		}
	}
	out := map[string]bool{}
	if len(ids) == 0 {
		return out, nil
	}
	found, err := myplan.ResponsibleWithWork(ctx, db, ids, start.AddDate(0, 0, -7), start.AddDate(0, 0, 6))
	if err != nil {
		return nil, err
	}
	for _, id := range found {
		out[byID[id]] = true
	}
	return out, nil
}

// leadWeek is the lead's This Week and backlog, or false where the page is
// one Go does not draw: the lead's own tab (it opens their Today
// workbench), the Partners tab, a pressed figure, an acting seat, a paged
// table.
func leadWeek(ctx context.Context, db schooldirectory.Querier, p auth.Principal, query url.Values, fy string,
	now time.Time) ([]*screensv1.PageBlock, bool, error) {
	who := strings.TrimSpace(query.Get("who"))
	if p.InActingAppointment || who == "me" || who == "partners" || myplan.ShowFilter(query.Get("show")) {
		return nil, false, nil
	}
	local := now.In(kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	start := myplan.ResolveWeek(query.Get("week"), today)
	people, team, err := leadPeople(ctx, db, p, start, now)
	if err != nil {
		return nil, true, err
	}
	week, err := myplan.ReadTeamWeek(ctx, db, people, start, now, fy, who)
	if err != nil {
		return nil, true, err
	}
	past, err := myplan.ReadTeamPastDue(ctx, db, myplan.OwnerIDs(p), team, now, strings.TrimSpace(query.Get("plans")))
	if err != nil {
		return nil, true, err
	}
	if week.Paged || past.Paged {
		return nil, false, nil
	}
	return append(myplan.TeamWeekBlocks(week), myplan.PastDueBlocks(past)...), true, nil
}

// LeadWeekBlocks is leadWeek for the comparison with the existing page's
// own This Week, before the dashboard around it is Go's.
func LeadWeekBlocks(ctx context.Context, db schooldirectory.Querier, p auth.Principal, query url.Values, fy string,
	now time.Time) ([]*screensv1.PageBlock, bool, error) {
	return leadWeek(ctx, db, p, query, fy, now)
}
