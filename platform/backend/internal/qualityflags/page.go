package qualityflags

import (
	"net/url"
	"regexp"
	"strings"
	"time"
	"unicode"

	_ "time/tzdata" // the raised dates are Nairobi's wherever the gateway runs

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// zone is settings.TIME_ZONE, the zone |date writes a time in.
var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("qualityflags: " + err.Error())
	}
	return z
}()

const dash = "—"

func collapse(text string) string { return closedschools.Collapse(text) }

func orDash(text string) string {
	if text == "" {
		return dash
	}
	return text
}

// pyTitle is Django's |title: str.title(), then a letter after
// "<lower>'" or after a digit lowered again.
func pyTitle(s string) string {
	out := []rune{}
	cased := false
	for _, r := range s {
		if cased {
			out = append(out, unicode.ToLower(r))
		} else {
			out = append(out, unicode.ToTitle(r))
		}
		cased = unicode.IsUpper(r) || unicode.IsLower(r) || unicode.IsTitle(r)
	}
	t := apostrophe.ReplaceAllStringFunc(string(out), strings.ToLower)
	return digitThenUpper.ReplaceAllStringFunc(t, strings.ToLower)
}

var (
	apostrophe     = regexp.MustCompile(`[a-z]'[A-Z]`)
	digitThenUpper = regexp.MustCompile(`\d[A-Z]`)
)

func header() *screensv1.PageHeader {
	return &screensv1.PageHeader{Eyebrow: "Quality & Insights", Title: "Quality Flags",
		Description: "Edify Operations · CD-raised, PL-actioned quality flags"}
}

func field(f *screensv1.DrawerField) *screensv1.PageFormItem {
	return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: f}}
}

func formText(text string) *screensv1.PageFormItem {
	return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Text{Text: text}}
}

// raiseForm is the "Raise a Flag" card, opening with what an analytics
// drill-down handed it.
func raiseForm(leads []lead, query url.Values) *screensv1.PageBlock {
	prefill := func(key string) string { return closedschools.StripSpace(query.Get(key)) }
	items := []*screensv1.PageFormItem{}
	if scope := prefill("scope_name"); scope != "" {
		items = append(items, formText(collapse("About: "+scope)),
			formText("Carried over from the analytics drill-down, so the Program Lead sees exactly what you were looking at."))
	}
	assign := &screensv1.DrawerField{Name: "assigned_to_user_id", Label: "Assign to Program Lead", Kind: "select", Required: true,
		Options: []*screensv1.DrawerOption{{Value: "", Label: "Select a Program Lead…"}}}
	for _, l := range leads {
		if l.ID == prefill("assign_to") {
			assign.Value = l.ID
		}
		assign.Options = append(assign.Options, &screensv1.DrawerOption{Value: l.ID, Label: collapse(l.Name)})
	}
	items = append(items,
		field(assign),
		field(&screensv1.DrawerField{Name: "category", Label: "Category", Kind: "text", Value: prefill("category"), Placeholder: "e.g. data-quality"}),
		field(&screensv1.DrawerField{Name: "note", Label: "Note", Kind: "textarea", Value: prefill("note"), Required: true}),
		field(&screensv1.DrawerField{Name: "recommended_action", Label: "Recommended Action", Kind: "text"}),
	)
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{
		Title: "Raise a Flag", Items: items, SubmitLabel: "Raise Flag", Key: "raise",
	}}}
}

// name is {% firstof f.scope_name f.category "Flag" %}.
func name(f flag) string {
	for _, n := range []string{deref(f.ScopeName), f.Category} {
		if n != "" {
			return n
		}
	}
	return "Flag"
}

// actions is the row's Actions cell: an open flag's Acknowledge and Resolve
// menu (the feed reads the Resolve drawer alone, not the Acknowledge form),
// an acknowledged flag's Resolve button, nothing once resolved or not the
// reader's.
func actions(p auth.Principal, f flag) *screensv1.PageCell {
	cell := &screensv1.PageCell{}
	mine := f.AssignedTo == p.UserID || p.ActiveRole == roleAdmin
	if f.Status == "resolved" || !mine {
		return cell
	}
	resolve := &screensv1.PageAction{Key: "button", Label: "Resolve", Primary: true, Enabled: true,
		Href: Path + "?resolve=" + f.ID, Drawer: true}
	if f.Status == "open" {
		resolve.Key, resolve.Primary = "menu", false
	}
	cell.Actions = []*screensv1.PageAction{resolve}
	return cell
}

func row(p auth.Principal, role Role, f flag) *screensv1.PageRow {
	note := orDash(f.Note)
	if ra := deref(f.RecommendedAction); ra != "" {
		note += " · " + ra
	}
	status, ok := rules.Statuses[f.Status]
	if !ok {
		status = f.Status
	}
	cells := []*screensv1.PageCell{}
	for _, text := range []string{
		name(f), note,
		orDash(deref(f.RaisedByName)) + " · " + f.CreatedAt.In(zone).Format("2 Jan 2006"),
		orDash(deref(f.Assignee)),
		pyTitle(f.Priority),
		orDash(deref(f.DueDate)),
		status,
		orDash(deref(f.ResolutionNote)),
	} {
		cells = append(cells, &screensv1.PageCell{Text: collapse(text)})
	}
	if role.Acts {
		cells = append(cells, actions(p, f))
	}
	return &screensv1.PageRow{Cells: cells}
}

// register is the "Quality flags" card: its title as a panel (the count
// beside it is a span the feed does not read), then the table, or the empty
// state's one cell.
func register(p auth.Principal, role Role, flags []flag) []*screensv1.PageBlock {
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Quality flags"}}}}
	t := &screensv1.PageTable{}
	if len(flags) == 0 {
		t.EmptyMessage = "No quality flags raised"
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{
			Text: "No quality flags raised Flags the Country Director raises to a Programme Lead appear here."}}}}
		return append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	}
	labels := []string{"Flag", "Note", "Raised by", "Assigned to", "Priority", "Due", "Status", "Resolution"}
	if role.Acts {
		labels = append(labels, "")
	}
	for _, l := range labels {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: l})
	}
	for _, f := range flags {
		t.Rows = append(t.Rows, row(p, role, f))
	}
	return append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
}

// page is the whole answer. The register lists at most rules.Limit flags,
// so its 50-row pager never shows.
func page(p auth.Principal, role Role, flags []flag, leads []lead, query url.Values) *screensv1.GetPageResponse {
	blocks := []*screensv1.PageBlock{}
	if role.Raises {
		blocks = append(blocks, raiseForm(leads, query))
	}
	blocks = append(blocks, register(p, role, flags)...)
	return &screensv1.GetPageResponse{Header: header(), Blocks: blocks, WebPath: Path}
}
