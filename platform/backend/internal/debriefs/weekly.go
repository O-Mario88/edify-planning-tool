package debriefs

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// The Weekly Debrief Report (debrief_views.weekly_debrief_report_view over
// WeeklyDebriefReportService.visible_report, pages/debriefs/
// weekly_report.html) as the existing feed reads it: the report the
// reader's role lands on for the week, drawn from the snapshot locked when
// it was generated. A Lead or Director with no report for the week has the
// existing page generate one as it opens: Go hands that on. Generating,
// signing and emailing stay the existing page's.

// WeeklyPath is the Weekly Debrief Report's path.
const WeeklyPath = "/debriefs/weekly-report"

const pdfPath = "/debriefs/weekly-report/pdf"

// weeklyReport is the stored report the page draws.
type weeklyReport struct {
	scope, status, commentary string
	snapshot                  reportSnapshot
}

type reportSnapshot struct {
	// The figures by name; a Lead's report and a country's carry different ones.
	RawTotals    map[string]*int `json:"totals"`
	MissingTeams []struct {
		PL     string `json:"pl"`
		Status string `json:"status"`
	} `json:"missing_teams"`
	Clusters []reportCluster `json:"clusters"`
	Team     []struct {
		Name      string `json:"name"`
		Submitted bool   `json:"submitted"`
	} `json:"team"`
}

type reportCluster struct {
	Label           string   `json:"label"`
	Kind            string   `json:"kind"`
	Trend           string   `json:"trend"`
	Confidence      string   `json:"confidence"`
	Mentions        int      `json:"mentions"`
	UniqueStaff     int      `json:"unique_staff"`
	SchoolsAffected int      `json:"schools_affected"`
	Districts       []string `json:"districts_affected"`
	Teams           []string `json:"pl_teams"`
	Sources         []struct {
		Excerpt   string `json:"excerpt"`
		DebriefID string `json:"debrief_id"`
	} `json:"sources"`
}

// weekBounds is week_bounds: the Monday-to-Sunday week holding the anchor,
// else the last completed week.
func weekBounds(anchor *time.Time, today time.Time) (time.Time, time.Time) {
	d := today.AddDate(0, 0, -7)
	if anchor != nil {
		d = *anchor
	}
	start := d.AddDate(0, 0, -((int(d.Weekday()) + 6) % 7))
	return start, start.AddDate(0, 0, 6)
}

func (s *Service) weekly(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	w := rules.Weekly
	if !w.Pages[p.ActiveRole] {
		return nil, true, pagegate.ErrNotAvailable
	}
	var anchor *time.Time
	if raw := query.Get("week"); raw != "" {
		at, err := time.Parse(time.DateOnly, raw)
		switch {
		case err == nil:
			anchor = &at
		case strings.ContainsAny(raw, "0123456789"):
			// date.fromisoformat reads more ISO forms than a plain date.
			return nil, false, nil
		}
	}
	start, end := weekBounds(anchor, day(s.now().In(zone)))
	report, err := s.visibleReport(ctx, p, start)
	if err != nil {
		return nil, true, err
	}
	if report == nil && slices.Contains(w.WritesOnOpen, p.ActiveRole) {
		return nil, false, nil
	}
	description := "Consolidated intelligence from daily debriefs, " + start.Format("2 Jan") + " – " + end.Format("2 Jan 2006") + "."
	if report != nil {
		description = label(w.Scopes, report.scope) + " · " + description
	}
	week := func(d time.Time) string { return WeeklyPath + "?week=" + d.Format(time.DateOnly) }
	h := &screensv1.PageHeader{Eyebrow: "My Work", Title: "Weekly Debrief Report", Description: description,
		Badges: []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{
			{Key: "prev", Label: "‹ Prev", Enabled: true, Href: week(start.AddDate(0, 0, -7))},
			{Key: "next", Label: "Next ›", Enabled: true, Href: week(start.AddDate(0, 0, 7))},
		}}
	var blocks []*screensv1.PageBlock
	if report == nil {
		blocks = []*screensv1.PageBlock{noReport(p.ActiveRole)}
	} else {
		blocks = report.blocks(start)
	}
	return &screensv1.GetPageResponse{Header: h, Blocks: blocks,
		Tabs: []*screensv1.PageTab{}, Dialogs: []*screensv1.PageDialog{}, WebPath: WeeklyPath}, true, nil
}

