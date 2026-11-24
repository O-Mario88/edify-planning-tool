package screens

import (
	"context"
	"errors"
	"log/slog"
	"regexp"
	"strconv"
	"strings"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// accountabilityPath is my_plan_views.accountability_action's route.
var accountabilityPath = regexp.MustCompile(`^/my-plan/([A-Za-z0-9]{1,30})/accountability/?$`)

// Accountant is the Go save behind the accountability drawer
// (internal/activities.Service).
type Accountant interface {
	AccountabilityDrawer(ctx context.Context, p auth.Principal, activityID string) (activities.AccountabilityView, error)
	SubmitAccountability(ctx context.Context, p auth.Principal, activityID string, f activities.AccountabilityForm, origin activities.Origin) (activities.Answer, error)
}

// WithAccountability makes the officer's accountability drawer Go's, with
// Django absent.
func (s *Service) WithAccountability(a Accountant) *Service {
	s.accountant = a
	return s
}

// accountabilityDrawerInGo is partials/my_plan/accountability_drawer.html.
func (s *Service) accountabilityDrawerInGo(ctx context.Context, p auth.Principal, path string) (*screensv1.GetDrawerResponse, bool, error) {
	m := accountabilityPath.FindStringSubmatch(path)
	if m == nil || s.accountant == nil {
		return nil, false, nil
	}
	view, err := s.accountant.AccountabilityDrawer(ctx, p, m[1])
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, refusal.Message)
	case err != nil:
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.GetDrawerResponse{Drawer: accountabilityDrawer(view)}, true, nil
}

func accountabilityDrawer(view activities.AccountabilityView) *screensv1.PageDrawer {
	title := "Submit accountability"
	if view.School != "" {
		title += " for " + view.School
	}
	text := func(t string) *screensv1.DrawerItem {
		return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: t}}
	}
	items := []*screensv1.DrawerItem{text("Disbursed to you: UGX " + groupedUGX(view.Total))}
	for _, line := range view.Lines {
		items = append(items, text(line[0]+" — "+line[1]))
	}
	field := func(f *screensv1.DrawerField) *screensv1.DrawerItem {
		return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: f}}
	}
	zero := 0.0
	items = append(items,
		field(&screensv1.DrawerField{Name: "amount_spent", Label: "Amount spent (UGX)", Kind: "number", Value: strconv.FormatInt(view.Total, 10), Min: &zero}),
		field(&screensv1.DrawerField{Name: "amount_returned", Label: "Amount returned (UGX)", Kind: "number", Value: "0", Min: &zero}),
		field(&screensv1.DrawerField{Name: "variance_note", Label: "Variance explanation", Kind: "textarea", Placeholder: "Why the amounts differ",
			Help: "Needed when the amount spent and the amount returned do not add up to the amount given."}),
		field(&screensv1.DrawerField{Name: "receipt_file", Label: "Receipts", Kind: "file"}),
		field(&screensv1.DrawerField{Name: "netsuite_code", Label: "NetSuite code", Kind: "text", Required: true, Placeholder: "e.g. EXP-2026-00889",
			Help: "Proves the expense is in NetSuite. It is separate from the activity's Salesforce ID."}),
	)
	return &screensv1.PageDrawer{Title: title, HasRequired: true, SubmitLabel: "Submit for finance review", CancelLabel: "Cancel",
		CanSubmit: true, Items: items}
}

// groupedUGX is the ugx filter's figure: thousands with commas.
func groupedUGX(amount int64) string {
	digits := strconv.FormatInt(amount, 10)
	neg := strings.HasPrefix(digits, "-")
	digits = strings.TrimPrefix(digits, "-")
	var out []string
	for len(digits) > 3 {
		out = append([]string{digits[len(digits)-3:]}, out...)
		digits = digits[:len(digits)-3]
	}
	out = append([]string{digits}, out...)
	if neg {
		return "-" + strings.Join(out, ",")
	}
	return strings.Join(out, ",")
}

// accountabilityInGo saves the drawer with Django absent.
func (s *Service) accountabilityInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, from activities.Origin) (
	*screensv1.SaveDrawerResponse, bool, error,
) {
	principal, ok := auth.PrincipalFrom(ctx)
	if !ok || s.accountant == nil || s.existingApp != nil {
		return nil, false, nil
	}
	path, _, _ := strings.Cut(message.GetPath(), "?")
	m := accountabilityPath.FindStringSubmatch(path)
	if m == nil {
		return nil, false, nil
	}
	v := message.GetValues()
	saved, err := s.accountant.SubmitAccountability(ctx, principal, m[1], activities.AccountabilityForm{
		Spent: v["amount_spent"], Returned: v["amount_returned"], VarianceNote: v["variance_note"],
		NetsuiteCode: v["netsuite_code"], ReceiptID: v["receipt_file"],
	}, from)
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(refusal.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go accountability failed before it was made", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(saved.Message)}, true, nil
}
