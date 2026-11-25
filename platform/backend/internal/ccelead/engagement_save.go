package ccelead

// The Regional Lead's engagement log and the Programme Lead's answers to it
// (apps.cce_leadership.services): an engagement recorded and corrected until
// it is shared; a training observation's feedback or a coaching
// conversation's notes shared with the Programme Leads it names; each
// acknowledged by a Programme Lead, and an observation passed on to the
// officer who delivered the training (coaching.pass_feedback_to_cceo). Each
// check is the existing one, in its order and words.

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

const (
	kindObservation   = "training_observation"
	kindPLCoaching    = "pl_coaching"
	kindCDQuarterly   = "cd_quarterly_review"
	kindCDAnnual      = "cd_annual_planning"
	engagementContext = "RegionalEngagement"
	leadershipNotice  = "leadership"
	// EventFeedbackShared and the rest are the services' event keys.
	eventFeedbackShared       = "cce_training_feedback_shared"
	eventFeedbackAcknowledged = "cce_training_feedback_acknowledged"
	eventPLCoachingShared     = "cce_pl_coaching_shared"
	eventPLCoachingAcked      = "cce_pl_coaching_acknowledged"
	noticeBodyMax             = 500
	subjectMax                = 255
	leadRecordsOnly           = "Only the Regional Programme Lead records CCE engagements and reports."
	// EngagementsURL and the others are the registers the drawers return to.
	EngagementsURL = "/cce-leadership/engagements"
	FeedbackURL    = "/cce-leadership/feedback"
	CoachingURL    = "/cce-leadership/coaching"
	ReportsURL     = "/cce-leadership/reports"
)

// IsRegionalLead is _is_lead / _require_lead.
func IsRegionalLead(p auth.Principal) bool { return p.ActiveRole == regionalLead }

// EngagementKinds are EngagementKind's choices, in order.
func EngagementKinds() [][2]string {
	out := make([][2]string, 0, len(rules.EngagementKinds))
	for _, k := range rules.EngagementKinds {
		out = append(out, [2]string{k[0], k[1]})
	}
	return out
}

// EngagementKindLabel is KIND_LABELS.
func EngagementKindLabel(kind string) string {
	for _, k := range rules.EngagementKinds {
		if k[0] == kind {
			return k[1]
		}
	}
	return kind
}

// Shareable is SHAREABLE_KINDS.
func Shareable(kind string) bool { return slices.Contains(rules.ShareableKinds, kind) }

// Lead is one Programme Lead in the Regional Lead's reach.
type Lead struct{ StaffID, Name, Country string }

// Reach is lead_reach: the countries served and the Programme Leads in them.
type Reach struct {
	Countries []string
	Leads     []Lead
}

// LeadReach is services.lead_reach.
func (c Coaching) LeadReach(ctx context.Context, p auth.Principal) (Reach, error) {
	r, err := leadReach(ctx, c.DB, p)
	if err != nil {
		return Reach{}, err
	}
	out := Reach{Countries: r.countries}
	for _, l := range r.leads {
		out.Leads = append(out.Leads, Lead{StaffID: l.staffID, Name: l.name, Country: l.country})
	}
	return out, nil
}

// LeadOptions is _lead_options.
func (r Reach) LeadOptions() []Choice {
	out := make([]Choice, 0, len(r.Leads))
	for _, l := range r.Leads {
		label := l.Name
		if l.Country != "" {
			label = l.Name + " · " + l.Country
		}
		out = append(out, Choice{l.StaffID, label})
	}
	return out
}

// Names is _lead_names.
func (r Reach) Names() map[string]string {
	out := map[string]string{}
	for _, l := range r.Leads {
		out[l.StaffID] = l.Name
	}
	return out
}

// inCountries is activities_in_countries on activity `a`.
const inCountries = `(sr.country = ANY($1)
  OR (a.school_id IS NULL AND dr.country = ANY($1))
  OR (a.school_id IS NULL AND cr.country = ANY($1)))`

const activityPlaces = `LEFT JOIN school s ON s.id = a.school_id LEFT JOIN region sr ON sr.id = s.region_id
LEFT JOIN cluster cl ON cl.id = a.cluster_id LEFT JOIN district d ON d.id = cl.district_id
LEFT JOIN region dr ON dr.id = d.region_id LEFT JOIN region cr ON cr.id = cl.region_id`

// observableTrainings is observable_trainings' query, the options first.
func (c Coaching) observableTrainings(ctx context.Context, q pgx.Tx, countries []string, id string, limit int) ([]Choice, error) {
	today := c.today()
	sql := `SELECT a.id, NULLIF(a.activity_name_snapshot, ''), a.activity_type, s.name, cl.name, a.planned_date
FROM activity a ` + activityPlaces + `
WHERE a.deleted_at IS NULL AND a.activity_type = ANY($2) AND a.planned_date >= $3::date AND a.planned_date <= $4::date
  AND NOT (COALESCE(a.status, '') = ANY($5)) AND ` + inCountries
	args := []any{countries, rules.Saves.TrainingTypes, today.AddDate(0, 0, -rules.Saves.LookbackDays).Format(time.DateOnly),
		today.AddDate(0, 0, rules.Saves.LookaheadDays).Format(time.DateOnly), rules.Saves.NotLiveStatuses}
	if id != "" {
		sql += ` AND a.id = $6`
		args = append(args, id)
	}
	sql += fmt.Sprintf(` ORDER BY a.planned_date DESC, a.id LIMIT %d`, limit)
	var rows pgx.Rows
	var err error
	if q != nil {
		rows, err = q.Query(ctx, sql, args...)
	} else {
		rows, err = c.DB.Query(ctx, sql, args...)
	}
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the trainings in reach: %w", err)
	}
	defer rows.Close()
	var out []Choice
	for rows.Next() {
		var aid string
		var o observation
		if err := rows.Scan(&aid, &o.name, &o.kind, &o.school, &o.cluster, &o.planned); err != nil {
			return nil, err
		}
		out = append(out, Choice{aid, trainingLabel(o)})
	}
	return out, rows.Err()
}

