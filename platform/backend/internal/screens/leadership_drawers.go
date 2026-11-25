package screens

// The Regional Lead's drawers (apps.frontend.views.cce_leadership_views)
// drawn and saved in Go through internal/ccelead with Django absent: Log an
// engagement and Observe a training, one engagement (edited until shared),
// Share with the Programme Lead, the Programme Lead's Training feedback and
// Regional Lead coaching (acknowledged, and an observation passed on to the
// officer), and the monthly report (started, written and submitted, and
// reviewed by the RVP). They are the shared HR form drawer, as Team
// Coaching's are.

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ccelead"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
)

// LeadershipDrawers is internal/ccelead.Coaching's leadership half.
type LeadershipDrawers interface {
	LeadReach(ctx context.Context, p auth.Principal) (ccelead.Reach, error)
	TrainingChoices(ctx context.Context, r ccelead.Reach) ([]ccelead.Choice, error)
	ActivityLabel(ctx context.Context, id string) (string, error)
	EngagementVisible(ctx context.Context, p auth.Principal, id string) (*ccelead.Engagement, error)
	FeedbackVisible(ctx context.Context, p auth.Principal, id string) (*ccelead.Engagement, error)
	RegionalCoachingVisible(ctx context.Context, p auth.Principal, id string) (*ccelead.Engagement, error)
	StaffNames(ctx context.Context, ids []string) (map[string]string, error)
	UserName(ctx context.Context, id string) (string, error)
	RecordEngagement(ctx context.Context, p auth.Principal, data map[string]string) (string, bool, error)
	UpdateEngagement(ctx context.Context, p auth.Principal, id string, data map[string]string) (bool, error)
	ShareEngagement(ctx context.Context, p auth.Principal, id string) (*ccelead.Engagement, error)
	DeliveringOfficer(ctx context.Context, p auth.Principal, activityID string) (*ccelead.Officer, error)
	DeliveredBy(ctx context.Context, activityID string) (string, error)
	Passed(ctx context.Context, id string) (bool, error)
	AcknowledgeFeedback(ctx context.Context, p auth.Principal, id, response string, passOn bool) error
	PassFeedback(ctx context.Context, p auth.Principal, id string) error
	AcknowledgeRegionalCoaching(ctx context.Context, p auth.Principal, id, response string) error
	ReportVisible(ctx context.Context, p auth.Principal, id string) (*ccelead.Report, error)
	MonthOptions() []ccelead.Choice
	DefaultReportMonth(ctx context.Context, p auth.Principal) (string, error)
	StartReport(ctx context.Context, p auth.Principal, period string) (time.Time, error)
	UpdateReport(ctx context.Context, p auth.Principal, id string, data map[string]string, submit bool) (*ccelead.Report, error)
	ReviewReport(ctx context.Context, p auth.Principal, id, decision, note string) (*ccelead.Report, error)
	ReportMetrics(ctx context.Context, p auth.Principal, period time.Time) (map[string]any, error)
}

// WithLeadershipDrawers makes the Regional Lead's drawers Go's.
func (s *Service) WithLeadershipDrawers(l LeadershipDrawers) *Service {
	s.leadership = l
	return s
}

const cceID = `([A-Za-z0-9]{1,30})`

var (
	engagementNew       = regexp.MustCompile(`^/cce-leadership/engagements/(new|record)$`)
	engagementOne       = regexp.MustCompile(`^/cce-leadership/engagements/` + cceID + `(/update)?$`)
	engagementShare     = regexp.MustCompile(`^/cce-leadership/engagements/` + cceID + `/share(/save)?$`)
	feedbackOne         = regexp.MustCompile(`^/cce-leadership/feedback/` + cceID + `$`)
	feedbackAcknowledge = regexp.MustCompile(`^/cce-leadership/feedback/` + cceID + `/acknowledge$`)
	feedbackPass        = regexp.MustCompile(`^/cce-leadership/feedback/` + cceID + `/pass$`)
	regionalCoaching    = regexp.MustCompile(`^/cce-leadership/coaching/` + cceID + `(/acknowledge)?$`)
	reportNew           = regexp.MustCompile(`^/cce-leadership/reports/(new|start)$`)
	reportOne           = regexp.MustCompile(`^/cce-leadership/reports/` + cceID + `$`)
	reportSave          = regexp.MustCompile(`^/cce-leadership/reports/` + cceID + `/save$`)
	reportReview        = regexp.MustCompile(`^/cce-leadership/reports/` + cceID + `/review$`)
)

func choices(pairs [][2]string) []ccelead.Choice {
	out := make([]ccelead.Choice, 0, len(pairs))
	for _, p := range pairs {
		out = append(out, ccelead.Choice{Value: p[0], Label: p[1]})
	}
	return out
}

