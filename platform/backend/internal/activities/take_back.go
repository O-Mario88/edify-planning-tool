package activities

import (
	"context"
	"fmt"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
)

// A plan that changes takes its unpaid weekly fund request back
// (apps.fund_requests.plan_changes, owner 2026-10-07): a move into or out of a
// week whose request was sent and not paid brings that request back to its
// owner, rebuilt from the changed plan, instead of refusing the move.

// weekSentUnpaid is plan_changes.SENT_UNPAID_STATUSES.
var weekSentUnpaid = []string{"submitted_to_pl", "submitted_to_cd", "confirmed_for_advance", "not_requested"}

const takenBackEvent = "weekly_fund_request_taken_back"

// takenWeek is a weekly request the move brought back, as it was sent.
type takenWeek struct {
	id, was, owner string
	start, end     time.Time
	total          int64
}

// mondayOf is the Monday of day's week.
func mondayOf(day time.Time) time.Time {
	return time.Date(day.Year(), day.Month(), day.Day()-(int(day.Weekday())+6)%7, 0, 0, 0, 0, time.UTC)
}

// weekLabel is plan_changes._week_label: "7 Dec – 13 Dec".
func weekLabel(start, end time.Time) string {
	return start.Format("2 Jan") + " – " + end.Format("2 Jan")
}

// takenBackOwnerBody is _notify_owner's words.
func takenBackOwnerBody(what, week, was string, stillThere bool) string {
	switch {
	case !stillThere:
		return fmt.Sprintf("%s changed after the fund request for %s was sent. Nothing is left to fund in that week, "+
			"so the request has been withdrawn.", what, week)
	case was == "not_requested":
		return fmt.Sprintf("%s changed in %s, a week you had set to No Advance. The week's request is open again with "+
			"the new figures: send it for approval, or choose No Advance again.", what, week)
	}
	return fmt.Sprintf("%s changed after the fund request for %s was sent, so the request has come back to you with "+
		"the new figures. Send it for approval again.", what, week)
}

// takenBackWaiting is what the request's reviewers were waiting to do; "" when
// nobody had it on their list.
func takenBackWaiting(was string) string {
	switch was {
	case "submitted_to_pl", "submitted_to_cd":
		return "approve"
	case "confirmed_for_advance":
		return "disburse"
	}
	return ""
}

// takenBackReviewerBody is _notify_reviewers' words.
func takenBackReviewerBody(owner, week string, total int64, what, waiting string) string {
	return fmt.Sprintf("%s's fund request for %s (UGX %s) went back to them because %s in that week changed. "+
		"There is nothing to %s until it is sent again with the new figures.", owner, week, groupThousands(total), what, waiting)
}

// takeBackWeeks brings the move's sent-but-unpaid weeks back inside its
// transaction, and notes the owner's days in each week whose split is stale
// so they are priced again (resync_stale_batches).
func takeBackWeeks(ctx context.Context, tx pgx.Tx, pl *movePlan) error {
	owners := []string{pl.ownerUID}
	rows, err := tx.Query(ctx, `SELECT DISTINCT responsible_user FROM activity_schedule_cost_line
WHERE activity_id = $1 AND responsible_user IS NOT NULL AND responsible_user <> ''`, pl.a.id)
	if err != nil {
		return fmt.Errorf("activities: reading the visit's money owners: %w", err)
	}
	lineOwners, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return fmt.Errorf("activities: reading a money owner: %w", err)
	}
	for _, owner := range lineOwners {
		if !slices.Contains(owners, owner) {
			owners = append(owners, owner)
		}
	}
	weeks := []string{mondayOf(pl.a.plannedDate).Format(time.DateOnly), mondayOf(pl.newDay).Format(time.DateOnly)}
	taken, err := tx.Query(ctx, `SELECT request_id, was, owner, week_start, week_end, total
FROM gateway_day_money.take_back_weeks($1, $2, $3::date[], $4)`, pl.a.id, owners, weeks, pl.now)
	if err != nil {
		return fmt.Errorf("activities: taking the week's request back: %w", err)
	}
	for taken.Next() {
		var w takenWeek
		if err := taken.Scan(&w.id, &w.was, &w.owner, &w.start, &w.end, &w.total); err != nil {
			taken.Close()
			return fmt.Errorf("activities: reading a request taken back: %w", err)
		}
		pl.taken = append(pl.taken, w)
	}
	taken.Close()
	if err := taken.Err(); err != nil {
		return fmt.Errorf("activities: taking the week's request back: %w", err)
	}
	for _, w := range pl.taken {
		stale, err := tx.Query(ctx, `SELECT batch_id FROM gateway_day_money.stale_days($1, $2::date, $3::date)`,
			w.owner, w.start.Format(time.DateOnly), w.end.Format(time.DateOnly))
		if err != nil {
			return fmt.Errorf("activities: reading the week's stale days: %w", err)
		}
		ids, err := pgx.CollectRows(stale, pgx.RowTo[string])
		if err != nil {
			return fmt.Errorf("activities: reading a stale day: %w", err)
		}
		for _, id := range ids {
			pl.staleDays = append(pl.staleDays, []string{id, w.owner})
		}
	}
	return nil
}

