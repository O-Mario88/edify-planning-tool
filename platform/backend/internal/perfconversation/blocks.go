package perfconversation

import (
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
)

// The page's parts are written as the template writes them, a tree of
// elements with the template's spaces between them, and read by the feed's
// own rules: a card holding one form with little around it is that form
// (page_forms._form_of), anything else a panel whose forms are skipped.

var el = feeddom.El

// feedOf appends the blocks the feed reads card as.
func feedOf(out []*screensv1.PageBlock, card *feeddom.Node) []*screensv1.PageBlock {
	if form := feeddom.CardForm(card); form != nil {
		return append(out, formBlock(card, form))
	}
	return feeddom.Walk(el("div", "", card), out)
}

// formBlock is page_forms.read over a card's one form: the card's first
// heading and line outside the form, the form's fields as drawer_blocks
// reads them, its button and where it posts.
func formBlock(card, form *feeddom.Node) *screensv1.PageBlock {
	f := &screensv1.PageForm{SubmitLabel: "Save", Key: form.Get("action")}
	if h := feeddom.Outside(card, form, func(n *feeddom.Node) bool {
		switch n.Tag() {
		case "h1", "h2", "h3", "h4":
			return true
		}
		return false
	}); h != nil {
		f.Title = h.Text()
	}
	if line := feeddom.Outside(card, form, func(n *feeddom.Node) bool { return n.Tag() == "p" && n.Text() != "" }); line != nil {
		f.Text = line.Text()
	}
	for _, control := range form.FindAll(func(n *feeddom.Node) bool {
		return n.Tag() == "textarea" || n.Tag() == "select" || (n.Tag() == "input" && n.Get("type") != "hidden")
	}) {
		f.Items = append(f.Items, &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: fieldOf(control)}})
	}
	if buttons := form.FindAll(func(n *feeddom.Node) bool { return n.Tag() == "button" }); len(buttons) > 0 {
		f.SubmitLabel = buttons[0].Text()
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: f}}
}

// postForm is a form posting to action: its controls, then its button.
func postForm(action, submit string, parts ...any) *feeddom.Node {
	form := el("form", "").Attr("method", "post", "action", action)
	for _, p := range parts {
		form.Add(p, " ")
	}
	return form.Add(el("button", "", submit).Attr("type", "submit"))
}

// fieldOf is a control as drawer_blocks reads one of these: a textarea with
// its words, a select with its choices and the chosen one (none chosen,
// none), or a text input.
func fieldOf(n *feeddom.Node) *screensv1.DrawerField {
	switch n.Tag() {
	case "textarea":
		return &screensv1.DrawerField{Name: n.Get("name"), Label: n.Get("aria-label"), Kind: "textarea", Placeholder: n.Get("placeholder"), Value: n.Written()}
	case "select":
		field := &screensv1.DrawerField{Name: n.Get("name"), Label: n.Get("aria-label"), Kind: "select"}
		for _, o := range n.FindAll(func(x *feeddom.Node) bool { return x.Tag() == "option" }) {
			field.Options = append(field.Options, &screensv1.DrawerOption{Value: o.Get("value"), Label: o.Text()})
			if o.Get("selected") != "" {
				field.Value = o.Get("value")
			}
		}
		return field
	}
	return &screensv1.DrawerField{Name: n.Get("name"), Label: n.Get("aria-label"), Kind: "text", Placeholder: n.Get("placeholder"), Value: n.Get("value")}
}

func textarea(name, placeholder string, value *string) *feeddom.Node {
	return el("textarea", "", deref(value)).Attr("name", name, "placeholder", placeholder)
}

