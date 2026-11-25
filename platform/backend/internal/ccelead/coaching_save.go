package ccelead

// A Programme Lead's coaching records (apps.cce_leadership.coaching):
// recorded, corrected until the officer acknowledges them, shared with the
// officer (who is told and asked to acknowledge), and their follow-up closed.
// Each check is the existing one, in its order and words.

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// CoachingRefusal is a coaching rule saying no, in the existing words.
type CoachingRefusal struct {
	Message           string
	NotFound, Refused bool
}

func (r *CoachingRefusal) Error() string { return r.Message }

func badRequest(m string) error { return &CoachingRefusal{Message: m} }
func forbidden(m string) error  { return &CoachingRefusal{Message: m, Refused: true} }
func missing(m string) error    { return &CoachingRefusal{Message: m, NotFound: true} }

// CoachingKinds are CoachingKind's choices, in order; the last, Regional
// Lead feedback passed on, is never recorded by hand (RECORDABLE_KINDS).
var CoachingKinds = [][2]string{
	{"one_to_one", "Monthly one-to-one"},
	{"field_observation", "School visit observation"},
	{"training_observation", "Training observation"},
	{"performance_checkin", "Performance check-in"},
	{"debrief_feedback", "Field debrief feedback"},
	{"recognition", "Recognition"},
	{"regional_feedback", "Regional Lead feedback passed on"},
}

// ObservationCriteria are OBSERVATION_CRITERIA: field, label, hint.
var ObservationCriteria = [][3]string{
	{"rating_biblical_integration", "Biblical integration", "Christ-centered values are woven through the content, not added on."},
	{"rating_need_alignment", "Answers the schools' SSA need", "The content targets the needs the schools' SSA results show."},
	{"rating_facilitation", "Facilitation quality", "Clear, well paced and modelled on good teaching practice."},
	{"rating_participation", "Participant engagement", "Teachers and leaders practise, question and contribute."},
	{"rating_application", "Practical application in schools", "Participants leave with practice they can use and be coached on."},
}

// RatingScale is RATING_SCALE.
var RatingScale = [][2]string{{"1", "1 · Not evident"}, {"2", "2 · Emerging"}, {"3", "3 · Established"}, {"4", "4 · Exemplary"}}

// RatedKind is RATED_KINDS.
func RatedKind(kind string) bool {
	return kind == "field_observation" || kind == "training_observation"
}

// RecordableKind is RECORDABLE_KINDS.
func RecordableKind(kind string) bool {
	if kind == "regional_feedback" {
		return false
	}
	for _, k := range CoachingKinds {
		if k[0] == kind {
			return true
		}
	}
	return false
}

// KindLabel is KIND_LABELS.
func KindLabel(kind string) string {
	for _, k := range CoachingKinds {
		if k[0] == kind {
			return k[1]
		}
	}
	return kind
}

const (
	eventShared        = "cceo_coaching_shared"
	activityLookback   = 120
	activityLookahead  = 14
	debriefLookback    = 60
	leadOnly           = "Only the officer's Programme Lead records coaching."
	notYoursToChange   = "Only the Programme Lead who wrote this coaching changes it."
	coachingNotFound   = "Coaching record not found."
	alreadyAcknowleged = "The officer has acknowledged this coaching, so it can no longer be changed."
)

// notLive are NOT_LIVE_STATUSES.
var notLive = []string{"cancelled", "rejected", "deferred", "not_planned", "awaiting_owner_approval"}

// Coaching is the coaching saves over the gateway's pool.
type Coaching struct {
	DB      *pgxpool.Pool
	Push    activities.NoticePush
	Logger  *slog.Logger
	Now     func() time.Time
	Kampala *time.Location
}

func (c Coaching) now() time.Time {
	if c.Now != nil {
		return c.Now()
	}
	return time.Now()
}

func (c Coaching) today() time.Time {
	loc := c.Kampala
	if loc == nil {
		loc = time.UTC
	}
	l := c.now().In(loc)
	return time.Date(l.Year(), l.Month(), l.Day(), 0, 0, 0, 0, time.UTC)
}

// Officer is one team member a lead may coach.
type Officer struct{ StaffID, UserID, Name string }

