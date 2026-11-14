package ccelead

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// FeedbackPath is Training Feedback.
const FeedbackPath = "/cce-leadership/feedback"

// feedbackLimit is how many observations the register reads.
const feedbackLimit = 500

const (
	programLead     = "Program Lead"
	countryDirector = "CountryDirector"
	impact          = "ImpactAssessment"
)

// pyRound1 is Python's round(x, 1); pyStr1 writes it as Python writes a float.
func pyRound1(x float64) float64 {
	r, _ := strconv.ParseFloat(strconv.FormatFloat(x, 'f', 1, 64), 64)
	return r
}

func pyStr1(x float64) string { return strconv.FormatFloat(x, 'f', 1, 64) }

// observations is feedback_visible_to as a WHERE clause on
// cce_regional_engagement `e` (a training observation): Admin every one; the
// Regional Lead their own; of those shared, a Programme Lead's those shared
// with them, and a Country Director's and Impact Assessment's those of their
// own country; nothing for anyone else or without the staff record or
// country the rule reads.
func observations(ctx context.Context, db schooldirectory.Querier, p auth.Principal) (string, []any, error) {
	switch p.ActiveRole {
	case adminRole:
		return "TRUE", nil, nil
	case regionalLead:
		return "e.author_id = $1", []any{p.UserID}, nil
	case programLead:
		staff := p.StaffProfileID
		if staff == "" {
			err := db.QueryRow(ctx, `SELECT id FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL ORDER BY id LIMIT 1`, p.UserID).Scan(&staff)
			if err != nil && err != pgx.ErrNoRows {
				return "", nil, fmt.Errorf("ccelead: reading the lead's staff record: %w", err)
			}
		}
		if staff == "" {
			return "FALSE", nil, nil
		}
		return "e.feedback_shared_at IS NOT NULL AND e.program_lead_ids @> ARRAY[$1]::varchar[]", []any{staff}, nil
	case countryDirector, impact:
		var country *string
		err := db.QueryRow(ctx, `SELECT country FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL ORDER BY id LIMIT 1`, p.UserID).Scan(&country)
		if err != nil && err != pgx.ErrNoRows {
			return "", nil, fmt.Errorf("ccelead: reading the reader's country: %w", err)
		}
		if country == nil || *country == "" {
			return "FALSE", nil, nil
		}
		return "e.feedback_shared_at IS NOT NULL AND e.country = $1", []any{*country}, nil
	}
	return "FALSE", nil, nil
}

type observation struct {
	id, author, subject, country, recommendation string
	held                                         time.Time
	shared, acknowledged                         *time.Time
	ratings                                      []float64
	activity, name, kind, school, cluster        *string
	planned                                      *time.Time
	delivery, partner, staff                     *string
	passed                                       bool
}

// trainingLabel is services.training_label: when, what and where.
func trainingLabel(o observation) string {
	name := deref(o.name)
	if name == "" {
		name = rules.ActivityTypes[deref(o.kind)]
		if name == "" {
			name = deref(o.kind)
		}
	}
	place := deref(o.school)
	if place == "" {
		place = deref(o.cluster)
	}
	when := "Undated"
	if o.planned != nil {
		when = o.planned.Format("2 Jan")
	}
	parts := []string{}
	for _, part := range []string{when, name, place} {
		if part != "" {
			parts = append(parts, part)
		}
	}
	return strings.Join(parts, " · ")
}

