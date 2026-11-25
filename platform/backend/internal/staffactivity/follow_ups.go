package staffactivity

// Manager follow-ups from the Staff Activity Log (apps.staff_activity.
// follow_ups): who may raise one about whom, who may take which step, and
// the reads the drawers and the page draw. A Programme Lead follows up with
// the people they supervise; a Country Director's follow-up about someone a
// Lead manages goes to that Lead. A follow-up is support and changes nobody's
// record.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// ErrHandedOn is the existing application's case: Go does not answer it.
var ErrHandedOn = errPassOn

// Refused is the view's refusal (HttpResponseForbidden, a 404), its words
// the existing view's.
type Refused struct {
	Message  string
	NotFound bool
}

func (r *Refused) Error() string { return r.Message }

// FollowUpError is follow_ups.FollowUpError: a step the reader may not take,
// its words shown to them.
type FollowUpError struct{ Message string }

func (e *FollowUpError) Error() string { return e.Message }

const (
	followUpEvent          = "staff_activity.follow_up"
	followUpEscalatedEvent = "staff_activity.follow_up_escalated"
	followUpContext        = "StaffUsageFollowUp"
	followUpCategory       = "staff_activity"
	routeManager           = "manager_to_staff"
	routeDirector          = "director_to_manager"
	statusSent             = "sent"
	statusEscalated        = "escalated"
	statusClosed           = "closed"
	statusResolvedManager  = "resolved_by_manager"
	statusResolvedActivity = "resolved_by_activity"
	priorityHigh           = "high"
	// FollowUpQueuePath is the header's Follow-up Queue (follow_up_queue_view).
	FollowUpQueuePath = followUpQueueURL
	// followUpPrefix is one follow-up (follow_up_detail_view).
	followUpPrefix = "/staff-activity/follow-ups/"
	// defaultDueDays is default_due_date's three days.
	defaultDueDays = 3
	queueLimit     = 200
	closedShown    = 20
	noteMax        = 4000
	historyNoteMax = 1000
	auditNoteMax   = 500
)

var priorities = [][2]string{{"low", "Low"}, {"normal", "Normal"}, {"high", "High"}}

var routes = [][2]string{{routeManager, "Manager to staff member"}, {routeDirector, "Country Director to manager"}}

var resolvedStatuses = []string{"resolved_by_activity", statusResolvedManager, statusClosed, "canceled"}

// autoResolve is AUTO_RESOLVE: what the platform sees resolve a follow-up.
var autoResolve = map[string]string{
	"no_login":          "login",
	"low_engagement":    "action",
	"planning_not_done": "Planning",
	"evidence_not_done": "Evidence",
}

// step is one TRANSITIONS entry.
type step struct {
	key, label, to, by, route string
	from                      []string
	noteRequired              bool
}

func openStatuses() []string { return rules.FollowUpOpenStatuses }

// steps is TRANSITIONS, in its order.
var steps = []step{
	{key: "acknowledge", label: "Acknowledge", from: []string{statusSent, statusEscalated}, to: "acknowledged", by: "assignee"},
	{key: "schedule_support", label: "Support scheduled", from: []string{statusSent, "acknowledged", "waiting_for_staff"},
		to: "support_scheduled", by: "manager"},
	{key: "wait_for_staff", label: "Waiting for staff", from: []string{statusSent, "acknowledged", "support_scheduled"},
		to: "waiting_for_staff", by: "manager"},
	{key: "return", label: "Return for clarification", from: []string{statusSent, "acknowledged"}, to: "returned",
		by: "assignee", noteRequired: true},
	{key: "resend", label: "Send again", from: []string{"returned"}, to: statusSent, by: "creator", noteRequired: true},
	{key: "escalate", label: "Escalate to the Country Director",
		from: []string{statusSent, "acknowledged", "support_scheduled", "waiting_for_staff"}, to: statusEscalated,
		by: "creator", route: routeManager, noteRequired: true},
	{key: "resolve", label: "Resolve", from: nil, to: statusResolvedManager, by: "manager", noteRequired: true},
	{key: "close", label: "Close", from: []string{"resolved_by_activity", statusResolvedManager}, to: statusClosed, by: "creator"},
	{key: "cancel", label: "Cancel", from: nil, to: "canceled", by: "creator", noteRequired: true},
}

func stepFor(key string) (step, bool) {
	for _, s := range steps {
		if s.key == key {
			return s, true
		}
	}
	return step{}, false
}

