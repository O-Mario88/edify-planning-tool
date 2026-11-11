package acting

import (
	"context"
	"encoding/json"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// Notice kinds the existing application sends its notifications for
// (apps/accounts/account_event_relay.py → apps.acting.services._notify_*).
const (
	NoticeAppointed   = "acting_appointed"
	NoticeCancelled   = "acting_cancelled"
	NoticeRescheduled = "acting_rescheduled"
)

// Notifier tells the existing application, which still sends notifications,
// that an appointment was made, cancelled or moved. Best effort: the
// appointment is already committed and audited.
type Notifier func(ctx context.Context, kind, appointmentID string)

// TokenIssuer is an access token for a person working in a role.
type TokenIssuer func(userID, role string, now time.Time) (string, error)

// Service is the acting leadership rules.
type Service struct {
	store  *Store
	now    func() time.Time
	notify Notifier
	issue  TokenIssuer
}

// NewService wires the service; notify may be nil.
func NewService(store *Store, now func() time.Time, notify Notifier, issue TokenIssuer) *Service {
	if notify == nil {
		notify = func(context.Context, string, string) {}
	}
	return &Service{store: store, now: now, notify: notify, issue: issue}
}

// ── Who may appoint, manage and read ───────────────────────────────────────

// holdsPermanently is _holds_permanently: role is on the account, or the
// account's role list was never filled in.
func holdsPermanently(p auth.Principal, role string) bool {
	return len(p.Roles) == 0 || slices.Contains(p.Roles, role)
}

// appointingPolicy is appointing_policy: the appointment this person may
// make, working in their own permanent role. Nobody in an acting capacity
// appoints anyone.
func appointingPolicy(p auth.Principal) (Role, bool) {
	if p.InActingAppointment {
		return Role{}, false
	}
	entry, ok := offeredBy(p.ActiveRole)
	if !ok || !holdsPermanently(p, p.ActiveRole) {
		return Role{}, false
	}
	return entry, true
}

func (s *Service) reachOf(ctx context.Context, p auth.Principal) (reach, *seat, error) {
	r := reach{userID: p.UserID}
	if p.ActiveRole == roleAdmin {
		r.all = true
	}
	own, err := s.store.seat(ctx, s.store.db, p.StaffProfileID)
	if err != nil || own == nil {
		return r, nil, err
	}
	r.staffID = own.StaffID
	r.country = own.Country
	r.readsTheCountry = p.ActiveRole == roleCountryDirector || p.ActiveRole == roleHumanResources
	return r, own, nil
}

// mayManage is may_manage: cancel. The seat's leader in the role that
// appointed; a Country Director for an Acting Program Lead in their
// country; an Admin for any. Never from an acting capacity.
func mayManage(p auth.Principal, own *seat, a Appointment) bool {
	if p.InActingAppointment {
		return false
	}
	if p.ActiveRole == roleAdmin {
		return true
	}
	if !holdsPermanently(p, p.ActiveRole) {
		return false
	}
	if own != nil && a.SeatID == own.StaffID && p.ActiveRole == a.ByRole {
		return true
	}
	return p.ActiveRole == roleCountryDirector && a.ScopeType == ScopePLTeam &&
		own != nil && own.Country != "" && own.Country == a.Country
}

// mayChangeMonth is reschedule's gate: the appointing leader, in their own
// role, for their own seat.
func mayChangeMonth(p auth.Principal, own *seat, a Appointment) bool {
	_, appoints := appointingPolicy(p)
	return appoints && own != nil && a.SeatID == own.StaffID
}

// ── Reading ────────────────────────────────────────────────────────────────

// Board is board: current, upcoming (soonest first) and history.
type Board struct {
	Current, Upcoming, History []*identityv1.ActingAppointment
	CanAppointLabel            string
}

// Board reads the appointments the caller may read.
func (s *Service) Board(ctx context.Context, p auth.Principal) (Board, error) {
	r, own, err := s.reachOf(ctx, p)
	if err != nil {
		return Board{}, err
	}
	rows, err := s.store.visible(ctx, r)
	if err != nil {
		return Board{}, err
	}
	today := Today(s.now())
	var board Board
	var upcoming []Appointment
	for _, a := range rows {
		switch state(a.Start, a.End, a.CancelledAt != nil, today) {
		case stateActive:
			board.Current = append(board.Current, s.message(p, own, a, today))
		case stateUpcoming:
			upcoming = append(upcoming, a)
		default:
			board.History = append(board.History, s.message(p, own, a, today))
		}
	}
	slices.SortStableFunc(upcoming, func(x, y Appointment) int { return x.Start.Compare(y.Start) })
	for _, a := range upcoming {
		board.Upcoming = append(board.Upcoming, s.message(p, own, a, today))
	}
	if entry, ok := appointingPolicy(p); ok && own != nil {
		board.CanAppointLabel = entry.ShortLabel
	}
	return board, nil
}

// Get is one appointment; not found unless the caller may read it, so an id
// from another team says nothing.
func (s *Service) Get(ctx context.Context, p auth.Principal, id string) (*identityv1.ActingAppointment, error) {
	r, own, err := s.reachOf(ctx, p)
	if err != nil {
		return nil, err
	}
	a, ok, err := oneIn(ctx, s.store.db, r, strings.TrimSpace(id), false)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, notFound("That acting appointment was not found.")
	}
	return s.message(p, own, a, Today(s.now())), nil
}

