package screens

import (
	"context"
	"errors"
	"log/slog"
	"strings"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerassigned"
)

// A partner login's Cancel drawer and save on its own work, with Django
// absent (my_plan_views.cancel_activity_drawer_view and
// cancel_activity_action for the partner): a team member is refused
// (_member_may_not_cancel), work that is not the organisation's is not
// theirs to open (can_view_record), and the rest is the drawer and the
// cancel the activities package makes.

const (
	partnerMemberCancelRefusal = "Only your organisation's Partner Admin cancels its work."
	partnerCancelDenied        = "Access Denied."
	// partnerWorkMissing is the view's 404, which the feed reads as the
	// drawer not being available.
	partnerWorkMissing = "This drawer is not available."
)

// PartnerCanceller is the partner's cancel (internal/activities.Service).
type PartnerCanceller interface {
	CancelPartnerWork(ctx context.Context, p auth.Principal, req activities.PartnerCancelRequest, origin activities.Origin) (activities.CancelAnswer, error)
	RecordCancelDenied(ctx context.Context, p auth.Principal, activityID string, origin activities.Origin) error
}

// WithPartnerCancel makes the partner's own cancel Go's with Django absent.
func (s *Service) WithPartnerCancel(c PartnerCanceller) *Service {
	s.partnerCancel = c
	return s
}

// partnerDoor is the partner login's answer for one activity: its
// organisations, a refusal in the existing words, or false when the
// request is not a partner's (or not one Go takes).
func (s *Service) partnerDoor(ctx context.Context, p auth.Principal, id string) (partners []string, refusal string, ok bool, err error) {
	if s.existingApp != nil || p.InActingAppointment || s.db == nil {
		return nil, "", false, nil
	}
	if partners, err = partnerassigned.PartnerIDs(ctx, s.db, p); err != nil || len(partners) == 0 {
		return nil, "", false, err
	}
	member, err := partnerassigned.IsTeamMember(ctx, s.db, p)
	if err != nil {
		return nil, "", false, err
	}
	if member {
		return partners, partnerMemberCancelRefusal, true, nil
	}
	var theirs, found bool
	if err := s.db.QueryRow(ctx, `SELECT true, COALESCE(assigned_partner_id = ANY($2), false) FROM activity
WHERE id = $1 AND deleted_at IS NULL`, id, partners).Scan(&found, &theirs); errors.Is(err, pgx.ErrNoRows) {
		return partners, partnerWorkMissing, true, nil
	} else if err != nil {
		return nil, "", false, err
	}
	if !theirs {
		return partners, partnerCancelDenied, true, nil
	}
	return partners, "", true, nil
}

// partnerCancelDrawerInGo is the partner's Cancel drawer.
func (s *Service) partnerCancelDrawerInGo(ctx context.Context, p auth.Principal, pathOnly string) (*screensv1.GetDrawerResponse, bool, error) {
	drawers, ok := s.planDrawers.(interface {
		PartnerCancelDrawer(ctx context.Context, id string) (*screensv1.PageDrawer, error)
	})
	m := cancelDrawer.FindStringSubmatch(strings.TrimSpace(pathOnly))
	if !ok || m == nil || s.partnerCancel == nil {
		return nil, false, nil
	}
	_, refusal, taken, err := s.partnerDoor(ctx, p, m[1])
	if err != nil || !taken {
		return nil, err != nil, err
	}
	if refusal == partnerWorkMissing {
		return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, partnerWorkMissing)
	}
	if refusal != "" {
		return &screensv1.GetDrawerResponse{Refusal: refusal}, true, nil
	}
	d, err := drawers.PartnerCancelDrawer(ctx, m[1])
	switch {
	case errors.Is(err, myplan.ErrDetailHandOn):
		return nil, false, nil
	case err != nil:
		return nil, true, err
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

// partnerCancelInGo is the partner's cancel, posted from the drawer.
func (s *Service) partnerCancelInGo(ctx context.Context, message *screensv1.SaveDrawerRequest) (*screensv1.SaveDrawerResponse, bool, error) {
	p, signed := auth.PrincipalFrom(ctx)
	m := cancelDrawer.FindStringSubmatch(message.GetPath())
	if !signed || m == nil || s.partnerCancel == nil {
		return nil, false, nil
	}
	partners, refusal, taken, err := s.partnerDoor(ctx, p, m[1])
	if err != nil || !taken {
		return nil, err != nil, err
	}
	if refusal != "" {
		if refusal == partnerCancelDenied {
			// The view's own refusal of a save names the action, and writes
			// its row.
			refusal = "Access Denied: You do not have permission to cancel this activity."
			if err := s.partnerCancel.RecordCancelDenied(ctx, p, m[1], activities.Origin{}); err != nil && s.logger != nil {
				s.logger.WarnContext(ctx, "the refused cancel's audit row was not written", slog.String("error", err.Error()))
			}
		}
		return &screensv1.SaveDrawerResponse{Saved: false, Error: refusal}, true, nil
	}
	form := directDrawerForm(message)
	cancelled, err := s.partnerCancel.CancelPartnerWork(ctx, p, activities.PartnerCancelRequest{
		ActivityID: m[1], Reason: strings.TrimSpace(form.Get("reason")), PartnerIDs: partners}, activities.Origin{})
	var r *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		return nil, false, nil
	case errors.As(err, &r):
		return &screensv1.SaveDrawerResponse{Saved: false, Error: collapse(cancelErrorTitle + r.Message)}, true, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go partner cancel failed", slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: collapse(cancelled.Message) + " " + toastClose}, true, nil
}
