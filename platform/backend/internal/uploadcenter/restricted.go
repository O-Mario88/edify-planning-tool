package uploadcenter

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
)

// RestrictedPath is where a person who disagreed with a required policy
// lands until HR resolves it (documents.views.restricted_view,
// pages/documents/restricted.html, which extends base.html rather than the
// shell): its own minimal chrome, then each policy the reader disagreed with
// that gates the application and is in force, with their reason and the
// form that changes the answer to Agree (the save stays with the existing
// application).
const RestrictedPath = "/policy-agreement/restricted"

// readableStatuses are documents.READABLE_STATUSES: a policy in force.
var readableStatuses = []string{"published", "effective"}

func (s *Service) restricted(ctx context.Context, p auth.Principal) (*screensv1.GetPageResponse, bool, error) {
	// disagreed_for, newest first (the model's ordering), joined to the
	// document and its version as the queryset is.
	rows, err := s.db.Query(ctx, `
SELECT a.id, d.title, d.description, a.comment, d.slug, d.agreement_statement
FROM document_acknowledgement a INNER JOIN document_asset d ON a.document_id = d.id
INNER JOIN document_version v ON a.version_id = v.id
WHERE a.state = 'disagreed' AND a.user_id = $1 AND d.blocks_application_access AND d.status = ANY($2)
ORDER BY a.created_at DESC`,
		p.UserID, readableStatuses)
	if err != nil {
		return nil, true, fmt.Errorf("uploadcenter: reading the reader's disagreements: %w", err)
	}
	type declined struct{ id, title, description, comment, slug, statement string }
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (declined, error) {
		var x declined
		return x, r.Scan(&x.id, &x.title, &x.description, &x.comment, &x.slug, &x.statement)
	})
	if err != nil {
		return nil, true, fmt.Errorf("uploadcenter: reading the reader's disagreements: %w", err)
	}
	text := func(lines ...string) *screensv1.PageBlock {
		panel := &screensv1.PagePanel{}
		for _, l := range lines {
			panel.Items = append(panel.Items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: l}})
		}
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: panel}}
	}
	// base.html's own parts as the feed reads them: the page's title, the
	// loading and offline notices, and the bar's Sign out.
	blocks := []*screensv1.PageBlock{
		text("Policy Response — Edify"),
		text("Loading your workspace…", "Preparing your dashboard…"),
		text("You are offline", "Changes cannot be sent. Keep this page open and reconnect to continue."),
		text("Sign out"),
	}
	el := feeddom.El
	for _, x := range list {
		form := el("form", "").Attr("method", "post", "action", "/api/documents/acknowledge/"+x.id)
		form.Add(el("p", "", x.statement), " ", el("input", "").Attr("type", "hidden", "name", "choice", "value", "agree"), " ",
			el("label", "", el("span", "", "Comment"), " ", el("textarea", "").Attr("name", "comment")), " ",
			el("button", "", "Change my answer to Agree").Attr("type", "submit"))
		card := el("section", "card", el("h2", "", x.title), " ", el("p", "", x.description), " ",
			el("p", "", el("strong", "", "Your reason:"), " ", x.comment), " ",
			el("div", "", el("a", "", "Read the policy again").Attr("href", "/documents/"+x.slug+"/"), " ",
				el("a", "", "Contact support").Attr("href", "/support")), " ", form)
		if f := feeddom.CardForm(card); f != nil {
			blocks = append(blocks, responseForm(card, f))
			continue
		}
		blocks = feeddom.Walk(el("div", "", card), blocks)
	}
	header := &screensv1.PageHeader{Eyebrow: "Policy", Title: "HR is reviewing your response",
		Description: "You recorded a disagreement with a required policy. HR and your Country Director have been notified. Nothing has been suspended — you can change your answer at any time."}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: RestrictedPath}, true, nil
}

// responseForm is page_forms.read over a response card: its title and first
// line outside the form, then the form's statement (a text item, when it
// has words) and its comment field, its button and where it posts.
func responseForm(card, form *feeddom.Node) *screensv1.PageBlock {
	f := &screensv1.PageForm{SubmitLabel: "Change my answer to Agree", Key: form.Get("action")}
	if h := feeddom.Outside(card, form, func(n *feeddom.Node) bool { return n.Tag() == "h2" }); h != nil {
		f.Title = h.Text()
	}
	if line := feeddom.Outside(card, form, func(n *feeddom.Node) bool { return n.Tag() == "p" && n.Text() != "" }); line != nil {
		f.Text = line.Text()
	}
	for _, n := range form.FindAll(func(n *feeddom.Node) bool { return n.Tag() == "p" || n.Tag() == "textarea" }) {
		if n.Tag() == "p" {
			if t := n.Text(); t != "" {
				f.Items = append(f.Items, &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Text{Text: t}})
			}
			continue
		}
		f.Items = append(f.Items, &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{
			Field: &screensv1.DrawerField{Name: n.Get("name"), Kind: "textarea", Value: n.Written()}}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: f}}
}
