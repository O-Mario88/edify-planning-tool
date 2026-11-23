package activities

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The Programme Accountant's visit waits for the school owner's yes
// (apps.planning.visit_requests).
const (
	awaitingOwnerApproval = "awaiting_owner_approval"
	justificationRequired = "Explain why you need to visit this school. The request goes to the school's owner, who decides on it."
	visitRequestedEvent   = "school_visit_requested"
	visitRequestQueue     = "/planning/visit-requests"
	requestQueueLabel     = "Open the request queue"
	decideRequestLabel    = "Decide on Visit Request"
	activityCategory      = "activity"
	activitySubject       = "Activity"
	schoolOwnerStandIn    = "the school's owner"
	schoolCCEOStandIn     = "the school's CCEO"
)

// VisitRequests answers whose approval a requester's visit needs: the
// profile to ask, or the sentence refusing the school.
type VisitRequests interface {
	VisitRequestOwner(ctx context.Context, p auth.Principal, code string) (owner, refusal string, err error)
	// OperationalRefusal is get_operational_school_or_404: the sentence
	// refusing the school, and whether there is such a school.
	OperationalRefusal(ctx context.Context, p auth.Principal, code string) (refusal string, found bool, err error)
}

// WithVisitRequests lets Go make the Accountant's visit requests.
func (s *Service) WithVisitRequests(requests VisitRequests) *Service {
	s.requests = requests
	return s
}

// visitTarget is where a visit goes and whose it is. A set approvalOwner makes
// it a request that person decides on.
type visitTarget struct {
	school                     school
	responsible, approvalOwner string
	// core is the Core package the visit counts against, if any.
	core *coreBooking
}

// requestTarget is the view's school for a requester. A school nobody owns
// has nobody to ask, so the visit would be scheduled outright: handed on.
func (s *Service) requestTarget(ctx context.Context, p auth.Principal, schoolID, purpose string, now time.Time) (*visitTarget, error) {
	sc, _, err := s.targetSchool(ctx, p, schoolID, purpose, now)
	if err != nil {
		return nil, err
	}
	owner, refusal, err := s.requests.VisitRequestOwner(ctx, p, sc.Code)
	if err != nil {
		return nil, fmt.Errorf("activities: reading whose approval the visit needs: %w", err)
	}
	if refusal != "" {
		return nil, &Refusal{Message: refusal, Forbidden: true}
	}
	if owner == "" {
		return nil, handOn("a requester's visit with nobody to ask")
	}
	return &visitTarget{school: *sc, responsible: p.StaffProfileID, approvalOwner: owner}, nil
}

// requestEntitlement is assert_outreach_activity_allowed, the part of the
// entitlement every visit meets: the rest waits for the owner's approval.
func requestEntitlement(sc school, activityType string) error {
	if !in(rules.Gate.OutreachOnlyTypes, sc.Type) || in(rules.Gate.OutreachActivityTypes, activityType) {
		return nil
	}
	label, ok := rules.Gate.SchoolTypeLabels[sc.Type]
	if !ok {
		label = "Programme"
	}
	return refuse("%s is a %s school: it receives no training or assessment, and is planned only for a Donor Visit or a Content/Story Collection visit.", sc.Name, label)
}

// requestedMessage is the view's confirmation of a request.
func requestedMessage(owner string) string {
	return fmt.Sprintf("Requested, pending %s's approval. It takes effect on your plan and enters your budget once approved.", owner)
}

// requestNotice is what notify_requested tells the owner.
func requestNotice(person, where, justification, owner string, day time.Time) scheduledNotice {
	if person == "" {
		person = "A staff member"
	}
	return scheduledNotice{
		title:       "Visit request for your school",
		body:        fmt.Sprintf("%s asks to visit %s on %s: %s", person, where, day.Format("2 Jan 2006"), justification),
		event:       visitRequestedEvent,
		category:    activityCategory,
		contextType: activitySubject,
		route:       visitRequestQueue,
		label:       decideRequestLabel,
		recipient:   owner,
	}
}

// tellRequestOwner is notify_requested: the request's audit row, then the
// owner's notice. Neither undoes the request, so the caller only logs a failure.
func (s *Service) tellRequestOwner(ctx context.Context, pl *plan) error {
	r := pl.row
	role := pl.p.ActiveRole
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("activities: opening the request's audit: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	now := s.now()
	cover, err := coverageStamp(ctx, tx, pl.p.UserID, now)
	if err != nil {
		return fmt.Errorf("activities: reading the actor's cover: %w", err)
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "visit_request_submitted", SubjectKind: audit.Text(activitySubject), SubjectID: audit.Text(r.id),
		ActorID: audit.Text(pl.p.UserID), ActorRole: &role, Reason: audit.Text(r.justification), Success: true,
		IPAddress: nilIfEmpty(pl.origin.IP), UserAgent: nilIfEmpty(pl.origin.UserAgent),
		CorrelationID: nilIfEmpty(pl.origin.CorrelationID),
		Payload: withStamps(map[string]any{
			"schoolId": r.schoolID, "activityType": r.activityType, "approvalOwnerId": r.approvalOwner,
		}, cover),
	}, now); err != nil {
		return fmt.Errorf("activities: auditing the request: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("activities: committing the request's audit: %w", err)
	}
	return s.deliverNotice(ctx, pl, requestNotice(pl.p.Name, pl.school.Name, r.justification, r.approvalOwner, r.plannedDate))
}