// Options is who the caller may appoint, and when.
type Options struct {
	Entry      Role
	Candidates []Candidate
	Months     []Month
}

// Options lists eligible_appointees and month_options.
func (s *Service) Options(ctx context.Context, p auth.Principal) (Options, error) {
	entry, leader, err := s.mayAppoint(ctx, p)
	if err != nil {
		return Options{}, err
	}
	people, err := s.store.eligible(ctx, s.store.db, entry, *leader)
	if err != nil {
		return Options{}, err
	}
	return Options{Entry: entry, Candidates: people, Months: monthOptions(Today(s.now()))}, nil
}

// Preview is what the confirmation step states.
type Preview struct {
	Entry                                Role
	AppointeeName, MonthLabel, Effective string
	Statement                            string
}

// Preview is preview: validated as the appointment itself will be.
func (s *Service) Preview(ctx context.Context, p auth.Principal, staffID, month string) (Preview, error) {
	entry, leader, err := s.mayAppoint(ctx, p)
	if err != nil {
		return Preview{}, err
	}
	person, err := s.eligibleAppointee(ctx, s.store.db, p, entry, *leader, staffID)
	if err != nil {
		return Preview{}, err
	}
	start, end, err := appointableMonth(strings.TrimSpace(month), Today(s.now()))
	if err != nil {
		return Preview{}, err
	}
	if err := s.store.conflictAt(ctx, s.store.db, entry, leader.StaffID, person.UserID, start, ""); err != nil {
		return Preview{}, err
	}
	return Preview{
		Entry: entry, AppointeeName: person.Name, MonthLabel: monthLabel(start), Effective: effectiveLabel(start, end),
		Statement: confirmationStatement(entry, person.Name, start, end),
	}, nil
}

// confirmationStatement is confirmation_statement, word for word.
func confirmationStatement(entry Role, name string, start, end time.Time) string {
	first := strings.SplitN(name, " ", 2)[0]
	if first == "" {
		first = name
	}
	period := fmt.Sprintf("from %s %d through %s %d", start.Format("January"), start.Day(), end.Format("January"), end.Day())
	if entry.ScopeType == ScopePLTeam {
		return fmt.Sprintf("%s will receive %s operational access for your entire PL team, including your own "+
			"operational scope, %s. Your permanent PL role will remain unchanged.", first, entry.ShortLabel, period)
	}
	return fmt.Sprintf("%s will receive %s operational access for the country %s. Your permanent Country "+
		"Director role will remain unchanged.", first, entry.ShortLabel, period)
}

// ── Appoint ────────────────────────────────────────────────────────────────

func (s *Service) mayAppoint(ctx context.Context, p auth.Principal) (Role, *seat, error) {
	entry, ok := appointingPolicy(p)
	var leader *seat
	if ok {
		var err error
		if leader, err = s.store.seat(ctx, s.store.db, p.StaffProfileID); err != nil {
			return Role{}, nil, err
		}
	}
	if !ok || leader == nil {
		s.auditAlone(ctx, "acting_assignment.refused", p, nil, false,
			"Not a permanent leader who may appoint an acting leader.", nil)
		return Role{}, nil, forbidden("Only a Program Lead or Country Director, working in their own role, can appoint an acting leader.")
	}
	return entry, leader, nil
}