// TrainingChoices is _observation_fields' options: the trainings in reach.
func (c Coaching) TrainingChoices(ctx context.Context, r Reach) ([]Choice, error) {
	if len(r.Countries) == 0 {
		return nil, nil
	}
	return c.observableTrainings(ctx, nil, r.Countries, "", 200)
}

// ActivityLabel is training_label for one activity, "" when there is none.
func (c Coaching) ActivityLabel(ctx context.Context, id string) (string, error) {
	if id == "" {
		return "", nil
	}
	var o observation
	err := c.DB.QueryRow(ctx, `SELECT NULLIF(a.activity_name_snapshot, ''), a.activity_type, s.name, cl.name, a.planned_date
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id WHERE a.id = $1`, id).
		Scan(&o.name, &o.kind, &o.school, &o.cluster, &o.planned)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("ccelead: reading the training: %w", err)
	}
	return trainingLabel(o), nil
}

// Engagement is one RegionalEngagement.
type Engagement struct {
	ID, Author, Kind, FY, Country, Subject, Notes, Actions, Recommendation, Feedback, Response, ActivityID string
	LeadIDs                                                                                                []string
	Held                                                                                                   time.Time
	FollowUpDue, Shared, Acknowledged                                                                      *time.Time
	Ratings                                                                                                map[string]int
}

// IsObservation is is_observation.
func (e *Engagement) IsObservation() bool { return e.Kind == kindObservation }

// AverageRating is average_rating: "" when nothing is rated.
func (e *Engagement) AverageRating() string {
	var sum, n int
	for _, c := range ObservationCriteria {
		if v := e.Ratings[c[0]]; v != 0 {
			sum += v
			n++
		}
	}
	if n == 0 {
		return ""
	}
	return pyStr1(pyRound1(float64(sum) / float64(n)))
}

func engagementSelect() string {
	cols := []string{"e.id", "e.author_id", "e.kind", "e.fy", "e.country", "e.subject", "e.notes", "e.agreed_actions",
		"e.recommendation", "e.feedback", "e.lead_response", "COALESCE(e.activity_id, '')", "e.program_lead_ids", "e.held_on",
		"e.follow_up_due", "e.feedback_shared_at", "e.acknowledged_at"}
	for _, c := range ObservationCriteria {
		cols = append(cols, "e."+c[0])
	}
	return "SELECT " + strings.Join(cols, ", ") + " FROM cce_regional_engagement e"
}

func scanEngagement(row pgx.Row) (Engagement, error) {
	var e Engagement
	ratings := make([]*int16, len(ObservationCriteria))
	dest := []any{&e.ID, &e.Author, &e.Kind, &e.FY, &e.Country, &e.Subject, &e.Notes, &e.Actions, &e.Recommendation, &e.Feedback,
		&e.Response, &e.ActivityID, &e.LeadIDs, &e.Held, &e.FollowUpDue, &e.Shared, &e.Acknowledged}
	for i := range ratings {
		dest = append(dest, &ratings[i])
	}
	if err := row.Scan(dest...); err != nil {
		return e, err
	}
	e.Ratings = map[string]int{}
	for i, c := range ObservationCriteria {
		if ratings[i] != nil {
			e.Ratings[c[0]] = int(*ratings[i])
		}
	}
	return e, nil
}

// oneEngagement reads one engagement through a visibility clause.
func (c Coaching) oneEngagement(ctx context.Context, q pgx.Tx, where string, args []any, id string, lock bool) (*Engagement, error) {
	sql := engagementSelect() + " WHERE " + where + fmt.Sprintf(" AND e.id = $%d", len(args)+1)
	if lock {
		sql += " FOR UPDATE"
	}
	var row pgx.Row
	if q != nil {
		row = q.QueryRow(ctx, sql, append(args, id)...)
	} else {
		row = c.DB.QueryRow(ctx, sql, append(args, id)...)
	}
	e, err := scanEngagement(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the engagement: %w", err)
	}
	return &e, nil
}

// engagementsWhere is engagements_visible_to.
func engagementsWhere(p auth.Principal) (string, []any) {
	switch p.ActiveRole {
	case adminRole:
		return "TRUE", nil
	case regionalLead:
		return "e.author_id = $1", []any{p.UserID}
	}
	return "FALSE", nil
}

// EngagementVisible is engagements_visible_to(...).filter(id=).first().
func (c Coaching) EngagementVisible(ctx context.Context, p auth.Principal, id string) (*Engagement, error) {
	where, args := engagementsWhere(p)
	return c.oneEngagement(ctx, nil, where, args, id, false)
}

// FeedbackVisible is feedback_visible_to(...).filter(id=).first().
func (c Coaching) FeedbackVisible(ctx context.Context, p auth.Principal, id string) (*Engagement, error) {
	where, args, err := observations(ctx, c.DB, p)
	if err != nil {
		return nil, err
	}
	return c.oneEngagement(ctx, nil, "e.kind = 'training_observation' AND "+where, args, id, false)
}

