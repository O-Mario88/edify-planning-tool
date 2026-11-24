package activities

import (
	"context"
	"fmt"
	"slices"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Start activity (my_plan_views.start_activity_action and
// services.start_completion) for an officer's own staff school visit.

// startableStatuses is services.STARTABLE_STATUSES.
var startableStatuses = []string{"scheduled", "in_progress", "partner_scheduled", "assigned_to_partner", "rescheduled"}

const notStartable = "Activity must be scheduled before completion can start."

// StartActivity starts the visit, or refuses it in the existing words, or
// hands it on (ErrHandOn).
func (s *Service) StartActivity(ctx context.Context, p auth.Principal, activityID, notes string, origin Origin) (Answer, error) {
	if p.InActingAppointment || p.StaffProfileID == "" || p.ActiveRole != officerRole || slices.Contains(p.Roles, programmeLeadRole) {
		return Answer{}, handOn("not an officer starting their own visit")
	}
	a, err := readCompletedVisit(ctx, s.db, strings.TrimSpace(activityID))
	if err != nil {
		return Answer{}, err
	}
	switch {
	case a == nil:
		return Answer{}, handOn("not a staff school visit with a school and a day")
	case a.other:
		return Answer{}, handOn("a visit in a cluster, a project, a pair or a partner's hands")
	case !ownsVisit(p, a.responsible):
		return Answer{}, handOn("someone else's visit")
	}
	now := s.now()
	if err := s.ownVisitSchool(ctx, p, a.schoolID, now); err != nil {
		return Answer{}, err
	}
	if !in(startableStatuses, a.status) {
		return Answer{}, refuse(notStartable)
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return Answer{}, fmt.Errorf("activities: opening the start: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var started bool
	if err := tx.QueryRow(ctx, `SELECT gateway_completion.start_visit($1, $2)`, a.id, now).Scan(&started); err != nil {
		return Answer{}, fmt.Errorf("activities: starting the visit: %w", err)
	}
	if !started {
		return Answer{}, refuse(notStartable)
	}
	if err := tx.Commit(ctx); err != nil {
		return Answer{}, fmt.Errorf("activities: committing the start: %w", err)
	}
	// The activity's save marks its owner's year for the ledger rebuild
	// (apps.targets.ledger_sync), as every activity save does.
	if err := s.markOwnerYears(ctx, a.responsible, a.plannedDate); err != nil {
		s.logger.Warn("activities: the start's ledger mark was not written", "activity", a.id, "err", err)
	}
	if err := s.auditStarted(ctx, p, a.id, strings.TrimSpace(notes), origin); err != nil {
		s.logger.Warn("activities: the start's audit row was not written", "activity", a.id, "err", err)
	}
	return Answer{ActivityID: a.id, Status: startedStatus, Message: rules.Move.SavedMessage}, nil
}

func (s *Service) auditStarted(ctx context.Context, p auth.Principal, activityID, notes string, origin Origin) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := coverageStamp(ctx, tx, p.UserID, s.now())
	if err != nil {
		return err
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "start_activity", SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(activityID),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true,
		Reason:    audit.Text("Activity execution started"),
		IPAddress: nilIfEmpty(origin.IP), UserAgent: nilIfEmpty(origin.UserAgent), CorrelationID: nilIfEmpty(origin.CorrelationID),
		Payload: withStamps(map[string]any{"notes": notes}, cover),
	}, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