// eligibleAppointee is _eligible_appointee; someone outside the leader's
// reach or role is refused and the attempt audited (_audit_out_of_reach).
func (s *Service) eligibleAppointee(ctx context.Context, q queryer, p auth.Principal, entry Role, leader seat, staffID string) (Candidate, error) {
	wanted := strings.TrimSpace(staffID)
	if wanted == "" {
		return Candidate{}, refuse(fmt.Sprintf("Choose the %s to appoint.", entry.AppointeeRole))
	}
	people, err := s.store.eligible(ctx, q, entry, leader)
	if err != nil {
		return Candidate{}, err
	}
	for _, person := range people {
		if person.StaffID == wanted {
			return person, nil
		}
	}
	if len(wanted) > 30 {
		wanted = wanted[:30]
	}
	s.auditAlone(ctx, "acting_assignment.refused", p, nil, false,
		"Appointee is outside the appointing leader's reach or role.",
		map[string]any{"requested_staff_profile_id": wanted, "policy": entry.Key})
	return Candidate{}, forbidden(fmt.Sprintf("You can appoint only a %s in your own %s.", entry.AppointeeRole, strings.ToLower(entry.ScopeLabel)))
}

// Appoint is appoint: one acting leader, one seat, one calendar month.
func (s *Service) Appoint(ctx context.Context, p auth.Principal, staffID, month string) (*identityv1.ActingAppointment, error) {
	entry, leader, err := s.mayAppoint(ctx, p)
	if err != nil {
		return nil, err
	}
	now := s.now()
	today := Today(now)
	id := cuid.New()
	err = s.store.write(ctx, func(tx pgx.Tx) error {
		// The seat's own row serialises two appointments for one seat; the
		// unique constraints are what finally hold if anything gets past.
		if _, err := tx.Exec(ctx, `SELECT id FROM staff_profile WHERE id = $1 FOR UPDATE`, leader.StaffID); err != nil {
			return fmt.Errorf("acting: locking the seat: %w", err)
		}
		person, err := s.eligibleAppointee(ctx, tx, p, entry, *leader, staffID)
		if err != nil {
			return err
		}
		start, end, err := appointableMonth(strings.TrimSpace(month), today)
		if err != nil {
			return err
		}
		if err := s.store.conflictAt(ctx, tx, entry, leader.StaffID, person.UserID, start, ""); err != nil {
			return err
		}
		snapshot, err := s.grantSnapshot(ctx, tx, entry, *leader)
		if err != nil {
			return err
		}
		if err := insertAppointment(ctx, tx, id, entry, person, p, *leader, start, end, snapshot, now); err != nil {
			return err
		}
		if err := syncHint(ctx, tx, person.UserID); err != nil {
			return err
		}
		a, _, err := oneIn(ctx, tx, reach{all: true}, id, false)
		if err != nil {
			return err
		}
		return s.audit(ctx, tx, "acting_assignment.created", p, id, true, "", describe(a), now)
	})
	if err != nil {
		return nil, err
	}
	s.notify(ctx, NoticeAppointed, id)
	return s.reread(ctx, p, id)
}

func insertAppointment(ctx context.Context, tx pgx.Tx, id string, entry Role, person Candidate, p auth.Principal,
	leader seat, start, end time.Time, snapshot map[string]any, now time.Time) error {
	encoded, err := json.Marshal(snapshot)
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `
INSERT INTO acting_assignment (id, created_at, updated_at, role_key, acting_role, appointee_id, appointee_role,
  appointed_by_id, appointed_by_role, scope_type, seat_id, country, start_date, end_date, cancel_reason,
  in_capacity, grant_snapshot, revisions)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, '', true, $14, '[]'::jsonb)`,
		id, now, entry.Key, entry.ActingRole, person.UserID, entry.AppointeeRole, p.UserID, entry.AppointerRole,
		entry.ScopeType, leader.StaffID, leader.Country, start, end, encoded)
	if isUniqueViolation(err) {
		return conflict("An acting appointment for that month was made a moment ago. Reload the page to see it.")
	}
	if err != nil {
		return fmt.Errorf("acting: recording the appointment: %w", err)
	}
	return nil
}

// grantSnapshot is grant_snapshot: what was granted, as it stood that day.
func (s *Service) grantSnapshot(ctx context.Context, q queryer, entry Role, leader seat) (map[string]any, error) {
	members, err := s.store.seatMembers(ctx, q, entry, leader)
	if err != nil {
		return nil, err
	}
	snapshot := map[string]any{
		"policy": entry.Key, "acting_role": entry.ActingRole, "scope_type": entry.ScopeType,
		"seat": map[string]any{
			"staff_profile_id": leader.StaffID, "user_id": leader.UserID, "name": leader.Name, "country": leader.Country,
		},
		"seat_members": members,
	}
	for key, value := range entry.Granted {
		snapshot[key] = value
	}
	return snapshot, nil
}