// regionalCoachingWhere is regional_coaching_visible_to.
func (c Coaching) regionalCoachingWhere(ctx context.Context, p auth.Principal) (string, []any, error) {
	switch p.ActiveRole {
	case adminRole:
		return "e.kind = 'pl_coaching'", nil, nil
	case regionalLead:
		return "e.kind = 'pl_coaching' AND e.author_id = $1", []any{p.UserID}, nil
	case programLead:
		staff, err := c.staffOf(ctx, p)
		if err != nil || staff == "" {
			return "FALSE", nil, err
		}
		return "e.kind = 'pl_coaching' AND e.feedback_shared_at IS NOT NULL AND e.program_lead_ids @> ARRAY[$1]::varchar[]",
			[]any{staff}, nil
	}
	return "FALSE", nil, nil
}

// RegionalCoachingVisible is regional_coaching_visible_to(...).filter(id=).
func (c Coaching) RegionalCoachingVisible(ctx context.Context, p auth.Principal, id string) (*Engagement, error) {
	where, args, err := c.regionalCoachingWhere(ctx, p)
	if err != nil {
		return nil, err
	}
	return c.oneEngagement(ctx, nil, where, args, id, false)
}

// staffOf is _staff_id: the principal's staff record.
func (c Coaching) staffOf(ctx context.Context, p auth.Principal) (string, error) {
	if p.StaffProfileID != "" {
		return p.StaffProfileID, nil
	}
	var staff string
	err := c.DB.QueryRow(ctx, `SELECT id FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL ORDER BY id LIMIT 1`, p.UserID).
		Scan(&staff)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("ccelead: reading the lead's staff record: %w", err)
	}
	return staff, nil
}

