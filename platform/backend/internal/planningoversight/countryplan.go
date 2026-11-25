package planningoversight

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Piece 3: the Team Plan's country lens (scope.groups_by_lead for a
// country reader): the country's staff work under one tab per Programme
// Lead (system_program_leads, then Unassigned), the chosen Lead's roster as
// officer switches with only the open officer's four tables drawn (the
// others are fetched when picked, cd_team_detail.html's lazy panels), one
// chart series per Lead, and the country's flagged schools. The region lens
// is handed on.

const (
	unassignedKey      = "unassigned"
	countryDescription = "Country plans, team delivery and unresolved risks."
	regionDescription  = "Your region's country programmes by Programme Lead: plans, team delivery and unresolved risks."
	leadChartTitle     = "Planning and delivery progress by Programme Lead"
	leadChartSubtitle  = "Each Lead's team · "
)

// officerGroup is one officer switch of the chosen Lead's team.
type officerGroup struct {
	id, name string
	items    []*item
}

// buildCountryPlan answers the country lens for p, or served=false.
func (s *Service) buildCountryPlan(ctx context.Context, p auth.Principal, reader Reader, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	now := s.now()
	per, ok := partneroversight.ReadPeriod(query, now)
	if !ok {
		return nil, false, nil
	}
	w, served, err := s.lensBase(ctx, p, reader, query, per, now)
	if !served || err != nil {
		return nil, served, err
	}
	w.country, w.lensTitle = true, "Country"
	var regions []string
	if reader.Scope == "region" {
		w.region, w.lensTitle = true, "Regional"
		regions, err = s.regionalReach(ctx, p, now)
		if err != nil || regions == nil {
			return nil, err != nil, err
		}
	}
	items, err := s.buildItems(ctx, nil, regions, w.years, w.read, w.today)
	if err != nil {
		return nil, true, err
	}
	if err := s.stampLeads(ctx, items); err != nil {
		return nil, true, err
	}
	// A region lens reads no team, so team_flagged_schools finds no school
	// (its responsible officer must be one of an empty team).
	if !w.region {
		w.flagged, err = s.flaggedFor(ctx, nil, per, now)
		if errors.Is(err, errHandOn) {
			return nil, false, nil
		}
		if err != nil {
			return nil, true, err
		}
	}
	leads, err := partneroversight.SystemProgramLeads(ctx, s.db)
	if err != nil {
		return nil, true, err
	}
	w.tabs, w.tabItems = leadTabs(leads, items)
	if len(w.tabs) == 0 {
		return nil, false, nil
	}
	w.owner = w.tabs[0].Key
	asked := strings.TrimSpace(query.Get("program_lead"))
	for _, t := range w.tabs {
		if t.Key == asked {
			w.owner = asked
		}
	}
	for i := range w.tabs {
		w.tabs[i].Active = w.tabs[i].Key == w.owner
	}
	visible := inFamily(w.tabItems[w.owner], w.activity)
	w.summary = summarize(visible, w.today)

	roster, err := s.roster(ctx, w.owner)
	if err != nil {
		return nil, true, err
	}
	w.groups, err = s.officerGroups(ctx, roster, visible)
	if err != nil {
		return nil, true, err
	}
	if len(w.groups) == 0 {
		return nil, false, nil
	}
	w.shown = shownOfficer(w.groups, query.Get("officer"))
	open := w.groups[w.shown]
	viewer := []string{p.UserID, p.StaffProfileID}
	if len(open.items) > 0 && (slices.Contains(viewer, open.id) || strings.EqualFold(open.name, p.Name)) {
		return nil, false, nil
	}
	for _, it := range open.items {
		if it.owner != "" && slices.Contains(viewer, it.owner) {
			return nil, false, nil
		}
	}
	w.streams, err = s.streams(ctx, p.Country, open.items, w.today)
	if errors.Is(err, errHandOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	for _, rows := range w.streams {
		for _, it := range rows {
			if it.showsComplete {
				return nil, false, nil
			}
		}
	}
	return teamPage(w), true, nil
}

// regionalReach is the region lens's regions: the reader's reach
// (schooldirectory: every country's, the owner's rule for regional roles),
// nil for a reader with no region or no geography assigned, whose page
// carries the existing "no countries are assigned" note (handed on).
func (s *Service) regionalReach(ctx context.Context, p auth.Principal, now time.Time) ([]string, error) {
	var assigned bool
	err := s.db.QueryRow(ctx, `SELECT EXISTS (
  SELECT 1 FROM staff_geography_assignment g
  LEFT JOIN district d ON d.id = g.district_id
  JOIN region r ON r.id = COALESCE(g.region_id, d.region_id)
  WHERE g.staff_id = $1)`, p.StaffProfileID).Scan(&assigned)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the reader's geography: %w", err)
	}
	if !assigned {
		return nil, nil
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, err
	}
	if len(scope.RegionIDs) == 0 {
		return nil, nil
	}
	return scope.RegionIDs, nil
}

