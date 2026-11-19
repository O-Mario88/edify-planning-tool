package adminops

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
)

// ReportPath is Report a Problem (admin_ops.views.report_problem_view,
// pages/admin_ops/report_problem.html): the form every signed-in role
// raises a support ticket with (the save stays with the existing
// application), then the reader's own twenty newest tickets.
const ReportPath = "/support"

const (
	reportTicketLimit = 20
	titleMaxLength    = 255
	defaultUrgency    = "medium"
)

func (s *Service) report(ctx context.Context, p auth.Principal) (*screensv1.GetPageResponse, bool, error) {
	rows, err := s.db.Query(ctx, `SELECT COALESCE(reference, ''), COALESCE(title, ''), COALESCE(status, ''), COALESCE(resolution, '')
FROM admin_support_ticket WHERE reporter_id = $1 ORDER BY created_at DESC LIMIT $2`, p.UserID, reportTicketLimit)
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the reader's tickets: %w", err)
	}
	type mine struct{ reference, title, status, resolution string }
	tickets, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (mine, error) {
		var t mine
		return t, row.Scan(&t.reference, &t.title, &t.status, &t.resolution)
	})
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the reader's tickets: %w", err)
	}
	maxLength := int32(titleMaxLength)
	category := &screensv1.DrawerField{Name: "category", Kind: "select"}
	for i, c := range rules.TicketCategoryChoices {
		if i == 0 {
			category.Value = c[0] // no choice is marked: the first is the one sent
		}
		category.Options = append(category.Options, &screensv1.DrawerOption{Value: c[0], Label: c[1]})
	}
	urgency := &screensv1.DrawerField{Name: "urgency", Kind: "select", Value: defaultUrgency}
	for _, c := range rules.SeverityChoices {
		urgency.Options = append(urgency.Options, &screensv1.DrawerOption{Value: c[0], Label: c[1]})
	}
	field := func(f *screensv1.DrawerField) *screensv1.PageFormItem {
		return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: f}}
	}
	form := &screensv1.PageForm{
		Items: []*screensv1.PageFormItem{
			field(&screensv1.DrawerField{Name: "title", Kind: "text", Required: true, Placeholder: "The Schedule button does nothing", MaxLength: &maxLength}),
			field(category), field(urgency),
			field(&screensv1.DrawerField{Name: "description", Kind: "textarea", Placeholder: "What were you trying to do, and what did you see instead?"}),
		},
		SubmitLabel: "Send to the platform team", Key: ReportPath,
	}
	// "Your Reports", written as the template writes it and read by the
	// feed's own panel rules.
	el := feeddom.El
	section := el("section", "card", el("h2", "", "Your Reports"), " ")
	for _, t := range tickets {
		status := t.status
		if l, ok := rules.TicketStatuses[t.status]; ok {
			status = l
		}
		ticket := el("div", "py-3", el("div", "flex", el("span", "edify-text-caption", t.reference), " ",
			el("span", "px-1.5 rounded-pill edify-text-caption bg-slate-100", status)), " ", el("p", "", t.title))
		if t.resolution != "" {
			ticket.Add(" ", el("p", "", t.resolution))
		}
		section.Add(ticket, " ")
	}
	if len(tickets) == 0 {
		section.Add(el("p", "", "You have not reported anything yet."))
	}
	blocks := feeddom.Walk(el("div", "", section), []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Form{Form: form}}})
	header := &screensv1.PageHeader{Eyebrow: "Help", Title: "Report a Problem",
		Description: "Tell the platform team what went wrong. We capture the page you were on and your browser automatically — never your password, tokens or message contents."}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: ReportPath}, true, nil
}
