package activities

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// The Salesforce ID drawer (my_plan_views.salesforce_id_action) for an
// officer's own staff school visit (a cluster session: salesforce_session.go): the ID is reserved and the visit handed
// in with it (services.hand_in_with_id), whatever day it was planned for.
// Unlike the Complete drawer it carries no attendance or notes, and writes
// no complete_activity row.

// salesforceEntryFields are the drawer's own fields.
var salesforceEntryFields = []string{"csrfmiddlewaretoken", "salesforce_id", "actual_delivery_date", "verification_note"}

// handInStatuses are hand_in_with_id's STARTABLE_STATUSES and
// SUBMITTABLE_STATUSES for a staff visit Go hands in.
var handInStartable = []string{"scheduled", "rescheduled"}

const salesforceIDMissing = "Error: SF ID cannot be blank."

// EnterSalesforceID saves the ID and hands the visit in, or refuses it in
// the existing words, or hands it on (ErrHandOn).
func (s *Service) EnterSalesforceID(ctx context.Context, p auth.Principal, activityID string, form url.Values, origin Origin) (CompleteAnswer, error) {
	for name, values := range form {
		if !slices.Contains(salesforceEntryFields, name) && slices.ContainsFunc(values, func(v string) bool { return strings.TrimSpace(v) != "" }) {
			return CompleteAnswer{}, handOn("the drawer posted " + name)
		}
	}
	session, err := readCompletedMeeting(ctx, s.db, strings.TrimSpace(activityID))
	if err != nil {
		return CompleteAnswer{}, err
	}
	if session != nil {
		m, err := s.meetingInCase(ctx, p, session.id)
		if err != nil {
			return CompleteAnswer{}, err
		}
		if m == nil {
			return CompleteAnswer{}, handOn("the session is no longer there")
		}
		return s.enterSessionID(ctx, p, m, form, origin)
	}
	if p.InActingAppointment || p.StaffProfileID == "" || p.ActiveRole != officerRole || slices.Contains(p.Roles, programmeLeadRole) {
		return CompleteAnswer{}, handOn("not an officer entering their own visit's ID")
	}
	a, err := readCompletedVisit(ctx, s.db, strings.TrimSpace(activityID))
	if err != nil {
		return CompleteAnswer{}, err
	}
	switch {
	case a == nil:
		return CompleteAnswer{}, handOn("not a staff school visit with a school and a day")
	case a.other:
		return CompleteAnswer{}, handOn("a visit in a cluster, a project, a pair or a partner's hands, or a OneTest visit")
	case !ownsVisit(p, a.responsible):
		return CompleteAnswer{}, handOn("someone else's visit")
	case a.status != startedStatus && !in(handInStartable, a.status):
		return CompleteAnswer{}, handOn("a visit in status " + a.status)
	case in(completionPurposes, a.purpose) || a.collectsSSA:
		return CompleteAnswer{}, handOn("a visit whose purpose the drawer decides, or one collecting the SSA")
	case a.verification == confirmedVerification:
		return CompleteAnswer{}, handOn("a visit IA has confirmed")
	case !in(visitRecordTypes, strings.ToUpper(a.recordType)) || a.costing == onetestCostingProfile:
		return CompleteAnswer{}, handOn("a visit kept under another Salesforce record type, or a OneTest visit")
	case a.salesforceID != "":
		return CompleteAnswer{}, handOn("a visit that already holds a Salesforce ID")
	}
	now := s.now()
	if err := s.ownVisitSchool(ctx, p, a.schoolID, now); err != nil {
		return CompleteAnswer{}, err
	}
	pl := &completionPlan{p: p, a: *a, origin: origin, now: now, raw: pyStrip(form.Get("salesforce_id"))}
	if pl.raw == "" {
		return CompleteAnswer{}, refuse(salesforceIDMissing)
	}
	if pl.delivered, err = s.completedOn(form.Get("actual_delivery_date")); err != nil {
		return CompleteAnswer{}, err
	}
	if !sameDay(pl.delivered, a.plannedDate) {
		return CompleteAnswer{}, handOn("done on another day than planned: the work and its money move")
	}
	if err := s.judgeSalesforceID(pl); err != nil {
		return CompleteAnswer{}, err
	}
	if err := s.writeSalesforceEntry(ctx, pl); err != nil {
		return CompleteAnswer{}, err
	}
	if follower, ok := s.pricing.(CompletionFollower); ok {
		if err := follower.HandedIn(ctx, a.id, p.UserID, p.ActiveRole); err != nil {
			s.logger.Warn("activities: the hand-in's notices were not sent", "activity", a.id, "err", err)
		}
	}
	if in(rules.LedgerCreditedTypes, a.activityType) {
		if err := s.markOwnerYears(ctx, a.responsible, a.plannedDate); err != nil {
			s.logger.Warn("activities: the target ledger was not marked", "activity", a.id, "err", err)
		}
	}
	return CompleteAnswer{ActivityID: a.id, Status: handedInStatus, Message: rules.Move.SavedMessage}, nil
}

// writeSalesforceEntry is reserve_salesforce_id and hand_in_with_id in one
// transaction: a visit not yet started is started first (start_completion),
// then handed in with the ID, its attendance and notes left as they stand.
func (s *Service) writeSalesforceEntry(ctx context.Context, pl *completionPlan) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("activities: opening the ID's entry: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if in(handInStartable, pl.a.status) {
		var started bool
		if err := tx.QueryRow(ctx, `SELECT gateway_completion.start_visit($1, $2)`, pl.a.id, pl.now).Scan(&started); err != nil {
			return fmt.Errorf("activities: starting the visit: %w", err)
		}
		if !started {
			return handOn("the visit could not be started")
		}
	}
	var answer string
	err = tx.QueryRow(ctx, `SELECT gateway_completion.hand_in_with_id($1, $2, $3, $4, $5, $6, $7, $8)`,
		pl.a.id, pl.delivered, pl.raw, pl.normalized, pl.p.UserID, pl.now, cuid.New(), cuid.New()).Scan(&answer)
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == uniqueViolation {
		return refuse("%s", salesforceTakenRefusal)
	}
	if err != nil {
		return fmt.Errorf("activities: handing the visit in: %w", err)
	}
	if holder, held := strings.CutPrefix(answer, "held:"); held {
		message, err := takenBy(ctx, tx, holder)
		if err != nil {
			return err
		}
		return refuse("%s", message)
	}
	if answer != "" {
		return handOn("the hand-in met " + answer)
	}
	if err := s.appendSalesforceRow(ctx, tx, pl); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("activities: committing the ID's entry: %w", err)
	}
	return nil
}