// StaffNames is StaffProfile id → its user's name.
func (c Coaching) StaffNames(ctx context.Context, ids []string) (map[string]string, error) {
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := c.DB.Query(ctx, `SELECT sp.id, COALESCE(u.name, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE sp.id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the Programme Leads' names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, err
		}
		out[id] = name
	}
	return out, rows.Err()
}

// UserName is _author_names for one account.
func (c Coaching) UserName(ctx context.Context, id string) (string, error) {
	var name string
	err := c.DB.QueryRow(ctx, `SELECT COALESCE(name, '') FROM "user" WHERE id = $1`, id).Scan(&name)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("ccelead: reading the author's name: %w", err)
	}
	return name, nil
}

// cleanEngagement is _clean_engagement.
type cleanEngagement struct {
	kind, fy, country, subject, notes, actions, recommendation, feedback, activityID string
	held                                                                             time.Time
	followUpDue                                                                      *time.Time
	leadIDs                                                                          []string
	ratings                                                                          map[string]int
}

func splitIDs(raw string) []string {
	var out []string
	for _, part := range strings.Split(raw, ",") {
		if part = strings.TrimSpace(part); part != "" {
			out = append(out, part)
		}
	}
	return out
}

func (c Coaching) cleanEngagementData(ctx context.Context, q pgx.Tx, p auth.Principal, data map[string]string, instance *Engagement) (cleanEngagement, error) {
	r, err := c.LeadReach(ctx, p)
	if err != nil {
		return cleanEngagement{}, err
	}
	kind := strings.TrimSpace(data["kind"])
	if kind == "" && instance != nil {
		kind = instance.Kind
	}
	if !slices.ContainsFunc(rules.EngagementKinds, func(k [2]string) bool { return k[0] == kind }) {
		return cleanEngagement{}, badRequest("Choose what kind of engagement this was.")
	}
	today := c.today()
	held, err := parseDay(data["held_on"], "the date it was held")
	if err != nil {
		return cleanEngagement{}, err
	}
	if held == nil {
		return cleanEngagement{}, badRequest("Enter the date it was held.")
	}
	if held.After(today) {
		return cleanEngagement{}, badRequest("Record an engagement once it has happened: choose today or an earlier date.")
	}
	due, err := parseDay(data["follow_up_due"], "the follow-up date")
	if err != nil {
		return cleanEngagement{}, err
	}
	if due != nil && due.Before(*held) {
		return cleanEngagement{}, badRequest("The follow-up date cannot be before the engagement.")
	}
	leads := map[string]Lead{}
	for _, l := range r.Leads {
		leads[l.StaffID] = l
	}
	ids := splitIDs(data["program_lead_ids"])
	for _, id := range ids {
		if _, ok := leads[id]; !ok {
			return cleanEngagement{}, badRequest("Choose Programme Leads who work in your region.")
		}
	}
	country := strings.TrimSpace(data["country"])
	if country != "" && !slices.Contains(r.Countries, country) {
		return cleanEngagement{}, badRequest("Choose a country in your region.")
	}
	out := cleanEngagement{kind: kind, held: *held, fy: operationalFY(*held), followUpDue: due,
		notes: strings.TrimSpace(data["notes"]), actions: strings.TrimSpace(data["agreed_actions"])}
	if kind == kindObservation {
		return c.cleanObservation(ctx, q, p, r, data, instance, out, ids, country)
	}
	if kind == kindPLCoaching && len(ids) == 0 {
		return cleanEngagement{}, badRequest("Choose the Programme Lead you met.")
	}
	if (kind == kindCDQuarterly || kind == kindCDAnnual) && country == "" {
		return cleanEngagement{}, badRequest("Choose the country whose Country Director you met.")
	}
	if kind == kindPLCoaching && country == "" {
		seen := map[string]bool{}
		for _, id := range ids {
			if leads[id].Country != "" {
				seen[leads[id].Country] = true
			}
		}
		if len(seen) == 1 {
			for k := range seen {
				country = k
			}
		}
	}
	subject := cutRunes(strings.TrimSpace(data["subject"]), subjectMax)
	if subject == "" {
		names := make([]string, 0, len(ids))
		for _, id := range ids {
			names = append(names, leads[id].Name)
		}
		label := EngagementKindLabel(kind)
		who := strings.Join(names, ", ")
		if who == "" {
			who = country
		}
		subject = label
		if who != "" {
			subject = label + " · " + who
		}
	}
	out.country, out.leadIDs, out.subject = country, ids, cutRunes(subject, subjectMax)
	return out, nil
}

func (c Coaching) cleanObservation(ctx context.Context, q pgx.Tx, p auth.Principal, r Reach, data map[string]string,
	instance *Engagement, out cleanEngagement, ids []string, country string) (cleanEngagement, error) {
	activityID := strings.TrimSpace(data["activity_id"])
	if activityID == "" {
		return cleanEngagement{}, badRequest("Choose the training you observed.")
	}
	label := ""
	if len(r.Countries) > 0 {
		found, err := c.observableTrainings(ctx, q, r.Countries, activityID, 1)
		if err != nil {
			return cleanEngagement{}, err
		}
		if len(found) == 1 {
			label = found[0].Label
		}
	}
	if label == "" && instance != nil && instance.ActivityID == activityID {
		var err error
		if label, err = c.ActivityLabel(ctx, activityID); err != nil {
			return cleanEngagement{}, err
		}
	}
	if label == "" {
		return cleanEngagement{}, badRequest("Choose a training in your region from the last four months.")
	}
	ratings := map[string]int{}
	for _, crit := range ObservationCriteria {
		v, err := strconv.Atoi(strings.TrimSpace(data[crit[0]]))
		if err != nil || v < 1 || v > 4 {
			return cleanEngagement{}, badRequest(fmt.Sprintf("Rate “%s” from 1 to 4.", crit[1]))
		}
		ratings[crit[0]] = v
	}
	recommendation := strings.TrimSpace(data["recommendation"])
	if _, ok := rules.Recommendations[recommendation]; !ok {
		return cleanEngagement{}, badRequest("Choose what you recommend for this training.")
	}
	feedback := strings.TrimSpace(data["feedback"])
	if feedback == "" {
		return cleanEngagement{}, badRequest("Write the feedback for the Programme Lead: what worked and what to change.")
	}
	if len(ids) == 0 {
		var err error
		if ids, err = c.supervisingLeads(ctx, activityID, r); err != nil {
			return cleanEngagement{}, err
		}
	}
	placed, err := c.activityCountry(ctx, activityID)
	if err != nil {
		return cleanEngagement{}, err
	}
	if placed == "" {
		placed = country
	}
	subject := cutRunes(strings.TrimSpace(data["subject"]), subjectMax)
	if subject == "" {
		subject = cutRunes("Observed: "+label, subjectMax)
	}
	out.activityID, out.country, out.leadIDs, out.recommendation, out.feedback, out.subject, out.ratings =
		activityID, placed, ids, recommendation, feedback, subject, ratings
	return out, nil
}

// activityCountry is activity_country.
func (c Coaching) activityCountry(ctx context.Context, id string) (string, error) {
	var country string
	err := c.DB.QueryRow(ctx, `SELECT COALESCE(CASE
    WHEN a.school_id IS NOT NULL AND s.region_id IS NOT NULL THEN COALESCE(sr.country, '')
    WHEN a.cluster_id IS NOT NULL AND cl.district_id IS NOT NULL AND d.region_id IS NOT NULL THEN COALESCE(dr.country, '')
    WHEN a.cluster_id IS NOT NULL AND cl.region_id IS NOT NULL THEN COALESCE(cr.country, '')
    ELSE '' END, '')
FROM activity a `+activityPlaces+` WHERE a.id = $1`, id).Scan(&country)
	if err != nil {
		return "", fmt.Errorf("ccelead: reading the training's country: %w", err)
	}
	return country, nil
}

// supervisingLeads is supervising_leads: the leads in reach who deliver or
// monitor the training, or supervise whoever does.
func (c Coaching) supervisingLeads(ctx context.Context, activityID string, r Reach) ([]string, error) {
	var owners []string
	var resp, mon *string
	if err := c.DB.QueryRow(ctx, `SELECT responsible_staff_id, monitored_by_staff_id FROM activity WHERE id = $1`, activityID).
		Scan(&resp, &mon); err != nil {
		return nil, fmt.Errorf("ccelead: reading the training's owners: %w", err)
	}
	for _, v := range []*string{resp, mon} {
		if v != nil && *v != "" && !slices.Contains(owners, *v) {
			owners = append(owners, *v)
		}
	}
	if len(owners) == 0 {
		return []string{}, nil
	}
	inReach := map[string]bool{}
	for _, l := range r.Leads {
		inReach[l.StaffID] = true
	}
	rows, err := c.DB.Query(ctx, `SELECT id FROM staff_profile WHERE deleted_at IS NULL AND (id = ANY($1) OR user_id = ANY($1))
UNION ALL SELECT a.supervisor_id FROM staff_supervisor_assignment a WHERE a.supervisee_id IN (
  SELECT id FROM staff_profile WHERE deleted_at IS NULL AND (id = ANY($1) OR user_id = ANY($1)))`, owners)
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the training's Programme Leads: %w", err)
	}
	defer rows.Close()
	set := map[string]bool{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		if inReach[id] {
			set[id] = true
		}
	}
	out := make([]string, 0, len(set))
	for id := range set {
		out = append(out, id)
	}
	slices.Sort(out)
	return out, rows.Err()
}

func ratingArgs(ratings map[string]int) []any {
	out := make([]any, 0, len(ObservationCriteria))
	for _, crit := range ObservationCriteria {
		if v, ok := ratings[crit[0]]; ok {
			out = append(out, v)
		} else {
			out = append(out, nil)
		}
	}
	return out
}

// RecordEngagement is engagement_record: record_engagement, and
// share_feedback when share_now is ticked, both or neither.
func (c Coaching) RecordEngagement(ctx context.Context, p auth.Principal, data map[string]string) (string, bool, error) {
	shareNow := checkedValue(data["share_now"])
	if shareNow && !Shareable(strings.TrimSpace(data["kind"])) {
		return "", false, badRequest("Only a coaching conversation or a training observation is shared with the Programme Lead. Untick “share” to record this engagement.")
	}
	if !IsRegionalLead(p) {
		return "", false, forbidden(leadRecordsOnly)
	}
	now := c.now().UTC().Truncate(time.Microsecond)
	id := cuid.New()
	var shared *Engagement
	err := c.write(ctx, func(tx pgx.Tx) error {
		cl, err := c.cleanEngagementData(ctx, tx, p, data, nil)
		if err != nil {
			return err
		}
		leadIDs := cl.leadIDs
		if leadIDs == nil {
			leadIDs = []string{}
		}
		args := []any{id, now, p.UserID, cl.kind, cl.held, cl.fy, cl.country, leadIDs, cl.subject, cl.notes, cl.actions,
			dayOrNil(cl.followUpDue), cl.recommendation, cl.feedback, nilIfEmpty(cl.activityID)}
		args = append(args, ratingArgs(cl.ratings)...)
		if _, err := tx.Exec(ctx, `INSERT INTO cce_regional_engagement (id, created_at, updated_at, author_id, kind, held_on, fy,
  country, program_lead_ids, subject, notes, agreed_actions, follow_up_due, recommendation, feedback, lead_response, activity_id,
  rating_biblical_integration, rating_need_alignment, rating_facilitation, rating_participation, rating_application)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, '', $15, $16, $17, $18, $19, $20)`, args...); err != nil {
			return fmt.Errorf("ccelead: recording the engagement: %w", err)
		}
		if err := coachingAuditAs(ctx, tx, "cce.engagement_recorded", engagementContext, id, p, map[string]any{
			"kind": cl.kind, "held_on": cl.held.Format(time.DateOnly)}, now); err != nil {
			return err
		}
		if shareNow {
			e, err := c.shareInTx(ctx, tx, p, id, now)
			if err != nil {
				return err
			}
			shared = e
		}
		return nil
	})
	if err != nil {
		return "", false, err
	}
	if shared != nil {
		c.tellLeads(ctx, shared, now)
	}
	return id, shared != nil, nil
}

func nilIfEmpty(s string) any {
	if s == "" {
		return nil
	}
	return s
}

func checkedValue(v string) bool {
	v = strings.TrimSpace(strings.ToLower(v))
	return v != "" && v != "false" && v != "off" && v != "0"
}

// ownEngagement is _own_engagement.
func (c Coaching) ownEngagement(ctx context.Context, tx pgx.Tx, p auth.Principal, id string, lock bool) (*Engagement, error) {
	where, args := engagementsWhere(p)
	e, err := c.oneEngagement(ctx, tx, where, args, id, lock)
	if err != nil {
		return nil, err
	}
	if e == nil {
		return nil, missing("Engagement not found.")
	}
	if e.Author != p.UserID {
		return nil, forbidden("Only the Regional Lead who recorded an engagement changes it.")
	}
	return e, nil
}

// UpdateEngagement is engagement_update: update_engagement, then the share
// refusal and share_feedback, all or nothing.
func (c Coaching) UpdateEngagement(ctx context.Context, p auth.Principal, id string, data map[string]string) (bool, error) {
	if !IsRegionalLead(p) {
		return false, forbidden(leadRecordsOnly)
	}
	now := c.now().UTC().Truncate(time.Microsecond)
	var shared *Engagement
	err := c.write(ctx, func(tx pgx.Tx) error {
		e, err := c.ownEngagement(ctx, tx, p, id, false)
		if err != nil {
			return err
		}
		if e.Shared != nil {
			return forbidden("This has been shared with the Programme Lead, so it can no longer be changed.")
		}
		withKind := map[string]string{}
		for k, v := range data {
			withKind[k] = v
		}
		withKind["kind"] = e.Kind
		cl, err := c.cleanEngagementData(ctx, tx, p, withKind, e)
		if err != nil {
			return err
		}
		leadIDs := cl.leadIDs
		if leadIDs == nil {
			leadIDs = []string{}
		}
		recommendation, feedback, activity := e.Recommendation, e.Feedback, nilIfEmpty(e.ActivityID)
		ratings := ratingArgs(e.Ratings)
		if cl.kind == kindObservation {
			recommendation, feedback, activity, ratings = cl.recommendation, cl.feedback, cl.activityID, ratingArgs(cl.ratings)
		}
		args := []any{id, now, cl.kind, cl.held, cl.fy, cl.country, leadIDs, cl.subject, cl.notes, cl.actions,
			dayOrNil(cl.followUpDue), recommendation, feedback, activity}
		args = append(args, ratings...)
		if _, err := tx.Exec(ctx, `UPDATE cce_regional_engagement SET updated_at = $2, kind = $3, held_on = $4, fy = $5,
  country = $6, program_lead_ids = $7, subject = $8, notes = $9, agreed_actions = $10, follow_up_due = $11,
  recommendation = $12, feedback = $13, activity_id = $14, rating_biblical_integration = $15, rating_need_alignment = $16,
  rating_facilitation = $17, rating_participation = $18, rating_application = $19 WHERE id = $1`, args...); err != nil {
			return fmt.Errorf("ccelead: saving the engagement: %w", err)
		}
		if err := coachingAuditAs(ctx, tx, "cce.engagement_updated", engagementContext, id, p, nil, now); err != nil {
			return err
		}
		if checkedValue(data["share_now"]) {
			if !Shareable(e.Kind) {
				return badRequest("Only a coaching conversation or a training observation is shared with the Programme Lead. Untick “share” to record this engagement.")
			}
			if shared, err = c.shareInTx(ctx, tx, p, id, now); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return false, err
	}
	if shared != nil {
		c.tellLeads(ctx, shared, now)
	}
	return shared != nil, nil
}

// shareInTx is share_feedback's transaction.
func (c Coaching) shareInTx(ctx context.Context, tx pgx.Tx, p auth.Principal, id string, now time.Time) (*Engagement, error) {
	if !IsRegionalLead(p) {
		return nil, forbidden(leadRecordsOnly)
	}
	e, err := c.ownEngagement(ctx, tx, p, id, true)
	if err != nil {
		return nil, err
	}
	if !Shareable(e.Kind) {
		return nil, badRequest("Only a training observation or a coaching conversation is shared with the Programme Lead.")
	}
	if e.Shared != nil {
		return nil, badRequest("This was already shared with the Programme Lead.")
	}
	if len(e.LeadIDs) == 0 {
		return nil, badRequest("Name the Programme Lead who should receive this before sharing it.")
	}
	if _, err := tx.Exec(ctx, `UPDATE cce_regional_engagement SET feedback_shared_at = $2, updated_at = $2 WHERE id = $1`, id, now); err != nil {
		return nil, fmt.Errorf("ccelead: sharing the engagement: %w", err)
	}
	e.Shared = &now
	action := "cce.pl_coaching_shared"
	if e.IsObservation() {
		action = "cce.training_feedback_shared"
	}
	leadIDs := make([]any, len(e.LeadIDs))
	for i, l := range e.LeadIDs {
		leadIDs[i] = l
	}
	if err := coachingAuditAs(ctx, tx, action, engagementContext, id, p, map[string]any{"program_lead_ids": leadIDs}, now); err != nil {
		return nil, err
	}
	return e, nil
}

// ShareEngagement is engagement_share: share_feedback.
func (c Coaching) ShareEngagement(ctx context.Context, p auth.Principal, id string) (*Engagement, error) {
	now := c.now().UTC().Truncate(time.Microsecond)
	var e *Engagement
	err := c.write(ctx, func(tx pgx.Tx) error {
		var err error
		e, err = c.shareInTx(ctx, tx, p, id, now)
		return err
	})
	if err != nil {
		return nil, err
	}
	c.tellLeads(ctx, e, now)
	return e, nil
}

// tellLeads is share_feedback's notice to the Programme Leads it names.
func (c Coaching) tellLeads(ctx context.Context, e *Engagement, now time.Time) {
	var users []string
	rows, err := c.DB.Query(ctx, `SELECT user_id FROM staff_profile WHERE id = ANY($1) AND user_id IS NOT NULL`, e.LeadIDs)
	if err == nil {
		for rows.Next() {
			var u string
			if rows.Scan(&u) == nil {
				users = append(users, u)
			}
		}
		rows.Close()
	}
	event, title, route, label := eventPLCoachingShared, "Coaching notes from your Regional Lead", CoachingURL, "Acknowledge Coaching"
	body := e.Subject + "."
	if e.Actions != "" {
		body += " Agreed actions: " + e.Actions
	}
	if e.IsObservation() {
		event, title, route, label = eventFeedbackShared, "Training feedback from your Regional Lead", FeedbackURL, "Acknowledge Feedback"
		body = e.Subject + ". " + e.Feedback
	}
	c.leadershipNotice(ctx, e.ID, event, title, body, "high", route, label, now, users...)
}

// leadershipNotice is services._notify: never failing the saved work.
func (c Coaching) leadershipNotice(ctx context.Context, id, event, title, body, priority, route, label string, now time.Time,
	to ...string) {
	var recipients []activities.NoticeTo
	for _, u := range to {
		if u != "" {
			recipients = append(recipients, activities.NoticeTo{UserID: u, Route: route + "?open=" + id, Label: label})
		}
	}
	if len(recipients) == 0 {
		return
	}
	contextType := engagementContext
	if route == ReportsURL {
		contextType = reportContext
	}
	err := activities.SendNotices(ctx, c.DB, c.Push, nil, c.Logger, now, id, "", activities.Origin{}, activities.Notice{
		Title: title, Body: cutRunes(body, noticeBodyMax), Event: event, Category: leadershipNotice, ContextType: contextType,
		Priority: priority,
	}, recipients)
	if err != nil && c.Logger != nil {
		c.Logger.WarnContext(ctx, "ccelead: a leadership notice was not sent", "event", event, "record", id, "err", err)
	}
}

// acknowledge is acknowledge_feedback / acknowledge_regional_coaching's
// transaction.
func (c Coaching) acknowledge(ctx context.Context, tx pgx.Tx, p auth.Principal, e *Engagement, response, action, already string,
	now time.Time) error {
	locked, err := c.oneEngagement(ctx, tx, "TRUE", nil, e.ID, true)
	if err != nil {
		return err
	}
	if locked.Acknowledged != nil {
		return badRequest(already)
	}
	if _, err := tx.Exec(ctx, `UPDATE cce_regional_engagement SET acknowledged_at = $2, acknowledged_by_id = $3, lead_response = $4,
  updated_at = $2 WHERE id = $1`, e.ID, now, p.UserID, response); err != nil {
		return fmt.Errorf("ccelead: acknowledging the engagement: %w", err)
	}
	e.Acknowledged, e.Response = &now, response
	return coachingAuditAs(ctx, tx, action, engagementContext, e.ID, p, nil, now)
}

// AcknowledgeFeedback is feedback_acknowledge: acknowledge_feedback and,
// when asked, pass_feedback_to_cceo, both or neither.
func (c Coaching) AcknowledgeFeedback(ctx context.Context, p auth.Principal, id, response string, passOn bool) error {
	if p.ActiveRole != programLead {
		return forbidden("The Programme Lead the feedback is addressed to acknowledges it.")
	}
	response = strings.TrimSpace(response)
	if response == "" {
		return badRequest("Say what you will change in the training, or why it stays as delivered.")
	}
	e, err := c.FeedbackVisible(ctx, p, id)
	if err != nil {
		return err
	}
	if e == nil {
		return missing("Feedback not found.")
	}
	now := c.now().UTC().Truncate(time.Microsecond)
	var passed *Record
	err = c.write(ctx, func(tx pgx.Tx) error {
		if err := c.acknowledge(ctx, tx, p, e, response, "cce.training_feedback_acknowledged",
			"This feedback was already acknowledged.", now); err != nil {
			return err
		}
		if passOn {
			r, err := c.passInTx(ctx, tx, p, e, now)
			if err != nil {
				return err
			}
			passed = r
		}
		return nil
	})
	if err != nil {
		return err
	}
	c.leadershipNotice(ctx, e.ID, eventFeedbackAcknowledged, "A Programme Lead acknowledged your training feedback",
		e.Subject+". "+response, "normal", EngagementsURL, "Open Engagement Log", now, e.Author)
	c.resolveNotice(ctx, eventFeedbackShared, e.ID, p.UserID, now)
	if passed != nil {
		c.tellOfficer(ctx, p, *passed, "Regional Lead feedback passed on by "+leadName(p), now)
	}
	return nil
}

// resolveNotice is _resolve_notice: the reader's own notice that asked.
func (c Coaching) resolveNotice(ctx context.Context, event, id, userID string, now time.Time) {
	err := c.write(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `SELECT gateway_notifications.resolve_condition_for($1, $2, $3, $4, $5)`,
			event, engagementContext, id, userID, now)
		return err
	})
	if err != nil && c.Logger != nil {
		c.Logger.WarnContext(ctx, "ccelead: the notice was not closed", "event", event, "record", id, "err", err)
	}
}

// AcknowledgeRegionalCoaching is acknowledge_regional_coaching.
func (c Coaching) AcknowledgeRegionalCoaching(ctx context.Context, p auth.Principal, id, response string) error {
	if p.ActiveRole != programLead {
		return forbidden("The Programme Lead the coaching was shared with acknowledges it.")
	}
	response = strings.TrimSpace(response)
	if response == "" {
		return badRequest("Say what you will do about the actions agreed, and by when.")
	}
	e, err := c.RegionalCoachingVisible(ctx, p, id)
	if err != nil {
		return err
	}
	if e == nil {
		return missing("Coaching not found.")
	}
	now := c.now().UTC().Truncate(time.Microsecond)
	if err := c.write(ctx, func(tx pgx.Tx) error {
		return c.acknowledge(ctx, tx, p, e, response, "cce.pl_coaching_acknowledged", "This coaching was already acknowledged.", now)
	}); err != nil {
		return err
	}
	c.leadershipNotice(ctx, e.ID, eventPLCoachingAcked, "A Programme Lead acknowledged your coaching notes",
		e.Subject+". "+response, "normal", EngagementsURL, "Open Engagement Log", now, e.Author)
	c.resolveNotice(ctx, eventPLCoachingShared, e.ID, p.UserID, now)
	return nil
}

// DeliveringOfficer is delivering_team_member: the officer on the lead's team
// who delivered the training, nil for partner delivery or none.
func (c Coaching) DeliveringOfficer(ctx context.Context, p auth.Principal, activityID string) (*Officer, error) {
	if activityID == "" {
		return nil, nil
	}
	var delivery, responsible *string
	err := c.DB.QueryRow(ctx, `SELECT delivery_type, responsible_staff_id FROM activity WHERE id = $1`, activityID).
		Scan(&delivery, &responsible)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the training's delivery: %w", err)
	}
	if (delivery != nil && *delivery == "partner") || responsible == nil || *responsible == "" {
		return nil, nil
	}
	team, err := c.Team(ctx, p)
	if err != nil {
		return nil, err
	}
	return OfficerFor(team, *responsible), nil
}

// Passed is passed_engagement_ids for one observation.
func (c Coaching) Passed(ctx context.Context, id string) (bool, error) {
	var passed bool
	err := c.DB.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM cce_cceo_coaching WHERE source_engagement_id = $1)`, id).Scan(&passed)
	if err != nil {
		return false, fmt.Errorf("ccelead: reading whether the feedback was passed on: %w", err)
	}
	return passed, nil
}

