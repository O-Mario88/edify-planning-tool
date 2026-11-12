package escalations

import (
	"net/url"
	"strconv"
	"strings"
	"time"

	_ "time/tzdata" // the page's dates are Nairobi's wherever the gateway runs

	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// pageParam is the one page parameter every list on the page shares
// ({% paginate rows "escalation_rows_page" %} in _table.html).
const pageParam = "escalation_rows_page"

// decidedLimit is board()'s [:20] on the recently decided.
const decidedLimit = 20

// zone is settings.TIME_ZONE, the zone |date writes a time in.
var zone = mustZone("Africa/Nairobi")

func mustZone(name string) *time.Location {
	z, err := time.LoadLocation(name)
	if err != nil {
		panic("escalations: " + err.Error())
	}
	return z
}

// board is board(): the reader's escalations, and the person a raise goes to.
type board struct {
	rows                   []escalation
	raiseToID, raiseToName string
}

func (b board) filter(keep func(escalation) bool) []escalation {
	out := []escalation{}
	for _, e := range b.rows {
		if keep(e) {
			out = append(out, e)
		}
	}
	return out
}

func collapse(text string) string { return closedschools.Collapse(text) }

func orDash(text *string) string {
	if text == nil || *text == "" {
		return "—"
	}
	return *text
}

// pyText is how the template writes a value that may be missing: "None".
func pyText(text *string) string {
	if text == nil {
		return "None"
	}
	return *text
}

// header is the page's header: what the page is for, by what the reader
// may do. The figures beside it are the header's own and the feed does not
// read them.
func header(role Role) *screensv1.PageHeader {
	canDecide, canRaise := role.DecidesFor != "" || role.DecidesAll, role.RaisesTo != ""
	var description string
	switch {
	case canDecide && canRaise:
		description = "Decisions your team has put in front of you, and the ones you have sent up to the " + addresseeLabel(role.RaisesTo)
	case canDecide && role.DecidesFor == rules.RegionalLevel:
		description = "Decisions the Country Director has put in front of you"
	case canDecide:
		description = "Decisions your team has put in front of you"
	default:
		description = "Decisions above your authority, routed to your " + addresseeLabel(role.RaisesTo)
	}
	return &screensv1.PageHeader{Eyebrow: "Leadership", Title: "Escalations", Description: description}
}

func option(value, label string) *screensv1.DrawerOption {
	return &screensv1.DrawerOption{Value: value, Label: label}
}

func field(f *screensv1.DrawerField) *screensv1.PageFormItem {
	return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: f}}
}

