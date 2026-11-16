package staffactivity

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trainingsummary"
)

// A Programme Lead's log (viewer_scope's "team" mode): themselves and the
// people they supervise, the officers of a Lead they cover included, as the
// lead's dashboard carries it (partials/staff_activity/_workspace.html,
// embedded): the section's head, the filters, the figures, the team's
// insights, the team's table and the picked person's note.

const (
	teamDesc       = "How your team uses the platform: active time, the parts they use, and the meaningful work they complete."
	teamTableTitle = "Your team"
)

// teamIDs is presence.team_user_ids kept to the roles the log covers
// (_tracked): the lead, their supervisees, and the officers they cover.
func (s *Service) teamIDs(ctx context.Context, p auth.Principal, now time.Time) ([]string, error) {
	ids := map[string]bool{p.UserID: true}
	rows, err := s.db.Query(ctx, `SELECT sub.user_id FROM staff_supervisor_assignment a
JOIN staff_profile sup ON sup.id = a.supervisor_id JOIN staff_profile sub ON sub.id = a.supervisee_id
WHERE sup.user_id = $1 AND sup.deleted_at IS NULL AND sub.deleted_at IS NULL AND sub.user_id IS NOT NULL`, p.UserID)
	if err != nil {
		return nil, fmt.Errorf("staffactivity: the lead's team: %w", err)
	}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return nil, fmt.Errorf("staffactivity: the lead's team: %w", err)
		}
		ids[id] = true
	}
	rows.Close()
	members, err := trainingsummary.TeamMembers(ctx, s.db, p.StaffProfileID, now)
	if err != nil {
		return nil, err
	}
	for _, m := range members {
		if m.UserID != "" {
			ids[m.UserID] = true
		}
	}
	all := make([]string, 0, len(ids))
	for id := range ids {
		all = append(all, id)
	}
	tracked, err := s.db.Query(ctx, `SELECT id FROM "user" WHERE id = ANY($1) AND active_role = ANY($2)`, all, rules.InternalRoles)
	if err != nil {
		return nil, fmt.Errorf("staffactivity: the lead's team: %w", err)
	}
	defer tracked.Close()
	var out []string
	for tracked.Next() {
		var id string
		if err := tracked.Scan(&id); err != nil {
			return nil, fmt.Errorf("staffactivity: the lead's team: %w", err)
		}
		out = append(out, id)
	}
	sort.Strings(out)
	return out, tracked.Err()
}

// teamLog is activity_log for a Programme Lead.
func (s *Service) teamLog(ctx context.Context, p auth.Principal, query url.Values) (*theLog, error) {
	now := s.now()
	today := dateOf(now)
	f := filters{period: query.Get("period"), on: query.Get("on"), role: strings.TrimSpace(query.Get("role")),
		status: strings.TrimSpace(query.Get("status")), q: runes(strings.TrimSpace(query.Get("q")), 80)}
	chosen := choosePeriod(f.period, f.on, today)
	ids, err := s.teamIDs(ctx, p, now)
	if err != nil {
		return nil, err
	}
	everyone, err := buildPeople(ctx, s.db, ids, chosen, now, today)
	if err != nil {
		return nil, err
	}
	// The reader's own row: nobody follows up with themselves.
	for _, x := range everyone {
		if x.id == p.UserID {
			x.suggestions, x.reasons = 0, nil
			if x.usageKey == "follow_up" {
				x.usageKey, x.usageLabel = "normal", "Normal"
			}
		}
	}
	sort.SliceStable(everyone, func(i, j int) bool { return everyone[i].id == p.UserID && everyone[j].id != p.UserID })
	l := &theLog{period: chosen, everyone: everyone, total: len(everyone), filters: f, today: today, canFollowUp: true}
	l.people = narrow(everyone, f)
	for _, role := range rules.InternalRoles {
		if slices.ContainsFunc(everyone, func(x *person) bool { return x.role == role }) {
			name, _ := label(rules.RoleFilterLabels, role)
			l.roleOptions = append(l.roleOptions, [2]string{role, name})
		}
	}
	if l.followUpCount, err = followUpCount(ctx, s.db, p.UserID); err != nil {
		return nil, err
	}
	if len(l.people) > rules.PageSize {
		// More people than one page: the pager is not drawn here.
		return nil, errPassOn
	}
	if l.insights, err = teamInsights(ctx, s.db, l.people, chosen, today); err != nil {
		return nil, err
	}
	return l, nil
}

// TeamEmbed is the lead's log as their dashboard carries it, or false where
// Go does not draw it: an acting seat, or more people than one page.
func (s *Service) TeamEmbed(ctx context.Context, p auth.Principal, query url.Values) ([]*screensv1.PageBlock, bool, error) {
	if p.ActiveRole != rules.Roles.ProgramLead || p.InActingAppointment {
		return nil, false, nil
	}
	l, err := s.teamLog(ctx, p, query)
	if errors.Is(err, errPassOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	exportQuery := url.Values{}
	for k, v := range query {
		if k != "page" && k != "staff_page" {
			exportQuery[k] = v
		}
	}
	queue := followUpQueue
	if l.followUpCount > 0 {
		queue = fmt.Sprintf("%s %d", queue, l.followUpCount)
	}
	head := &screensv1.PagePanel{Title: "Staff Activity", Subtitle: teamDesc, Items: []*screensv1.PagePanelItem{
		{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
			{Text: "Export", Href: "/staff-activity/export?" + exportQuery.Encode()},
			{Text: queue, Href: followUpQueueURL, Drawer: true},
		}}}},
	}}
	caption := fmt.Sprintf("%d of %d staff · %s · active time excludes idle tabs (after %d minutes untouched)",
		len(l.people), l.total, capfirst(l.period.label), rules.Thresholds.IdleSeconds/60)
	return []*screensv1.PageBlock{
		block(head),
		filtersBlock(l),
		stripBlock(figures(l.people)),
		insightsBlock(l),
		block(&screensv1.PagePanel{Title: teamTableTitle, Items: []*screensv1.PagePanelItem{text(caption)}}),
		teamTable(l, p.UserID),
		block(&screensv1.PagePanel{Items: []*screensv1.PagePanelItem{text(pickedNote)}}),
	}, true, nil
}

// teamTable is the team's people in one list, the reader's own row without
// a follow-up.
func teamTable(l *theLog, self string) *screensv1.PageBlock {
	cols := make([]*screensv1.PageColumn, len(columns))
	for i, c := range columns {
		cols[i] = &screensv1.PageColumn{Label: c}
	}
	rows := []*screensv1.PageRow{}
	labels := func(x *person) (string, string, string) {
		at := ""
		if x.lastActionAt != nil {
			at = clock(x.lastActionAt, l.today)
		}
		return clock(x.firstActive, l.today), clock(x.lastActive, l.today), at
	}
	for _, x := range l.people {
		r := row(x, l, labels)
		if x.id == self {
			r.Cells[len(r.Cells)-1] = &screensv1.PageCell{Actions: []*screensv1.PageAction{}}
		}
		rows = append(rows, r)
	}
	if len(rows) == 0 {
		rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{cell(nobody)}})
	}
	return block(&screensv1.PageTable{Columns: cols, Rows: rows})
}