// ratingSelect is a rating's select: its prompt, then the five ratings, the
// stored one chosen when it is one of them.
func ratingSelect(name, label, prompt string, value *string) *feeddom.Node {
	s := el("select", "").Attr("aria-label", label, "name", name)
	s.Add(el("option", "", prompt).Attr("value", ""))
	for _, r := range rules.Ratings {
		o := el("option", "", r[1]).Attr("value", r[0])
		if value != nil && *value == r[0] {
			o.Attr("selected", "selected")
		}
		s.Add(" ", o)
	}
	return s
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

func orDash(s *string) string {
	if s == nil || *s == "" {
		return "—"
	}
	return *s
}

// ratingText is {% firstof row.p.get_x_rating_display row.p.x_rating %}:
// the rating columns declare no choices, so there is no display and the
// stored value is shown as it is.
func ratingText(value string) string { return value }

// notice is an empty state: its line and why.
func notice(line, why string) *feeddom.Node {
	return el("div", "edify-surface rounded-surface", el("p", "font-bold", line), " ", el("p", "edify-text-caption", why))
}

// agreementCard is the priorities an employee submitted, waiting on the
// reviewer's agreement.
func agreementCard(c conversation, priorities []priority) *feeddom.Node {
	list := el("ul", "divide-y")
	for _, pr := range priorities {
		list.Add(el("li", "px-5", el("span", "", strconv.Itoa(pr.sequence)+". "+pr.outcome), " ",
			el("span", "edify-text-caption shrink-0", "weight "+strconv.Itoa(pr.weight)+"%")), " ")
	}
	if len(priorities) == 0 {
		list.Add(el("li", "px-5", "No priorities are recorded on this agreement."))
	}
	note := el("label", "flex-1", el("span", "edify-text-caption", "Note for the record (optional)"), " ",
		el("input", "").Attr("type", "text", "name", "note"))
	form := el("form", "").Attr("method", "post", "action", "/performance-conversation/"+c.reviewID+"/agree-priorities")
	form.Add(" ", note, " ", el("button", "", "Agree these priorities").Attr("type", "submit"))
	return el("section", "edify-surface rounded-surface",
		el("div", "px-5", el("h2", "", c.target.name+" submitted their priorities for your agreement"), " ",
			el("p", "edify-text-caption", "Agreeing locks them as the FY"+c.fy+" agreement the year's conversations are held against.")),
		" ", list, " ", form)
}

// priorityCard is one priority: its outcome and weight, then the employee's,
// manager's and functional manager's columns, each a form for the one who
// writes it and its words for everyone else.
func priorityCard(pr priority, caps map[string]bool) *feeddom.Node {
	alignment := "None"
	if pr.alignment != nil {
		alignment = *pr.alignment
	}
	lead := el("div", "", el("p", "font-bold", strconv.Itoa(pr.sequence)+". "+pr.outcome), " ",
		el("p", "edify-text-caption", alignment+" · weight "+strconv.Itoa(pr.weight)+"%"))
	if pr.mandatory {
		lead.Add(" ", el("p", "edify-text-caption",
			"Organisation priority. Milestones and phasing are yours to agree; whether it applies is not."))
	}
	head := el("div", "px-5", el("div", "flex", lead, " ", el("div", "text-right shrink-0", el("span", "edify-badge", "Qualitative"))))
	save := "/performance-conversation/priority/" + pr.id + "/save"
	employee := el("div", "p-4", el("p", "edify-text-caption uppercase", "Employee"), " ")
	if caps["employee"] {
		employee.Add(postForm(save, "Save my reflection",
			el("input", "").Attr("type", "hidden", "name", "channel", "value", "employee"),
			textarea("employee_reflection", "Progress, achievements, barriers, support needed", pr.reflection),
			ratingSelect("employee_rating", "Employee rating", "Self-rating…", pr.employeeRating)))
	} else {
		employee.Add(el("p", "whitespace-pre-line", orDash(pr.reflection)))
		if deref(pr.employeeRating) != "" {
			employee.Add(" ", el("p", "edify-text-caption", "Rating: "+ratingText(*pr.employeeRating)))
		}
	}
	manager := el("div", "p-4", el("p", "edify-text-caption uppercase", "Manager"), " ")
	if caps["manager"] {
		manager.Add(postForm(save, "Save manager review",
			el("input", "").Attr("type", "hidden", "name", "channel", "value", "manager"),
			textarea("manager_assessment", "Manager comment", pr.assessment),
			ratingSelect("manager_rating", "Manager rating", "Manager rating…", pr.managerRating),
			textarea("agreed_action", "Agreed action", pr.action)))
	} else {
		manager.Add(el("p", "whitespace-pre-line", orDash(pr.assessment)))
		if deref(pr.managerRating) != "" {
			manager.Add(" ", el("p", "edify-text-caption", "Rating: "+ratingText(*pr.managerRating)))
		}
		if deref(pr.action) != "" {
			manager.Add(" ", el("p", "edify-text-caption", "Agreed: "+*pr.action))
		}
	}
	functional := el("div", "p-4", el("p", "edify-text-caption uppercase", "Functional Manager"), " ")
	if caps["functional"] {
		functional.Add(postForm(save, "Save rating",
			el("input", "").Attr("type", "hidden", "name", "channel", "value", "functional"),
			ratingSelect("functional_manager_rating", "Functional manager rating", "Functional rating…", pr.functionalRating)))
	} else if deref(pr.functionalRating) != "" {
		functional.Add(el("p", "", ratingText(*pr.functionalRating)))
	} else {
		functional.Add(el("p", "", "—"))
	}
	return el("div", "edify-surface rounded-surface", head, " ",
		el("div", "grid", employee, " ", manager, " ", functional))
}

// valuesCard is Edify Values & Spiritual Formation: each commitment, with
// the employee's form or their words, and the manager's.
func valuesCard(values []commitment, caps map[string]bool) *feeddom.Node {
	list := el("ul", "divide-y")
	for _, v := range values {
		kind := v.kind
		if l, ok := rules.ValueKinds[v.kind]; ok {
			kind = l
		}
		item := el("li", "px-5", el("div", "flex", el("p", "font-bold", v.name), " ", el("span", "edify-text-caption", kind)), " ")
		save := "/performance-conversation/value/" + v.id + "/save"
		if caps["employee"] {
			item.Add(postForm(save, "Save commitment",
				el("input", "").Attr("name", "agreed_behaviour", "value", deref(v.behaviour), "placeholder", "Agreed behaviour / commitment"),
				textarea("employee_reflection", "My reflection", v.reflection)), " ")
		} else {
			if deref(v.behaviour) != "" {
				item.Add(el("p", "edify-text-caption", "Commitment: "+*v.behaviour), " ")
			}
			if deref(v.reflection) != "" {
				item.Add(el("p", "edify-text-caption", "Reflection: "+*v.reflection), " ")
			}
		}
		if caps["manager"] {
			item.Add(postForm(save, "Save observation", textarea("manager_evidence", "Manager observation", v.evidence)))
		} else if deref(v.evidence) != "" {
			item.Add(el("p", "edify-text-caption", "Manager: "+*v.evidence))
		}
		list.Add(item, " ")
	}
	return el("div", "edify-surface rounded-surface",
		el("div", "px-5", el("h2", "", "Edify Values & Spiritual Formation"), " ",
			el("p", "edify-text-caption", "Manual and reflective — never rated from activity counts.")),
		" ", list)
}

// signOffCard is the sign-off, its form holding only the window and the
// button (no field, so the card is read as its words).
func signOffCard() *feeddom.Node {
	form := el("form", "").Attr("method", "post")
	form.Add(el("input", "").Attr("type", "hidden", "name", "window"), " ", el("button", "", "Sign off & lock").Attr("type", "submit"))
	return el("div", "edify-surface rounded-surface",
		el("div", "", el("p", "font-bold", "Sign off this conversation"), " ",
			el("p", "edify-text-caption", "Locks the snapshot permanently. Only HR can reopen it, with a reason.")),
		" ", form)
}
