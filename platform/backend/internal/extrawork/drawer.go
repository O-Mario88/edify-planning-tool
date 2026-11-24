package extrawork

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// ActionDrawer is the drawer behind a row's button: Submit Result is
// extra_work_submit_drawer; the others are the page's one-press forms, asked
// in a drawer because the web posts a button only through one.
func (s *Service) ActionDrawer(ctx context.Context, p auth.Principal, id, action string) (*screensv1.PageDrawer, error) {
	var a assignmentRow
	var instruction, expected, assignerRole, returnReason string
	err := s.db.QueryRow(ctx, `SELECT title, assigner_id, assignee_id, reviewer_id, status, evidence_required, due_date,
  COALESCE(instruction, ''), COALESCE(expected_output, ''), COALESCE(assigner_role, ''), COALESCE(return_reason, '')
  FROM hr_extra_assignment WHERE id = $1`, id).Scan(&a.title, &a.assigner, &a.assignee, &a.reviewer, &a.status,
		&a.evidenceRequired, &a.due, &instruction, &expected, &assignerRole, &returnReason)
	if errors.Is(err, pgx.ErrNoRows) || (err == nil && a.gate(p.UserID, action) != nil) {
		return nil, refuse("Assignment not found.")
	}
	if err != nil {
		return nil, fmt.Errorf("extrawork: reading the assignment: %w", err)
	}
	text := func(t string) *screensv1.DrawerItem {
		return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: t}}
	}
	field := func(f *screensv1.DrawerField) *screensv1.DrawerItem {
		return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: f}}
	}
	d := &screensv1.PageDrawer{CancelLabel: "Cancel", CanSubmit: true}
	switch action {
	case "start":
		d.Title, d.SubmitLabel = "Start "+a.title, "Start"
		d.Items = []*screensv1.DrawerItem{text("Start this assignment?")}
	case "submit":
		d.Title, d.Subtitle, d.SubmitLabel, d.HasRequired = "Submit result for "+a.title, "Due "+a.due.Format("02 Jan 2006"),
			"Submit for verification", true
		if a.status == "returned" {
			d.Items = append(d.Items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{
				Text: "Returned: " + returnReason, Tone: "danger"}}})
		}
		d.Items = append(d.Items, text("What was asked"), text(instruction))
		if expected != "" {
			d.Items = append(d.Items, text("Expected output: "+expected))
		}
		evidence := "Evidence (optional)"
		if a.evidenceRequired {
			evidence = "Evidence"
		}
		d.Items = append(d.Items,
			field(&screensv1.DrawerField{Name: "outcome", Label: "What was delivered", Kind: "textarea", Required: true}),
			field(&screensv1.DrawerField{Name: "evidence_note", Label: evidence, Kind: "textarea", Required: a.evidenceRequired,
				Placeholder: "Attendance, document name or record reference"}),
			field(&screensv1.DrawerField{Name: "evidence_uri", Label: "Evidence link (optional)", Kind: "text", Placeholder: "https://…"}),
			text("Goes to "+assignerRole+" for verification."))
	case "verify":
		d.Title, d.SubmitLabel = "Verify "+a.title, "Verify & Complete"
		d.Items = []*screensv1.DrawerItem{text("Confirm the work was delivered. The assignee can never verify their own work.")}
	case "return":
		d.Title, d.SubmitLabel, d.HasRequired = "Return "+a.title, "Return", true
		d.Items = []*screensv1.DrawerItem{field(&screensv1.DrawerField{Name: "reason", Label: "What must be corrected",
			Kind: "textarea", Required: true})}
	case "cancel":
		d.Title, d.SubmitLabel = "Cancel "+a.title, "Cancel assignment"
		d.Items = []*screensv1.DrawerItem{text("Cancel this assignment? The assignee is told.")}
	default:
		return nil, refuse("Unknown action")
	}
	return d, nil
}
