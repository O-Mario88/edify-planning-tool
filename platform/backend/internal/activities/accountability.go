package activities

import (
	"context"
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	evidencestore "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/evidence"
)

// The officer's accountability for a disbursed activity
// (my_plan_views.accountability_action, through
// advance_service.submit_accountability for each advance).

// AccountabilityForm is the drawer's fields; ReceiptID is a staged file.
type AccountabilityForm struct {
	Spent, Returned, VarianceNote, NetsuiteCode, ReceiptID string
}

// EvidenceKeeper keeps a staged file as an activity's evidence
// (internal/evidence.Service).
type EvidenceKeeper interface {
	Keep(ctx context.Context, p auth.Principal, stagedID, activityID, kind string) (string, error)
}

// WithEvidence lets a save keep the files it carries.
func (s *Service) WithEvidence(keeper EvidenceKeeper) *Service {
	s.evidence = keeper
	return s
}

// savedInPlace is htmx_saved.SAVED_MESSAGE.
const savedInPlace = "Saved. Press Refresh to see it on the page."

// allocateAccountability is the view's split: each advance's share of the
// spend and the return, by what it disbursed, rounded as Python rounds, the
// remainder to the last.
func allocateAccountability(spent, returned int64, shares []int64) [][2]int64 {
	var total int64
	for _, share := range shares {
		total += share
	}
	out := make([][2]int64, len(shares))
	spentLeft, returnedLeft := spent, returned
	for i, share := range shares {
		var s, r int64
		if i == len(shares)-1 || total == 0 {
			s, r = spentLeft, returnedLeft
		} else {
			s = int64(math.RoundToEven(float64(spent) * float64(share) / float64(total)))
			r = int64(math.RoundToEven(float64(returned) * float64(share) / float64(total)))
		}
		spentLeft -= s
		returnedLeft -= r
		out[i] = [2]int64{s, r}
	}
	return out
}

// accountabilityAmounts reads the two figures: an empty spend is the whole
// advance, an empty return none.
func accountabilityAmounts(rawSpent, rawReturned string, total int64) (int64, int64, error) {
	bad := refuse("%s", "Amounts must be whole UGX numbers.")
	spent := total
	if s := strings.TrimSpace(rawSpent); s != "" {
		v, err := strconv.ParseInt(s, 10, 64)
		if err != nil {
			return 0, 0, bad
		}
		spent = v
	}
	var returned int64
	if r := strings.TrimSpace(rawReturned); r != "" {
		v, err := strconv.ParseInt(r, 10, 64)
		if err != nil {
			return 0, 0, bad
		}
		returned = v
	}
	return spent, returned, nil
}

// accountabilityRefusal is submit_accountability's refusal for what the
// database answered; spent is the share the advance was given.
func accountabilityRefusal(answer string, spent int64) error {
	switch {
	case answer == "ok":
		return nil
	case answer == "gone":
		return refuse("%s", "Advance request not found.")
	case answer == "not_disbursed":
		return refuse("%s", "Accountability applies to a disbursed advance.")
	case answer == "not_owner":
		return refuse("%s", "Only the responsible user can submit accountability.")
	case answer == "unreceipted":
		return refuse("%s", "Confirm receipt of the disbursed funds first — accountability opens once you have confirmed the money actually arrived.")
	case answer == "no_netsuite":
		return refuse("%s", "NetSuite Code is required — accountability is incomplete without proof the expense was entered into NetSuite.")
	case answer == "negative":
		return refuse("%s", "Amount spent and amount returned must not be negative.")
	case answer == "netsuite_used":
		return refuse("%s", "This NetSuite Code already clears another advance. A NetSuite Code clears at most one advance, so each advance needs its own.")
	case answer == "returned_on_overspend":
		return refuse("%s", "Amount returned must be zero unless actual spend is less than the disbursed amount.")
	case strings.HasPrefix(answer, "variance:"):
		under, _ := strconv.ParseInt(strings.TrimPrefix(answer, "variance:"), 10, 64)
		return refuse("Actual spend (UGX %s) is UGX %s less than the disbursed amount — enter the returned amount or a variance explanation.",
			groupThousands(spent), groupThousands(under))
	}
	return fmt.Errorf("activities: the accountability answered %q", answer)
}

// accountedBody is the Programme Lead's notice.
func accountedBody(owner string, accounted int64, netsuite string) string {
	return fmt.Sprintf("%s accounted for UGX %s (%s). Confirm the money is accounted for so the Accountant can settle it.",
		owner, groupThousands(accounted), netsuite)
}

type disbursedAdvance struct {
	id, owner string
	share     int64
	accounted [2]int64
}