func checklistField(name, label string, value []string, options []ccelead.Choice, help string) *screensv1.DrawerField {
	f := selectField(name, label, strings.Join(value, ","), "", false, options, help)
	f.Kind = "checklist"
	return f
}

// cceDay is _day: "%-d %b %Y" of the value as stored.
func cceDay(t *time.Time) string {
	if t == nil {
		return ""
	}
	return t.Format("2 Jan 2006")
}

func ratingChoices() []ccelead.Choice { return choices(ccelead.RatingScale) }

func ratingLabel(v int) string {
	for _, r := range ccelead.RatingScale {
		if r[0] == fmt.Sprint(v) {
			return r[1]
		}
	}
	return ""
}

// generalFields is _general_fields.
func generalFields(r ccelead.Reach, e *ccelead.Engagement, kind string, today time.Time) []*screensv1.DrawerField {
	var kinds [][2]string
	for _, k := range ccelead.EngagementKinds() {
		if k[0] != "training_observation" {
			kinds = append(kinds, k)
		}
	}
	held, leads, country, subject, notes, actions, due := today.Format(time.DateOnly), []string{}, "", "", "", "", ""
	kindField := selectField("kind", "Kind of engagement", kind, "Choose the kind", true, choices(kinds), "")
	if e != nil {
		held, leads, country, subject, notes, actions = e.Held.Format(time.DateOnly), e.LeadIDs, e.Country, e.Subject, e.Notes, e.Actions
		if e.FollowUpDue != nil {
			due = e.FollowUpDue.Format(time.DateOnly)
		}
		kindField = &screensv1.DrawerField{Name: "kind", Label: "Kind of engagement", Kind: "hidden", Value: e.Kind, Required: true}
	}
	countries := make([]ccelead.Choice, 0, len(r.Countries))
	for _, c := range r.Countries {
		countries = append(countries, ccelead.Choice{Value: c, Label: c})
	}
	maxSubject := int32(255)
	fields := []*screensv1.DrawerField{
		kindField,
		{Name: "held_on", Label: "Held on", Kind: "date", Required: true, Value: held},
		checklistField("program_lead_ids", "Programme Leads", leads, r.LeadOptions(), "Everyone you met; a coaching conversation names at least one."),
		selectField("country", "Country", country, "No single country", false, countries,
			"Required for a Country Director review or the annual budget input."),
		{Name: "subject", Label: "Subject", Kind: "text", Value: subject, MaxLength: &maxSubject,
			Placeholder: "Filled in from the kind and the people when left empty"},
		{Name: "notes", Label: "What was discussed", Kind: "textarea", Value: notes, Placeholder: "Progress on CCE KPIs, training needs, lessons learned"},
		{Name: "agreed_actions", Label: "Agreed actions", Kind: "textarea", Value: actions},
		{Name: "follow_up_due", Label: "Follow up by", Kind: "date", Value: due},
	}
	if e == nil || e.Kind == "pl_coaching" {
		fields = append(fields, &screensv1.DrawerField{Name: "share_now", Label: "Share the coaching notes with the Programme Lead now",
			Kind: "checkbox", Help: "Coaching conversations only. They read the subject, what was discussed, the actions agreed and the " +
				"follow-up date, and are asked to acknowledge them. Shared notes can no longer be edited."})
	}
	return fields
}

