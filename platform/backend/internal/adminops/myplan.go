package adminops

import (
	"context"
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// workItem is an admin_ops_work_item row as My Plan and Planning draw it.
type workItem struct {
	ID, Reference, Title, Category, Severity, Status, Route, NextAction string
	Incident                                                            *string
	Scheduled, Due                                                      *time.Time
	CompletedAt                                                         *time.Time
	Note                                                                string
	CreatedAt                                                           time.Time
}

const workItemColumns = `id, reference, title, category, severity, status, affected_route, next_action, incident_id,
  scheduled_date, due_date, completed_at, verification_note, created_at`

func scanWorkItem(r pgx.CollectableRow) (workItem, error) {
	var w workItem
	err := r.Scan(&w.ID, &w.Reference, &w.Title, &w.Category, &w.Severity, &w.Status, &w.Route, &w.NextAction, &w.Incident,
		&w.Scheduled, &w.Due, &w.CompletedAt, &w.Note, &w.CreatedAt)
	return w, err
}

// myPlanSection is one of My Plan's sections: its heading, its empty line
// and its work.
type myPlanSection struct {
	title, empty string
	items        []workItem
}

// myPlan is admin_my_plan_view (AdminMyPlanService.context).
func (s *Service) myPlan(ctx context.Context) (*screensv1.GetPageResponse, bool, error) {
	rows, err := s.db.Query(ctx, `SELECT `+workItemColumns+` FROM admin_ops_work_item
WHERE status = ANY($1) ORDER BY scheduled_date, created_at DESC`, rules.MyPlanStatuses)
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the scheduled work: %w", err)
	}
	active, err := pgx.CollectRows(rows, scanWorkItem)
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the scheduled work: %w", err)
	}
	rows, err = s.db.Query(ctx, `SELECT `+workItemColumns+` FROM admin_ops_work_item
WHERE status = $1 ORDER BY completed_at DESC LIMIT $2`, rules.DoneWorkItemStatus, rules.RecentlyDone)
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the closed work: %w", err)
	}
	done, err := pgx.CollectRows(rows, scanWorkItem)
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the closed work: %w", err)
	}
	return myPlanPage(sectionWork(active, s.now().In(zone)), done), true, nil
}

// sectionWork sorts the active work into My Plan's sections, as
// AdminMyPlanService.context does: monitoring, then critical, then past its
// due date, then scheduled today, then this week (to Sunday), then later.
func sectionWork(active []workItem, now time.Time) []myPlanSection {
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	weekEnd := today.AddDate(0, 0, 6-(int(today.Weekday())+6)%7)
	sections := []myPlanSection{
		{title: "Critical Now", empty: "No critical platform work right now."},
		{title: "Due Today", empty: "Nothing is scheduled for today."},
		{title: "Needs Attention", empty: "Nothing is past its due date."},
		{title: "Planned This Week", empty: "Nothing else is planned this week."},
		{title: "Planned Later", empty: "Nothing is planned beyond this week."},
		{title: "Monitoring and Verification", empty: "Nothing is under post-change monitoring."},
	}
	day := func(t *time.Time) time.Time { return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC) }
	for _, w := range active {
		i := 4
		switch {
		case w.Status == rules.MonitoringStatus:
			i = 5
		case w.Severity == "critical" && w.Status != rules.DoneWorkItemStatus:
			i = 0
		case w.Due != nil && day(w.Due).Before(today):
			i = 2
		case w.Scheduled != nil && day(w.Scheduled).Equal(today):
			i = 1
		case w.Scheduled != nil && !day(w.Scheduled).After(weekEnd):
			i = 3
		}
		sections[i].items = append(sections[i].items, w)
	}
	return sections
}

// completes is whether the row's action is the Complete form (an input the
// feed reads); a scheduled row's Start form is only a button.
func completes(w workItem) bool {
	return w.Status == "in_progress" || w.Status == rules.MonitoringStatus
}