// SubmitAccountability is accountability_action's save for the activity's
// own officer; anyone else's is handed on.
func (s *Service) SubmitAccountability(ctx context.Context, p auth.Principal, activityID string, f AccountabilityForm, origin Origin) (Answer, error) {
	activityID = strings.TrimSpace(activityID)
	if p.UserID == "" || p.StaffProfileID == "" || p.InActingAppointment {
		return Answer{}, handOn("not an officer accounting for their own activity")
	}
	var delivery, responsible string
	err := s.db.QueryRow(ctx, `SELECT COALESCE(delivery_type, ''), COALESCE(responsible_staff_id, '')
  FROM activity WHERE id = $1 AND deleted_at IS NULL`, activityID).Scan(&delivery, &responsible)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		return Answer{}, refuse("%s", "Not found.")
	case err != nil:
		return Answer{}, fmt.Errorf("activities: reading the activity: %w", err)
	case delivery == "partner":
		return Answer{}, handOn("a partner's activity")
	case responsible != p.StaffProfileID && responsible != p.UserID:
		return Answer{}, handOn("someone else's activity")
	}
	advances, err := s.disbursedAdvances(ctx, activityID)
	if err != nil {
		return Answer{}, err
	}
	if len(advances) == 0 {
		return Answer{}, refuse("%s", "No disbursed advance is awaiting accountability on this activity.")
	}
	shares := make([]int64, len(advances))
	var total int64
	for i, a := range advances {
		shares[i] = a.share
		total += a.share
	}
	spent, returned, err := accountabilityAmounts(f.Spent, f.Returned, total)
	if err != nil {
		return Answer{}, err
	}
	netsuite, note := strings.TrimSpace(f.NetsuiteCode), strings.TrimSpace(f.VarianceNote)
	if receipt := strings.TrimSpace(f.ReceiptID); receipt != "" {
		if s.evidence == nil {
			return Answer{}, handOn("no evidence store")
		}
		if _, err := s.evidence.Keep(ctx, p, receipt, activityID, ""); err != nil {
			var refusal *evidencestore.Refusal
			if errors.As(err, &refusal) {
				return Answer{}, refuse("Receipt upload error: %s", refusal.Message)
			}
			return Answer{}, err
		}
	}
	for i, split := range allocateAccountability(spent, returned, shares) {
		advances[i].accounted = split
	}
	if err := s.writeAccountability(ctx, p, advances, netsuite, note); err != nil {
		return Answer{}, err
	}
	s.afterAccountability(ctx, p, activityID, advances, netsuite, spent, returned, origin)
	return Answer{ActivityID: activityID, Message: savedInPlace}, nil
}