// observationFields is _observation_fields; the trainings offered.
func (s *Service) observationFields(ctx context.Context, r ccelead.Reach, e *ccelead.Engagement, today time.Time) ([]*screensv1.DrawerField, []ccelead.Choice, error) {
	options, err := s.leadership.TrainingChoices(ctx, r)
	if err != nil {
		return nil, nil, err
	}
	if e != nil && e.ActivityID != "" {
		known := false
		for _, o := range options {
			if o.Value == e.ActivityID {
				known = true
			}
		}
		if !known {
			label, err := s.leadership.ActivityLabel(ctx, e.ActivityID)
			if err != nil {
				return nil, nil, err
			}
			options = append([]ccelead.Choice{{Value: e.ActivityID, Label: label}}, options...)
		}
	}
	activity, held, recommendation, feedback, notes, leads := "", today.Format(time.DateOnly), "", "", "", []string{}
	if e != nil {
		activity, held, recommendation, feedback, notes, leads = e.ActivityID, e.Held.Format(time.DateOnly), e.Recommendation, e.Feedback, e.Notes, e.LeadIDs
	}
	fields := []*screensv1.DrawerField{
		{Name: "kind", Kind: "hidden", Value: "training_observation"},
		selectField("activity_id", "Training observed", activity, "Choose the training", true, options, ""),
		{Name: "held_on", Label: "Observed on", Kind: "date", Required: true, Value: held},
	}
	for _, crit := range ccelead.ObservationCriteria {
		value := ""
		if e != nil && e.Ratings[crit[0]] != 0 {
			value = fmt.Sprint(e.Ratings[crit[0]])
		}
		fields = append(fields, selectField(crit[0], crit[1], value, "Rate from 1 to 4", true, ratingChoices(), crit[2]))
	}
	fields = append(fields,
		selectField("recommendation", "Recommendation", recommendation, "Choose a recommendation", true, choices(ccelead.RecommendationChoices()), ""),
		&screensv1.DrawerField{Name: "feedback", Label: "Feedback for the Programme Lead", Kind: "textarea", Required: true, Value: feedback,
			Placeholder: "What worked, what to change, and what to ask of the training partner"},
		checklistField("program_lead_ids", "Send to", leads, r.LeadOptions(),
			"Leave empty to send it to the Programme Lead of the team that ran the training."),
		&screensv1.DrawerField{Name: "notes", Label: "Private notes", Kind: "textarea", Value: notes,
			Help: "Kept in your log; not shared with the Programme Lead."},
		&screensv1.DrawerField{Name: "share_now", Label: "Share the feedback with the Programme Lead now", Kind: "checkbox",
			Help: "They are notified and asked to acknowledge it. Shared feedback can no longer be edited."},
	)
	return fields, options, nil
}

func (s *Service) newEngagementDrawer(ctx context.Context, p auth.Principal, kind string) (*screensv1.PageDrawer, error) {
	r, err := s.leadership.LeadReach(ctx, p)
	if err != nil {
		return nil, err
	}
	if !ccelead.IsRegionalLead(p) {
		return formDrawer(formSpec{title: "Log an engagement", subtitle: "Regional CCE leadership",
			empty: "Only the Regional Programme Lead records CCE engagements."}), nil
	}
	today := s.clock().In(kampalaZone())
	today = time.Date(today.Year(), today.Month(), today.Day(), 0, 0, 0, 0, time.UTC)
	if kind == "training_observation" {
		fields, options, err := s.observationFields(ctx, r, nil, today)
		if err != nil {
			return nil, err
		}
		const subtitle = "Constructive critique for the Programme Lead and the training partner"
		if len(options) == 0 {
			return formDrawer(formSpec{title: "Observe a training", subtitle: subtitle,
				empty: "No training in your region was held in the last four months or is planned for the next two weeks."}), nil
		}
		return formDrawer(formSpec{title: "Observe a training", subtitle: subtitle, action: true, submit: "Record observation", fields: fields,
			note: "Rate what you saw against Edify's Biblical integration framework and the schools' SSA needs, then say what should change."}), nil
	}
	return formDrawer(formSpec{title: "Log an engagement", subtitle: "A conversation, meeting or visit you held", action: true,
		submit: "Record engagement", fields: generalFields(r, nil, kind, today)}), nil
}

// engagementFacts is _engagement_facts.
func (s *Service) engagementFacts(ctx context.Context, e *ccelead.Engagement, names map[string]string) ([][2]string, error) {
	leads := make([]string, 0, len(e.LeadIDs))
	for _, id := range e.LeadIDs {
		name := names[id]
		if name == "" {
			name = "Programme Lead"
		}
		leads = append(leads, name)
	}
	held := e.Held
	facts := [][2]string{{"Kind", ccelead.EngagementKindLabel(e.Kind)}, {"Held on", cceDay(&held)}, {"Country", e.Country},
		{"Programme Leads", strings.Join(leads, ", ")}}
	if e.IsObservation() {
		training := e.Subject
		if e.ActivityID != "" {
			label, err := s.leadership.ActivityLabel(ctx, e.ActivityID)
			if err != nil {
				return nil, err
			}
			training = label
		}
		facts = append(facts, [2]string{"Training", training})
		for _, crit := range ccelead.ObservationCriteria {
			facts = append(facts, [2]string{crit[1], ratingLabel(e.Ratings[crit[0]])})
		}
		average := e.AverageRating()
		if average != "" {
			average += " of 4"
		}
		facts = append(facts, [2]string{"Average rating", average}, [2]string{"Recommendation", ccelead.RecommendationLabel(e.Recommendation)},
			[2]string{"Feedback", e.Feedback}, [2]string{"Shared", cceDay(e.Shared)}, [2]string{"Acknowledged", cceDay(e.Acknowledged)},
			[2]string{"Programme Lead's response", e.Response})
		return facts, nil
	}
	facts = append(facts, [2]string{"Subject", e.Subject}, [2]string{"What was discussed", e.Notes},
		[2]string{"Agreed actions", e.Actions}, [2]string{"Follow up by", cceDay(e.FollowUpDue)})
	if e.Kind == "pl_coaching" {
		facts = append(facts, [2]string{"Shared", cceDay(e.Shared)}, [2]string{"Acknowledged", cceDay(e.Acknowledged)},
			[2]string{"Programme Lead's response", e.Response})
	}
	return facts, nil
}