// tellTakenBack is plan_changes._tell after the move has landed and been
// priced: for each request taken back, its audit row, its owner's notice
// and a word to whoever had it on their list. None of it undoes the move.
func (s *Service) tellTakenBack(ctx context.Context, pl *movePlan) {
	what := pl.a.nameSnapshot + " at " + pl.school.Name
	for _, w := range pl.taken {
		if err := s.tellOneTakenBack(ctx, pl, w, what); err != nil {
			s.logger.Warn("activities: a request taken back was not told", "request", w.id, "err", err)
		}
	}
}

func (s *Service) tellOneTakenBack(ctx context.Context, pl *movePlan, w takenWeek, what string) error {
	var stillThere bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM weekly_fund_request WHERE id = $1)`, w.id).Scan(&stillThere); err != nil {
		return err
	}
	if err := s.auditTakenBack(ctx, pl, w, what); err != nil {
		return err
	}
	week := weekLabel(w.start, w.end)
	context := ""
	if stillThere {
		context = w.id
	}
	owner := workflowNotices{db: s.db, push: s.noticePush, live: s.live, logger: s.logger}
	if err := owner.sendTo(ctx, s.now(), context, pl.p.UserID, Origin{}, scheduledNotice{
		title: "Weekly fund request came back to you", body: takenBackOwnerBody(what, week, w.was, stillThere),
		event: takenBackEvent, category: "finance", contextType: "WeeklyFundRequest", priority: "high",
	}, []noticeRecipient{takenBackRecipient(w.owner, context)}); err != nil {
		return fmt.Errorf("telling the owner: %w", err)
	}
	waiting := takenBackWaiting(w.was)
	if waiting == "" {
		return nil
	}
	reviewers, err := s.takenBackReviewers(ctx, w)
	if err != nil || len(reviewers) == 0 {
		return err
	}
	var name string
	_ = s.db.QueryRow(ctx, `SELECT COALESCE(name, '') FROM "user" WHERE id = $1`, w.owner).Scan(&name)
	if name == "" {
		name = "A staff member"
	}
	recipients := make([]noticeRecipient, 0, len(reviewers))
	for _, id := range reviewers {
		recipients = append(recipients, takenBackRecipient(id, ""))
	}
	return owner.sendTo(ctx, s.now(), "", pl.p.UserID, Origin{}, scheduledNotice{
		title: "Weekly fund request taken back", body: takenBackReviewerBody(name, week, w.total, what, waiting),
		event: takenBackEvent, category: "finance", contextType: "WeeklyFundRequest",
	}, recipients)
}

// takenBackRecipient is one person told, with NotificationLinkResolver's
// link: the owner opens the request to send it again; a reviewer is only
// told, and goes to the list it left.
func takenBackRecipient(userID, requestID string) noticeRecipient {
	if requestID != "" {
		return noticeRecipient{id: userID, route: "/fund-requests/weekly/" + requestID, label: "Send Fund Request"}
	}
	return noticeRecipient{id: userID, route: "/fund-requests/weekly", label: "View Fund Requests"}
}

// takenBackReviewers is who had the request on their list, never its owner.
func (s *Service) takenBackReviewers(ctx context.Context, w takenWeek) ([]string, error) {
	var query string
	switch w.was {
	case "submitted_to_pl":
		query = `SELECT sup.user_id FROM staff_supervisor_assignment ssa
JOIN staff_profile sv ON sv.id = ssa.supervisee_id JOIN staff_profile sup ON sup.id = ssa.supervisor_id
WHERE sv.user_id = $1 AND sup.user_id IS NOT NULL ORDER BY ssa.id`
	case "submitted_to_cd":
		query = `SELECT id FROM "user" WHERE active_role = 'CountryDirector' AND is_active AND $1 <> '' ORDER BY id`
	case "confirmed_for_advance":
		query = `SELECT id FROM "user" WHERE active_role = 'Accountant' AND is_active AND $1 <> '' ORDER BY id`
	default:
		return nil, nil
	}
	rows, err := s.db.Query(ctx, query, w.owner)
	if err != nil {
		return nil, fmt.Errorf("activities: reading who had the request: %w", err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, err
	}
	return slices.DeleteFunc(ids, func(id string) bool { return id == "" || id == w.owner }), nil
}

func (s *Service) auditTakenBack(ctx context.Context, pl *movePlan, w takenWeek, what string) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "weekly_fund_request.taken_back", SubjectKind: audit.Text("WeeklyFundRequest"), SubjectID: audit.Text(w.id),
		ActorID: audit.Text(pl.p.UserID), ActorRole: audit.Text(pl.p.ActiveRole), Success: true,
		Reason: audit.Text("A planned activity in this week was changed."),
		Payload: map[string]any{
			"week_start": w.start.Format(time.DateOnly), "from_status": w.was, "total_when_sent": w.total, "activity": what,
		},
	}, s.now()); err != nil {
		return fmt.Errorf("auditing the request taken back: %w", err)
	}
	return tx.Commit(ctx)
}
