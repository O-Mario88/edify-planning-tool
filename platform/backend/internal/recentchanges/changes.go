// Package recentchanges is the Planning page's Recent changes drawer in Go
// with Django absent (undo_views.recent_changes_drawer_view and
// apps.planning.undo.recent_changes): the reader's own partner hand-overs,
// project enrolments and cluster moves from the last week, each with what
// Undo would do or why it no longer can.
//
// The drawer reads; Undo itself is not reachable from the Go web, so the
// rows carry no Undo button (docs/migration/189).
package recentchanges

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
)

// ErrHandOn says the existing application keeps this request.
var ErrHandOn = errors.New("recentchanges: handed on")

// window is UNDO_WINDOW.
const window = 7 * 24 * time.Hour

// Change is one row of the list.
type Change struct {
	Kind                     string
	MadeAt                   time.Time
	Summary, Effect, Blocked string
}

// Service reads the list.
type Service struct {
	db  *pgxpool.Pool
	now func() time.Time
}

// New makes the service.
func New(db *pgxpool.Pool, now func() time.Time) *Service { return &Service{db: db, now: now} }

func plural(n int64, unit string) string {
	if n == 1 {
		return fmt.Sprintf("1 %s", unit)
	}
	return fmt.Sprintf("%d %ss", n, unit)
}

// timesince is django.utils.timesince to two adjacent units, for the ages a
// week's window holds (weeks, days, hours, minutes).
func timesince(d, now time.Time) string {
	seconds := int64(now.Sub(d) / time.Second)
	if seconds < 60 {
		return "0 minutes"
	}
	chunks := []struct {
		size int64
		unit string
	}{{7 * 86400, "week"}, {86400, "day"}, {3600, "hour"}, {60, "minute"}}
	parts := make([]int64, len(chunks))
	for i, c := range chunks {
		parts[i] = seconds / c.size
		seconds -= parts[i] * c.size
	}
	first := 0
	for first < len(parts) && parts[first] == 0 {
		first++
	}
	out := []string{plural(parts[first], chunks[first].unit)}
	if next := first + 1; next < len(parts) && parts[next] != 0 {
		out = append(out, plural(parts[next], chunks[next].unit))
	}
	return strings.Join(out, ", ")
}

func heading(t string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Heading{Heading: t}}
}

func text(t string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: t}}
}

func note(t, tone string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: t, Tone: tone}}}
}

// drawerFor is recent_changes_drawer.html and its list.
func drawerFor(changes []Change, now time.Time) *screensv1.PageDrawer {
	d := &screensv1.PageDrawer{Title: "Recent changes", HasRequired: true, CancelLabel: "Cancel",
		Subtitle: "Your partner, project and cluster changes from the last 7 days. Undo one made by mistake."}
	if len(changes) == 0 {
		d.Items = []*screensv1.DrawerItem{note("Nothing to undo. Schools you assign to a partner, add to a project or put in a cluster show here for a week.", "info")}
		return d
	}
	for _, c := range changes {
		d.Items = append(d.Items, heading(c.Summary), text(c.Kind+" · "+timesince(c.MadeAt, now)+" ago"))
		if c.Blocked != "" {
			d.Items = append(d.Items, note(c.Blocked, "warning"))
		} else {
			d.Items = append(d.Items, text(c.Effect))
		}
	}
	return d
}

// Drawer is recent_changes_drawer_view for p.
func (s *Service) Drawer(ctx context.Context, p auth.Principal) (*screensv1.PageDrawer, error) {
	if p.InActingAppointment || !clusterpage.RoleDoors(p.ActiveRole).AddSchools {
		return nil, ErrHandOn
	}
	now := s.now()
	changes, err := s.recent(ctx, p, now)
	if err != nil {
		return nil, err
	}
	return drawerFor(changes, now), nil
}

// actorIDs is undo.actor_ids.
func actorIDs(p auth.Principal) []string {
	ids := []string{}
	for _, id := range []string{p.StaffProfileID, p.UserID} {
		if id != "" && (len(ids) == 0 || ids[0] != id) {
			ids = append(ids, id)
		}
	}
	return ids
}

// recent is undo.recent_changes: partner, project and cluster changes from
// the window, newest first (a stable sort, as Python's is).
func (s *Service) recent(ctx context.Context, p auth.Principal, now time.Time) ([]Change, error) {
	ids := actorIDs(p)
	if len(ids) == 0 {
		return nil, nil
	}
	since := now.Add(-window)
	partners, err := s.partnerChanges(ctx, ids, since)
	if err != nil {
		return nil, err
	}
	projects, err := s.projectChanges(ctx, ids, since)
	if err != nil {
		return nil, err
	}
	clusters, err := s.clusterChanges(ctx, p, ids, since)
	if err != nil {
		return nil, err
	}
	all := append(append(partners, projects...), clusters...)
	sort.SliceStable(all, func(i, j int) bool { return all[i].MadeAt.After(all[j].MadeAt) })
	return all, nil
}
