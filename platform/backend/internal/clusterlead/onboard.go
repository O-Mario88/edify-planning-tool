package clusterlead

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"connectrpc.com/connect"

	clustersv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/clusters/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trace"
)

// Onboarding a Cluster Leader (owner, 2026-11-11: "add cluster leader user
// category so the staff can onboard them"). The existing application writes
// the account (apps/clusters/leader_onboarding.py: the Cluster Leader role
// alone, an invitation, no staff profile), as the signed-in person; this
// gateway applies the cluster policy first and then gives the leader the
// cluster. The gateway never writes the existing "user" table itself.

// OnboardInput is what the person onboarding a leader enters.
type OnboardInput struct {
	Name, Email, Phone string
}

// Onboarded is the existing application's answer.
type Onboarded struct {
	UserID   string
	Existing bool
	// Only when email cannot reach the leader.
	InviteToken string
}

// Onboarder creates (or finds) a leader's account in the existing application.
type Onboarder interface {
	Onboard(ctx context.Context, clusterID string, in OnboardInput) (Onboarded, error)
}

// ErrOnboardingUnavailable: no existing application is configured, or it did not answer.
var ErrOnboardingUnavailable = errors.New("clusterlead: onboarding is not reachable")

// OnboardRefusal is the existing application refusing, with its reason.
type OnboardRefusal struct {
	Status  int
	Message string
}

func (e *OnboardRefusal) Error() string { return e.Message }

const (
	maxNameLength  = 200
	maxEmailLength = 254
	maxPhoneLength = 40
)

// WithOnboarder sets how accounts are made, and the existing application's
// address for the set-password link.
func (s *Service) WithOnboarder(o Onboarder, appBaseURL string) *Service {
	s.onboarder, s.appBaseURL = o, strings.TrimRight(appBaseURL, "/")
	return s
}

// OnboardLeader makes a Cluster Leader account and gives it the cluster.
func (s *Service) OnboardLeader(
	ctx context.Context, request *connect.Request[clustersv1.OnboardLeaderRequest],
) (*connect.Response[clustersv1.OnboardLeaderResponse], error) {
	msg := request.Msg
	principal, cluster, err := s.administered(ctx, msg.GetClusterId())
	if err != nil {
		return nil, err
	}
	in := OnboardInput{Name: strings.TrimSpace(msg.GetName()), Email: strings.TrimSpace(msg.GetEmail()), Phone: strings.TrimSpace(msg.GetPhone())}
	switch {
	case in.Name == "" || in.Email == "":
		return nil, invalid(ctx, "Enter the leader's name and email: the invitation goes to the email.")
	case len(in.Name) > maxNameLength || len(in.Email) > maxEmailLength || len(in.Phone) > maxPhoneLength:
		return nil, invalid(ctx, "The name, email or phone number is too long.")
	}
	reason, err := reasonOf(ctx, msg.GetReason())
	if err != nil {
		return nil, err
	}
	if s.onboarder == nil {
		return nil, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "Onboarding is not available on this server.")
	}
	made, err := s.onboarder.Onboard(ctx, cluster.ID, in)
	var refusal *OnboardRefusal
	switch {
	case errors.As(err, &refusal) && refusal.Status == http.StatusConflict:
		return nil, apierr.New(ctx, connect.CodeAlreadyExists, apierr.ReasonInvalidArgument, refusal.Message)
	case errors.As(err, &refusal) && refusal.Status == http.StatusForbidden:
		return nil, notAdministrator(ctx)
	case errors.As(err, &refusal):
		return nil, invalid(ctx, refusal.Message)
	case errors.Is(err, ErrOnboardingUnavailable):
		return nil, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "The account service did not answer. Nothing was created; try again.")
	case err != nil:
		return nil, s.internal(ctx, err)
	}
	account, err := s.data.InvitedLeader(ctx, made.UserID)
	if errors.Is(err, ErrNotFound) {
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
			"That account cannot lead a cluster: it is not a Cluster Leader account, or it is disabled.")
	}
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	response := &clustersv1.OnboardLeaderResponse{ExistingAccount: made.Existing}
	if made.InviteToken != "" && s.appBaseURL != "" {
		response.InviteLink = s.appBaseURL + "/set-password?token=" + url.QueryEscape(made.InviteToken)
	}
	id, err := newID()
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	err = s.data.CreateAssignment(ctx, NewAssignment{ID: id, ClusterID: cluster.ID, UserID: account.UserID,
		StartsOn: s.today(), ActorID: principal.UserID, Reason: reason})
	if errors.Is(err, ErrAlreadyAssigned) {
		response.AlreadyLeading = true
		assignments, err := s.data.ClusterAssignments(ctx, cluster.ID)
		if err != nil {
			return nil, s.internal(ctx, err)
		}
		for _, a := range assignments {
			if a.UserID == account.UserID && a.Status != "ended" {
				response.Assignment = toAssignment(a)
				break
			}
		}
		return connect.NewResponse(response), nil
	}
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	created, err := s.data.Assignment(ctx, id)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	response.Assignment = toAssignment(created)
	return connect.NewResponse(response), nil
}