// statusLine is the row's second line: its route, its status, and the
// Incident link's word.
func statusLine(w workItem) string {
	line := label(rules.WorkItemStatuses, w.Status)
	if w.Route != "" {
		line = w.Route + " · " + line
	}
	if w.Incident != nil && *w.Incident != "" {
		line += " · Incident"
	}
	return collapse(line)
}

// rowWords is everything a row shows as the feed reads it, in order.
func rowWords(w workItem) []string {
	words := []string{label(rules.Severities, w.Severity), w.Reference, label(rules.WorkItemCategories, w.Category)}
	if w.Scheduled != nil {
		words = append(words, w.Scheduled.Format("02 Jan"))
	}
	words = append(words, w.Title, statusLine(w))
	if w.Status != "scheduled" && !completes(w) {
		words = append(words, label(rules.WorkItemStatuses, w.Status))
	}
	out := []string{}
	for _, t := range words {
		if t = collapse(t); t != "" {
			out = append(out, t)
		}
	}
	return out
}

// truncateChars is |truncatechars:n: the text cut to n characters, the last
// an ellipsis, when it is longer.
func truncateChars(text string, n int) string {
	if utf8.RuneCountInString(text) <= n {
		return text
	}
	return string([]rune(text)[:n-1]) + "…"
}

func myPlanPage(sections []myPlanSection, done []workItem) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Platform Operations", Title: "Admin My Plan",
		Description: "The Admin's own scheduled platform work — maintenance, support, incidents, security, features and releases. No school visits, no field activities."}
	blocks := []*screensv1.PageBlock{}
	for _, sec := range sections {
		heading := sec.title + " " + strconv.Itoa(len(sec.items))
		if len(sec.items) == 0 {
			blocks = append(blocks, panel(heading, []string{sec.empty}))
			continue
		}
		if form := completeForm(heading, sec.items); form != nil {
			blocks = append(blocks, form)
			continue
		}
		items := []*screensv1.PagePanelItem{}
		for _, w := range sec.items {
			for _, t := range rowWords(w) {
				items = append(items, panelText(t))
			}
		}
		blocks = append(blocks,
			&screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: heading}},
			&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: items}}})
	}
	closed := []*screensv1.PagePanelItem{}
	for _, w := range done {
		when := ""
		if w.CompletedAt != nil {
			when = w.CompletedAt.In(zone).Format("02 Jan 15:04")
		}
		closed = append(closed, panelText(collapse(w.Reference+" · "+w.Title)),
			panelText(collapse("Verified "+when+" — "+truncateChars(w.Note, 120))))
	}
	if len(closed) == 0 {
		closed = append(closed, panelText("Nothing closed yet. Completing work requires a verification note, so this list records how each result was checked."))
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Recently Verified and Closed", Items: closed}}})
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: MyPlanPath}
}

// completeForm is a section card read as its one form (page_forms.read):
// one row, whose action is the Complete form, with no more than
// formIntroLimit characters around it. Nil otherwise.
func completeForm(heading string, items []workItem) *screensv1.PageBlock {
	if len(items) != 1 || !completes(items[0]) {
		return nil
	}
	w := items[0]
	if utf8.RuneCountInString(collapse(heading+" "+strings.Join(rowWords(w), " "))) > formIntroLimit {
		return nil
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{
		Title: heading,
		Text:  collapse(w.Title),
		Items: []*screensv1.PageFormItem{{Kind: &screensv1.PageFormItem_Field{Field: &screensv1.DrawerField{
			Name: "verification_note", Label: collapse("How was " + w.Reference + " verified?"), Kind: "text",
			Required: true, Placeholder: "How was this verified?",
		}}}},
		SubmitLabel: "Complete",
		Key:         "/admin-ops/work-items/" + w.ID + "/complete",
	}}}
}

func panelText(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

// severityRank is AdminPlanningService's order: critical first, unknown
// last.
func severityRank(severity string) int {
	i := slices.IndexFunc(rules.SeverityChoices, func(c [2]string) bool { return c[0] == severity })
	if i < 0 {
		return 9
	}
	return i
}