// visibleReport is visible_report: a Lead's own team report; a country
// reader's country report (a Director's own country's, when they have one);
// finalized only for those who read only finalized intelligence; never a
// superseded version; the latest version.
func (s *Service) visibleReport(ctx context.Context, p auth.Principal, start time.Time) (*weeklyReport, error) {
	w := rules.Weekly
	args := []any{start.Format(time.DateOnly)}
	where := "week_start = $1::date AND status <> 'superseded'"
	switch {
	case p.ActiveRole == w.TeamReader:
		args = append(args, p.UserID)
		where += " AND scope_kind = 'pl_team' AND scope_id = $2"
	case slices.Contains(w.CountryReaders, p.ActiveRole):
		where += " AND scope_kind = 'country'"
		if p.ActiveRole == w.OwnCountryReader {
			var country string
			err := s.db.QueryRow(ctx, `SELECT COALESCE(country, '') FROM staff_profile WHERE user_id = $1 LIMIT 1`, p.UserID).Scan(&country)
			if err != nil && !errors.Is(err, pgx.ErrNoRows) {
				return nil, fmt.Errorf("debriefs: reading the Director's country: %w", err)
			}
			if country != "" {
				args = append(args, country)
				where += " AND scope_id = $2"
			}
		}
	default:
		return nil, nil
	}
	if slices.Contains(w.FinalizedReaders, p.ActiveRole) {
		where += " AND status = 'finalized'"
	}
	var r weeklyReport
	var raw []byte
	err := s.db.QueryRow(ctx, `SELECT scope_kind, status, COALESCE(commentary, ''), snapshot FROM weekly_debrief_report
WHERE `+where+` ORDER BY version DESC LIMIT 1`, args...).Scan(&r.scope, &r.status, &r.commentary, &raw)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the week's report: %w", err)
	}
	if err := json.Unmarshal(raw, &r.snapshot); err != nil {
		return nil, fmt.Errorf("debriefs: reading the report's snapshot: %w", err)
	}
	return &r, nil
}

// noReport is the empty page: what the reader waits for, and Generate for
// those it is offered to.
func noReport(role string) *screensv1.PageBlock {
	w := rules.Weekly
	note := "Generate a draft from this week's daily debriefs."
	if slices.Contains(w.FinalizedReaders, role) {
		note = "The Country Director has not finalized this week's country report yet."
	}
	text := "No report for this week yet. " + note
	if slices.Contains(w.Generators, role) {
		text += " Generate Draft Report"
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: text}}
}

// total is a figure as the template prints it: nothing when the snapshot
// lacks it.
func (r *weeklyReport) total(key string) string {
	if v := r.snapshot.RawTotals[key]; v != nil {
		return strconv.Itoa(*v)
	}
	return ""
}

func plural(n int, word string) string {
	if n == 1 {
		return word
	}
	return word + "s"
}

func section(title string) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: title}}
}

func plainPanel(items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Badges: []*screensv1.PageBadge{}, Items: items}}}
}

var groupTitles = map[string]string{"challenge": "Key Challenges", "suggestion": "Staff Suggestions"}