// HTTPOnboarder asks the existing application to make the account, as the
// signed-in person (their bearer token), so it checks them too.
type HTTPOnboarder struct {
	base string
	http *http.Client
}

// NewHTTPOnboarder returns an onboarder for the existing application at
// base; nil when base is empty (no existing application on this server).
func NewHTTPOnboarder(base string) Onboarder {
	if strings.TrimSpace(base) == "" {
		return nil
	}
	return &HTTPOnboarder{base: strings.TrimRight(base, "/"), http: &http.Client{Timeout: 20 * time.Second}}
}

// Onboard posts to /api/clusters/{id}/leaders.
func (h *HTTPOnboarder) Onboard(ctx context.Context, clusterID string, in OnboardInput) (Onboarded, error) {
	payload, err := json.Marshal(map[string]string{"name": in.Name, "email": in.Email, "phone": in.Phone})
	if err != nil {
		return Onboarded{}, err
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost,
		h.base+"/api/clusters/"+url.PathEscape(clusterID)+"/leaders", bytes.NewReader(payload))
	if err != nil {
		return Onboarded{}, err
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("Accept", "application/json")
	request.Header.Set("Authorization", "Bearer "+auth.BearerFrom(ctx))
	if span := trace.FromContext(ctx); span.RequestID != "" {
		request.Header.Set(trace.HeaderRequestID, span.RequestID)
	}
	response, err := h.http.Do(request)
	if err != nil {
		return Onboarded{}, fmt.Errorf("%w: %v", ErrOnboardingUnavailable, err)
	}
	defer func() { _ = response.Body.Close() }()
	raw, _ := io.ReadAll(io.LimitReader(response.Body, 1<<16))
	if response.StatusCode >= 500 {
		return Onboarded{}, fmt.Errorf("%w: status %d", ErrOnboardingUnavailable, response.StatusCode)
	}
	var answer struct {
		User struct {
			ID string `json:"id"`
		} `json:"user"`
		Existing    bool    `json:"existing"`
		InviteToken *string `json:"inviteToken"`
		Message     string  `json:"message"`
		Detail      string  `json:"detail"`
	}
	_ = json.Unmarshal(raw, &answer)
	if response.StatusCode >= 300 {
		message := answer.Message
		if message == "" {
			message = answer.Detail
		}
		if message == "" {
			message = "The account could not be created."
		}
		return Onboarded{}, &OnboardRefusal{Status: response.StatusCode, Message: message}
	}
	if answer.User.ID == "" {
		return Onboarded{}, errors.New("clusterlead: onboarding answered without an account id")
	}
	out := Onboarded{UserID: answer.User.ID, Existing: answer.Existing}
	if answer.InviteToken != nil {
		out.InviteToken = *answer.InviteToken
	}
	return out, nil
}
