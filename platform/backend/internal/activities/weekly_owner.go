package activities

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The owner's own decisions on their weekly fund request, from the Fund
// Requests page (budget_views.weekly_fund_request_confirm_action,
// _self_funded_action, _not_requested_action and _receipt_action, through
// apps.fund_requests.weekly_service).

const (
	weekSend     = "send"
	weekSelfFund = "self_fund"
	weekSkip     = "skip"
	weekReceipt  = "receipt"
)

// weekOwnerForm is each save's path on the page, and the decision it posts.
var weekOwnerForm = regexp.MustCompile(`^/fund-requests/weekly/([A-Za-z0-9_-]{1,64})/(confirm|self-funded|not-requested|confirm-receipt)/?$`)

var weekFormOps = map[string]string{
	"confirm": weekSend, "self-funded": weekSelfFund, "not-requested": weekSkip, "confirm-receipt": weekReceipt,
}

// WeekOwnerForm reads a page form's key: the request and the decision, or
// false for any other form.
func WeekOwnerForm(path string) (requestID, op string, ok bool) {
	m := weekOwnerForm.FindStringSubmatch(path)
	if m == nil {
		return "", "", false
	}
	return m[1], weekFormOps[m[2]], true
}

// WeekOwnerPath is the save's path for one decision on a request.
func WeekOwnerPath(requestID, op string) string {
	for form, o := range weekFormOps {
		if o == op {
			return "/fund-requests/weekly/" + requestID + "/" + form
		}
	}
	return ""
}

// submissionStatus is _submission_status_for: a CCEO's request goes to their
// Programme Lead; a Country Director's or an Admin's straight to the
// Accountant; anyone else's to the Country Director.
func submissionStatus(ownerRole string) string {
	switch ownerRole {
	case "CCEO":
		return "submitted_to_pl"
	case "CountryDirector", "Admin":
		return "confirmed_for_advance"
	}
	return "submitted_to_cd"
}

// ownerRoleOf is _owner_role: the role stamped on the request, else the
// owner's active role, else their first; nobody found is a CCEO.
func ownerRoleOf(stamped string, found bool, active string, roles []string) string {
	switch {
	case stamped != "":
		return stamped
	case !found:
		return "CCEO"
	case active != "":
		return active
	case len(roles) > 0:
		return roles[0]
	}
	return "CCEO"
}

// weekSubmittedBody is _notify_weekly_approver's body.
func weekSubmittedBody(start, end time.Time, total int64) string {
	return fmt.Sprintf("A weekly fund request (%s – %s, UGX %s) needs your review.",
		start.Format("Jan 02"), end.Format("Jan 02"), groupThousands(total))
}

// weekRefusal is the existing service's refusal for what the database
// answered, or nil when the answer is the request's new standing.
func weekRefusal(op, answer string) error {
	switch {
	case answer == "gone":
		return refuse("%s", "Weekly fund request not found.")
	case answer == "not_owner" && op == weekReceipt:
		return refuse("%s", "Only the owner can confirm receipt of these funds.")
	case answer == "not_owner":
		return refuse("%s", "Only the owner can confirm this request.")
	case strings.HasPrefix(answer, "status:"):
		return refuse("Cannot request advance in status '%s'.", strings.TrimPrefix(answer, "status:"))
	case answer == "paid":
		return refuse("%s", "Cannot cancel a disbursed request.")
	case answer == "not_disbursed":
		return refuse("%s", "These funds are not marked as disbursed.")
	case answer == "no_bank":
		return refuse("%s", "Confirm only after receiving the bank message and verifying the funds arrived.")
	case answer == "changed":
		return refuse("%s", "This request changed while you were deciding. Open it again.")
	}
	return nil
}

// weekSavedMessage is what each view says once the save is made.
func weekSavedMessage(op string) string {
	switch op {
	case weekSend:
		return "Weekly advance request submitted for supervisor approval."
	case weekSelfFund:
		return "Self Fund request sent for approval."
	case weekSkip:
		return "No advance will be requested for this week."
	case weekReceipt:
		return "Receipt confirmed — you can now account for this week's spend."
	}
	return ""
}

// unsettledLimit is how many waiting cost rows a decision settles first.
const unsettledLimit = 200

