package partneroversight

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
)

// work draws the page for a team-lens reader whose workspace holds partner
// work, or hands it on (served false) where it draws what this piece does
// not build yet: work waiting for IA verification (its reviewer's Verify
// and Return), Core Schools, Special Project work, a decided hand-back,
// group trainings a Partner facilitates, withdrawal requests, a Partner
// needing follow-up, the Clusters tab (two tables), an activity filter, or
// a table longer than one page.
func (s *Service) work(ctx context.Context, p auth.Principal, w workspace, own []string, supervised []string,
	activityType string, now time.Time) (*screensv1.GetPageResponse, bool, error) {
	if activityType != "" {
		return nil, false, nil
	}
	staff := own
	if !w.role.OwnWorkOnly {
		var err error
		if staff, err = bothIDSpaces(ctx, s.db, append(append([]string{}, own...), supervised...)); err != nil {
			return nil, true, err
		}
	}
	operational, _ := strconv.Atoi(schooldirectory.OperationalFY(now))
	years, err := schoolplanning.Horizon(ctx, s.db, p.Country, w.period.fy, operational, w.fyOptions, now)
	if err != nil {
		return nil, true, err
	}
	if held, err := handedOn(ctx, s.db, staff, years); err != nil || held {
		return nil, !held, err
	}
	today := dateOf(now.In(zone))
	items, err := readItems(ctx, s.db, staff, years, today)
	if err != nil {
		return nil, true, err
	}
	items = narrow(items, w.period)
	if err := annotate(ctx, s.db, items, today); err != nil {
		return nil, true, err
	}
	follow, err := followUps(ctx, s.db, "", w.period.fy)
	if err != nil {
		return nil, true, err
	}

	v := &workView{w: w, today: today, years: years}
	counts := map[string]int{}
	names := map[string]string{}
	for _, i := range items {
		if i.partnerID != "" {
			counts[i.partnerID]++
			names[i.partnerID] = i.partnerName
		}
	}
	for id, n := range counts {
		v.partners = append(v.partners, partnerTab{key: id, label: names[id], count: n})
	}
	sort.SliceStable(v.partners, func(a, b int) bool {
		if v.partners[a].label != v.partners[b].label {
			return v.partners[a].label < v.partners[b].label
		}
		return v.partners[a].key < v.partners[b].key
	})
	for idx, t := range v.partners {
		v.partners[idx].followUp = follow[t.key]
		if idx > 0 && t.label == v.partners[idx-1].label {
			// Two Partners of one name: Python's set order picks between
			// them.
			return nil, false, nil
		}
	}
	requested := w.partnerAsked
	if requested == "" {
		requested = "all"
	}
	for idx := range v.partners {
		if v.partners[idx].key == requested {
			v.partnerTab = &v.partners[idx]
		}
	}
	if v.partnerTab == nil && len(v.partners) > 0 {
		v.partnerTab = &v.partners[0]
	}
	partnerItems := []*item{}
	if v.partnerTab != nil {
		v.partner = v.partnerTab.key
		for _, i := range items {
			if i.partnerID == v.partner {
				partnerItems = append(partnerItems, i)
			}
		}
	}
	for _, i := range partnerItems {
		if i.activityStatus == "awaiting_ia_verification" || i.projectID != "" || i.resolution != "" {
			return nil, false, nil
		}
	}

	// The team members: the roster first, then whoever holds the Partner's
	// work, in the order it arrives; "all" when the one asked for is none.
	order := []string{}
	labels := map[string]string{}
	for _, m := range w.members {
		if _, ok := labels[m.key]; !ok {
			order = append(order, m.key)
		}
		labels[m.key] = m.name
	}
	memberKey := func(i *item) string { return orDefault(i.cceoID, "unassigned") }
	for _, i := range partnerItems {
		k := memberKey(i)
		if _, ok := labels[k]; !ok {
			order = append(order, k)
		}
		labels[k] = orDefault(i.cceoName, "Unassigned")
	}
	member := w.memberAsked
	if member == "" {
		member = "all"
	}
	if _, ok := labels[member]; !ok {
		member = "all"
	}
	v.w.member = member
	v.members = []memberTab{{key: "all", label: allMembers, count: len(partnerItems)}}
	for _, k := range order {
		n := 0
		for _, i := range partnerItems {
			if memberKey(i) == k {
				n++
			}
		}
		v.members = append(v.members, memberTab{key: k, label: labels[k], count: n})
	}
	for _, i := range partnerItems {
		if member == "all" || memberKey(i) == member {
			v.typed = append(v.typed, i)
		}
	}
	for _, i := range v.typed {
		if w.status == "" || i.deliveryPhase() == w.status {
			v.shown = append(v.shown, i)
		}
	}
	orderForMonitoring(v.shown)
	v.tableItems = v.shown
	core := 0
	for _, i := range v.shown {
		if i.isCoreSchoolWork() {
			core++
		}
	}
	v.tab = workTabOpen(tablesFor(v.shown), w.work, core)
	v.w.work = v.tab
	if v.tab == "clusters" || v.tab == "core" {
		return nil, false, nil
	}
	for _, t := range tablesFor(v.shown) {
		if tableTab[t.title] == v.tab && len(t.items) > tablePageSize {
			return nil, false, nil
		}
	}
	if w.withTarget {
		if s.target == nil {
			return nil, false, nil
		}
		t, c, b, h, ok, err := s.target(ctx, p, strconv.Itoa(operational), now)
		if err != nil {
			return nil, true, err
		}
		if ok {
			v.target = &target{target: t, core: c, beyond: b, held: h}
		}
	}
	header := &screensv1.PageHeader{Eyebrow: eyebrow, Title: title, Description: description}
	if w.role.CreatePartner {
		header.Actions = []*screensv1.PageAction{{
			Key: "add_partner_organisation", Label: "Add Partner Organisation",
			Enabled: true, Href: "/partners/create", Drawer: true,
		}}
	}
	out := &screensv1.GetPageResponse{Header: header, Blocks: v.blocks(), WebPath: Path}
	if v.selectable {
		out.Selection = &screensv1.PageSelection{Noun: "selected", Actions: []*screensv1.PageSelectionAction{
			{Label: "Withdraw selected", Href: "/partner-oversight/withdraw/bulk", Param: "assignment_ids"},
		}}
	}
	return out, true, nil
}