func (s step) fromStatuses() []string {
	if s.from == nil {
		return openStatuses()
	}
	return s.from
}

// StepAction is one step open to the reader (actions_for).
type StepAction struct {
	Key, Label   string
	NoteRequired bool
}

// account is a party's name and address.
type party struct{ id, name, email string }

// firstOf is {% firstof name email %}.
func (a party) firstOf() string {
	if a.name != "" {
		return a.name
	}
	return a.email
}

// named is follow_ups._name.
func (a party) named() string {
	if a.id == "" {
		return "Someone"
	}
	if s := a.firstOf(); s != "" {
		return s
	}
	return "Someone"
}

// followUp is one StaffUsageFollowUp row with its parties.
type followUp struct {
	id, route, periodKey, trigger, note, priority, status, resolution string
	subject, assignee, createdBy                                      party
	snapshot                                                          map[string]any
	due, createdAt                                                    time.Time
	history                                                           []map[string]any
	overdue                                                           bool
}

func (f *followUp) isOpen() bool { return slices.Contains(openStatuses(), f.status) }

func (f *followUp) triggerLabel() string { return choice(rules.Person.FollowUpTriggers, f.trigger) }

func (f *followUp) statusLabel() string { return choice(rules.Person.FollowUpStatuses, f.status) }

const followUpSelect = `SELECT f.id, f.route, f.period_key, f.trigger, f.note, f.priority, f.status, f.resolution,
  f.subject_id, COALESCE(su.name, ''), COALESCE(su.email, ''), f.assignee_id, COALESCE(au.name, ''), COALESCE(au.email, ''),
  COALESCE(f.created_by_id, ''), COALESCE(cu.name, ''), COALESCE(cu.email, ''),
  f.snapshot, f.due_date, f.created_at, f.history
FROM staff_usage_follow_up f
JOIN "user" su ON su.id = f.subject_id
JOIN "user" au ON au.id = f.assignee_id
LEFT JOIN "user" cu ON cu.id = f.created_by_id`

func scanFollowUp(r pgx.Row) (*followUp, error) {
	var f followUp
	var snapshot, history []byte
	if err := r.Scan(&f.id, &f.route, &f.periodKey, &f.trigger, &f.note, &f.priority, &f.status, &f.resolution,
		&f.subject.id, &f.subject.name, &f.subject.email, &f.assignee.id, &f.assignee.name, &f.assignee.email,
		&f.createdBy.id, &f.createdBy.name, &f.createdBy.email, &snapshot, &f.due, &f.createdAt, &history); err != nil {
		return nil, err
	}
	if len(snapshot) > 0 {
		if err := json.Unmarshal(snapshot, &f.snapshot); err != nil {
			return nil, fmt.Errorf("staffactivity: reading a follow-up's snapshot: %w", err)
		}
	}
	if len(history) > 0 {
		var entries []any
		if err := json.Unmarshal(history, &entries); err != nil {
			return nil, fmt.Errorf("staffactivity: reading a follow-up's history: %w", err)
		}
		for _, e := range entries {
			m, ok := e.(map[string]any)
			if !ok {
				return nil, errPassOn // history_rows reads dicts only
			}
			f.history = append(f.history, m)
		}
	}
	return &f, nil
}

// loadFollowUp is get_object_or_404; nil when there is none.
func (s *Service) loadFollowUp(ctx context.Context, id string) (*followUp, error) {
	f, err := scanFollowUp(s.db.QueryRow(ctx, followUpSelect+` WHERE f.id = $1`, id))
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("staffactivity: reading the follow-up: %w", err)
	}
	return f, nil
}

// viewerScope is services.viewer_scope; nil when the log is not the reader's.
type viewerScope struct {
	ids         []string
	selfID      string
	canFollowUp bool
}

func (v *viewerScope) holds(id string) bool { return v != nil && slices.Contains(v.ids, id) }

// scope is viewer_scope. A Lead in an acting appointment reads the seat's
// team too (seat(user, SCOPE_PL_TEAM)), which Go does not read: handed on.
func (s *Service) scope(ctx context.Context, p auth.Principal) (*viewerScope, error) {
	switch p.ActiveRole {
	case rules.Roles.ProgramLead:
		if p.Acting != nil {
			return nil, errPassOn
		}
		ids, err := s.teamIDs(ctx, p, s.now())
		if err != nil {
			return nil, err
		}
		v := &viewerScope{ids: ids, canFollowUp: true}
		if slices.Contains(ids, p.UserID) {
			v.selfID = p.UserID
		}
		return v, nil
	case rules.Roles.CountryDirector, rules.Roles.Admin:
		country, err := readerCountry(ctx, s.db, p.UserID)
		if err != nil {
			return nil, err
		}
		ids, err := countryRoster(ctx, s.db, p.UserID, country)
		if err != nil {
			return nil, err
		}
		return &viewerScope{ids: ids, canFollowUp: p.ActiveRole == rules.Roles.CountryDirector}, nil
	}
	return nil, nil
}