// DecideOwnWeek makes the owner's decision on their weekly request, or
// refuses it in the existing words.
func (s *Service) DecideOwnWeek(ctx context.Context, p auth.Principal, requestID, op string, bankMessage bool, origin Origin) (Answer, error) {
	requestID = strings.TrimSpace(requestID)
	if p.UserID == "" || weekSavedMessage(op) == "" {
		return Answer{}, handOn("not an owner's decision on a week")
	}
	if op != weekReceipt {
		// settled_first: figures a save left to be priced are settled before
		// the request is read or sent.
		if err := s.settleWaiting(ctx); err != nil {
			return Answer{}, err
		}
	}
	var answer string
	var err error
	switch op {
	case weekSend, weekSelfFund:
		answer, err = s.sendWeek(ctx, p, requestID, op)
	case weekSkip:
		answer, err = s.writeWeek(ctx, `SELECT gateway_day_money.skip_week($1, $2, $3)`, requestID, p.UserID, s.now())
	case weekReceipt:
		answer, err = s.writeWeek(ctx, `SELECT gateway_day_money.confirm_week_receipt($1, $2, $3, $4)`,
			requestID, p.UserID, bankMessage, s.now())
	}
	if err != nil {
		return Answer{}, err
	}
	if refusal := weekRefusal(op, answer); refusal != nil {
		return Answer{}, refusal
	}
	s.afterOwnWeek(ctx, p, requestID, op, answer, origin)
	return Answer{Status: answer, Message: weekSavedMessage(op)}, nil
}

