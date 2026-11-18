package clusterlead

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// Action items, requests to staff, and the counts the Home and the report
// are made of.

const selectItem = `
SELECT a.id::text, a.cluster_id, COALESCE(a.activity_id, ''), a.title, COALESCE(a.owner_school_id, ''),
       CASE WHEN a.owner_school_id IS NOT NULL THEN COALESCE(s.name, '') ELSE a.owner_name END,
       a.status, a.due_on
FROM cluster_leadership.action_item a
LEFT JOIN school s ON s.id = a.owner_school_id`

func scanItem(row pgx.CollectableRow) (Item, error) {
	var i Item
	err := row.Scan(&i.ID, &i.ClusterID, &i.ActivityID, &i.Title, &i.OwnerSchoolID, &i.Owner, &i.Status, &i.DueOn)
	return i, err
}

// Items is the cluster's action items: open ones first, by due date.
func (s *Store) Items(ctx context.Context, clusterID string, openOnly bool) ([]Item, error) {
	rows, err := s.db.Query(ctx, selectItem+`
WHERE a.cluster_id = $1 AND (NOT $2 OR a.status = 'open')
ORDER BY (a.status <> 'open'), a.due_on NULLS LAST, a.created_at`, clusterID, openOnly)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading action items: %w", err)
	}
	return pgx.CollectRows(rows, scanItem)
}

// ItemByID is one action item with its history.
func (s *Store) ItemByID(ctx context.Context, id string) (Item, error) {
	rows, err := s.db.Query(ctx, selectItem+` WHERE a.id::text = $1`, id)
	if err != nil {
		return Item{}, fmt.Errorf("clusterlead: reading an action item: %w", err)
	}
	item, err := pgx.CollectOneRow(rows, scanItem)
	if errors.Is(err, pgx.ErrNoRows) {
		return Item{}, ErrNotFound
	}
	if err != nil {
		return Item{}, err
	}
	item.History, err = s.history(ctx, "action_item_event", "action_item_id", id)
	return item, err
}

// SaveItem writes a new or edited open action item with its event.
func (s *Store) SaveItem(ctx context.Context, i Item, ownerName string, isNew bool, actorID string) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		var err error
		event := "updated"
		if isNew {
			event = "created"
			_, err = tx.Exec(ctx, `
INSERT INTO cluster_leadership.action_item
  (id, cluster_id, activity_id, title, owner_school_id, owner_name, due_on, status, created_by, country_code)
VALUES ($1, $2, $3, $4, $5, $6, $7, 'open', $8, `+registry.ClusterCountryCode("$2")+`)`,
				i.ID, i.ClusterID, nullable(i.ActivityID), i.Title, nullable(i.OwnerSchoolID), ownerName, i.DueOn, actorID)
		} else {
			tag, updateErr := tx.Exec(ctx, `
UPDATE cluster_leadership.action_item
SET title = $2, owner_school_id = $3, owner_name = $4, due_on = $5
WHERE id::text = $1 AND status = 'open'`, i.ID, i.Title, nullable(i.OwnerSchoolID), ownerName, i.DueOn)
			err = updateErr
			if err == nil && tag.RowsAffected() == 0 {
				return ErrNotLive
			}
		}
		if err != nil {
			return fmt.Errorf("clusterlead: saving an action item: %w", err)
		}
		return appendTo(ctx, tx, "action_item_event", "action_item_id", i.ID, event, actorID, "")
	})
}

// CloseItem marks an open item done or cancelled.
func (s *Store) CloseItem(ctx context.Context, id, status, note, actorID string) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `
UPDATE cluster_leadership.action_item SET status = $2, closed_by = $3, closed_at = now()
WHERE id::text = $1 AND status = 'open'`, id, status, actorID)
		if err != nil {
			return fmt.Errorf("clusterlead: closing an action item: %w", err)
		}
		if tag.RowsAffected() == 0 {
			return ErrNotLive
		}
		return appendTo(ctx, tx, "action_item_event", "action_item_id", id, status, actorID, note)
	})
}