// raiseForm is the "Escalate to …" card: whom it goes to, when to use it,
// and its fields, opening with what a drill-down handed it.
func raiseForm(role Role, b board, query url.Values) *screensv1.PageBlock {
	label := addresseeLabel(role.RaisesTo)
	title := "Escalate to the " + label
	if b.raiseToName != "" {
		title = "Escalate to " + b.raiseToName + ", your " + label
	}
	var text string
	switch role.RaisesTo {
	case rules.RegionalLevel:
		text = "Use this when a decision sits above country authority — a structural funding gap, a partner failing across regions, or a policy exception."
	case "CD":
		text = "Use this when a decision sits above your team — a funding gap across clusters, a partner failing in more than one district, staffing you cannot cover, or a policy exception."
	default:
		text = "Use this when something is blocking your schools that you cannot clear yourself — a partner not delivering, a cluster you cannot cover, or a decision your Programme Lead has to make."
	}
	if role.RaisesTo != rules.RegionalLevel && b.raiseToID == "" {
		text += " No supervisor is on file for you, so this goes to every " + label + " in your country."
	}
	prefill := func(key string) string { return closedschools.StripSpace(query.Get(key)) }

	category := &screensv1.DrawerField{Name: "category", Label: "Category", Kind: "select", Value: rules.Categories[0][0], Required: true}
	for _, c := range rules.Categories {
		if c[0] == prefill("category") {
			category.Value = c[0]
		}
		category.Options = append(category.Options, option(c[0], c[1]))
	}
	severity := &screensv1.DrawerField{Name: "severity", Label: "Severity", Kind: "select"}
	for i, s := range rules.Severities {
		if i == 0 || s[0] == rules.DefaultSeverity {
			severity.Value = s[0]
		}
		severity.Options = append(severity.Options, option(s[0], s[1]))
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{
		Title: collapse(title),
		Text:  collapse(text),
		Items: []*screensv1.PageFormItem{
			field(category),
			field(severity),
			field(&screensv1.DrawerField{Name: "subject", Label: "Subject", Kind: "text", Value: prefill("subject"), Required: true,
				Placeholder: "One line: what needs deciding", MaxLength: proto.Int32(255)}),
			field(&screensv1.DrawerField{Name: "detail", Label: "What is happening", Kind: "textarea", Value: prefill("detail"), Required: true,
				Placeholder: "The situation, what you have already tried, and why it needs a decision above you."}),
			field(&screensv1.DrawerField{Name: "requested_decision", Label: "Decision you are asking for", Kind: "text",
				Placeholder: "e.g. Approve a 12M reallocation from Q3 to Q2", MaxLength: proto.Int32(512)}),
			field(&screensv1.DrawerField{Name: "due_date", Label: "Needed by", Kind: "date"}),
		},
		SubmitLabel: collapse("Send to " + label),
		Key:         "raise",
		CanSave:     true,
	}}}
}

func textItem(text string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: text}}
}

// card is a list's card read as the feed reads it: its title (and the line
// under it) as a panel, and its table, or the empty state's two lines.
func card(title string, lines ...string) *screensv1.PageBlock {
	p := &screensv1.PagePanel{Title: title}
	for _, l := range lines {
		p.Items = append(p.Items, textItem(l))
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: p}}
}

func pill(text string) *screensv1.PageCell {
	return &screensv1.PageCell{Text: collapse(text), Tone: "primary", Badge: true}
}

func plain(text string) *screensv1.PageCell { return &screensv1.PageCell{Text: collapse(text)} }

// status is the row's status pill: the decision once resolved, else
// Overdue past its wait, Acknowledged, or Open.
func status(e escalation) string {
	switch {
	case e.Status == rules.Statuses.Resolved:
		if e.Decision == nil || *e.Decision == "" {
			return "None"
		}
		if label, ok := lookup(rules.Decisions, *e.Decision); ok {
			return label
		}
		return "None"
	case e.Overdue:
		return "Overdue"
	case e.Status == rules.Statuses.Acknowledged:
		return "Acknowledged"
	}
	return "Open"
}

// opened is what opening the row shows, as the feed reads it: one panel of
// its lines, a label followed by a figure read as a data row. The decide
// forms beside them are not read.
func opened(e escalation) []*screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{}
	add := func(text string) {
		if t := collapse(text); t != "" {
			items = append(items, textItem(t))
		}
	}
	add("What is happening")
	add(e.Detail)
	if e.RequestedDecision != nil && *e.RequestedDecision != "" {
		add("Asking for: " + *e.RequestedDecision)
	}
	raised := orDash(e.RaisedByName) + " · raised " + e.CreatedAt.In(zone).Format("2 Jan 2006")
	if e.DueDate != nil {
		raised += " · needed by " + e.DueDate.Format("2 Jan 2006")
	}
	add(raised)
	if e.Status == rules.Statuses.Resolved {
		add(display(rules.AddresseeLabels, e.AddressedRole) + " decision")
		add(status(e))
		add(pyText(e.DecisionNote))
		decided := "decided "
		if e.ResolvedAt != nil {
			decided += e.ResolvedAt.In(zone).Format("2 Jan 2006")
		}
		add(decided)
	}
	return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: schoolprofile.PairedItems(items)}}}}
}