// disbursedAdvances is a.advance_requests.filter(status="disbursed") in the
// model's order, each with what it disbursed (disbursed_amount or amount).
func (s *Service) disbursedAdvances(ctx context.Context, activityID string) ([]disbursedAdvance, error) {
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(responsible_user_id, ''),
  COALESCE(NULLIF(disbursed_amount, 0), NULLIF(amount, 0), 0)::bigint
  FROM advance_request WHERE activity_id = $1 AND status = 'disbursed' ORDER BY created_at DESC`, activityID)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the disbursed advances: %w", err)
	}
	defer rows.Close()
	var out []disbursedAdvance
	for rows.Next() {
		var a disbursedAdvance
		if err := rows.Scan(&a.id, &a.owner, &a.share); err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

// writeAccountability submits every advance together: one refused leaves
// them all as they were.
func (s *Service) writeAccountability(ctx context.Context, p auth.Principal, advances []disbursedAdvance, netsuite, note string) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return fmt.Errorf("activities: opening the accountability: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	now := s.now()
	for _, a := range advances {
		var answer string
		if err := tx.QueryRow(ctx, `SELECT gateway_day_money.account_advance($1, $2, $3, $4, $5, $6, $7, $8)`,
			a.id, p.UserID, p.ActiveRole, netsuite, a.accounted[0], a.accounted[1], note, now).Scan(&answer); err != nil {
			return fmt.Errorf("activities: submitting the accountability: %w", err)
		}
		if err := accountabilityRefusal(answer, a.accounted[0]); err != nil {
			return err
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("activities: committing the accountability: %w", err)
	}
	return nil
}

// afterAccountability is each advance's audit row and its Programme Lead's
// notice, then the activity's own audit row; none blocks the save.
func (s *Service) afterAccountability(ctx context.Context, p auth.Principal, activityID string, advances []disbursedAdvance,
	netsuite string, spent, returned int64, origin Origin) {
	for _, a := range advances {
		if err := s.auditAccountability(ctx, p, "advance_request.submit_accountability", "AdvanceRequest", a.id,
			map[string]any{"accounted": a.accounted[0], "returned": a.accounted[1], "netsuite_id": netsuite}, origin); err != nil {
			s.logger.Warn("activities: the advance's audit row was not written", "advance", a.id, "err", err)
		}
		if err := s.tellAccountabilityLead(ctx, p, a, netsuite, origin); err != nil {
			s.logger.Warn("activities: the accountability's lead was not told", "advance", a.id, "err", err)
		}
	}
	if err := s.auditAccountability(ctx, p, "accountability_submitted", "Activity", activityID,
		map[string]any{"netsuite_code": netsuite, "amount_spent": spent, "amount_returned": returned}, origin); err != nil {
		s.logger.Warn("activities: the accountability's audit row was not written", "activity", activityID, "err", err)
	}
}

func (s *Service) auditAccountability(ctx context.Context, p auth.Principal, action, kind, id string, payload map[string]any, origin Origin) error {
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
		Action: action, SubjectKind: audit.Text(kind), SubjectID: audit.Text(id),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true,
		IPAddress: nilIfEmpty(origin.IP), UserAgent: nilIfEmpty(origin.UserAgent), CorrelationID: nilIfEmpty(origin.CorrelationID),
		Payload: withStamps(payload, cover),
	}, s.now()); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

// tellAccountabilityLead is _notify(_supervisor_ids(owner), ...): the link
// is NotificationLinkResolver's AdvanceRequest fallback.
func (s *Service) tellAccountabilityLead(ctx context.Context, p auth.Principal, a disbursedAdvance, netsuite string, origin Origin) error {
	if a.owner == "" {
		return nil
	}
	rows, err := s.db.Query(ctx, `SELECT sup.user_id, COALESCE(u.active_role, '') FROM staff_supervisor_assignment ssa
JOIN staff_profile sv ON sv.id = ssa.supervisee_id JOIN staff_profile sup ON sup.id = ssa.supervisor_id
LEFT JOIN "user" u ON u.id = sup.user_id
WHERE sv.user_id = $1 AND sup.user_id IS NOT NULL AND sup.user_id <> '' ORDER BY ssa.id`, a.owner)
	if err != nil {
		return fmt.Errorf("reading the leads: %w", err)
	}
	type lead struct{ id, role string }
	leads, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (lead, error) {
		var l lead
		return l, r.Scan(&l.id, &l.role)
	})
	if err != nil || len(leads) == 0 {
		return err
	}
	name := "a staff member"
	var found string
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(name, '') FROM "user" WHERE id = $1`, a.owner).Scan(&found); err == nil && found != "" {
		name = found
	}
	seen := map[string]bool{}
	recipients := make([]noticeRecipient, 0, len(leads))
	for _, l := range leads {
		if seen[l.id] {
			continue
		}
		seen[l.id] = true
		r := noticeRecipient{id: l.id, route: "/fund-requests/weekly", label: "Open Fund Request"}
		if strings.EqualFold(l.role, "Accountant") {
			r.route, r.label = "/disbursements", "Open Finance Queue"
		}
		recipients = append(recipients, r)
	}
	return workflowNotices{db: s.db, push: s.noticePush, live: s.live, logger: s.logger}.sendTo(ctx, s.now(), a.id, p.UserID, origin,
		scheduledNotice{
			title: "Fund accountability awaiting your approval", body: accountedBody(name, a.accounted[0], netsuite),
			event: "advance_accountability_submitted", category: "finance", contextType: "AdvanceRequest", priority: "high",
		}, recipients)
}

// AccountabilityView is what the accountability drawer shows: the school,
// what was disbursed, and each advance's line.
type AccountabilityView struct {
	School string
	Total  int64
	Lines  [][2]string
}

// AccountabilityDrawer reads the drawer for the activity's own officer;
// anyone else's is handed on.
func (s *Service) AccountabilityDrawer(ctx context.Context, p auth.Principal, activityID string) (AccountabilityView, error) {
	var delivery, responsible, school string
	err := s.db.QueryRow(ctx, `SELECT COALESCE(a.delivery_type, ''), COALESCE(a.responsible_staff_id, ''), COALESCE(sc.name, '')
  FROM activity a LEFT JOIN school sc ON sc.id = a.school_id WHERE a.id = $1 AND a.deleted_at IS NULL`,
		strings.TrimSpace(activityID)).Scan(&delivery, &responsible, &school)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		return AccountabilityView{}, refuse("%s", "Not found.")
	case err != nil:
		return AccountabilityView{}, fmt.Errorf("activities: reading the activity: %w", err)
	case p.StaffProfileID == "" || p.InActingAppointment || delivery == "partner" || (responsible != p.StaffProfileID && responsible != p.UserID):
		return AccountabilityView{}, handOn("not the officer's own staff activity")
	}
	rows, err := s.db.Query(ctx, `SELECT COALESCE(l.label, ''), COALESCE(NULLIF(r.disbursed_amount, 0), NULLIF(r.amount, 0), 0)::bigint
  FROM advance_request r LEFT JOIN activity_schedule_cost_line l ON l.id = r.budget_line_id
  WHERE r.activity_id = $1 AND r.status = 'disbursed' ORDER BY r.created_at DESC`, activityID)
	if err != nil {
		return AccountabilityView{}, fmt.Errorf("activities: reading the disbursed advances: %w", err)
	}
	defer rows.Close()
	view := AccountabilityView{School: school}
	for rows.Next() {
		var label string
		var amount int64
		if err := rows.Scan(&label, &amount); err != nil {
			return AccountabilityView{}, err
		}
		view.Total += amount
		view.Lines = append(view.Lines, [2]string{label, "UGX " + groupThousands(amount)})
	}
	return view, rows.Err()
}
