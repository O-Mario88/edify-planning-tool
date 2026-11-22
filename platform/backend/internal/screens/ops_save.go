package screens

import (
	"context"
	"errors"
	"regexp"
	"strconv"
	"strings"
	"time"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/fieldops"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/financeops"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workforceops"
)

var (
	reIADecide             = regexp.MustCompile(`^/ia/(?:verification|activities)/([A-Za-z0-9_-]+)/decide/?$`)
	reSSADecide            = regexp.MustCompile(`^/ssa/records/([A-Za-z0-9_-]+)/decide/?$`)
	rePartnerDate          = regexp.MustCompile(`^/partner/assignments/([A-Za-z0-9_-]+)/date/?$`)
	rePartnerReturn        = regexp.MustCompile(`^/partner/assignments/([A-Za-z0-9_-]+)/return/?$`)
	reWeeklyTransition     = regexp.MustCompile(`^/finance/weekly-requests/([A-Za-z0-9_-]+)/(approve_pl|approve_cd|disburse|return|confirm_receipt|submit_accountability)/?$`)
	reBudgetDecide         = regexp.MustCompile(`^/finance/monthly-budgets/([A-Za-z0-9_-]+)/decide/?$`)
	reAdvanceTransition    = regexp.MustCompile(`^/finance/advances/([A-Za-z0-9_-]+)/(disburse|confirm_receipt|submit_accountability|verify_return)/?$`)
	reLeaveDecide          = regexp.MustCompile(`^/(?:leave|hr/leave-approvals)/([A-Za-z0-9_-]+)/decide/?$`)
	reLeaveRequest         = regexp.MustCompile(`^/(?:personal-time-off|leave)/request/?$`)
	reEscalationDecide     = regexp.MustCompile(`^/escalations/([A-Za-z0-9_-]+)/decide/?$`)
	reEscalationRaise      = regexp.MustCompile(`^/escalations(?:/raise)?/?$`)
	reProfileEdit          = regexp.MustCompile(`^/profile/edit/?$`)
	reHelpFeedback         = regexp.MustCompile(`^/help/([A-Za-z0-9_-]+)/feedback/?$`)
	reTeamActionTransition = regexp.MustCompile(`^/actions/([A-Za-z0-9_-]+)/(acknowledge|start|block|return|cancel|escalate|resolve)/?$`)
)

// WithOpsSaves connects native Go FieldOps, FinanceOps, and WorkforceOps
// services to SaveDrawer so operational drawers execute in Go with zero Django
// fallback.
func (s *Service) WithOpsSaves(field *fieldops.Service, finance *financeops.Service, workforce *workforceops.Service) *Service {
	s.fieldOps = field
	s.financeOps = finance
	s.workforceOps = workforce
	return s
}