// Team is coaching._team: the lead's team, by name.
func (c Coaching) Team(ctx context.Context, p auth.Principal) ([]Officer, error) {
	team, err := leadTeam(ctx, c.DB, p.StaffProfileID, c.now())
	if err != nil {
		return nil, err
	}
	out := make([]Officer, 0, len(team))
	for _, o := range team {
		out = append(out, Officer{StaffID: o.staff, UserID: o.user, Name: o.name})
	}
	return out, nil
}

// IsLead is _is_lead / _require_program_lead.
func IsLead(p auth.Principal) bool { return p.ActiveRole == programLead }

// OfficerFor is coaching.officer_for: a team member by either id.
func OfficerFor(team []Officer, id string) *Officer {
	id = strings.TrimSpace(id)
	if id == "" {
		return nil
	}
	for i := range team {
		if id == team[i].StaffID || id == team[i].UserID {
			return &team[i]
		}
	}
	return nil
}

// Choice is one option of a drawer's select.
type Choice struct{ Value, Label string }

// ActivityChoices is _activity_options: the officers' recent and imminent
// work, newest first, each named for the officer when several are offered.
func (c Coaching) ActivityChoices(ctx context.Context, scope []Officer, named bool) ([]Choice, error) {
	owners, byID := ownerIDs(scope)
	if len(owners) == 0 {
		return nil, nil
	}
	today := c.today()
	rows, err := c.DB.Query(ctx, `SELECT a.id, COALESCE(a.responsible_staff_id, ''), COALESCE(a.monitored_by_staff_id, ''),
  NULLIF(a.activity_name_snapshot, ''), a.activity_type, s.name, cl.name, a.planned_date
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
WHERE (a.responsible_staff_id = ANY($1) OR a.monitored_by_staff_id = ANY($1)) AND a.deleted_at IS NULL
  AND a.planned_date >= $2::date AND a.planned_date <= $3::date AND NOT (COALESCE(a.status, '') = ANY($4))
ORDER BY a.planned_date DESC, a.id LIMIT 200`, owners, today.AddDate(0, 0, -activityLookback).Format(time.DateOnly),
		today.AddDate(0, 0, activityLookahead).Format(time.DateOnly), notLive)
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the officers' work: %w", err)
	}
	defer rows.Close()
	var out []Choice
	for rows.Next() {
		var id, resp, mon string
		var o observation
		if err := rows.Scan(&id, &resp, &mon, &o.name, &o.kind, &o.school, &o.cluster, &o.planned); err != nil {
			return nil, err
		}
		label := trainingLabel(o)
		if named {
			owner := byID[resp]
			if owner == "" {
				owner = byID[mon]
			}
			if owner != "" {
				label = owner + " · " + label
			}
		}
		out = append(out, Choice{id, label})
	}
	return out, rows.Err()
}

// DebriefChoices is _debrief_options: the officers' field debriefs of the
// last two months.
func (c Coaching) DebriefChoices(ctx context.Context, scope []Officer, named bool) ([]Choice, error) {
	var users []string
	names := map[string]string{}
	for _, o := range scope {
		if o.UserID != "" {
			users = append(users, o.UserID)
			names[o.UserID] = o.Name
		}
	}
	if len(users) == 0 {
		return nil, nil
	}
	rows, err := c.DB.Query(ctx, `SELECT d.id, d.submitted_by_user_id,
  concat_ws(' · ', CASE WHEN d.date IS NULL THEN 'Undated' ELSE to_char(d.date AT TIME ZONE 'UTC', 'FMDD Mon') END,
    COALESCE(NULLIF(d.title, ''), 'Field debrief'))
FROM daily_debrief d WHERE d.submitted_by_user_id = ANY($1) AND d.deleted_at IS NULL
  AND (d.date AT TIME ZONE 'Africa/Kampala')::date >= $2::date
ORDER BY d.date DESC, d.id LIMIT 100`, users, c.today().AddDate(0, 0, -debriefLookback).Format(time.DateOnly))
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the officers' debriefs: %w", err)
	}
	defer rows.Close()
	var out []Choice
	for rows.Next() {
		var id, by, label string
		if err := rows.Scan(&id, &by, &label); err != nil {
			return nil, err
		}
		if named && names[by] != "" {
			label = names[by] + " · " + label
		}
		out = append(out, Choice{id, label})
	}
	return out, rows.Err()
}

func ownerIDs(scope []Officer) ([]string, map[string]string) {
	var owners []string
	byID := map[string]string{}
	for _, o := range scope {
		for _, id := range []string{o.StaffID, o.UserID} {
			if id != "" {
				owners = append(owners, id)
				byID[id] = o.Name
			}
		}
	}
	return owners, byID
}

