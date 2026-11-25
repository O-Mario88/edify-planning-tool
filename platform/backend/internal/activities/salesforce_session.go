package activities

// The Salesforce ID drawer (my_plan_views.salesforce_id_action) on an
// officer's own staff cluster session: the TS- ID reserved, then
// hand_in_with_id. With its head count recorded the session passes Submit's
// gates and is handed in as Submit hands it in (the lead told, the work moved
// to the day it was done). Without one Submit refuses it ("Training
// completion requires attendance"), and the view hands it in through
// hand_in_entered_work, which tells nobody and moves nothing: the drawer
// closes with "Saved and sent to your Programme Lead to approve". The case
// is the meeting completion's (meetingInCase); a group training a Core school
// takes a place at is handed on, its package credit not yet Go's.

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// sentToLeadMessage is _sent_to_lead's toast for what Submit found missing.
const sentToLeadMessage = "Saved and sent to your Programme Lead to approve. They will see what is still missing: " +
	trainingAttendanceAsked

// futureDayRefusal is completed_day.FUTURE_DAY.
const futureDayRefusal = "The completion date cannot be in the future."

// sessionCompletedOn is completion_day as the view asks it: a day after
// today is refused in its words; the rest as the Complete drawer reads it.
func (s *Service) sessionCompletedOn(raw string) (time.Time, error) {
	if stripped := pyStrip(raw); isoDate.MatchString(stripped) {
		now := s.now().In(s.kampala)
		today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
		if day, err := time.Parse(time.DateOnly, stripped); err == nil && day.After(today) {
			return time.Time{}, refuse("%s", futureDayRefusal)
		}
	}
	return s.completedOn(raw)
}

// sessionHeadCount is what the session holds of its attendance.
type sessionHeadCount struct {
	counted  bool
	attended []string
}

// enterSessionID is EnterSalesforceID for a cluster session Go takes.
func (s *Service) enterSessionID(ctx context.Context, p auth.Principal, m *completedMeeting, form url.Values, origin Origin) (CompleteAnswer, error) {
	for name, values := range form {
		if !slices.Contains(salesforceEntryFields, name) && slices.ContainsFunc(values, func(v string) bool { return strings.TrimSpace(v) != "" }) {
			return CompleteAnswer{}, handOn("the drawer posted " + name)
		}
	}
	pl := &completionPlan{
		p: p, origin: origin, now: s.now(), sessions: true, raw: pyStrip(form.Get("salesforce_id")),
		a: completedVisit{id: m.id, activityType: m.kind, status: m.status, responsible: m.responsible,
			plannedDate: *m.planned},
	}
	if pl.raw == "" {
		return CompleteAnswer{}, refuse(salesforceIDMissing)
	}
	var err error
	if pl.delivered, err = s.sessionCompletedOn(form.Get("actual_delivery_date")); err != nil {
		return CompleteAnswer{}, err
	}
	if err := s.judgeTrainingID(pl); err != nil {
		return CompleteAnswer{}, err
	}
	count, err := readSessionHeadCount(ctx, s.db, m.id)
	if err != nil {
		return CompleteAnswer{}, err
	}
	if m.kind == clusterTrainingType {
		if err := s.noCoreSchoolCredited(ctx, m, count.attended); err != nil {
			return CompleteAnswer{}, err
		}
	}
	if count.counted && !sameDay(pl.delivered, pl.a.plannedDate) {
		// Only Submit's hand-in moves the work to the day it was done.
		if pl.done, err = s.prepareDoneDay(ctx, pl, true); err != nil {
			return CompleteAnswer{}, err
		}
	}
	if err := s.writeSessionID(ctx, pl, count.counted); err != nil {
		return CompleteAnswer{}, err
	}
	if count.counted {
		s.afterDoneDay(ctx, pl)
		if follower, ok := s.pricing.(CompletionFollower); ok {
			if err := follower.HandedIn(ctx, m.id, p.UserID, p.ActiveRole); err != nil {
				s.logger.Warn("activities: the hand-in's notices were not sent", "activity", m.id, "err", err)
			}
		}
	}
	if in(rules.LedgerCreditedTypes, m.kind) {
		days := []time.Time{pl.a.plannedDate}
		if pl.done != nil && pl.done.move != nil {
			days = append(days, pl.done.move.newDay)
		}
		if err := s.markOwnerYears(ctx, m.responsible, days...); err != nil {
			s.logger.Warn("activities: the target ledger was not marked", "activity", m.id, "err", err)
		}
	}
	if count.counted {
		s.settleDoneDay(ctx, pl.done)
		return CompleteAnswer{ActivityID: m.id, Status: handedInStatus, Message: rules.Move.SavedMessage}, nil
	}
	return CompleteAnswer{ActivityID: m.id, Status: handedInStatus, Message: sentToLeadMessage}, nil
}

// readSessionHeadCount reads whether Submit's attendance gate passes and the
// register the package credit would read.
func readSessionHeadCount(ctx context.Context, q Querier, id string) (sessionHeadCount, error) {
	var c sessionHeadCount
	err := q.QueryRow(ctx, `SELECT COALESCE(teachers_attended, 0) > 0 OR COALESCE(leaders_attended, 0) > 0,
       COALESCE(attended_school_ids, '{}') FROM activity WHERE id = $1`, id).Scan(&c.counted, &c.attended)
	if err != nil {
		return c, fmt.Errorf("activities: reading the session's head count: %w", err)
	}
	return c, nil
}

// writeSessionID is the reservation and the hand-in in one transaction,
// with the reservation's audit row.
func (s *Service) writeSessionID(ctx context.Context, pl *completionPlan, counted bool) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("activities: opening the session's ID entry: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var answer string
	err = tx.QueryRow(ctx, `SELECT gateway_completion.hand_in_session_with_id($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
		pl.a.id, pl.delivered, pl.raw, pl.normalized, counted, pl.p.UserID, pl.now, cuid.New(), cuid.New()).Scan(&answer)
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == uniqueViolation {
		return refuse("%s", salesforceTakenRefusal)
	}
	if err != nil {
		return fmt.Errorf("activities: handing the session in: %w", err)
	}
	if holder, held := strings.CutPrefix(answer, "held:"); held {
		message, err := takenBy(ctx, tx, holder)
		if err != nil {
			return err
		}
		return refuse("%s", message)
	}
	if answer != "" {
		return handOn("the session's hand-in met " + answer)
	}
	if err := s.appendSalesforceRow(ctx, tx, pl); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("activities: committing the session's ID entry: %w", err)
	}
	return nil
}
