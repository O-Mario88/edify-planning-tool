package adminops

import (
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	_ "time/tzdata" // the registers' times are Nairobi's wherever the gateway runs

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// zone is settings.TIME_ZONE, the zone |date writes a time in.
var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("adminops: " + err.Error())
	}
	return z
}()

const (
	eyebrow = "Platform Operations"
	// formIntroLimit is page_forms.INTRO_LIMIT: a card showing more than this
	// many characters outside its one form is not read as that form.
	formIntroLimit = 400
	resolveLabel   = "Resolve"
)

func collapse(text string) string { return closedschools.Collapse(text) }

func orDefault(text, fallback string) string {
	if text == "" {
		return fallback
	}
	return text
}

func header(title, purpose string) *screensv1.PageHeader {
	return &screensv1.PageHeader{Eyebrow: eyebrow, Title: title, Description: purpose}
}

func item(title string, lines []string, badges []*screensv1.PageBadge, href string) *screensv1.PageListItem {
	out := &screensv1.PageListItem{Title: collapse(title), Badges: badges, Href: href}
	for _, l := range lines {
		if t := collapse(l); t != "" {
			out.Lines = append(out.Lines, t)
		}
	}
	return out
}

func list(items []*screensv1.PageListItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_List{List: &screensv1.PageList{Items: items}}}
}

func badge(text, tone string) *screensv1.PageBadge {
	return &screensv1.PageBadge{Text: collapse(text), Tone: tone}
}

// metric is a context figure: its value, and its helper as the note when it
// is a sentence (brief_helper), the line kept beside the value otherwise.
func metric(name string, value int, helper string) *screensv1.PageMetric {
	m := &screensv1.PageMetric{Label: name, Value: strconv.Itoa(value)}
	if brief := schoolprofile.BriefHelper(helper); brief != helper {
		m.Note = helper
		m.Helper = brief
	} else {
		m.Helper = helper
	}
	return m
}

// ticketLine is the reporter's role, the page and when it was raised.
func ticketLine(t ticket) string {
	return orDefault(t.ReporterRole, "user") + " · " + orDefault(t.Route, "unknown page") + " · " + t.CreatedAt.In(zone).Format("02 Jan 15:04")
}

func resolvable(t ticket) bool { return slices.Contains(rules.ResolvableTicketStatuses, t.Status) }

// supportPage is Support Tickets as the feed reads it: the attention
// figures, then the queue. The queue's card is read as its one resolve form
// when it holds exactly one and shows no more than formIntroLimit characters
// around it (page_forms._form_of); otherwise as a list of its tickets, each
// with its status, and none of their forms.
func supportPage(tickets []ticket, untriaged, open int) *screensv1.GetPageResponse {
	h := header("Support Tickets", "Every user request for platform help, in one canonical workflow — submitted through triage and verification to a resolution the reporter is told about.")
	strip := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Support attention", Metrics: []*screensv1.PageMetric{
		metric("Awaiting triage", untriaged, "Needs an owner"),
		metric("Open tickets", open, "Active support workload"),
	}}}}
	blocks := []*screensv1.PageBlock{strip}
	if form := supportForm(tickets); form != nil {
		return &screensv1.GetPageResponse{Header: h, Blocks: append(blocks, form), WebPath: SupportPath}
	}
	items := []*screensv1.PageListItem{}
	for _, t := range tickets {
		items = append(items, item(t.Title, []string{ticketLine(t)},
			[]*screensv1.PageBadge{badge(label(rules.TicketStatuses, t.Status), "plain")}, ""))
	}
	if len(tickets) == 0 {
		items = append(items, item("No support tickets", []string{"Users raise these from Report a Problem on any page."}, nil, ""))
	}
	return &screensv1.GetPageResponse{Header: h, Blocks: append(blocks, list(items)), WebPath: SupportPath}
}