func (s *Service) settleWaiting(ctx context.Context) error {
	if s.pricing == nil {
		return nil
	}
	rows, err := s.db.Query(ctx, `SELECT id FROM gateway_costing.read_unsettled_costs($1)`, unsettledLimit)
	if err != nil {
		return fmt.Errorf("activities: reading the costs waiting: %w", err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[int64])
	if err != nil {
		return fmt.Errorf("activities: reading the costs waiting: %w", err)
	}
	if len(ids) == 0 {
		return nil
	}
	if err := s.pricing.Settle(ctx, ids, ""); err != nil {
		s.logger.Warn("activities: the costs waiting were not all settled", "err", err)
	}
	return nil
}

// sendWeek is request_advance: routed by the owner's role.
func (s *Service) sendWeek(ctx context.Context, p auth.Principal, requestID, op string) (string, error) {
	var owner, stamped string
	err := s.db.QueryRow(ctx, `SELECT COALESCE(responsible_user, ''), COALESCE(responsible_role, '')
  FROM weekly_fund_request WHERE id = $1`, requestID).Scan(&owner, &stamped)
	if errors.Is(err, pgx.ErrNoRows) {
		return "gone", nil
	}
	if err != nil {
		return "", fmt.Errorf("activities: reading the weekly request: %w", err)
	}
	var active string
	var roles []string
	found := true
	switch err := s.db.QueryRow(ctx, `SELECT COALESCE(active_role, ''), COALESCE(roles, '{}') FROM "user" WHERE id = $1`,
		owner).Scan(&active, &roles); {
	case errors.Is(err, pgx.ErrNoRows):
		found = false
	case err != nil:
		return "", fmt.Errorf("activities: reading the request's owner: %w", err)
	}
	role := ownerRoleOf(stamped, found, active, roles)
	funding := "advance"
	if op == weekSelfFund {
		funding = "self_fund"
	}
	return s.writeWeek(ctx, `SELECT gateway_day_money.send_week($1, $2, $3, $4, $5, $6, $7)`,
		requestID, p.UserID, stamped, role, submissionStatus(role), funding, s.now())
}

func (s *Service) writeWeek(ctx context.Context, query string, args ...any) (string, error) {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return "", fmt.Errorf("activities: opening the weekly request: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var answer string
	if err := tx.QueryRow(ctx, query, args...).Scan(&answer); err != nil {
		return "", fmt.Errorf("activities: saving the weekly request: %w", err)
	}
	if weekRefusal("", answer) != nil || answer == "not_owner" || answer == "not_disbursed" {
		return answer, nil
	}
	if err := tx.Commit(ctx); err != nil {
		return "", fmt.Errorf("activities: committing the weekly request: %w", err)
	}
	return answer, nil
}

// ownWeek is what the audit row and the approver's notice read.
type ownWeek struct {
	owner, funding string
	start, end     time.Time
	total          int64
}

// afterOwnWeek is the audit row and the approver's notice; neither blocks
// the decision.
func (s *Service) afterOwnWeek(ctx context.Context, p auth.Principal, requestID, op, status string, origin Origin) {
	if op == weekSkip || status == "already" {
		return
	}
	var w ownWeek
	if err := s.db.QueryRow(ctx, `SELECT responsible_user, COALESCE(funding_source, ''), week_start_date, week_end_date,
  COALESCE(total_amount, 0)::bigint FROM weekly_fund_request WHERE id = $1`, requestID).Scan(
		&w.owner, &w.funding, &w.start, &w.end, &w.total); err != nil {
		s.logger.Warn("activities: the weekly request was not read after its save", "request", requestID, "err", err)
		return
	}
	action, payload := "weekly_fund_request.submit", map[string]any{"routed": status, "funding_source": w.funding}
	if op == weekReceipt {
		action, payload = "weekly_fund_request.receipt_confirmed", map[string]any{"bank_message_received": true}
	}
	if err := s.auditOwnWeek(ctx, p, requestID, action, w, payload, origin); err != nil {
		s.logger.Warn("activities: the weekly request's audit row was not written", "request", requestID, "err", err)
	}
	if op == weekReceipt {
		return
	}
	if err := s.tellWeekApprover(ctx, p, requestID, status, w, origin); err != nil {
		s.logger.Warn("activities: the weekly request's approver was not told", "request", requestID, "err", err)
	}
}

func (s *Service) auditOwnWeek(ctx context.Context, p auth.Principal, requestID, action string, w ownWeek,
	payload map[string]any, origin Origin) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	cover, err := coverageStamp(ctx, tx, p.UserID, s.now())
	if err != nil {
		return err
	}
	full := map[string]any{"week_start": w.start.Format(time.DateOnly), "total": w.total}
	for k, v := range payload {
		full[k] = v
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: action, SubjectKind: audit.Text("WeeklyFundRequest"), SubjectID: audit.Text(requestID),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true,
		IPAddress: nilIfEmpty(origin.IP), UserAgent: nilIfEmpty(origin.UserAgent), CorrelationID: nilIfEmpty(origin.CorrelationID),
		Payload: withStamps(full, cover),
	}, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// tellWeekApprover is _notify_weekly_approver: the owner's supervisors for a
// Programme Lead's approval, every active Country Director for theirs.
func (s *Service) tellWeekApprover(ctx context.Context, p auth.Principal, requestID, status string, w ownWeek, origin Origin) error {
	var query string
	switch status {
	case "submitted_to_pl":
		query = `SELECT sup.user_id FROM staff_supervisor_assignment ssa
JOIN staff_profile sv ON sv.id = ssa.supervisee_id JOIN staff_profile sup ON sup.id = ssa.supervisor_id
WHERE sv.user_id = $1 AND sup.user_id IS NOT NULL AND sup.user_id <> '' ORDER BY ssa.id`
	case "submitted_to_cd":
		query = `SELECT id FROM "user" WHERE active_role = 'CountryDirector' AND is_active AND $1 <> '' ORDER BY id`
	default:
		return nil
	}
	rows, err := s.db.Query(ctx, query, w.owner)
	if err != nil {
		return fmt.Errorf("reading the approvers: %w", err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return fmt.Errorf("reading the approvers: %w", err)
	}
	recipients := make([]noticeRecipient, 0, len(ids))
	seen := map[string]bool{}
	for _, id := range ids {
		if seen[id] {
			continue
		}
		seen[id] = true
		recipients = append(recipients, noticeRecipient{id: id, route: "/fund-requests/weekly/" + requestID, label: "Review Fund Request"})
	}
	if len(recipients) == 0 {
		return nil
	}
	return workflowNotices{db: s.db, push: s.noticePush, live: s.live, logger: s.logger}.sendTo(ctx, s.now(), requestID, p.UserID, origin,
		scheduledNotice{
			title: "Weekly fund request awaiting your approval", body: weekSubmittedBody(w.start, w.end, w.total),
			event: "weekly_fund_request_submitted", category: "finance", contextType: "WeeklyFundRequest", priority: "high",
		}, recipients)
}

// ConfirmMonthReceipt is fund_receipt_confirm_action: the requester confirms
// their disbursed monthly plan's funds arrived.
func (s *Service) ConfirmMonthReceipt(ctx context.Context, p auth.Principal, fundRequestID string, origin Origin) (Answer, error) {
	fundRequestID = strings.TrimSpace(fundRequestID)
	if p.UserID == "" {
		return Answer{}, handOn("nobody signed in")
	}
	answer, err := s.writeWeek(ctx, `SELECT gateway_day_money.confirm_month_receipt($1, $2, $3)`, fundRequestID, p.UserID, s.now())
	if err != nil {
		return Answer{}, err
	}
	switch answer {
	case "gone":
		return Answer{}, refuse("%s", "Fund plan not found.")
	case "not_owner":
		return Answer{}, refuse("%s", "Only the requester can confirm receipt of these funds.")
	case "not_disbursed":
		return Answer{}, refuse("%s", "These funds are not marked as disbursed.")
	}
	var period string
	var total int64
	_ = s.db.QueryRow(ctx, `SELECT COALESCE(period_key, ''), COALESCE(total_amount, 0)::bigint FROM fund_request WHERE id = $1`,
		fundRequestID).Scan(&period, &total)
	if answer == "confirmed" {
		if err := s.auditAccountability(ctx, p, "fund_request.receipt_confirmed", "FundRequest", fundRequestID,
			map[string]any{"period_key": period, "total": total}, origin); err != nil {
			s.logger.Warn("activities: the plan's receipt audit row was not written", "plan", fundRequestID, "err", err)
		}
	}
	return Answer{Message: "Receipt confirmed for " + period + "."}, nil
}