const selectRequest = `
SELECT r.id::text, r.cluster_id, r.subject, r.body, r.status, COALESCE(asker.name, ''), r.created_at,
       r.answer, COALESCE(answerer.name, ''), r.answered_at
FROM cluster_leadership.leader_request r
LEFT JOIN "user" asker ON asker.id = r.created_by
LEFT JOIN "user" answerer ON answerer.id = r.answered_by`

func scanRequest(row pgx.CollectableRow) (Request, error) {
	var r Request
	err := row.Scan(&r.ID, &r.ClusterID, &r.Subject, &r.Body, &r.Status, &r.AskedBy, &r.AskedAt,
		&r.Answer, &r.AnsweredBy, &r.AnsweredAt)
	return r, err
}

// Requests is the cluster's requests to staff, newest first.
func (s *Store) Requests(ctx context.Context, clusterID string) ([]Request, error) {
	rows, err := s.db.Query(ctx, selectRequest+` WHERE r.cluster_id = $1 ORDER BY r.created_at DESC`, clusterID)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading requests: %w", err)
	}
	return pgx.CollectRows(rows, scanRequest)
}

// RequestByID is one request.
func (s *Store) RequestByID(ctx context.Context, id string) (Request, error) {
	rows, err := s.db.Query(ctx, selectRequest+` WHERE r.id::text = $1`, id)
	if err != nil {
		return Request{}, fmt.Errorf("clusterlead: reading a request: %w", err)
	}
	request, err := pgx.CollectOneRow(rows, scanRequest)
	if errors.Is(err, pgx.ErrNoRows) {
		return Request{}, ErrNotFound
	}
	return request, err
}

// CreateRequest records a leader's request.
func (s *Store) CreateRequest(ctx context.Context, id, clusterID, subject, body, actorID string) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `
INSERT INTO cluster_leadership.leader_request (id, cluster_id, subject, body, status, created_by, country_code)
VALUES ($1, $2, $3, $4, 'open', $5, `+registry.ClusterCountryCode("$2")+`)`, id, clusterID, subject, body, actorID)
		if err != nil {
			return fmt.Errorf("clusterlead: recording a request: %w", err)
		}
		return nil
	})
}

// AnswerRequestRecord answers an open request.
func (s *Store) AnswerRequestRecord(ctx context.Context, id, answer, actorID string) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `
UPDATE cluster_leadership.leader_request SET status = 'answered', answer = $2, answered_by = $3, answered_at = now()
WHERE id::text = $1 AND status = 'open'`, id, answer, actorID)
		if err != nil {
			return fmt.Errorf("clusterlead: answering a request: %w", err)
		}
		if tag.RowsAffected() == 0 {
			return ErrNotLive
		}
		return nil
	})
}

// Operations is what the Home counts from the portal's records.
type Operations struct {
	// Member schools not yet invited to the next upcoming activity.
	NotInvitedToNext int32
	// Invitations to upcoming activities with no answer yet.
	Unanswered int32
	// Upcoming trainings with member schools not yet invited.
	TrainingsShort int32
	// Held activities in the last 60 days without submitted minutes.
	MinutesDue int32
	OpenItems  int32
	Overdue    int32
	Returned   int32
	// Cluster actions (migration 0004): schools waiting on the leader's
	// reply, actions whose every school is finished (to review and close),
	// and schools waiting on staff.
	ActionsNeedReply int32
	ActionsToReview  int32
	ActionsWithStaff int32
	// Confirmed schools per upcoming activity.
	Confirmed map[string]int32
}