// parts is _party: creator, assignee, manager.
func (f *followUp) parts(userID string) map[string]bool {
	out := map[string]bool{}
	if userID == "" {
		return out
	}
	if userID == f.createdBy.id {
		out["creator"] = true
	}
	if userID == f.assignee.id {
		out["assignee"] = true
	}
	if f.route == routeManager && out["creator"] {
		out["manager"] = true
	}
	if f.route == routeDirector && out["assignee"] {
		out["manager"] = true
	}
	return out
}

// canView is can_view.
func (s *Service) canView(ctx context.Context, f *followUp, p auth.Principal) (bool, error) {
	if len(f.parts(p.UserID)) > 0 {
		return true, nil
	}
	if p.ActiveRole != rules.Roles.CountryDirector && p.ActiveRole != rules.Roles.ProgramLead {
		return false, nil
	}
	v, err := s.scope(ctx, p)
	if err != nil {
		return false, err
	}
	return v.holds(f.subject.id), nil
}

// actionsFor is actions_for.
func (f *followUp) actionsFor(p auth.Principal) []StepAction {
	parts := f.parts(p.UserID)
	director := p.ActiveRole == rules.Roles.CountryDirector
	var out []StepAction
	for _, st := range steps {
		if !slices.Contains(st.fromStatuses(), f.status) || !parts[st.by] {
			continue
		}
		if st.route != "" && st.route != f.route {
			continue
		}
		if f.status == statusEscalated && st.key == "acknowledge" && !director {
			continue
		}
		out = append(out, StepAction{Key: st.key, Label: st.label, NoteRequired: st.noteRequired})
	}
	if f.status == statusEscalated && director {
		for _, key := range []string{"acknowledge", "resolve"} {
			if !slices.ContainsFunc(out, func(a StepAction) bool { return a.Key == key }) {
				st, _ := stepFor(key)
				out = append(out, StepAction{Key: st.key, Label: st.label, NoteRequired: st.noteRequired})
			}
		}
	}
	return out
}

// sweepAnswers is sweep_auto_resolutions' reading: the follow-ups among
// these whose condition the audit chain shows met after they were sent,
// with the reason it would record (_auto_reason).
func (s *Service) sweepAnswers(ctx context.Context, rows []*followUp) (map[string]string, error) {
	var pending []*followUp
	subjects := map[string]bool{}
	var earliest time.Time
	for _, f := range rows {
		need := autoResolve[f.trigger]
		if !f.isOpen() || f.status == statusEscalated || need == "" || need == "login" {
			continue
		}
		pending = append(pending, f)
		subjects[f.subject.id] = true
		if earliest.IsZero() || f.createdAt.Before(earliest) {
			earliest = f.createdAt
		}
	}
	answered := map[string]string{}
	if len(pending) == 0 {
		return answered, nil
	}
	ids := make([]string, 0, len(subjects))
	for id := range subjects {
		ids = append(ids, id)
	}
	actions := make([]string, 0, len(rules.MeaningfulActions))
	for key := range rules.MeaningfulActions {
		actions = append(actions, key)
	}
	type done struct {
		module string
		at     time.Time
	}
	seen := map[string][]done{}
	err := collect(ctx, s.db, "the follow-ups' answering actions", `SELECT actor_id, action, created_at FROM audit_log
WHERE actor_id = ANY($1) AND created_at >= $2 AND action = ANY($3) AND success ORDER BY created_at`, func(r pgx.Rows) error {
		var actor, action string
		var at time.Time
		if err := r.Scan(&actor, &action, &at); err != nil {
			return err
		}
		seen[actor] = append(seen[actor], done{module: rules.MeaningfulActions[action].Module, at: at})
		return nil
	}, ids, earliest, actions)
	if err != nil {
		return nil, err
	}
	for _, f := range pending {
		need := autoResolve[f.trigger]
		for _, d := range seen[f.subject.id] {
			if !d.at.Before(f.createdAt) && (need == "action" || d.module == need) {
				answered[f.id] = autoReason(need)
				break
			}
		}
	}
	return answered, nil
}