// passInTx is pass_feedback_to_cceo's transaction.
func (c Coaching) passInTx(ctx context.Context, tx pgx.Tx, p auth.Principal, e *Engagement, now time.Time) (*Record, error) {
	locked, err := c.oneEngagement(ctx, tx, "TRUE", nil, e.ID, true)
	if err != nil {
		return nil, err
	}
	if locked.Acknowledged == nil {
		return nil, badRequest("Acknowledge the Regional Lead's feedback before passing it on.")
	}
	member, err := c.DeliveringOfficer(ctx, p, locked.ActivityID)
	if err != nil {
		return nil, err
	}
	if member == nil {
		return nil, badRequest("This training was not delivered by an officer on your team, so there is no one to pass the feedback to.")
	}
	var exists bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM cce_cceo_coaching WHERE source_engagement_id = $1 AND cceo_staff_id = $2)`,
		e.ID, member.StaffID).Scan(&exists); err != nil {
		return nil, fmt.Errorf("ccelead: reading whether the feedback was passed on: %w", err)
	}
	if exists {
		return nil, badRequest("This feedback was already passed to the officer.")
	}
	today := c.today()
	label := locked.Subject
	if locked.ActivityID != "" {
		if label, err = c.ActivityLabel(ctx, locked.ActivityID); err != nil {
			return nil, err
		}
	}
	country := member.countryOr(ctx, tx, "")
	if country == "" {
		country = locked.Country
	}
	r := Record{ID: cuid.New(), Author: p.UserID, StaffID: member.StaffID, UserID: member.UserID, Kind: "regional_feedback",
		Subject: cutRunes("Regional Lead feedback · "+label, subjectMax), Growth: locked.Feedback, Actions: locked.Response,
		Shared: &now}
	args := []any{r.ID, now, p.UserID, member.StaffID, member.UserID, today, operationalFY(today), country, r.Subject,
		locked.Feedback, locked.Response, nilIfEmpty(locked.ActivityID), locked.ID}
	args = append(args, ratingArgs(locked.Ratings)...)
	if _, err := tx.Exec(ctx, `INSERT INTO cce_cceo_coaching (id, created_at, updated_at, author_id, cceo_staff_id, cceo_user_id,
  kind, held_on, fy, country, subject, strengths, growth_areas, agreed_actions, follow_up_due, cceo_response, follow_up_note,
  activity_id, debrief_id, source_engagement_id, shared_at, rating_biblical_integration, rating_need_alignment,
  rating_facilitation, rating_participation, rating_application)