// ── Change and cancel ──────────────────────────────────────────────────────

// Cancel is cancel: an upcoming or active appointment ends now. The record
// is kept.
func (s *Service) Cancel(ctx context.Context, p auth.Principal, id, reason string) (*identityv1.ActingAppointment, error) {
	r, own, err := s.reachOf(ctx, p)
	if err != nil {
		return nil, err
	}
	now := s.now()
	var refused *Appointment
	err = s.store.write(ctx, func(tx pgx.Tx) error {
		a, ok, err := oneIn(ctx, tx, r, strings.TrimSpace(id), true)
		if err != nil {
			return err
		}
		if !ok {
			return notFound("That acting appointment was not found.")
		}
		if !mayManage(p, own, a) {
			refused = &a
			return forbidden("You cannot cancel this acting appointment.")
		}
		was := state(a.Start, a.End, a.CancelledAt != nil, Today(now))
		if was != stateUpcoming && was != stateActive {
			return refuse(fmt.Sprintf("This appointment is already %s.", strings.ToLower(stateLabels[was])))
		}
		reason = strings.TrimSpace(reason)
		if len(reason) > 512 {
			reason = reason[:512]
		}
		if _, err := tx.Exec(ctx, `
UPDATE acting_assignment SET cancelled_at = $2, cancelled_by_id = $3, cancel_reason = $4, updated_at = $2
WHERE id = $1`, a.ID, now, p.UserID, reason); err != nil {
			return fmt.Errorf("acting: cancelling: %w", err)
		}
		if err := syncHint(ctx, tx, a.AppointeeID); err != nil {
			return err
		}
		a.CancelledAt, a.CancelReason = &now, reason
		payload := describe(a)
		payload["state_when_cancelled"] = was
		payload["reason"] = reason
		return s.audit(ctx, tx, "acting_assignment.cancelled", p, a.ID, true, "", payload, now)
	})
	if refused != nil {
		// Kept after the refused transaction has unwound.
		s.auditAlone(ctx, "acting_assignment.refused", p, &refused.ID, false,
			"Not permitted to cancel this acting appointment.", nil)
	}
	if err != nil {
		return nil, err
	}
	s.notify(ctx, NoticeCancelled, id)
	return s.reread(ctx, p, id)
}

// ChangeMonth is reschedule: an appointment that has not begun moves to
// another month, its first month kept on the row. One that has begun is
// never edited.
func (s *Service) ChangeMonth(ctx context.Context, p auth.Principal, id, month string) (*identityv1.ActingAppointment, error) {
	r, own, err := s.reachOf(ctx, p)
	if err != nil {
		return nil, err
	}
	now := s.now()
	today := Today(now)
	changed := false
	err = s.store.write(ctx, func(tx pgx.Tx) error {
		a, ok, err := oneIn(ctx, tx, r, strings.TrimSpace(id), true)
		if err != nil {
			return err
		}
		if !ok {
			return notFound("That acting appointment was not found.")
		}
		if !mayChangeMonth(p, own, a) {
			return forbidden("Only the appointing leader can change this appointment.")
		}
		if state(a.Start, a.End, a.CancelledAt != nil, today) != stateUpcoming {
			return refuse("Only an appointment that has not begun can be changed. Cancel this one and make a new appointment instead.")
		}
		start, end, err := appointableMonth(strings.TrimSpace(month), today)
		if err != nil || start.Equal(a.Start) {
			return err
		}
		entry, ok := ByKey(a.RoleKey)
		if !ok {
			return refuse("This appointment's kind is no longer offered.")
		}
		if err := s.store.conflictAt(ctx, tx, entry, a.SeatID, a.AppointeeID, start, a.ID); err != nil {
			return err
		}
		before := describe(a)
		revisions := make([]any, 0, len(a.Revisions)+1)
		for _, revision := range a.Revisions {
			revisions = append(revisions, revision)
		}
		revisions = append(revisions, map[string]any{
			"start_date": a.Start.Format("2006-01-02"), "end_date": a.End.Format("2006-01-02"),
			"changed_at": now.Format(time.RFC3339Nano), "changed_by": p.UserID,
		})
		encoded, err := json.Marshal(revisions)
		if err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `
UPDATE acting_assignment SET start_date = $2, end_date = $3, revisions = $4, reminded_at = NULL, updated_at = $5
WHERE id = $1`, a.ID, start, end, encoded, now)
		if isUniqueViolation(err) {
			return conflict("Another acting appointment already stands for that month.")
		}
		if err != nil {
			return fmt.Errorf("acting: changing the month: %w", err)
		}
		if err := syncHint(ctx, tx, a.AppointeeID); err != nil {
			return err
		}
		a.Start, a.End = start, end
		changed = true
		return s.audit(ctx, tx, "acting_assignment.updated", p, a.ID, true, "",
			map[string]any{"before": before, "after": describe(a)}, now)
	})
	if err != nil {
		return nil, err
	}
	if changed {
		s.notify(ctx, NoticeRescheduled, id)
	}
	return s.reread(ctx, p, id)
}

