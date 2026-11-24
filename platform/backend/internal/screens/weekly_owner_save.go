package screens

import (
	"context"
	"errors"
	"log/slog"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// WeekOwner is the Go save behind an owner's buttons on their weekly fund
// request (internal/activities.Service).
type WeekOwner interface {
	DecideOwnWeek(ctx context.Context, p auth.Principal, requestID, op string, bankMessage bool, origin activities.Origin) (activities.Answer, error)
}

// WithWeekOwner makes the owner's weekly request buttons Go's. The Fund
// Requests page draws them (as drawers at each save's own path) only when Go
// saves them.
func (s *Service) WithWeekOwner(owner WeekOwner) *Service {
	s.weekOwner = owner
	return s
}

// bankReceivedLabel is weekly_request_workflow.html's attestation.
const bankReceivedLabel = "I have received the bank message and verified the funds are in my account."

// weekOwnerDrawer is the button's drawer: what the button says, and the
// attestation Fund Received asks for.
func (s *Service) weekOwnerDrawer(path string) (*screensv1.GetDrawerResponse, bool) {
	if s.weekOwner == nil {
		return nil, false
	}
	_, op, ok := activities.WeekOwnerForm(path)
	if !ok {
		return nil, false
	}
	drawer := &screensv1.PageDrawer{CancelLabel: "Cancel", CanSubmit: true}
	note := func(text string) *screensv1.DrawerItem {
		return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: text}}
	}
	switch op {
	case "send":
		drawer.Title, drawer.SubmitLabel = "Send for Approval", "Send for Approval"
		drawer.Items = []*screensv1.DrawerItem{note("Send this week's advance request to your approver.")}
	case "self_fund":
		drawer.Title, drawer.SubmitLabel = "Self Fund", "Self Fund"
		drawer.Items = []*screensv1.DrawerItem{note("The same planned amount follows supervisor approval, disbursement and receipt confirmation.")}
	case "skip":
		drawer.Title, drawer.SubmitLabel = "No Advance This Week", "No Advance This Week"
		drawer.Items = []*screensv1.DrawerItem{note("Skip the advance for this week? The planned work stays; no money will be requested.")}
	default:
		drawer.Title, drawer.SubmitLabel, drawer.HasRequired = "Fund Received", "Fund Received", true
		drawer.Items = []*screensv1.DrawerItem{
			fieldItem("bank_message_received", bankReceivedLabel, "checkbox", "", true),
			note("Only click Fund Received after receiving the bank message and verifying the funds arrived."),
		}
	}
	return &screensv1.GetDrawerResponse{Drawer: drawer}, true
}

// weekOwnerInGo saves an owner's button with Django absent; served is false
// for any other path.
func (s *Service) weekOwnerInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (
	*screensv1.SaveDrawerResponse, bool, error,
) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok || s.weekOwner == nil || s.existingApp != nil {
		return nil, false, nil
	}
	path, _, _ := strings.Cut(message.GetPath(), "?")
	requestID, op, ok := activities.WeekOwnerForm(path)
	if !ok {
		return nil, false, nil
	}
	bank := message.GetValues()["bank_message_received"]
	saved, err := s.weekOwner.DecideOwnWeek(ctx, principal, requestID, op, bank == "yes" || bank == "on", from)
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go weekly request save failed before it was made", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(saved.Message)}, true, nil
}