func (s *Service) opsInGo(ctx context.Context, req *screensv1.SaveDrawerRequest) (*screensv1.SaveDrawerResponse, bool, error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return nil, false, nil
	}
	rawPath := req.GetPath()
	if i := strings.IndexByte(rawPath, '?'); i >= 0 {
		rawPath = rawPath[:i]
	}
	vals := req.GetValues()

	if s.fieldOps != nil {
		if m := reIADecide.FindStringSubmatch(rawPath); m != nil {
			status, err := s.fieldOps.IADecideActivity(ctx, p, m[1], vals["decision"], vals["note"])
			return opsDrawerResult(ctx, status, "IA decision recorded.", err)
		}
		if m := reSSADecide.FindStringSubmatch(rawPath); m != nil {
			status, err := s.fieldOps.DecideSSA(ctx, p, m[1], vals["decision"], vals["reason"])
			return opsDrawerResult(ctx, status, "SSA decision recorded.", err)
		}
		if m := rePartnerDate.FindStringSubmatch(rawPath); m != nil {
			d, perr := time.Parse(time.DateOnly, strings.TrimSpace(vals["date"]))
			if perr != nil {
				return nil, true, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "Date must be YYYY-MM-DD.")
			}
			status, err := s.fieldOps.DatePartnerAssignment(ctx, p, m[1], d)
			return opsDrawerResult(ctx, status, "Partner activity dated.", err)
		}
		if m := rePartnerReturn.FindStringSubmatch(rawPath); m != nil {
			status, err := s.fieldOps.ReturnPartnerAssignment(ctx, p, m[1], vals["reason"])
			return opsDrawerResult(ctx, status, "Partner activity returned.", err)
		}
	}

	if s.financeOps != nil {
		if m := reWeeklyTransition.FindStringSubmatch(rawPath); m != nil {
			amt, _ := strconv.ParseInt(strings.TrimSpace(vals["amount"]), 10, 64)
			ret, _ := strconv.ParseInt(strings.TrimSpace(vals["returned"]), 10, 64)
			res, err := s.financeOps.TransitionWeeklyRequest(ctx, p, m[1], m[2], amt, ret, vals["method"], vals["reference"], vals["reason"])
			return opsDrawerResult(ctx, res.Status, "Weekly fund request updated.", err)
		}
		if m := reBudgetDecide.FindStringSubmatch(rawPath); m != nil {
			status, err := s.financeOps.DecideMonthlyBudget(ctx, p, m[1], vals["status"], vals["note"])
			return opsDrawerResult(ctx, status, "Monthly budget updated.", err)
		}
		if m := reAdvanceTransition.FindStringSubmatch(rawPath); m != nil {
			amt, _ := strconv.ParseInt(strings.TrimSpace(vals["amount"]), 10, 64)
			ret, _ := strconv.ParseInt(strings.TrimSpace(vals["returned"]), 10, 64)
			res, err := s.financeOps.TransitionAdvance(ctx, p, m[1], m[2], amt, ret, vals["method"], vals["reference"])
			return opsDrawerResult(ctx, res.Status, "Activity advance updated.", err)
		}
	}

	if s.workforceOps != nil {
		if m := reLeaveDecide.FindStringSubmatch(rawPath); m != nil {
			status, err := s.workforceOps.DecideLeave(ctx, p, m[1], vals["decision"], vals["note"])
			return opsDrawerResult(ctx, status, "Leave request updated.", err)
		}
		if reLeaveRequest.MatchString(rawPath) {
			_, err := s.workforceOps.RequestLeave(ctx, p, vals["leave_type"], vals["start_date"], vals["end_date"], vals["reason"], vals["handover_notes"])
			return opsDrawerResult(ctx, "pending", "Leave request submitted.", err)
		}
		if m := reEscalationDecide.FindStringSubmatch(rawPath); m != nil {
			status, err := s.workforceOps.DecideEscalation(ctx, p, m[1], vals["decision"], vals["note"])
			return opsDrawerResult(ctx, status, "Escalation updated.", err)
		}
		if reEscalationRaise.MatchString(rawPath) && (req.GetForm() == "raise" || strings.HasSuffix(strings.TrimSuffix(rawPath, "/"), "/raise")) {
			_, err := s.workforceOps.RaiseEscalation(ctx, p, vals["category"], vals["severity"], vals["subject"], vals["detail"], vals["requested_decision"], vals["due_date"])
			return opsDrawerResult(ctx, "open", "Escalation sent.", err)
		}
		if reProfileEdit.MatchString(rawPath) {
			err := s.workforceOps.UpdateOwnProfile(ctx, p, vals["name"], vals["phone"])
			return opsDrawerResult(ctx, "saved", "Profile updated.", err)
		}
		if m := reHelpFeedback.FindStringSubmatch(rawPath); m != nil {
			helpful := strings.EqualFold(strings.TrimSpace(vals["helpful"]), "true") || vals["helpful"] == "1"
			_, err := s.workforceOps.RecordHelpFeedback(ctx, p, m[1], helpful, vals["feedback_type"], vals["comment"], vals["page_context"])
			return opsDrawerResult(ctx, "saved", "Feedback recorded.", err)
		}
		if m := reTeamActionTransition.FindStringSubmatch(rawPath); m != nil {
			status, err := s.workforceOps.TransitionTeamAction(ctx, p, m[1], m[2], vals["reason"])
			return opsDrawerResult(ctx, status, "Action updated.", err)
		}
	}

	return nil, false, nil
}

func opsDrawerResult(ctx context.Context, status, msg string, err error) (*screensv1.SaveDrawerResponse, bool, error) {
	if err != nil {
		switch {
		case errors.Is(err, fieldops.ErrForbidden), errors.Is(err, fieldops.ErrQuarantined),
			errors.Is(err, financeops.ErrForbidden), errors.Is(err, workforceops.ErrForbidden):
			return nil, true, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied, err.Error())
		case errors.Is(err, fieldops.ErrInvalidInput), errors.Is(err, financeops.ErrInvalidInput),
			errors.Is(err, workforceops.ErrInvalidInput):
			return nil, true, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, err.Error())
		default:
			return nil, true, apierr.New(ctx, connect.CodeInternal, apierr.ReasonInternal, err.Error())
		}
	}
	if status != "" && status != "saved" {
		msg = msg + " (" + status + ")"
	}
	return &screensv1.SaveDrawerResponse{
		Saved:   true,
		Message: msg,
	}, true, nil
}