func (s *Service) oneEngagementDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	e, err := s.leadership.EngagementVisible(ctx, p, id)
	if err != nil {
		return nil, err
	}
	if e == nil {
		return formDrawer(formSpec{title: "Engagement", subtitle: "Regional CCE leadership", empty: "This engagement is not in your log."}), nil
	}
	r, err := s.leadership.LeadReach(ctx, p)
	if err != nil {
		return nil, err
	}
	kind := ccelead.EngagementKindLabel(e.Kind)
	if !(ccelead.IsRegionalLead(p) && e.Author == p.UserID && e.Shared == nil) {
		facts, err := s.engagementFacts(ctx, e, r.Names())
		if err != nil {
			return nil, err
		}
		empty := "Read only."
		if e.Shared != nil {
			empty = "This has been shared with the Programme Lead and can no longer be edited."
		}
		return formDrawer(formSpec{title: e.Subject, subtitle: kind, facts: facts, empty: empty}), nil
	}
	today := s.clock().In(kampalaZone())
	today = time.Date(today.Year(), today.Month(), today.Day(), 0, 0, 0, 0, time.UTC)
	var fields []*screensv1.DrawerField
	note := ""
	if e.IsObservation() {
		if fields, _, err = s.observationFields(ctx, r, e, today); err != nil {
			return nil, err
		}
		note = "The feedback stays private to you until you share it."
	} else {
		fields = generalFields(r, e, "", today)
		if e.Kind == "pl_coaching" {
			note = "The notes stay private to you until you share them with the Programme Lead."
		}
	}
	return formDrawer(formSpec{title: e.Subject, subtitle: kind, action: true, submit: "Save", fields: fields, note: note}), nil
}

func (s *Service) shareEngagementDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	const title = "Share with the Programme Lead"
	e, err := s.leadership.EngagementVisible(ctx, p, id)
	if err != nil {
		return nil, err
	}
	if e == nil {
		return formDrawer(formSpec{title: title, subtitle: "Regional CCE leadership", empty: "This engagement is not in your log."}), nil
	}
	r, err := s.leadership.LeadReach(ctx, p)
	if err != nil {
		return nil, err
	}
	facts, err := s.engagementFacts(ctx, e, r.Names())
	if err != nil {
		return nil, err
	}
	if !(ccelead.IsRegionalLead(p) && e.Author == p.UserID && ccelead.Shareable(e.Kind) && e.Shared == nil) {
		empty := "Only a coaching conversation or a training observation you recorded is shared with the Programme Lead."
		if e.Shared != nil {
			empty = "Shared on " + cceDay(e.Shared) + "."
		}
		return formDrawer(formSpec{title: title, subtitle: e.Subject, facts: facts, empty: empty}), nil
	}
	if len(e.LeadIDs) == 0 {
		return formDrawer(formSpec{title: title, subtitle: e.Subject, facts: facts,
			empty: "Name the Programme Lead in the engagement before sharing it."}), nil
	}
	note := "The Programme Lead reads the subject, what was discussed, the actions agreed and the follow-up date, and is asked to acknowledge them."
	if e.IsObservation() {
		note = "The Programme Lead reads the feedback and is asked to acknowledge it."
	}
	return formDrawer(formSpec{title: title, subtitle: e.Subject, facts: facts, action: true, submit: "Share",
		note: note + " Once shared it can no longer be edited."}), nil
}

func withLeadAuthor(facts [][2]string, author string, drop ...string) [][2]string {
	out := [][2]string{{"Regional Lead", author}}
	for _, f := range facts {
		skip := false
		for _, d := range drop {
			if f[0] == d {
				skip = true
			}
		}
		if !skip {
			out = append(out, f)
		}
	}
	return out
}