// Record is one coaching record as its drawers read it.
type Record struct {
	ID, Author, StaffID, UserID, Kind, Subject, Strengths, Growth, Actions string
	Response, FollowUpNote, Country, ActivityID, DebriefID                 string
	Held                                                                   time.Time
	FollowUpDue, Shared, Acknowledged, FollowUpDone                        *time.Time
	Ratings                                                                map[string]*int
}

const recordSelect = `SELECT id, author_id, cceo_staff_id, cceo_user_id, kind, subject, strengths, growth_areas, agreed_actions,
  cceo_response, follow_up_note, country, COALESCE(activity_id, ''), COALESCE(debrief_id, ''), held_on, follow_up_due, shared_at,
  acknowledged_at, follow_up_done_at, rating_biblical_integration, rating_need_alignment, rating_facilitation,
  rating_participation, rating_application FROM cce_cceo_coaching`

func scanRecord(row pgx.Row) (Record, error) {
	var r Record
	ratings := make([]*int, 5)
	err := row.Scan(&r.ID, &r.Author, &r.StaffID, &r.UserID, &r.Kind, &r.Subject, &r.Strengths, &r.Growth, &r.Actions,
		&r.Response, &r.FollowUpNote, &r.Country, &r.ActivityID, &r.DebriefID, &r.Held, &r.FollowUpDue, &r.Shared,
		&r.Acknowledged, &r.FollowUpDone, &ratings[0], &ratings[1], &ratings[2], &ratings[3], &ratings[4])
	r.Ratings = map[string]*int{}
	for i, c := range ObservationCriteria {
		r.Ratings[c[0]] = ratings[i]
	}
	return r, err
}

// Visible is the lead's own record among coaching_visible_to: written by
// them about an officer on their team.
func (c Coaching) Visible(ctx context.Context, p auth.Principal, id string) (*Record, error) {
	if !IsLead(p) {
		return nil, nil
	}
	team, err := c.Team(ctx, p)
	if err != nil || len(team) == 0 {
		return nil, err
	}
	var staff []string
	for _, o := range team {
		staff = append(staff, o.StaffID)
	}
	r, err := scanRecord(c.DB.QueryRow(ctx, recordSelect+` WHERE id = $1 AND author_id = $2 AND cceo_staff_id = ANY($3)`,
		id, p.UserID, staff))
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the coaching record: %w", err)
	}
	return &r, nil
}

// cleaned is _clean's answer.
type cleaned struct {
	officer                                  Officer
	kind, subject, strengths, growth, action string
	held                                     time.Time
	due                                      *time.Time
	activityID, debriefID                    *string
	ratings                                  map[string]*int
}

func parseDay(value, label string) (*time.Time, error) {
	value = strings.TrimSpace(value)
	if value == "" {
		return nil, nil
	}
	if len(value) > 10 {
		value = value[:10]
	}
	d, err := time.Parse(time.DateOnly, value)
	if err != nil {
		return nil, badRequest("Enter " + label + " as a date.")
	}
	return &d, nil
}