// supportForm is the queue's card read as its one resolve form, or nil. Its
// line is the card's first paragraph with words outside the form.
func supportForm(tickets []ticket) *screensv1.PageBlock {
	var only *ticket
	words := []string{}
	paragraphs := []string{}
	for i, t := range tickets {
		title, line := collapse(t.Title), collapse(ticketLine(t))
		words = append(words, t.Reference, label(rules.TicketStatuses, t.Status), label(rules.TicketCategories, t.Category), title, line)
		paragraphs = append(paragraphs, title, line)
		if resolvable(t) {
			if only != nil {
				return nil
			}
			only = &tickets[i]
			words = append(words, resolveLabel)
		}
	}
	if only == nil || utf8.RuneCountInString(collapse(strings.Join(words, " ")))-len(resolveLabel) > formIntroLimit {
		return nil
	}
	text := ""
	for _, p := range paragraphs {
		if p != "" {
			text = p
			break
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{
		Text: text,
		Items: []*screensv1.PageFormItem{{Kind: &screensv1.PageFormItem_Field{Field: &screensv1.DrawerField{
			Name: "resolution", Label: collapse("Resolution for " + only.Reference), Kind: "text", Placeholder: "What was fixed?",
		}}}},
		SubmitLabel: resolveLabel,
		Key:         "/admin-ops/tickets/" + only.ID + "/resolve",
	}}}
}

// severityTone is the severity pill's colour as the app's tone.
func severityTone(severity string) string {
	switch severity {
	case "critical":
		return "alert"
	case "high":
		return "caution"
	}
	return "plain"
}

func incidentsPage(incidents []incident) *screensv1.GetPageResponse {
	items := []*screensv1.PageListItem{}
	for _, i := range incidents {
		where := orDefault(i.Route, i.Component)
		items = append(items, item(i.Title, []string{where + " · last seen " + i.LastDetectedAt.In(zone).Format("02 Jan 15:04")},
			[]*screensv1.PageBadge{
				badge(label(rules.Severities, i.Severity), severityTone(i.Severity)),
				badge(label(rules.IncidentStatuses, i.Status), "plain"),
			}, IncidentsPath+"/"+i.ID))
	}
	if len(incidents) == 0 {
		items = append(items, item("No incidents recorded",
			[]string{"Server errors, broken routes, SLO breaches, failed jobs and browser-reported defects appear here automatically."}, nil, ""))
	}
	return &screensv1.GetPageResponse{
		Header: header("System Incidents", "Every unique platform defect, however many times it fires. Repeats update one incident rather than flooding the queue; a resolved defect that recurs reopens."),
		Blocks: []*screensv1.PageBlock{list(items)}, WebPath: IncidentsPath,
	}
}

func panel(title string, lines []string) *screensv1.PageBlock {
	p := &screensv1.PagePanel{Title: title}
	for _, l := range lines {
		if t := collapse(l); t != "" {
			p.Items = append(p.Items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}})
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: p}}
}

func maintenancePage(templates []template, open []work) *screensv1.GetPageResponse {
	recurring := []string{}
	for _, t := range templates {
		recurring = append(recurring, t.Name,
			label(rules.WorkItemCategories, t.Category)+" · every "+strconv.Itoa(t.Frequency)+" days · about "+strconv.Itoa(t.Estimate)+" min",
			"Next "+t.NextDue.Format("02 Jan 2006"))
	}
	if len(templates) == 0 {
		recurring = append(recurring, "No maintenance templates are configured yet.")
	}
	pending := []string{}
	for _, w := range open {
		status := label(rules.WorkItemStatuses, w.Status)
		if w.Scheduled != nil {
			status += " · scheduled " + w.Scheduled.Format("02 Jan")
		}
		pending = append(pending, w.Reference+" · "+w.Title, status)
	}
	if len(open) == 0 {
		pending = append(pending, "No maintenance work is open.")
	}
	return &screensv1.GetPageResponse{
		Header:  header("Maintenance Calendar", "Recurring platform upkeep. When a template falls due it generates a scheduled work item in Admin My Plan, so routine maintenance does not depend on anyone remembering it."),
		Blocks:  []*screensv1.PageBlock{panel("Recurring Maintenance", recurring), panel("Open Maintenance Work", pending)},
		WebPath: MaintenancePath,
	}
}