func (s *Service) feedbackDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	const title = "Training feedback"
	o, err := s.leadership.FeedbackVisible(ctx, p, id)
	if err != nil {
		return nil, err
	}
	if o == nil {
		return formDrawer(formSpec{title: title, subtitle: "Training quality", empty: "This feedback is not addressed to you."}), nil
	}
	names, err := s.leadership.StaffNames(ctx, o.LeadIDs)
	if err != nil {
		return nil, err
	}
	facts, err := s.engagementFacts(ctx, o, names)
	if err != nil {
		return nil, err
	}
	author, err := s.leadership.UserName(ctx, o.Author)
	if err != nil {
		return nil, err
	}
	facts = withLeadAuthor(facts, author, "Kind")
	isPL := p.ActiveRole == "Program Lead"
	var officer *ccelead.Officer
	passed := false
	if isPL && o.ActivityID != "" {
		by, err := s.leadership.DeliveredBy(ctx, o.ActivityID)
		if err != nil {
			return nil, err
		}
		facts = append(facts[:2], append([][2]string{{"Delivered by", by}}, facts[2:]...)...)
		if officer, err = s.leadership.DeliveringOfficer(ctx, p, o.ActivityID); err != nil {
			return nil, err
		}
		if passed, err = s.leadership.Passed(ctx, o.ID); err != nil {
			return nil, err
		}
	}
	officerName := "the officer"
	if officer != nil && officer.Name != "" {
		officerName = officer.Name
	}
	if isPL && o.Shared != nil && o.Acknowledged == nil {
		fields := []*screensv1.DrawerField{{Name: "response", Label: "Your response", Kind: "textarea", Required: true,
			Placeholder: "What will change in the training, with whom, and by when"}}
		if officer != nil {
			fields = append(fields, &screensv1.DrawerField{Name: "pass_to_cceo", Label: fmt.Sprintf("Pass this feedback to %s, who delivered it", officerName),
				Kind: "checkbox", Help: "Shared with them as coaching, with the ratings, the Regional Lead's feedback and your response as the " +
					"actions agreed. They are asked to acknowledge it."})
		}
		return formDrawer(formSpec{title: title, subtitle: o.Subject, facts: facts, action: true, submit: "Acknowledge feedback", fields: fields}), nil
	}
	if isPL && o.Acknowledged != nil && officer != nil && !passed {
		return formDrawer(formSpec{title: title, subtitle: o.Subject, facts: facts, action: true, submit: "Pass to " + officerName,
			note: fmt.Sprintf("Acknowledged. Pass it to %s, who delivered the training, as coaching they acknowledge: the ratings, the "+
				"Regional Lead's feedback and your response as the actions agreed.", officerName)}), nil
	}
	empty := "Read only."
	switch {
	case passed:
		empty = "Acknowledged and passed to the officer who delivered it."
	case o.Acknowledged != nil:
		empty = "Acknowledged."
	}
	return formDrawer(formSpec{title: title, subtitle: o.Subject, facts: facts, empty: empty}), nil
}

func (s *Service) regionalCoachingDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	const title = "Regional Lead coaching"
	e, err := s.leadership.RegionalCoachingVisible(ctx, p, id)
	if err != nil {
		return nil, err
	}
	if e == nil {
		return formDrawer(formSpec{title: title, subtitle: "Collaboration", empty: "This coaching was not shared with you."}), nil
	}
	names, err := s.leadership.StaffNames(ctx, e.LeadIDs)
	if err != nil {
		return nil, err
	}
	facts, err := s.engagementFacts(ctx, e, names)
	if err != nil {
		return nil, err
	}
	author, err := s.leadership.UserName(ctx, e.Author)
	if err != nil {
		return nil, err
	}
	facts = withLeadAuthor(facts, author, "Kind", "Country")
	if !(p.ActiveRole == "Program Lead" && e.Shared != nil && e.Acknowledged == nil) {
		empty := "Read only."
		if e.Acknowledged != nil {
			empty = "Acknowledged."
		}
		return formDrawer(formSpec{title: title, subtitle: e.Subject, facts: facts, empty: empty}), nil
	}
	return formDrawer(formSpec{title: title, subtitle: e.Subject, facts: facts, action: true, submit: "Acknowledge coaching",
		fields: []*screensv1.DrawerField{{Name: "response", Label: "Your response", Kind: "textarea", Required: true,
			Placeholder: "What you will do about each action agreed, and by when"}}}), nil
}

func (s *Service) newReportDrawer(ctx context.Context, p auth.Principal) (*screensv1.PageDrawer, error) {
	if !ccelead.IsRegionalLead(p) {
		return formDrawer(formSpec{title: "Start a monthly report", subtitle: "Collaboration and reporting",
			empty: "Only the Regional Programme Lead writes the monthly CCE report."}), nil
	}
	month, err := s.leadership.DefaultReportMonth(ctx, p)
	if err != nil {
		return nil, err
	}
	return formDrawer(formSpec{title: "Start a monthly report", subtitle: "To the RVP and the VP of CCE", action: true, submit: "Start report",
		fields: []*screensv1.DrawerField{selectField("period", "Month", month, "", true, s.leadership.MonthOptions(), "")},
		note:   "An existing report for the month opens again rather than starting a second one."}), nil
}