// clean is coaching._clean.
func (c Coaching) clean(ctx context.Context, q pgx.Tx, p auth.Principal, data map[string]string, instance *Record) (cleaned, error) {
	var out cleaned
	get := func(k string) string { return strings.TrimSpace(data[k]) }
	if instance == nil {
		team, err := c.Team(ctx, p)
		if err != nil {
			return out, err
		}
		o := OfficerFor(team, data["cceo_staff_id"])
		if o == nil {
			return out, badRequest("Choose an officer on your team.")
		}
		out.officer = *o
		if out.kind = get("kind"); !RecordableKind(out.kind) {
			return out, badRequest("Choose what kind of coaching this was.")
		}
	} else {
		if err := q.QueryRow(ctx, `SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(u.name, '') FROM staff_profile sp
LEFT JOIN "user" u ON u.id = sp.user_id WHERE sp.id = $1`, instance.StaffID).Scan(&out.officer.StaffID, &out.officer.UserID,
			&out.officer.Name); errors.Is(err, pgx.ErrNoRows) {
			return out, missing("The officer on this record no longer exists.")
		} else if err != nil {
			return out, err
		}
		out.kind = instance.Kind
	}
	held, err := parseDay(data["held_on"], "the date it was held")
	if err != nil {
		return out, err
	}
	if held == nil {
		return out, badRequest("Enter the date it was held.")
	}
	if held.After(c.today()) {
		return out, badRequest("Record coaching once it has happened: choose today or an earlier date.")
	}
	out.held = *held
	if out.due, err = parseDay(data["follow_up_due"], "the follow-up date"); err != nil {
		return out, err
	}
	if out.due != nil && out.due.Before(out.held) {
		return out, badRequest("The follow-up date cannot be before the coaching.")
	}
	out.strengths, out.growth, out.action = get("strengths"), get("growth_areas"), get("agreed_actions")
	if out.strengths == "" && out.growth == "" && out.action == "" {
		return out, badRequest("Write what the coaching covered: strengths, areas to grow or the actions agreed.")
	}
	if out.due != nil && out.action == "" {
		return out, badRequest("Write the actions agreed before setting a follow-up date.")
	}
	owners, _ := ownerIDs([]Officer{out.officer})
	if id := get("activity_id"); id != "" {
		found := instance != nil && instance.ActivityID == id
		if !found {
			if err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity WHERE id = $1 AND deleted_at IS NULL
  AND (responsible_staff_id = ANY($2) OR monitored_by_staff_id = ANY($2)))`, id, owners).Scan(&found); err != nil {
				return out, err
			}
		}
		if !found {
			return out, badRequest("Choose an activity this officer delivered or monitored.")
		}
		out.activityID = &id
	}
	if out.kind == "training_observation" && out.activityID == nil {
		return out, badRequest("Choose the training you observed.")
	}
	if id := get("debrief_id"); id != "" {
		found := instance != nil && instance.DebriefID == id
		if !found {
			if err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM daily_debrief WHERE id = $1 AND deleted_at IS NULL
  AND submitted_by_user_id = $2)`, id, out.officer.UserID).Scan(&found); err != nil {
				return out, err
			}
		}
		if !found {
			return out, badRequest("Choose a field debrief this officer submitted.")
		}
		out.debriefID = &id
	}
	out.ratings = map[string]*int{}
	if RatedKind(out.kind) {
		for _, crit := range ObservationCriteria {
			v, err := strconv.Atoi(strings.TrimSpace(data[crit[0]]))
			if err != nil || v < 1 || v > 4 {
				return out, badRequest("Rate “" + crit[1] + "” from 1 to 4.")
			}
			out.ratings[crit[0]] = &v
		}
	} else if instance != nil {
		out.ratings = nil // an existing record's ratings stay as they are
	}
	name := out.officer.Name
	if name == "" {
		name = "officer"
	}
	out.subject = cutRunes(get("subject"), 255)
	if out.subject == "" {
		out.subject = cutRunes(KindLabel(out.kind)+" · "+name, 255)
	}
	return out, nil
}

func cutRunes(s string, n int) string {
	r := []rune(s)
	if len(r) > n {
		return string(r[:n])
	}
	return s
}

// operationalFY is get_operational_fy for a day.
func operationalFY(d time.Time) string {
	if d.Month() >= time.October {
		return strconv.Itoa(d.Year() + 1)
	}
	return strconv.Itoa(d.Year())
}

