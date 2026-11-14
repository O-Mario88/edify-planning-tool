// Package leavepolicies is HR Leave Policies & Holiday Settings
// (/leave/policies): each leave type's policy and the public holidays
// planning treats as days off, as the existing page draws them
// (apps.frontend.views.leave_views.leave_policies_view and
// pages/leave/leave_policies.html) and the app's feed reads them. Its forms
// (a policy's entitlement and approver, adding and removing a holiday) stay
// with the existing application; the feed reads only their headings.
//
// The doors and the national list's length are exported to rules.json by
// `manage.py export_leave_policies_rules`;
// apps/hr/test_leave_policies_rules_export.py fails when the two differ.
package leavepolicies

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"time"

	_ "time/tzdata" // the server's day is Nairobi's wherever the gateway runs

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers.
const Path = "/leave/policies"

//go:embed rules.json
var rulesJSON []byte

// Role is what a role is given on the page.
type Role struct {
	Page  bool               `json:"page"`
	Strip *decisionlog.Strip `json:"strip"`
}

var rules = func() (r struct {
	Roles         map[string]Role `json:"roles"`
	NationalLimit int             `json:"national_limit"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || r.NationalLimit <= 0 {
		panic(fmt.Sprintf("leavepolicies: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("leavepolicies: " + err.Error())
	}
	return z
}()

// Service builds the page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func heading(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: t}}
}

func panel(title, subtitle string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Subtitle: subtitle, Items: items}}}
}

// Build answers path for p. served is false for a path this package does not
// answer, and for a database with no policy yet: the existing view writes
// the default policies on that first read, which Go never does.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, _ url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	// LeaveTypePolicy.objects.all(): no order, as the view reads them.
	rows, err := s.db.Query(ctx, `SELECT label, leave_type FROM leave_type_policy`)
	if err != nil {
		return nil, true, fmt.Errorf("leavepolicies: reading the policies: %w", err)
	}
	policies, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) ([2]string, error) {
		var p [2]string
		err := r.Scan(&p[0], &p[1])
		return p, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("leavepolicies: reading the policies: %w", err)
	}
	if len(policies) == 0 {
		return nil, false, nil
	}
	rows, err = s.db.Query(ctx, `SELECT name, date FROM public_holiday ORDER BY date`)
	if err != nil {
		return nil, true, fmt.Errorf("leavepolicies: reading the recorded holidays: %w", err)
	}
	recorded, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (added, error) {
		var a added
		err := r.Scan(&a.name, &a.date)
		return a, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("leavepolicies: reading the recorded holidays: %w", err)
	}
	now := s.now().In(zone)
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	upcoming, err := calendarpage.Upcoming(ctx, s.db, today, rules.NationalLimit)
	if err != nil {
		return nil, true, fmt.Errorf("leavepolicies: reading the national calendar: %w", err)
	}
	national := []calendarpage.Holiday{}
	for _, h := range upcoming {
		if !h.Recorded {
			national = append(national, h)
		}
	}
	return page(role, policies, recorded, national), true, nil
}

// added is a holiday recorded on the platform.
type added struct {
	name string
	date time.Time
}

// recordedDate is {{ h.date }}: Django's DATE_FORMAT for en-us, "N j, Y"
// (the month as Associated Press writes it).
func recordedDate(d time.Time) string {
	months := []string{"Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."}
	return fmt.Sprintf("%s %d, %d", months[d.Month()-1], d.Day(), d.Year())
}

func page(role Role, policies [][2]string, recorded []added, national []calendarpage.Holiday) *screensv1.GetPageResponse {
	blocks := []*screensv1.PageBlock{}
	if role.Strip != nil {
		tabs := &screensv1.PageLinkTabs{Label: role.Strip.Label, Scrolls: role.Strip.Scrolls}
		for _, t := range role.Strip.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})
	}
	items := []*screensv1.PagePanelItem{}
	for _, p := range policies {
		items = append(items, heading(p[0]), text("Key: "+p[1]))
	}
	blocks = append(blocks,
		panel("Leave Entitlement Policies", "Days per year, who approves, whether a supporting document is required and whether weekends count.", items...),
		panel("Public Holidays", "Dates planning treats as holidays for every team. Uganda's national holidays are built in; add a day only when "+
			"the Government declares one or announces an Eid date.",
			text(fmt.Sprintf("%d added · %d national in the next 12 months", len(recorded), len(national)))))
	days := []*screensv1.PagePanelItem{}
	for _, h := range recorded {
		days = append(days, text(h.name), text("Date: "+recordedDate(h.date)))
	}
	for _, h := range national {
		days = append(days, text(h.Label), text("Date: "+h.Date.Format("Monday 2 January 2006")), text("National calendar"))
	}
	if len(days) > 0 {
		blocks = append(blocks, panel("", "", days...))
	}
	blocks = append(blocks, panel("Add Public Holiday", ""))
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{Eyebrow: "Time & Availability", Title: "HR Leave Policies & Holiday Settings",
			Description: "Configure entitlements, required documents, approval roles, and global public holidays"},
		Blocks: blocks, WebPath: Path,
	}
}