// autoReason is _auto_reason for what a follow-up waited for.
func autoReason(need string) string {
	switch need {
	case "login":
		return "Signed in."
	case "action":
		return "Completed a meaningful action."
	}
	return "Completed " + strings.ToLower(need) + " work."
}

// asSwept draws these as the existing read draws them after its sweep: the
// answered ones resolved by activity (the row's status alone, as the sweep
// sets it on the instance it was given). Go writes nothing on a read; the
// resolution itself is the existing application's (doc 189).
func (s *Service) asSwept(ctx context.Context, rows []*followUp) error {
	answered, err := s.sweepAnswers(ctx, rows)
	if err != nil {
		return err
	}
	for _, f := range rows {
		if _, ok := answered[f.id]; ok {
			f.status = statusResolvedActivity
		}
	}
	return nil
}

// queue is queue_for.
type queue struct {
	toMe, fromMe, recentClosed []*followUp
	openCount                  int
}

func (s *Service) queueFor(ctx context.Context, p auth.Principal) (*queue, error) {
	var rows []*followUp
	read := func(sql string, args ...any) error {
		found, err := s.db.Query(ctx, sql, args...)
		if err != nil {
			return fmt.Errorf("staffactivity: reading the follow-up queue: %w", err)
		}
		defer found.Close()
		for found.Next() {
			f, err := scanFollowUp(found)
			if err != nil {
				return err
			}
			rows = append(rows, f)
		}
		return found.Err()
	}
	if err := read(followUpSelect+` WHERE f.assignee_id = $1 OR f.created_by_id = $1
ORDER BY f.due_date ASC, f.created_at DESC LIMIT $2`, p.UserID, queueLimit); err != nil {
		return nil, err
	}
	director := p.ActiveRole == rules.Roles.CountryDirector
	if director {
		have := make([]string, 0, len(rows))
		for _, f := range rows {
			have = append(have, f.id)
		}
		if err := read(followUpSelect+` WHERE f.status = $1 AND NOT (f.id = ANY($2)) ORDER BY f.created_at DESC`,
			statusEscalated, have); err != nil {
			return nil, err
		}
	}
	if err := s.asSwept(ctx, rows); err != nil {
		return nil, err
	}
	today := dateOf(s.now())
	q := &queue{}
	for _, f := range rows {
		f.overdue = f.isOpen() && f.due.Before(today)
		if !f.isOpen() {
			if len(q.recentClosed) < closedShown {
				q.recentClosed = append(q.recentClosed, f)
			}
			continue
		}
		q.openCount++
		if (f.assignee.id == p.UserID && f.status != statusEscalated) || (f.status == statusEscalated && director) {
			q.toMe = append(q.toMe, f)
		}
		if f.createdBy.id == p.UserID {
			q.fromMe = append(q.fromMe, f)
		}
	}
	return q, nil
}

// recipient is recipient_for: (assignee, route) for a follow-up the sender
// raises about this person.
func (s *Service) recipient(ctx context.Context, p auth.Principal, subject party) (party, string, error) {
	if p.ActiveRole == rules.Roles.CountryDirector {
		leadOf, _, err := programLeads(ctx, s.db)
		if err != nil {
			return party{}, "", err
		}
		if id := leadOf[subject.id]; id != "" && id != p.UserID {
			var lead party
			err := s.db.QueryRow(ctx, `SELECT id, COALESCE(name, ''), COALESCE(email, '') FROM "user" WHERE id = $1 AND is_active`, id).
				Scan(&lead.id, &lead.name, &lead.email)
			if err == nil {
				return lead, routeDirector, nil
			}
			if !errors.Is(err, pgx.ErrNoRows) {
				return party{}, "", fmt.Errorf("staffactivity: reading the Programme Lead: %w", err)
			}
		}
	}
	return subject, routeManager, nil
}

func (s *Service) account(ctx context.Context, id string) (party, error) {
	a := party{id: id}
	err := s.db.QueryRow(ctx, `SELECT COALESCE(name, ''), COALESCE(email, '') FROM "user" WHERE id = $1`, id).Scan(&a.name, &a.email)
	if err != nil {
		return party{}, fmt.Errorf("staffactivity: reading the account: %w", err)
	}
	return a, nil
}

// trimmed is Python's str.strip.
func trimmed(s string) string { return strings.TrimSpace(s) }