func (c Coaching) write(ctx context.Context, fn func(pgx.Tx) error) error {
	tx, err := c.DB.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := fn(tx); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func coachingAudit(ctx context.Context, tx pgx.Tx, action, id string, p auth.Principal, payload map[string]any, now time.Time) error {
	if payload == nil {
		payload = map[string]any{}
	}
	_, err := audit.Append(ctx, tx, audit.Entry{Action: action, SubjectKind: audit.Text("CceoCoaching"), SubjectID: audit.Text(id),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true, Payload: payload}, now)
	if err != nil {
		return fmt.Errorf("ccelead: auditing %s: %w", action, err)
	}
	return nil
}

// RecordCoaching is record_coaching; it says the new record's id.
func (c Coaching) RecordCoaching(ctx context.Context, p auth.Principal, data map[string]string) (string, error) {
	if !IsLead(p) {
		return "", forbidden(leadOnly)
	}
	id := cuid.New()
	now := c.now().UTC().Truncate(time.Microsecond)
	err := c.write(ctx, func(tx pgx.Tx) error {
		cl, err := c.clean(ctx, tx, p, data, nil)
		if err != nil {
			return err
		}
		var country string
		if err := tx.QueryRow(ctx, `SELECT COALESCE(country, '') FROM staff_profile WHERE id = $1`, cl.officer.StaffID).
			Scan(&country); err != nil {
			return err
		}
		r := cl.ratings
		if _, err := tx.Exec(ctx, `INSERT INTO cce_cceo_coaching (created_at, updated_at, id, author_id, cceo_staff_id, cceo_user_id,
  kind, held_on, fy, country, subject, strengths, growth_areas, agreed_actions, follow_up_due, rating_biblical_integration,
  rating_need_alignment, rating_facilitation, rating_participation, rating_application, cceo_response, follow_up_note,
  activity_id, debrief_id)
VALUES ($1, $1, $2, $3, $4, $5, $6, $7::date, $8, $9, $10, $11, $12, $13, $14::date, $15, $16, $17, $18, $19, '', '', $20, $21)`,
			now, id, p.UserID, cl.officer.StaffID, cl.officer.UserID, cl.kind, cl.held.Format(time.DateOnly),
			operationalFY(cl.held), country, cl.subject, cl.strengths, cl.growth, cl.action, dayOrNil(cl.due),
			r["rating_biblical_integration"], r["rating_need_alignment"], r["rating_facilitation"], r["rating_participation"],
			r["rating_application"], cl.activityID, cl.debriefID); err != nil {
			return fmt.Errorf("ccelead: recording the coaching: %w", err)
		}
		return coachingAudit(ctx, tx, "cce.coaching_recorded", id, p, map[string]any{
			"kind": cl.kind, "cceo_staff_id": cl.officer.StaffID, "held_on": cl.held.Format(time.DateOnly)}, now)
	})
	return id, err
}

func dayOrNil(d *time.Time) any {
	if d == nil {
		return nil
	}
	return d.Format(time.DateOnly)
}

// ownRecord is _own_record.
func (c Coaching) ownRecord(ctx context.Context, tx pgx.Tx, p auth.Principal, id string) (Record, error) {
	team, err := c.Team(ctx, p)
	if err != nil {
		return Record{}, err
	}
	var staff []string
	for _, o := range team {
		staff = append(staff, o.StaffID)
	}
	if len(staff) == 0 {
		return Record{}, missing(coachingNotFound)
	}
	r, err := scanRecord(tx.QueryRow(ctx, recordSelect+` WHERE id = $1 AND author_id = $2 AND cceo_staff_id = ANY($3) FOR UPDATE`,
		id, p.UserID, staff))
	if errors.Is(err, pgx.ErrNoRows) {
		return Record{}, missing(coachingNotFound)
	}
	return r, err
}

// UpdateCoaching is update_coaching: corrected until acknowledged; a shared
// record tells the officer it changed.
func (c Coaching) UpdateCoaching(ctx context.Context, p auth.Principal, id string, data map[string]string) (Record, error) {
	if !IsLead(p) {
		return Record{}, forbidden(leadOnly)
	}
	now := c.now().UTC().Truncate(time.Microsecond)
	var saved Record
	err := c.write(ctx, func(tx pgx.Tx) error {
		r, err := c.ownRecord(ctx, tx, p, id)
		if err != nil {
			return err
		}
		if r.Acknowledged != nil {
			return forbidden(alreadyAcknowleged)
		}
		cl, err := c.clean(ctx, tx, p, data, &r)
		if err != nil {
			return err
		}
		sets := `kind = $2, held_on = $3::date, fy = $4, country = $5, subject = $6, strengths = $7, growth_areas = $8,
  agreed_actions = $9, follow_up_due = $10::date, activity_id = $11, debrief_id = $12, updated_at = $13`
		args := []any{id, cl.kind, cl.held.Format(time.DateOnly), operationalFY(cl.held), cl.officer.countryOr(ctx, tx, r.Country),
			cl.subject, cl.strengths, cl.growth, cl.action, dayOrNil(cl.due), cl.activityID, cl.debriefID, now}
		if cl.ratings != nil {
			for _, crit := range ObservationCriteria {
				args = append(args, cl.ratings[crit[0]])
				sets += fmt.Sprintf(", %s = $%d", crit[0], len(args))
			}
		}
		if _, err := tx.Exec(ctx, `UPDATE cce_cceo_coaching SET `+sets+` WHERE id = $1`, args...); err != nil {
			return fmt.Errorf("ccelead: saving the coaching: %w", err)
		}
		if err := coachingAudit(ctx, tx, "cce.coaching_updated", id, p, nil, now); err != nil {
			return err
		}
		saved, err = scanRecord(tx.QueryRow(ctx, recordSelect+` WHERE id = $1`, id))
		return err
	})
	if err != nil {
		return Record{}, err
	}
	if saved.Shared != nil {
		c.tellOfficer(ctx, p, saved, leadName(p)+" updated coaching notes shared with you", now)
	}
	return saved, nil
}

// countryOr is member.country, read again.
func (o Officer) countryOr(ctx context.Context, tx pgx.Tx, fallback string) string {
	var country string
	if err := tx.QueryRow(ctx, `SELECT COALESCE(country, '') FROM staff_profile WHERE id = $1`, o.StaffID).Scan(&country); err != nil {
		return fallback
	}
	return country
}

func leadName(p auth.Principal) string {
	if p.Name != "" {
		return p.Name
	}
	return "Your Programme Lead"
}

// noticeBody is _notice_body.
func noticeBody(r Record) string {
	body := r.Subject + "."
	if r.Actions != "" {
		body += " Agreed actions: " + r.Actions
	}
	return cutRunes(body, 500)
}

func (c Coaching) tellOfficer(ctx context.Context, p auth.Principal, r Record, title string, now time.Time) {
	if r.UserID == "" {
		return
	}
	err := activities.SendNotices(ctx, c.DB, c.Push, nil, c.Logger, now, r.ID, "", activities.Origin{}, activities.Notice{
		Title: title, Body: noticeBody(r), Event: eventShared, Category: "performance", ContextType: "CceoCoaching",
		Priority: "high",
	}, []activities.NoticeTo{{UserID: r.UserID, Route: "/my-coaching?open=" + r.ID, Label: "Acknowledge Coaching"}})
	if err != nil && c.Logger != nil {
		c.Logger.WarnContext(ctx, "ccelead: the officer was not told of the coaching", "record", r.ID, "err", err)
	}
}

// ShareCoaching is share_coaching.
func (c Coaching) ShareCoaching(ctx context.Context, p auth.Principal, id string) (Record, error) {
	if !IsLead(p) {
		return Record{}, forbidden(leadOnly)
	}
	now := c.now().UTC().Truncate(time.Microsecond)
	var r Record
	err := c.write(ctx, func(tx pgx.Tx) error {
		var err error
		if r, err = c.ownRecord(ctx, tx, p, id); err != nil {
			return err
		}
		if r.Shared != nil {
			return badRequest("This coaching was already shared with the officer.")
		}
		if _, err := tx.Exec(ctx, `UPDATE cce_cceo_coaching SET shared_at = $2, updated_at = $2 WHERE id = $1`, id, now); err != nil {
			return fmt.Errorf("ccelead: sharing the coaching: %w", err)
		}
		r.Shared = &now
		return coachingAudit(ctx, tx, "cce.coaching_shared", id, p, map[string]any{"cceo_staff_id": r.StaffID}, now)
	})
	if err != nil {
		return Record{}, err
	}
	c.tellOfficer(ctx, p, r, "Coaching notes from "+leadName(p), now)
	return r, nil
}

// CompleteFollowUp is complete_follow_up.
func (c Coaching) CompleteFollowUp(ctx context.Context, p auth.Principal, id, note string) error {
	if !IsLead(p) {
		return forbidden(leadOnly)
	}
	note = strings.TrimSpace(note)
	if note == "" {
		return badRequest("Say what you found when you followed up: done, in progress or not started.")
	}
	now := c.now().UTC().Truncate(time.Microsecond)
	return c.write(ctx, func(tx pgx.Tx) error {
		r, err := c.ownRecord(ctx, tx, p, id)
		if err != nil {
			return err
		}
		if r.FollowUpDue == nil {
			return badRequest("This coaching has no follow-up date to close.")
		}
		if r.FollowUpDone != nil {
			return badRequest("This follow-up was already closed.")
		}
		if _, err := tx.Exec(ctx, `UPDATE cce_cceo_coaching SET follow_up_done_at = $2, follow_up_note = $3, updated_at = $2
WHERE id = $1`, id, now, note); err != nil {
			return fmt.Errorf("ccelead: closing the follow-up: %w", err)
		}
		return coachingAudit(ctx, tx, "cce.coaching_follow_up_closed", id, p, nil, now)
	})
}
