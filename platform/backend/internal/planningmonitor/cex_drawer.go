package planningmonitor

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ErrNoSuchDrawer is drawer_view's Http404: a kind other than activities.
var ErrNoSuchDrawer = errors.New("planningmonitor: no such execution drawer")

// cexStageTitles is drawer_view's _STAGE_TITLES: what each drill-down is
// called.
var cexStageTitles = map[string]string{
	"due": "Activities planned", "started": "Activities started", "not_started": "Activities not started",
	"executed": "Execution completed", "pl_review": "Waiting on PL review", "ia_review": "Waiting on IA verification",
	"verified": "Verified activities", "closed": "Fully closed activities", "returned": "Returned for correction",
	"overdue": "Overdue activities", "finance": "Verified, closure open", "cancelled": "Cancelled activities",
}

// cexStaffDelivery is the partner_key a row's staff delivery is opened with.
const cexStaffDelivery = "__staff__"

// CountryExecutionDrawer is drawer_view: the records behind a figure (a
// card, a backlog slice, an age bar, a row's View), filtered to what it
// counted, as partials/country_execution/drawer_activities.html is read.
func CountryExecutionDrawer(ctx context.Context, db schooldirectory.Querier, p auth.Principal, query url.Values,
	now time.Time) (*screensv1.PageDrawer, error) {
	get := func(name string) string {
		if v := query[name]; len(v) > 0 {
			return strings.TrimSpace(v[len(v)-1])
		}
		return ""
	}
	kind := get("kind")
	if kind == "" {
		kind = "activities"
	}
	if kind != "activities" {
		return nil, ErrNoSuchDrawer
	}
	q := map[string]string{}
	for k, v := range query {
		if len(v) > 0 {
			q[k] = v[len(v)-1]
		}
	}
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	s, err := buildCEXSnapshot(ctx, db, scope, cexReadFilters(q, today), today)
	if err != nil {
		return nil, err
	}
	k := cexActivityPick{stage: get("stage"), owner: get("owner"), lead: get("lead"), partner: get("partner_key"),
		blocker: get("blocker"), age: get("age")}
	asked := 1
	if n, ok := clusterpage.PyInt(get("page")); ok {
		asked = n
	}
	picked := s.pickActivities(k)
	items := []*screensv1.DrawerItem{cexDrawerText(s.drawerSubtitle(k, len(picked)))}
	reader := cpoReaderFor(p.ActiveRole, false)
	if reader.followUp && s.followUpLead(k) != "" {
		items = append(items, cexDrawerText("Follow Up with PL"))
	}
	if scope.SummaryOnly {
		items = append(items, cexDrawerText(fmt.Sprintf("%d activities. Activity rows are not shown for your role.", len(picked))))
	} else {
		list := s.listQuery(k)
		nodes, err := s.activityRowsNodes(ctx, db, picked, asked, func(total, page, pages int) *node {
			return cexDrawerPager(list, total, page, pages)
		})
		if err != nil {
			return nil, err
		}
		for _, b := range walk(nodes...) {
			items = append(items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Block{Block: b}})
		}
	}
	title := cexStageTitles[k.stage]
	if title == "" {
		title = "Activities"
	}
	return &screensv1.PageDrawer{Title: title, Subtitle: "Configure action details", HasRequired: true, Items: items,
		CancelLabel: "Cancel"}, nil
}

func cexDrawerText(text string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: text}}
}

// drawerSubtitle is the drawer's line: whose work, the period and the count.
func (s *cexSnapshot) drawerSubtitle(k cexActivityPick, total int) string {
	parts := []string{}
	if k.lead != "" {
		name := ""
		for _, l := range s.tree.leads {
			if l.key == k.lead {
				name = l.name
				break
			}
		}
		parts = append(parts, name)
	}
	if k.owner != "" {
		name := "Unassigned work"
		if o := s.data.owners[k.owner]; o != nil {
			name = o.name
		}
		parts = append(parts, name)
	}
	if k.partner != "" {
		name := s.data.partnerName[k.partner]
		switch {
		case k.partner == cexStaffDelivery:
			name = "Staff delivery"
		case name == "":
			name = "Partner"
		}
		parts = append(parts, name)
	}
	if k.blocker != "" {
		label := k.blocker
		for _, o := range rules.CountryExecution.Stages.OwnerLabels {
			if o[0] == k.blocker {
				label = o[1]
			}
		}
		parts = append(parts, "Waiting on "+label)
	}
	parts = append(parts, s.data.window.label())
	parts = slices.DeleteFunc(parts, func(p string) bool { return p == "" })
	unit := "activities"
	if total == 1 {
		unit = "activity"
	}
	return strings.Join(parts, " · ") + " · " + cpoFmt(total) + " " + unit
}

// followUpLead is the Lead the drawer's Follow Up goes to, if any.
func (s *cexSnapshot) followUpLead(k cexActivityPick) string {
	lead := k.lead
	if k.owner != "" && k.owner != rules.CountryOversight.NoOwner[0] {
		lead = ""
		if o := s.data.owners[k.owner]; o != nil {
			lead = o.leadKey
		}
	}
	if lead == rules.CountryOversight.NoLead[0] {
		return ""
	}
	return lead
}

// listQuery is the drawer's list_query: the tab's selection and the
// drawer's own narrowing, the blank ones dropped.
func (s *cexSnapshot) listQuery(k cexActivityPick) string {
	q := s.filters.query() + "&kind=activities"
	for _, kv := range [][2]string{{"stage", k.stage}, {"owner", k.owner}, {"lead", k.lead}, {"partner_key", k.partner},
		{"blocker", k.blocker}, {"age", k.age}} {
		if kv[1] != "" {
			q += "&" + kv[0] + "=" + url.QueryEscape(kv[1])
		}
	}
	return q
}

// cexDrawerPager is _pager.html with the drawer as its target.
func cexDrawerPager(list string, total, page, pages int) *node {
	if pages <= 1 {
		return nil
	}
	p := &screensv1.PagePager{Pages: []*screensv1.PagePagerPage{{Label: fmt.Sprintf("%d in all · page %d of %d", total, page, pages)}}}
	link := func(label string, to int) *screensv1.PagePagerPage {
		return &screensv1.PagePagerPage{Label: label, Href: fmt.Sprintf("%s/drawer?%s&page=%d", cexBase, list, to)}
	}
	if page > 1 {
		p.Pages = append(p.Pages, link("Previous", page-1))
	}
	if page < pages {
		p.Pages = append(p.Pages, link("Next", page+1))
	}
	return feeddom.PreBlock(&screensv1.PageBlock{Kind: &screensv1.PageBlock_Pager{Pager: p}})
}