// feedback is feedback_view.
func feedback(ctx context.Context, db schooldirectory.Querier, p auth.Principal, _ time.Time) (register, error) {
	where, args, err := observations(ctx, db, p)
	if err != nil {
		return register{}, err
	}
	ratings := []string{}
	for _, f := range rules.RatingFields {
		ratings = append(ratings, "e."+f)
	}
	rows, err := db.Query(ctx, fmt.Sprintf(`
SELECT e.id, e.author_id, e.subject, e.country, e.recommendation, e.held_on, e.feedback_shared_at, e.acknowledged_at,
       ARRAY[%s]::float8[],
       a.id, a.activity_name_snapshot, a.activity_type, sc.name, cl.name, a.planned_date, a.delivery_type, pa.name, a.responsible_staff_id,
       EXISTS (SELECT 1 FROM cce_cceo_coaching c WHERE c.source_engagement_id = e.id)
FROM cce_regional_engagement e
LEFT JOIN activity a ON a.id = e.activity_id LEFT JOIN school sc ON sc.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
LEFT JOIN partner pa ON pa.id = a.assigned_partner_id
WHERE e.kind = 'training_observation' AND %s ORDER BY e.held_on DESC, e.created_at DESC LIMIT %d`,
		strings.Join(ratings, ", "), where, feedbackLimit), args...)
	if err != nil {
		return register{}, fmt.Errorf("ccelead: reading the observations: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (observation, error) {
		var o observation
		var raw []*float64
		err := r.Scan(&o.id, &o.author, &o.subject, &o.country, &o.recommendation, &o.held, &o.shared, &o.acknowledged, &raw,
			&o.activity, &o.name, &o.kind, &o.school, &o.cluster, &o.planned, &o.delivery, &o.partner, &o.staff, &o.passed)
		for _, v := range raw {
			if v != nil && *v != 0 {
				o.ratings = append(o.ratings, *v)
			}
		}
		return o, err
	})
	if err != nil {
		return register{}, fmt.Errorf("ccelead: reading the observations: %w", err)
	}
	pl := p.ActiveRole == programLead
	ids := []string{}
	staff := []string{}
	for _, o := range list {
		ids = append(ids, o.author)
		if o.staff != nil {
			staff = append(staff, *o.staff)
		}
	}
	who, err := names(ctx, db, ids)
	if err != nil {
		return register{}, err
	}
	people, err := deliverers(ctx, db, staff)
	if err != nil {
		return register{}, err
	}
	reg := register{
		path: FeedbackPath, title: "Training Feedback", eyebrow: "Training quality", registerTitle: "Observed trainings",
		description: "The Regional Lead observes trainings and offers constructive critique. The Programme Lead acknowledges each " +
			"piece of feedback and says what will change.",
		emptyTitle: "No training feedback yet",
		emptyBody:  "Feedback appears here when the Regional Lead shares an observation of a training.",
		columns:    []string{"Training", "Observed"},
	}
	if pl {
		reg.description = "The Regional Lead observes trainings and offers constructive critique. The Programme Lead acknowledges " +
			"each piece of feedback, says what will change, and passes it to the officer who delivered the training."
		reg.columns = append(reg.columns, "Delivered by")
	} else {
		reg.columns = append(reg.columns, "Country")
	}
	reg.columns = append(reg.columns, "Regional Lead", "Rating", "Recommendation", "State")
	awaiting, acknowledged := 0, 0
	averages := []float64{}
	for _, o := range list {
		state := "Not shared yet"
		switch {
		case o.acknowledged != nil:
			state = "Acknowledged"
			if pl && o.passed {
				state = "Acknowledged · passed to the officer"
			}
		case o.shared != nil:
			state = "Awaiting the Programme Lead"
			if pl {
				state = "Awaiting your acknowledgement"
			}
		}
		if o.shared != nil {
			if o.acknowledged != nil {
				acknowledged++
			} else {
				awaiting++
			}
		}
		rating := ""
		if len(o.ratings) > 0 {
			sum := 0.0
			for _, r := range o.ratings {
				sum += r
			}
			avg := pyRound1(sum / float64(len(o.ratings)))
			averages = append(averages, avg)
			rating = pyStr1(avg) + " of 4"
		}
		training := o.subject
		if o.activity != nil {
			training = trainingLabel(o)
		}
		third := o.country
		if pl {
			third = ""
			if o.activity != nil {
				third = deliveredBy(o, people)
			}
		}
		reg.rows = append(reg.rows, []string{dash(training), dash(o.held.Format("2 Jan 2006")), dash(third), dash(who[o.author]),
			dash(rating), dash(rules.Recommendations[o.recommendation]), dash(state)})
		acts := []action{{label: "Open", drawer: FeedbackPath + "/" + o.id}}
		if pl && o.activity != nil {
			acts = append(acts, action{label: "Open training", href: "/activities/" + *o.activity})
		}
		reg.rowActions = append(reg.rowActions, acts)
	}
	average, across := "—", fmt.Sprintf("across %d observations", len(averages))
	if len(averages) == 1 {
		across = "across 1 observation"
	}
	if len(averages) > 0 {
		sum := 0.0
		for _, a := range averages {
			sum += a
		}
		average = pyStr1(pyRound1(sum/float64(len(averages)))) + " / 4"
	}
	awaitingTone := "info"
	if awaiting > 0 {
		awaitingTone = "warning"
	}
	reg.metrics = []metric{
		{"Feedback Awaiting Acknowledgement", strconv.Itoa(awaiting), "shared, not yet acknowledged", awaitingTone},
		{"Feedback Acknowledged", strconv.Itoa(acknowledged), "with the Programme Lead's response", "success"},
		{"Average Observation Rating", average, across, "info"},
	}
	return reg, nil
}

// deliverers is the people half of services.delivered_by: each id (a live
// People record's, or an account's) to the person's name.
func deliverers(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]string, error) {
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `
SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(u.name, '') FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1))`, ids)
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading who delivered the trainings: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var staff, user, name string
		if err := rows.Scan(&staff, &user, &name); err != nil {
			return nil, fmt.Errorf("ccelead: reading who delivered the trainings: %w", err)
		}
		out[staff], out[user] = name, name
	}
	return out, rows.Err()
}

// deliveredBy is services.delivered_by for one training: the partner (and
// "· partner") for partner delivery, else the officer's name.
func deliveredBy(o observation, people map[string]string) string {
	if deref(o.delivery) == "partner" {
		if name := deref(o.partner); name != "" {
			return name + " · partner"
		}
		return "Training partner"
	}
	if name := people[deref(o.staff)]; name != "" {
		return name
	}
	return "—"
}