// OperationsOf counts the cluster's operations on day; next is the next
// upcoming activity's id, or "".
func (s *Store) OperationsOf(ctx context.Context, clusterID, next string, day time.Time) (Operations, error) {
	ops := Operations{Confirmed: map[string]int32{}}
	err := s.db.QueryRow(ctx, `
SELECT
  (SELECT count(*) FROM school s WHERE`+memberPredicate+`
     AND $2 <> '' AND NOT EXISTS (SELECT 1 FROM cluster_leadership.invitation i
       WHERE i.activity_id = $2 AND i.school_id = s.id)),
  (SELECT count(*) FROM cluster_leadership.invitation i
     JOIN activity a ON a.id = i.activity_id AND a.deleted_at IS NULL AND a.status = ANY($4)
     WHERE i.cluster_id = $1 AND i.status IN ('invited', 'acknowledged')
       AND COALESCE((a.scheduled_date AT TIME ZONE $5)::date, a.planned_date) >= $3),
  (SELECT count(*) FROM activity a
     WHERE a.cluster_id = $1 AND a.deleted_at IS NULL AND a.status = ANY($4) AND a.meeting_kind = 'training'
       AND COALESCE((a.scheduled_date AT TIME ZONE $5)::date, a.planned_date) >= $3
       AND EXISTS (SELECT 1 FROM school s WHERE`+memberPredicate+`
         AND NOT EXISTS (SELECT 1 FROM cluster_leadership.invitation i
           WHERE i.activity_id = a.id AND i.school_id = s.id))),
  (SELECT count(*) FROM activity a
     WHERE a.cluster_id = $1 AND a.deleted_at IS NULL AND a.status <> 'cancelled'
       AND COALESCE((a.scheduled_date AT TIME ZONE $5)::date, a.planned_date) BETWEEN $3::date - 60 AND $3::date - 1
       AND NOT EXISTS (SELECT 1 FROM cluster_leadership.meeting_minutes m
         WHERE m.activity_id = a.id AND m.status = 'submitted')),
  (SELECT count(*) FROM cluster_leadership.action_item WHERE cluster_id = $1 AND status = 'open'),
  (SELECT count(*) FROM cluster_leadership.action_item WHERE cluster_id = $1 AND status = 'open' AND due_on < $3),
  (SELECT count(*) FROM cluster_leadership.meeting_plan WHERE cluster_id = $1 AND status = 'returned'),
  (SELECT count(*) FROM cluster_leadership.cluster_action_school x
     JOIN cluster_leadership.cluster_action ca ON ca.id = x.action_id
     WHERE ca.cluster_id = $1 AND ca.status = 'submitted' AND x.status IN ('clarification_requested', 'returned')),
  (SELECT count(*) FROM cluster_leadership.cluster_action ca
     WHERE ca.cluster_id = $1 AND ca.status = 'submitted' AND NOT EXISTS (
       SELECT 1 FROM cluster_leadership.cluster_action_school x
       LEFT JOIN activity act ON act.id = x.activity_id AND act.deleted_at IS NULL
       WHERE x.action_id = ca.id AND NOT (x.status IN ('returned', 'declined', 'cancelled')
         OR (x.status = 'accepted' AND act.status = ANY($6))))),
  (SELECT count(*) FROM cluster_leadership.cluster_action_school x
     JOIN cluster_leadership.cluster_action ca ON ca.id = x.action_id
     WHERE ca.cluster_id = $1 AND ca.status = 'submitted' AND x.status IN ('awaiting_review', 'under_review'))`,
		clusterID, next, day, plannedStatuses, zoneName, activityVerified).Scan(
		&ops.NotInvitedToNext, &ops.Unanswered, &ops.TrainingsShort, &ops.MinutesDue,
		&ops.OpenItems, &ops.Overdue, &ops.Returned, &ops.ActionsNeedReply, &ops.ActionsToReview, &ops.ActionsWithStaff)
	if err != nil {
		return Operations{}, fmt.Errorf("clusterlead: counting operations: %w", err)
	}
	rows, err := s.db.Query(ctx, `
SELECT activity_id, count(*) FROM cluster_leadership.invitation
WHERE cluster_id = $1 AND status = 'confirmed' GROUP BY activity_id`, clusterID)
	if err != nil {
		return Operations{}, fmt.Errorf("clusterlead: counting confirmations: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var count int32
		if err := rows.Scan(&id, &count); err != nil {
			return Operations{}, err
		}
		ops.Confirmed[id] = count
	}
	return ops, rows.Err()
}