func (s *Service) reread(ctx context.Context, p auth.Principal, id string) (*identityv1.ActingAppointment, error) {
	r, own, err := s.reachOf(ctx, p)
	if err != nil {
		return nil, err
	}
	a, ok, err := oneIn(ctx, s.store.db, r, id, false)
	if err != nil || !ok {
		return nil, err
	}
	return s.message(p, own, a, Today(s.now())), nil
}

// ── The appointee's own capacity ───────────────────────────────────────────

// SetCapacity is set_capacity: the appointee works in the acting capacity,
// or in their own role. Entering it also puts the account in the role the
// appointment was made from, so the capacity takes effect (the web switches
// the flag alone, and an account switched to another role it holds then
// saw nothing change).
func (s *Service) SetCapacity(ctx context.Context, p auth.Principal, acting bool) (*identityv1.ActingCapacity, string, error) {
	if p.Acting == nil {
		return nil, "", refuse("You have no active acting appointment.")
	}
	now := s.now()
	switched := acting && p.ActiveRole != p.Acting.AppointeeRole
	err := s.store.write(ctx, func(tx pgx.Tx) error {
		if switched {
			if err := switchRole(ctx, tx, p, p.Acting.AppointeeRole, now); err != nil {
				return err
			}
		}
		return SetCapacityInTx(ctx, tx, p, acting, now)
	})
	if err != nil {
		return nil, "", err
	}
	token := ""
	if switched && s.issue != nil {
		if token, err = s.issue(p.UserID, p.Acting.AppointeeRole, now); err != nil {
			return nil, "", err
		}
	}
	capacity := *p.Acting
	capacity.InCapacity = acting
	return CapacityOf(&capacity), token, nil
}

// SetCapacityInTx switches the capacity inside tx and audits a change; a
// switch to what it already is writes nothing. Role switching calls it to
// leave the acting capacity when the person goes back to a role they hold.
func SetCapacityInTx(ctx context.Context, tx pgx.Tx, p auth.Principal, acting bool, now time.Time) error {
	if p.Acting == nil || p.Acting.InCapacity == acting {
		return nil
	}
	if _, err := tx.Exec(ctx, `UPDATE acting_assignment SET in_capacity = $2, updated_at = $3 WHERE id = $1`,
		p.Acting.AppointmentID, acting, now); err != nil {
		return fmt.Errorf("acting: switching the capacity: %w", err)
	}
	a, ok, err := oneIn(ctx, tx, reach{all: true}, p.Acting.AppointmentID, false)
	if err != nil || !ok {
		return err
	}
	action := "acting_capacity.left"
	if acting {
		action = "acting_capacity.entered"
	}
	_, err = audit.Append(ctx, tx, audit.Entry{
		Action: action, SubjectKind: audit.Text("ActingAssignment"), SubjectID: audit.Text(a.ID),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true, Payload: describe(a),
	}, now)
	return err
}

// switchRole is the existing role switch, audited as one.
func switchRole(ctx context.Context, tx pgx.Tx, p auth.Principal, role string, now time.Time) error {
	if _, err := tx.Exec(ctx, `UPDATE "user" SET active_role = $2, updated_at = $3 WHERE id = $1`, p.UserID, role, now); err != nil {
		return fmt.Errorf("acting: switching role: %w", err)
	}
	_, err := audit.Append(ctx, tx, audit.Entry{
		Action: "role_switch", SubjectKind: audit.Text("User"), SubjectID: audit.Text(p.UserID),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(role), Success: true,
		Payload: map[string]any{"old_role": p.ActiveRole, "new_role": role},
	}, now)
	return err
}