// metricFacts is _metric_facts.
func metricFacts(m map[string]any) [][2]string {
	if len(m) == 0 {
		return nil
	}
	num := func(key string) string {
		switch v := m[key].(type) {
		case float64:
			return fmt.Sprint(int(v))
		case int:
			return fmt.Sprint(v)
		case nil:
			return "0"
		}
		return fmt.Sprint(m[key])
	}
	var byCountry []string
	if bc, ok := m["trainings_by_country"].(map[string]any); ok {
		keys := make([]string, 0, len(bc))
		for k := range bc {
			keys = append(keys, k)
		}
		sortStrings(keys)
		for _, k := range keys {
			byCountry = append(byCountry, fmt.Sprintf("%s %v", k, intOf(bc[k])))
		}
	}
	countries := strings.Join(byCountry, " · ")
	if countries == "" {
		countries = "None"
	}
	informed := "No plans judged"
	if v, ok := m["ssa_informed_plans_pct"]; ok && v != nil {
		informed = fmt.Sprintf("%v%%", intOf(v))
	}
	observed := num("trainings_observed")
	if v, ok := m["average_observation_rating"]; ok && v != nil {
		if f, isFloat := v.(float64); isFloat && f != 0 {
			observed += " · average " + pyFloat(f) + " of 4"
		}
	}
	return [][2]string{
		{"Trainings delivered", fmt.Sprintf("%s · %s teachers, %s leaders", num("trainings_delivered"), num("teachers_trained"), num("leaders_trained"))},
		{"Trainings by country", countries},
		{"Coaching and follow-up visits", num("coaching_follow_up_visits")},
		{"SSA assessments confirmed", num("ssa_confirmed")},
		{"Plans informed by the SSA", informed},
		{"Coaching conversations", num("coaching_conversations")},
		{"Trainings observed", observed},
		{"Country Director reviews", num("country_reviews")},
	}
}

func intOf(v any) any {
	if f, ok := v.(float64); ok && f == float64(int64(f)) {
		return int64(f)
	}
	return v
}

// pyFloat is str() of a Python float rounded to one place.
func pyFloat(f float64) string {
	s := fmt.Sprintf("%.1f", f)
	return s
}

func sortStrings(s []string) {
	for i := 1; i < len(s); i++ {
		for j := i; j > 0 && s[j] < s[j-1]; j-- {
			s[j], s[j-1] = s[j-1], s[j]
		}
	}
}

// toAnyMap reads Go's own figures the way the stored ones read.
func toAnyMap(m map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range m {
		switch n := v.(type) {
		case int:
			out[k] = float64(n)
		case map[string]any:
			out[k] = toAnyMap(n)
		default:
			out[k] = v
		}
	}
	return out
}

func (s *Service) oneReportDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	r, err := s.leadership.ReportVisible(ctx, p, id)
	if err != nil {
		return nil, err
	}
	if r == nil {
		return formDrawer(formSpec{title: "Monthly CCE report", subtitle: "Collaboration and reporting", empty: "This report is not in your reach."}), nil
	}
	title := r.Period.Format("January 2006") + " CCE report"
	facts := [][2]string{{"Status", ccelead.ReportStatusLabel(r.Status)}, {"Countries", strings.Join(r.Countries, ", ")},
		{"Submitted", cceDay(r.Submitted)}}
	if r.ReviewNote != "" {
		facts = append(facts, [2]string{"RVP's note", r.ReviewNote})
	}
	if ccelead.IsRegionalLead(p) && (r.Status == "draft" || r.Status == "returned") {
		preview, err := s.leadership.ReportMetrics(ctx, p, r.Period)
		if err != nil {
			return nil, err
		}
		var fields []*screensv1.DrawerField
		for _, sec := range ccelead.ReportSections() {
			fields = append(fields, &screensv1.DrawerField{Name: sec[0], Label: sec[1], Kind: "textarea", Value: r.Sections[sec[0]],
				Help: sec[2], Required: sec[0] == "executive_summary"})
		}
		fields = append(fields, &screensv1.DrawerField{Name: "submit", Label: "Submit to the RVP and the VP of CCE now", Kind: "checkbox",
			Help: "Leave unticked to keep it as a draft. The figures above are frozen when you submit."})
		spec := formSpec{title: title, subtitle: "Figures as of today", facts: append(facts, metricFacts(toAnyMap(preview))...),
			action: true, submit: "Save report", fields: fields, noteTone: "warning"}
		if r.Status == "returned" && r.ReviewNote != "" {
			spec.note = "Returned by the RVP: " + r.ReviewNote
		}
		return formDrawer(spec), nil
	}
	var content [][2]string
	for _, sec := range ccelead.ReportSections() {
		content = append(content, [2]string{sec[1], r.Sections[sec[0]]})
	}
	all := append(append(facts, content...), metricFacts(r.Metrics)...)
	if (p.ActiveRole == "RegionalVicePresident" || p.ActiveRole == "Admin") && r.Status == "submitted" {
		author, err := s.leadership.UserName(ctx, r.Author)
		if err != nil {
			return nil, err
		}
		if author == "" {
			author = "the Regional Lead"
		}
		return formDrawer(formSpec{title: title, subtitle: "From " + author, facts: all, action: true, submit: "Record review",
			fields: []*screensv1.DrawerField{
				selectField("decision", "Decision", "", "Choose a decision", true,
					[]ccelead.Choice{{Value: "acknowledge", Label: "Acknowledge the report"}, {Value: "return", Label: "Return it for revision"}}, ""),
				{Name: "note", Label: "Note to the Regional Lead", Kind: "textarea", Help: "Required when returning: say what the report needs."},
			}}), nil
	}
	return formDrawer(formSpec{title: title, subtitle: "Collaboration and reporting", facts: all, empty: "Read only."}), nil
}