// lensBase is what every lens reads first: the plain query, the period and
// the years it covers, and today.
func (s *Service) lensBase(ctx context.Context, p auth.Principal, reader Reader, query url.Values, per partneroversight.Period, now time.Time) (teamPlan, bool, error) {
	w := teamPlan{period: per, reader: reader, activity: allActivity, query: query}
	w.fyOptions = schooldirectory.FYOptions(now)
	years, label, read, err := s.planPeriod(ctx, p.Country, per, w.fyOptions, now)
	if err != nil {
		return w, true, err
	}
	w.years, w.periodLabel, w.read = years, label, read
	if a := strings.TrimSpace(query.Get("activity")); a != "" {
		w.activity = a
	}
	local := now.In(zone)
	w.today = time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	return w, true, nil
}

// stampLeads is _StaffDirectory.supervisor_of on each item's owner: the
// owner themself when they hold the Programme Lead role, else the Lead
// their reporting line names.
func (s *Service) stampLeads(ctx context.Context, items []*item) error {
	owners := []string{}
	for _, it := range items {
		if it.owner != "" && !slices.Contains(owners, it.owner) {
			owners = append(owners, it.owner)
		}
	}
	if len(owners) == 0 {
		return nil
	}
	lead := rules.TeamPlan.LeadRole
	rows, err := s.db.Query(ctx, `
SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE($2 = ANY(COALESCE(u.roles, '{}')) OR u.active_role = $2, false)
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.id = ANY($1) OR sp.user_id = ANY($1) ORDER BY sp.id`, owners, lead)
	if err != nil {
		return fmt.Errorf("planningoversight: reading the owners' Leads: %w", err)
	}
	canonical, leads, profiles := map[string]string{}, map[string]bool{}, []string{}
	for rows.Next() {
		var id, user string
		var isLead bool
		if err := rows.Scan(&id, &user, &isLead); err != nil {
			rows.Close()
			return fmt.Errorf("planningoversight: reading the owners' Leads: %w", err)
		}
		profiles = append(profiles, id)
		for _, key := range []string{id, user} {
			if key != "" {
				canonical[key] = id
				if isLead {
					leads[key] = true
				}
			}
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	supervisor := map[string]string{}
	if len(profiles) > 0 {
		rows, err := s.db.Query(ctx, `
SELECT a.supervisee_id, a.supervisor_id FROM staff_supervisor_assignment a
JOIN staff_profile sp ON sp.id = a.supervisor_id JOIN "user" u ON u.id = sp.user_id
WHERE a.supervisee_id = ANY($1) AND ($2 = ANY(COALESCE(u.roles, '{}')) OR u.active_role = $2)
ORDER BY a.supervisee_id, a.supervisor_id`, profiles, lead)
		if err != nil {
			return fmt.Errorf("planningoversight: reading the reporting lines: %w", err)
		}
		for rows.Next() {
			var supervisee, sup string
			if err := rows.Scan(&supervisee, &sup); err != nil {
				rows.Close()
				return fmt.Errorf("planningoversight: reading the reporting lines: %w", err)
			}
			if _, seen := supervisor[supervisee]; !seen {
				supervisor[supervisee] = sup
			}
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return err
		}
	}
	for _, it := range items {
		if it.owner == "" {
			continue
		}
		c := first(canonical[it.owner], it.owner)
		if leads[c] || leads[it.owner] {
			it.lead = c
			continue
		}
		it.lead = supervisor[c]
	}
	return nil
}

// leadTabs is _program_lead_tabs over the system's Leads: one tab each with
// the work its teams hold, then Unassigned for what no Lead supervises.
func leadTabs(leads []partneroversight.ProgramLead, items []*item) ([]Tab, map[string][]*item) {
	tabs, filed := []Tab{}, map[string][]*item{}
	of := map[string]string{}
	for _, l := range leads {
		tabs = append(tabs, Tab{Key: l.ID, Label: l.Name})
		filed[l.ID] = []*item{}
		for _, id := range l.IDs {
			of[id] = l.ID
		}
	}
	unassigned := []*item{}
	for _, it := range items {
		if key, ok := of[it.lead]; ok && it.lead != "" {
			filed[key] = append(filed[key], it)
			continue
		}
		unassigned = append(unassigned, it)
	}
	if len(unassigned) > 0 {
		tabs = append(tabs, Tab{Key: unassignedKey, Label: "Unassigned"})
		filed[unassignedKey] = unassigned
	}
	return tabs, filed
}

// officerGroups is group_by_owner over the Lead's roster: each roster
// member with the work filed under them, then everyone else's work by
// person (by name, Unassigned last).
func (s *Service) officerGroups(ctx context.Context, roster []person, visible []*item) ([]officerGroup, error) {
	groups := make([]officerGroup, len(roster))
	for i, m := range roster {
		groups[i] = officerGroup{id: m.id, name: m.name}
	}
	remaining := []*item{}
	for _, it := range visible {
		found := -1
		for i, m := range roster {
			if m.owns(it.owner) {
				found = i
			}
		}
		if found < 0 {
			remaining = append(remaining, it)
			continue
		}
		groups[found].items = append(groups[found].items, it)
	}
	people, err := s.peopleOf(ctx, remaining)
	if err != nil {
		return nil, err
	}
	others := make([]officerGroup, len(people))
	for i, p := range people {
		others[i] = officerGroup{id: p.id, name: p.name}
	}
	canonical, err := s.canonicalOf(ctx, remaining)
	if err != nil {
		return nil, err
	}
	for _, it := range remaining {
		key := first(canonical[it.owner], it.owner)
		for i := range others {
			if others[i].id == key {
				others[i].items = append(others[i].items, it)
				break
			}
		}
	}
	slices.SortStableFunc(others, func(x, y officerGroup) int {
		if (x.name == "Unassigned") != (y.name == "Unassigned") {
			if x.name == "Unassigned" {
				return 1
			}
			return -1
		}
		return compareText(x.name, y.name)
	})
	return append(groups, others...), nil
}

// canonicalOf is _canonical_staff_ids over the items' owners.
func (s *Service) canonicalOf(ctx context.Context, items []*item) (map[string]string, error) {
	out := map[string]string{}
	owners := []string{}
	for _, it := range items {
		if it.owner != "" {
			owners = append(owners, it.owner)
		}
	}
	if len(owners) == 0 {
		return out, nil
	}
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(user_id, '') FROM staff_profile WHERE id = ANY($1) OR user_id = ANY($1)`, owners)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the owners: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, user string
		if err := rows.Scan(&id, &user); err != nil {
			return nil, fmt.Errorf("planningoversight: reading the owners: %w", err)
		}
		for _, key := range []string{id, user} {
			if key != "" && slices.Contains(owners, key) {
				out[key] = id
			}
		}
	}
	return out, rows.Err()
}

// shownOfficer is _shown_officer: the officer the address names, else the
// first with work, else the first.
func shownOfficer(groups []officerGroup, asked string) int {
	for i, g := range groups {
		if g.id == asked {
			return i
		}
	}
	for i, g := range groups {
		if len(g.items) > 0 {
			return i
		}
	}
	return 0
}

// countryMiddle is team_country_workspace.html between the tiles and the
// chart: the Lead tabs, the chosen Lead's heading, and the officer
// switches with the open officer's panel.
func (w teamPlan) countryMiddle() []*screensv1.PageBlock {
	p := w.period
	rest := "&period=" + p.Kind + "&fy=" + p.FY + "&week=" + p.Week + "&month=" + strconv.Itoa(p.Month) + "&quarter=" + p.Quarter
	links := []*screensv1.PageLink{}
	for _, t := range w.tabs {
		links = append(links, &screensv1.PageLink{Text: t.Label, Href: "?program_lead=" + t.Key + rest, Caption: strconv.Itoa(len(w.tabItems[t.Key]))})
	}
	blocks := []*screensv1.PageBlock{panel("", "", &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}})}
	label := tabLabel(w.tabs, w.owner)
	if w.reader.MayDelegate {
		blocks = append(blocks, panel(label, "", text(w.periodLabel)))
	} else {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: label}})
	}
	segments := []*screensv1.PageSegment{}
	for i, g := range w.groups {
		f := summarize(g.items, w.today)
		parts := []string{initials(g.name), g.name, strconv.Itoa(f.total)}
		if f.atRisk > 0 {
			parts = append(parts, strconv.Itoa(f.atRisk))
		}
		seg := &screensv1.PageSegment{Label: strings.Join(parts, " ")}
		if i == w.shown {
			seg.Blocks = []*screensv1.PageBlock{fieldPlan(g.name, g.name+" Field Plan", f, w.streams)}
			param := "g" + strconv.Itoa(i+1) + "_page"
			for t := range sections {
				seg.Blocks = append(seg.Blocks, streamBlocks(t, w.streams[t], g.name, w.query, w.reader, param)...)
			}
		} else {
			seg.Blocks = []*screensv1.PageBlock{panel("", "", text("Loading "+g.name+"’s work…"))}
		}
		segments = append(segments, seg)
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Segments{Segments: &screensv1.PageSegments{
		Subtitle: sections[clientVisits][1], Segments: segments,
	}}})
	return blocks
}