VALUES ($1, $2, $2, $3, $4, $5, 'regional_feedback', $6, $7, $8, $9, '', $10, $11, NULL, '', '', $12, NULL, $13, $2,
  $14, $15, $16, $17, $18)`, args...); err != nil {
		return nil, fmt.Errorf("ccelead: passing the feedback on: %w", err)
	}
	if err := coachingAuditAs(ctx, tx, "cce.coaching_feedback_passed", "CceoCoaching", r.ID, p, map[string]any{
		"source_engagement_id": locked.ID, "cceo_staff_id": member.StaffID}, now); err != nil {
		return nil, err
	}
	return &r, nil
}

// PassFeedback is feedback_pass: pass_feedback_to_cceo.
func (c Coaching) PassFeedback(ctx context.Context, p auth.Principal, id string) error {
	if p.ActiveRole != programLead {
		return forbidden("Only the officer's Programme Lead records coaching.")
	}
	e, err := c.FeedbackVisible(ctx, p, id)
	if err != nil {
		return err
	}
	if e == nil {
		return missing("Feedback not found.")
	}
	now := c.now().UTC().Truncate(time.Microsecond)
	var passed *Record
	if err := c.write(ctx, func(tx pgx.Tx) error {
		var err error
		passed, err = c.passInTx(ctx, tx, p, e, now)
		return err
	}); err != nil {
		return err
	}
	c.tellOfficer(ctx, p, *passed, "Regional Lead feedback passed on by "+leadName(p), now)
	return nil
}

// RecommendationChoices are ObservationRecommendation's choices, in order.
func RecommendationChoices() [][2]string {
	out := make([][2]string, 0, len(rules.Saves.RecommendationOrder))
	for _, r := range rules.Saves.RecommendationOrder {
		out = append(out, r)
	}
	return out
}

// RecommendationLabel is RECOMMENDATION_LABELS.
func RecommendationLabel(value string) string { return rules.Recommendations[value] }

// DeliveredBy is delivered_by for one training.
func (c Coaching) DeliveredBy(ctx context.Context, activityID string) (string, error) {
	var o observation
	err := c.DB.QueryRow(ctx, `SELECT a.delivery_type, pa.name, a.responsible_staff_id FROM activity a
LEFT JOIN partner pa ON pa.id = a.assigned_partner_id WHERE a.id = $1`, activityID).Scan(&o.delivery, &o.partner, &o.staff)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("ccelead: reading who delivered the training: %w", err)
	}
	people := map[string]string{}
	if deref(o.delivery) != "partner" && deref(o.staff) != "" {
		if people, err = deliverers(ctx, c.DB, []string{deref(o.staff)}); err != nil {
			return "", err
		}
	}
	return deliveredBy(o, people), nil
}