// row is one escalation as _table.html writes it.
func row(e escalation, showRaiser bool) *screensv1.PageRow {
	age := strconv.Itoa(e.AgeDays) + "d"
	if e.DueDate != nil {
		age += " · by " + e.DueDate.Format("2 Jan")
	}
	cells := []*screensv1.PageCell{
		pill(strings.ToUpper(e.Severity)),
		plain(e.Subject),
		plain(display(rules.Categories, e.Category)),
	}
	if showRaiser {
		cells = append(cells, plain(orDash(e.RaisedByName)))
	}
	cells = append(cells, plain(display(rules.AddresseeLabels, e.AddressedRole)), plain(age), pill(status(e)), &screensv1.PageCell{})
	return &screensv1.PageRow{Cells: cells, DetailBlocks: opened(e)}
}

// table is one list's table, one page of it, and its pager past one page.
func table(rows []escalation, showRaiser bool, query url.Values) []*screensv1.PageBlock {
	t := &screensv1.PageTable{}
	labels := []string{"Severity", "Subject", "Category"}
	if showRaiser {
		labels = append(labels, "Raised by")
	}
	for _, l := range append(labels, "Addressed to", "Age", "Status") {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: l})
	}
	t.Columns = append(t.Columns, &screensv1.PageColumn{Numeric: true})
	number, pages := closedschools.PageOf(query.Get(pageParam), len(rows), rules.PageSize)
	for _, e := range rows[(number-1)*rules.PageSize : min(number*rules.PageSize, len(rows))] {
		t.Rows = append(t.Rows, row(e, showRaiser))
	}
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		out = append(out, closedschools.PagerPanel(pageParam, number, pages, len(rows), rules.PageSize, query, rules.QueryKeysNotPassed))
	}
	return out
}

// page is the whole answer.
func page(role Role, b board, query url.Values) *screensv1.GetPageResponse {
	canDecide, canRaise := role.DecidesFor != "" || role.DecidesAll, role.RaisesTo != ""
	open := func(e escalation) bool { return e.IsOpen }
	inbox := b.filter(func(e escalation) bool { return open(e) && e.CanDecide })
	raised := b.filter(func(e escalation) bool { return e.Mine })
	watching := b.filter(func(e escalation) bool { return open(e) && !e.CanDecide && !e.Mine })
	decided := b.filter(func(e escalation) bool { return !open(e) && !e.Mine })
	decided = decided[:min(len(decided), decidedLimit)]

	blocks := []*screensv1.PageBlock{}
	if canRaise {
		blocks = append(blocks, raiseForm(role, b, query))
	}
	if canDecide {
		switch {
		case len(inbox) > 0:
			blocks = append(blocks, card("Awaiting your decision"))
			blocks = append(blocks, table(inbox, true, query)...)
		case role.DecidesFor == rules.RegionalLevel:
			blocks = append(blocks, card("Awaiting your decision", "Nothing is waiting on your decision", "The Country Director has not escalated anything."))
		default:
			blocks = append(blocks, card("Awaiting your decision", "Nothing is waiting on your decision", "Your team has not escalated anything."))
		}
	}
	if canRaise {
		if len(raised) > 0 {
			blocks = append(blocks, card("Raised by you"))
			blocks = append(blocks, table(raised, false, query)...)
		} else {
			blocks = append(blocks, card("Raised by you", "No escalations yet", "Nothing is currently escalated to the "+addresseeLabel(role.RaisesTo)+"."))
		}
	}
	if len(watching) > 0 {
		blocks = append(blocks, card("Received by your Programme Leads", "Read-only — the Programme Lead each item is addressed to decides it."))
		blocks = append(blocks, table(watching, true, query)...)
	}
	if len(decided) > 0 {
		blocks = append(blocks, card("Recently decided"))
		blocks = append(blocks, table(decided, true, query)...)
	}
	return &screensv1.GetPageResponse{Header: header(role), Blocks: blocks, WebPath: Path}
}