// leadershipDrawerInGo answers the drawers; served is false for any other
// path, a role whose page refuses it, or with Django present.
func (s *Service) leadershipDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	if s.leadership == nil || s.existingApp != nil {
		return nil, false, nil
	}
	path, query, _ := strings.Cut(rawPath, "?")
	if !strings.HasPrefix(path, "/cce-leadership/") || !pageaccess.CanOpen(p.ActiveRole, false, path) {
		return nil, false, nil
	}
	var d *screensv1.PageDrawer
	var err error
	switch {
	case path == "/cce-leadership/engagements/new":
		d, err = s.newEngagementDrawer(ctx, p, queryValues(query)["kind"])
	case engagementShare.MatchString(path) && !strings.HasSuffix(path, "/save"):
		d, err = s.shareEngagementDrawer(ctx, p, engagementShare.FindStringSubmatch(path)[1])
	case engagementOne.MatchString(path) && !strings.HasSuffix(path, "/update"):
		d, err = s.oneEngagementDrawer(ctx, p, engagementOne.FindStringSubmatch(path)[1])
	case feedbackOne.MatchString(path):
		d, err = s.feedbackDrawer(ctx, p, feedbackOne.FindStringSubmatch(path)[1])
	case regionalCoaching.MatchString(path) && !strings.HasSuffix(path, "/acknowledge"):
		d, err = s.regionalCoachingDrawer(ctx, p, regionalCoaching.FindStringSubmatch(path)[1])
	case path == "/cce-leadership/reports/new":
		d, err = s.newReportDrawer(ctx, p)
	case reportOne.MatchString(path):
		d, err = s.oneReportDrawer(ctx, p, reportOne.FindStringSubmatch(path)[1])
	default:
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

// leadershipSaveInGo is the drawers' saves.
func (s *Service) leadershipSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest) (*screensv1.SaveDrawerResponse, bool, error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok || s.leadership == nil || s.existingApp != nil {
		return nil, false, nil
	}
	path, _, _ := strings.Cut(message.GetPath(), "?")
	if !strings.HasPrefix(path, "/cce-leadership/") || !pageaccess.CanOpen(p.ActiveRole, false, path) {
		return nil, false, nil
	}
	values := message.GetValues()
	saved := func(back, words string) (*screensv1.SaveDrawerResponse, bool, error) {
		return &screensv1.SaveDrawerResponse{Saved: true, Message: words, Redirect: back}, true, nil
	}
	refused := func(err error) (*screensv1.SaveDrawerResponse, bool, error) {
		var refusal *ccelead.CoachingRefusal
		if errors.As(err, &refusal) {
			return &screensv1.SaveDrawerResponse{Error: refusal.Message}, true, nil
		}
		return nil, true, err
	}
	switch {
	case engagementNew.MatchString(path):
		_, shared, err := s.leadership.RecordEngagement(ctx, p, values)
		if err != nil {
			return refused(err)
		}
		if shared {
			what := "Coaching conversation"
			if values["kind"] == "training_observation" {
				what = "Observation"
			}
			return saved(ccelead.EngagementsURL, what+" recorded and shared with the Programme Lead.")
		}
		return saved(ccelead.EngagementsURL, "Engagement recorded.")
	case engagementShare.MatchString(path):
		e, err := s.leadership.ShareEngagement(ctx, p, engagementShare.FindStringSubmatch(path)[1])
		if err != nil {
			return refused(err)
		}
		if e.IsObservation() {
			return saved(ccelead.EngagementsURL, "Feedback shared with the Programme Lead.")
		}
		return saved(ccelead.EngagementsURL, "Shared with the Programme Lead. They have been asked to acknowledge it.")
	case engagementOne.MatchString(path):
		id := engagementOne.FindStringSubmatch(path)[1]
		e, err := s.leadership.EngagementVisible(ctx, p, id)
		if err != nil {
			return nil, true, err
		}
		shared, err := s.leadership.UpdateEngagement(ctx, p, id, values)
		if err != nil {
			return refused(err)
		}
		if shared {
			what := "Coaching conversation"
			if e != nil && e.IsObservation() {
				what = "Observation"
			}
			return saved(ccelead.EngagementsURL, what+" saved and shared with the Programme Lead.")
		}
		return saved(ccelead.EngagementsURL, "Engagement saved.")
	case feedbackPass.MatchString(path):
		if err := s.leadership.PassFeedback(ctx, p, feedbackPass.FindStringSubmatch(path)[1]); err != nil {
			return refused(err)
		}
		return saved(ccelead.FeedbackURL, "Feedback passed to the officer, who is asked to acknowledge it.")
	case feedbackAcknowledge.MatchString(path), feedbackOne.MatchString(path):
		m := feedbackAcknowledge.FindStringSubmatch(path)
		if m == nil {
			m = feedbackOne.FindStringSubmatch(path)
			// The drawer's own path: an acknowledged observation's only
			// step is passing it on.
			o, err := s.leadership.FeedbackVisible(ctx, p, m[1])
			if err != nil {
				return nil, true, err
			}
			if o != nil && o.Acknowledged != nil {
				if err := s.leadership.PassFeedback(ctx, p, m[1]); err != nil {
					return refused(err)
				}
				return saved(ccelead.FeedbackURL, "Feedback passed to the officer, who is asked to acknowledge it.")
			}
		}
		passOn := checked(values["pass_to_cceo"])
		if err := s.leadership.AcknowledgeFeedback(ctx, p, m[1], values["response"], passOn); err != nil {
			return refused(err)
		}
		if passOn {
			return saved(ccelead.FeedbackURL, "Feedback acknowledged and passed to the officer. The Regional Lead has been told.")
		}
		return saved(ccelead.FeedbackURL, "Feedback acknowledged. The Regional Lead has been told.")
	case regionalCoaching.MatchString(path):
		if err := s.leadership.AcknowledgeRegionalCoaching(ctx, p, regionalCoaching.FindStringSubmatch(path)[1], values["response"]); err != nil {
			return refused(err)
		}
		return saved(ccelead.CoachingURL, "Coaching acknowledged. The Regional Lead has been told.")
	case reportNew.MatchString(path):
		period, err := s.leadership.StartReport(ctx, p, values["period"])
		if err != nil {
			return refused(err)
		}
		return saved(ccelead.ReportsURL, period.Format("January 2006")+" report ready to write.")
	case reportReview.MatchString(path):
		return s.reviewReport(ctx, p, reportReview.FindStringSubmatch(path)[1], values, saved, refused)
	case reportSave.MatchString(path), reportOne.MatchString(path):
		m := reportSave.FindStringSubmatch(path)
		if m == nil {
			m = reportOne.FindStringSubmatch(path)
			// The drawer's own path: the RVP's review of a submitted report.
			if !ccelead.IsRegionalLead(p) {
				return s.reviewReport(ctx, p, m[1], values, saved, refused)
			}
		}
		data := map[string]string{}
		for _, sec := range ccelead.ReportSections() {
			data[sec[0]] = values[sec[0]]
		}
		submit := checked(values["submit"])
		r, err := s.leadership.UpdateReport(ctx, p, m[1], data, submit)
		if err != nil {
			return refused(err)
		}
		if submit {
			return saved(ccelead.ReportsURL, r.Period.Format("January 2006")+" report submitted to the RVP.")
		}
		return saved(ccelead.ReportsURL, r.Period.Format("January 2006")+" report saved as a draft.")
	}
	return nil, false, nil
}

func (s *Service) reviewReport(ctx context.Context, p auth.Principal, id string, values map[string]string,
	saved func(string, string) (*screensv1.SaveDrawerResponse, bool, error),
	refused func(error) (*screensv1.SaveDrawerResponse, bool, error)) (*screensv1.SaveDrawerResponse, bool, error) {
	r, err := s.leadership.ReviewReport(ctx, p, id, values["decision"], values["note"])
	if err != nil {
		return refused(err)
	}
	return saved(ccelead.ReportsURL, fmt.Sprintf("%s report %s.", r.Period.Format("January 2006"), strings.ToLower(ccelead.ReportStatusLabel(r.Status))))
}