func (r *weeklyReport) blocks(start time.Time) []*screensv1.PageBlock {
	team := r.scope == "pl_team"
	first := screensv1.PageMetric{Label: "PL Reports", Value: r.total("pl_reports_included") + " in · " + r.total("pl_reports_missing") + " missing"}
	if team {
		first = screensv1.PageMetric{Label: "Reporting", Value: r.total("reporting") + " / " + r.total("members")}
	}
	activities := "—"
	if r.snapshot.RawTotals["activities_worked"] != nil {
		activities = r.total("activities_worked")
	} else if r.snapshot.RawTotals["direct_debriefs"] != nil {
		activities = r.total("direct_debriefs")
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
		Title: "Performance overview", Metrics: []*screensv1.PageMetric{
			&first,
			{Label: "Debriefs", Value: r.total("debriefs")},
			{Label: "Schools", Value: r.total("schools_supported")},
			{Label: "Activities", Value: activities},
		}}}}}
	if len(r.snapshot.MissingTeams) > 0 {
		parts := make([]string, 0, len(r.snapshot.MissingTeams))
		for _, m := range r.snapshot.MissingTeams {
			parts = append(parts, m.PL+" ("+m.Status+")")
		}
		blocks = append(blocks, plainPanel(text("Data completeness: "+strings.Join(parts, " · "))))
	}
	blocks = append(blocks, r.clusterBlocks()...)
	if team && len(r.snapshot.Team) > 0 {
		items := make([]*screensv1.PagePanelItem, 0, len(r.snapshot.Team))
		for _, m := range r.snapshot.Team {
			line := m.Name
			if !m.Submitted {
				line += " — not submitted"
			}
			items = append(items, text(line))
		}
		blocks = append(blocks, section("Team Submission Status"), plainPanel(items...))
	}
	if r.commentary != "" {
		blocks = append(blocks, section("Leadership Commentary"), plainPanel(text(oneLine(r.commentary))))
	}
	actions := []*screensv1.PagePanelItem{links(&screensv1.PageLink{Text: "Download PDF",
		Href: pdfPath + "?week=" + start.Format(time.DateOnly)})}
	if r.status == "finalized" {
		actions = append(actions, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: "Send by Email"}})
	}
	return append(blocks, plainPanel(actions...))
}

// clusterBlocks are the themes under their kind's heading, a heading each
// time the kind changes (regroup), or the empty note.
func (r *weeklyReport) clusterBlocks() []*screensv1.PageBlock {
	if len(r.snapshot.Clusters) == 0 {
		note := "No consolidated themes this week. No daily debriefs matched this reporting week"
		if r.scope == "country" {
			note += " from finalized team reports"
		}
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Empty{Empty: note + "."}}}
	}
	var out []*screensv1.PageBlock
	for i, c := range r.snapshot.Clusters {
		if i == 0 || c.Kind != r.snapshot.Clusters[i-1].Kind {
			title, ok := groupTitles[c.Kind]
			if !ok {
				title = "What Worked Well"
			}
			out = append(out, section(title))
		}
		out = append(out, c.block())
	}
	return out
}

var trendWords = map[string]string{"worsening": "Worsening", "repeated": "Repeated", "improving": "Improving", "new": "New"}

func (c reportCluster) block() *screensv1.PageBlock {
	badges := []*screensv1.PageBadge{}
	if word, ok := trendWords[c.Trend]; ok {
		badges = append(badges, &screensv1.PageBadge{Text: word, Tone: "plain"})
	}
	if c.Confidence == "low" {
		badges = append(badges, &screensv1.PageBadge{Text: "Needs review", Tone: "plain",
			Title: "Low-confidence classification — confirm before acting"})
	}
	line := fmt.Sprintf("%d %s · %d staff · %d %s", c.Mentions, plural(c.Mentions, "mention"),
		c.UniqueStaff, c.SchoolsAffected, plural(c.SchoolsAffected, "school"))
	if len(c.Districts) > 0 {
		line += " · " + strings.Join(c.Districts, ", ")
	}
	if len(c.Teams) > 0 {
		line += " · teams: " + strings.Join(c.Teams, ", ")
	}
	items := []*screensv1.PagePanelItem{text(line)}
	for _, src := range c.Sources[:min(2, len(c.Sources))] {
		items = append(items, &screensv1.PagePanelItem{
			Kind:      &screensv1.PagePanelItem_Text{Text: oneLine("“" + src.Excerpt + "” — source")},
			TextLinks: []*screensv1.PageLink{{Text: "source", Href: "/debriefs/" + src.DebriefID}},
		})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: c.Label, Badges: badges, Items: items}}}
}
