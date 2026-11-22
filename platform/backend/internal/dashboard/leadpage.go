package dashboard

import (
	"context"
	"errors"
	"net/url"
	"slices"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningmonitor"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/staffactivity"
)

// A Programme Lead's Home (_program_lead_dashboard on This Week,
// pages/dashboards/pl.html): the header, the year, the team pulse, the
// views' rail, then This Week carrying the Planning Monitor, the team's
// week, what needs the lead now and the Staff Activity Log.

// leadServed is whether Go draws the lead's page this query asks for:
// This Week plus Priorities, Team (and alias operations), Coaching, Programmes,
// and Collaboration. Map is served natively by Next.js CountryMapView.
func leadServed(query url.Values) bool {
	for key, values := range query {
		value := ""
		if len(values) > 0 {
			value = strings.ToLower(strings.TrimSpace(values[0]))
		}
		switch key {
		case "fy", "week", "who", "show", "plans":
		case "view":
			if alias, ok := rules.Lead.ViewAliases[value]; ok {
				if value == "today" {
					return false
				}
				value = alias
			}
			if value == "map" {
				return false
			}
		default:
			return false
		}
	}
	return true
}

// leadFY is the dashboard's year: the one asked for when it is offered,
// else the operational year.
func leadFY(query url.Values, now time.Time) (string, []string) {
	options := schooldirectory.FYOptions(now)
	fy := strings.TrimSpace(query.Get("fy"))
	if !slices.Contains(options, fy) {
		fy = operationalFY(now.UTC())
	}
	return fy, options
}

// leadYear is the year filter on the title line, the view kept.
func leadYear(fy string, options []string) *screensv1.PageBlock {
	filter := &screensv1.PageFilter{Name: "fy", Label: "Fiscal year", Value: fy}
	for _, y := range options {
		filter.Options = append(filter.Options, &screensv1.PageFilterOption{Value: y, Label: "FY " + y})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{filter},
		Hidden:  map[string]string{"view": rules.Lead.DefaultView},
	}}}
}

// leadViews is the views' rail, This Week chosen.
func leadViews(fy string) *screensv1.PageBlock {
	tabs := &screensv1.PageLinkTabs{Scrolls: true}
	for _, v := range rules.Lead.ViewTabs {
		href := Path + "?" + url.Values{"fy": {fy}, "view": {v[0]}}.Encode()
		tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: v[1], Href: href, Active: v[0] == rules.Lead.DefaultView})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}}
}

// buildLead answers /dashboard for a Programme Lead in their own seat.
func (s *Service) buildLead(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if p.InActingAppointment || !leadServed(query) {
		return nil, false, nil
	}
	now := s.now()
	fy, options := leadFY(query, now)
	activeView := normalizeLeadView(query.Get("view"))
	if activeView != rules.Lead.DefaultView {
		return s.buildLeadSecondaryView(ctx, p, activeView, fy, options, now)
	}
	week, served, err := leadWeek(ctx, s.db, p, query, fy, now)
	if err != nil || !served {
		return nil, served, err
	}
	monitor, err := planningmonitor.Read(ctx, s.db, p, fy, now)
	if errors.Is(err, planningmonitor.ErrNotDrawn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	ledger, err := monitor.Ledger(ctx, s.db)
	if err != nil {
		return nil, true, err
	}
	log, served, err := staffactivity.NewService(s.db, s.now).TeamEmbed(ctx, p, url.Values{})
	if err != nil || !served {
		return nil, served, err
	}
	strip, header, err := LeadPulse(ctx, s.db, p, fy, now)
	if err != nil {
		return nil, true, err
	}
	blocks := []*screensv1.PageBlock{leadYear(fy, options), strip, leadViews(fy)}
	blocks = append(blocks, planningmonitor.Blocks(monitor, ledger)...)
	blocks = append(blocks, week...)
	blocks = append(blocks, log...)
	return &screensv1.GetPageResponse{
		Header:    header,
		Blocks:    blocks,
		WebPath:   Path,
		Selection: myplan.ActivityBar(),
	}, true, nil
}