// handedOn is whether the reader's page holds what this piece hands on
// before any row is read: a withdrawal request their team must decide, or a
// group training or meeting a Partner facilitates for the team in the
// years read.
func handedOn(ctx context.Context, db schooldirectory.Querier, staff, years []string) (bool, error) {
	var held bool
	err := db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM partner_assignment_withdrawal w WHERE w.state = $1 AND w.supervising_pl_id = ANY($2))
    OR EXISTS (SELECT 1 FROM activity a LEFT JOIN cluster c ON c.id = a.cluster_id
      WHERE a.deleted_at IS NULL AND COALESCE(a.facilitating_partner_id, '') <> ''
        AND a.status <> ALL($3) AND a.fy = ANY($4)
        AND (a.responsible_staff_id = ANY($2) OR c.responsible_staff_id = ANY($2)))`,
		rules.WithdrawalRequested, staff, []string{"cancelled", "rejected", "deferred"}, years).Scan(&held)
	if err != nil {
		return false, fmt.Errorf("partneroversight: reading what the page hands on: %w", err)
	}
	return held, nil
}

// narrow is build_items' period narrowing: a month by the work's day (else
// the day it was handed over), a quarter by the work's quarter (else that
// day's), a week by that day.
func narrow(items []*item, p period) []*item {
	day := func(i *item) *time.Time {
		if i.scheduledDate != nil {
			return i.scheduledDate
		}
		return i.assignmentDate
	}
	out := []*item{}
	for _, i := range items {
		d := day(i)
		switch p.kind {
		case "month":
			if d == nil || int(d.Month()) != p.month {
				continue
			}
		case "quarter":
			q := i.quarter
			if q == "" && d != nil {
				q = quarterOf(*d)
			}
			if q != p.quarter {
				continue
			}
		case "week":
			start := isoWeekStart(p.week)
			if d == nil || d.Before(start) || !d.Before(start.AddDate(0, 0, 7)) {
				continue
			}
		}
		out = append(out, i)
	}
	return out
}

// isoWeekStart is the Monday of an ISO week "YYYY-Www".
func isoWeekStart(week string) time.Time {
	year, _ := strconv.Atoi(week[:4])
	n, _ := strconv.Atoi(week[6:])
	jan4 := time.Date(year, time.January, 4, 0, 0, 0, 0, time.UTC)
	monday := jan4.AddDate(0, 0, -((int(jan4.Weekday()) + 6) % 7))
	return monday.AddDate(0, 0, (n-1)*7)
}