// CapacityOf is the session's view of an appointment.
func CapacityOf(a *auth.ActingAppointment) *identityv1.ActingCapacity {
	if a == nil {
		return nil
	}
	return &identityv1.ActingCapacity{
		AppointmentId: a.AppointmentID, Label: a.Label, ShortLabel: a.ShortLabel, MonthLabel: a.MonthLabel,
		SeatName: a.SeatName, AppointeeRole: a.AppointeeRole, InCapacity: a.InCapacity,
	}
}

// ── Audit ──────────────────────────────────────────────────────────────────

// scopeLabel is scope_label: "John Lead's PL team", or the country.
func scopeLabel(a Appointment) string {
	if a.ScopeType == ScopePLTeam {
		if a.SeatName != "" {
			return a.SeatName + "'s PL team"
		}
		return "PL team"
	}
	if a.Country != "" {
		return a.Country
	}
	return "Country"
}

func labelOf(a Appointment) string {
	if entry, ok := ByKey(a.RoleKey); ok {
		return entry.Label
	}
	return a.RoleKey
}

// describe is _describe, key for key.
func describe(a Appointment) map[string]any {
	return map[string]any{
		"assignment_id": a.ID,
		"acting_role":   a.ActingRole,
		"acting_label":  labelOf(a),
		"appointee": map[string]any{
			"user_id": a.AppointeeID, "name": a.AppointeeName, "permanent_role": a.AppointeeRole,
		},
		"appointed_by": map[string]any{
			"user_id": a.AppointedByID, "name": a.AppointedByName, "role": a.ByRole,
		},
		"scope_type":            a.ScopeType,
		"scope":                 scopeLabel(a),
		"seat_staff_profile_id": a.SeatID,
		"country":               a.Country,
		"month":                 monthLabel(a.Start),
		"start_date":            a.Start.Format("2006-01-02"),
		"end_date":              a.End.Format("2006-01-02"),
	}
}

func (s *Service) audit(ctx context.Context, tx pgx.Tx, action string, p auth.Principal, subjectID string,
	success bool, reason string, payload map[string]any, now time.Time) error {
	entry := audit.Entry{
		Action: action, SubjectKind: audit.Text("ActingAssignment"), SubjectID: audit.Text(subjectID),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: success, Reason: audit.Text(reason),
	}
	if payload != nil {
		entry.Payload = payload
	}
	_, err := audit.Append(ctx, tx, entry, now)
	return err
}

// auditAlone writes a refusal in a transaction of its own, so the attempt
// is kept when nothing else of it is. A refusal that cannot be audited is
// still a refusal.
func (s *Service) auditAlone(ctx context.Context, action string, p auth.Principal, subjectID *string,
	success bool, reason string, payload map[string]any) {
	id := ""
	if subjectID != nil {
		id = *subjectID
	}
	_ = s.store.write(ctx, func(tx pgx.Tx) error {
		return s.audit(ctx, tx, action, p, id, success, reason, payload, s.now())
	})
}

// ── The contract's view ────────────────────────────────────────────────────

func (s *Service) message(p auth.Principal, own *seat, a Appointment, today time.Time) *identityv1.ActingAppointment {
	st := state(a.Start, a.End, a.CancelledAt != nil, today)
	m := &identityv1.ActingAppointment{
		Id: a.ID, RoleKey: a.RoleKey, Label: labelOf(a), AppointeeUserId: a.AppointeeID, AppointeeName: a.AppointeeName,
		AppointeeRole: a.AppointeeRole, AppointedByName: a.AppointedByName, AppointedByRole: a.ByRole,
		ScopeLabel: scopeLabel(a), Month: monthValue(a.Start), MonthLabel: monthLabel(a.Start),
		EffectiveLabel: effectiveLabel(a.Start, a.End), State: st, StateLabel: stateLabels[st],
		CancelledByName: a.CancelledByName, CancelReason: a.CancelReason,
		CanCancel:      (st == stateUpcoming || st == stateActive) && mayManage(p, own, a),
		CanChangeMonth: st == stateUpcoming && mayChangeMonth(p, own, a),
	}
	if entry, ok := ByKey(a.RoleKey); ok {
		m.ShortLabel = entry.ShortLabel
	}
	if a.CancelledAt != nil {
		m.CancelledAt = a.CancelledAt.Format(time.RFC3339)
	}
	for _, revision := range a.Revisions {
		if start, ok := revision["start_date"].(string); ok {
			if day, err := time.Parse("2006-01-02", start); err == nil {
				m.EarlierMonths = append(m.EarlierMonths, monthLabel(day))
			}
		}
	}
	return m
}
