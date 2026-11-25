package screens

// Team Coaching's drawers (apps.frontend.views.coaching_views) drawn and saved
// in Go through internal/ccelead with Django absent: Log coaching, a record
// (edited until the officer acknowledges it, read-only after), Share and
// Follow up agreed actions. They are the shared HR form drawer
// (partials/hr/form_drawer.html) in the same order: the facts, the note, the
// fields, the submit; or the facts and a note when nothing may be done.

import (
	"context"
	"errors"
	"fmt"
	"math"
	"regexp"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ccelead"
)

// CoachingDrawers is internal/ccelead.Coaching.
type CoachingDrawers interface {
	Team(ctx context.Context, p auth.Principal) ([]ccelead.Officer, error)
	ActivityChoices(ctx context.Context, scope []ccelead.Officer, named bool) ([]ccelead.Choice, error)
	DebriefChoices(ctx context.Context, scope []ccelead.Officer, named bool) ([]ccelead.Choice, error)
	Visible(ctx context.Context, p auth.Principal, id string) (*ccelead.Record, error)
	RecordCoaching(ctx context.Context, p auth.Principal, data map[string]string) (string, error)
	UpdateCoaching(ctx context.Context, p auth.Principal, id string, data map[string]string) (ccelead.Record, error)
	ShareCoaching(ctx context.Context, p auth.Principal, id string) (ccelead.Record, error)
	CompleteFollowUp(ctx context.Context, p auth.Principal, id, note string) error
	OfficerVisible(ctx context.Context, p auth.Principal, id string) (*ccelead.Record, error)
	AcknowledgeCoaching(ctx context.Context, p auth.Principal, id, response string) error
}

// WithCoachingDrawers makes Team Coaching's drawers Go's.
func (s *Service) WithCoachingDrawers(c CoachingDrawers) *Service {
	s.coaching = c
	return s
}

const teamCoaching = "/team/coaching"

var (
	coachingNew      = regexp.MustCompile(`^/team/coaching/new$`)
	coachingOne      = regexp.MustCompile(`^/team/coaching/([A-Za-z0-9]{1,30})$`)
	coachingShare    = regexp.MustCompile(`^/team/coaching/([A-Za-z0-9]{1,30})/share$`)
	coachingFollowUp = regexp.MustCompile(`^/team/coaching/([A-Za-z0-9]{1,30})/follow-up$`)
	myCoaching       = regexp.MustCompile(`^/my-coaching/([A-Za-z0-9]{1,30})$`)
)

// formSpec is hr_programme_views._drawer's context.
type formSpec struct {
	title, subtitle, note, noteTone, submit, empty string
	facts                                          [][2]string
	fields                                         []*screensv1.DrawerField
	action                                         bool
}

// formDrawer is partials/hr/form_drawer.html.
func formDrawer(f formSpec) *screensv1.PageDrawer {
	d := &screensv1.PageDrawer{Title: f.title, Subtitle: f.subtitle}
	if len(f.facts) > 0 {
		var facts []*screensv1.PageFact
		for _, x := range f.facts {
			value := x[1]
			if value == "" {
				value = "—"
			}
			facts = append(facts, fact(x[0], value))
		}
		d.Items = append(d.Items, factsItem(facts...))
	}
	switch {
	case f.action:
		if f.note != "" {
			tone := f.noteTone
			if tone == "" {
				tone = "info"
			}
			d.Items = append(d.Items, note(f.note, tone))
		}
		for _, field := range f.fields {
			if field.Required {
				d.HasRequired = true
			}
			d.Items = append(d.Items, actingField(field))
		}
		d.CanSubmit, d.SubmitLabel, d.CancelLabel = true, f.submit, "Cancel"
		if d.SubmitLabel == "" {
			d.SubmitLabel = "Save"
		}
	case f.empty != "":
		d.Items = append(d.Items, note(f.empty, "info"))
		d.CancelLabel = "Close"
	}
	return d
}

func selectField(name, label, value, blank string, required bool, choices []ccelead.Choice, help string) *screensv1.DrawerField {
	var options []*screensv1.DrawerOption
	if blank != "" {
		options = append(options, &screensv1.DrawerOption{Value: "", Label: blank})
	}
	for _, c := range choices {
		options = append(options, &screensv1.DrawerOption{Value: c.Value, Label: c.Label})
	}
	return &screensv1.DrawerField{Name: name, Label: label, Kind: "select", Value: value, Required: required, Options: options, Help: help}
}

func coachDay(t *time.Time) string {
	if t == nil {
		return ""
	}
	return t.Format("2 Jan 2006")
}

// coachingFields is _coaching_fields.
func (s *Service) coachingFields(ctx context.Context, team []ccelead.Officer, member *ccelead.Officer, kind string,
	r *ccelead.Record, prefill map[string]string) ([]*screensv1.DrawerField, error) {
	rated := ccelead.RatedKind(kind)
	var fields []*screensv1.DrawerField
	if r == nil {
		var people []ccelead.Choice
		for _, m := range team {
			people = append(people, ccelead.Choice{Value: m.StaffID, Label: m.Name})
		}
		value := ""
		if member != nil {
			value = member.StaffID
		}
		fields = append(fields, selectField("cceo_staff_id", "Officer", value, "Choose the officer", true, people, ""))
		var kinds []ccelead.Choice
		for _, k := range ccelead.CoachingKinds {
			if ccelead.RecordableKind(k[0]) && ccelead.RatedKind(k[0]) == rated {
				kinds = append(kinds, ccelead.Choice{Value: k[0], Label: k[1]})
			}
		}
		label := "Kind of coaching"
		if rated {
			label = "What was observed"
		}
		fields = append(fields, selectField("kind", label, kind, "Choose the kind", true, kinds, ""))
	}
	held := s.clock().In(kampalaZone()).Format(time.DateOnly)
	if r != nil {
		held = r.Held.Format(time.DateOnly)
	}
	heldLabel := "Held on"
	if rated {
		heldLabel = "Observed on"
	}
	fields = append(fields, &screensv1.DrawerField{Name: "held_on", Label: heldLabel, Kind: "date", Required: true, Value: held})
	scope := team
	if member != nil {
		scope = []ccelead.Officer{*member}
	}
	activities, err := s.coaching.ActivityChoices(ctx, scope, member == nil)
	if err != nil {
		return nil, err
	}
	activity := prefill["activity"]
	if r != nil {
		activity = r.ActivityID
	}
	if rated {
		fields = append(fields, selectField("activity_id", "Training or visit observed", activity, "Choose the activity", false,
			activities, "Required for a training observation."))
		for _, crit := range ccelead.ObservationCriteria {
			value := ""
			if r != nil && r.Ratings[crit[0]] != nil {
				value = fmt.Sprint(*r.Ratings[crit[0]])
			}
			var scale []ccelead.Choice
			for _, x := range ccelead.RatingScale {
				scale = append(scale, ccelead.Choice{Value: x[0], Label: x[1]})
			}
			fields = append(fields, selectField(crit[0], crit[1], value, "Rate from 1 to 4", true, scale, crit[2]))
		}
	} else {
		fields = append(fields, selectField("activity_id", "Activity it concerns", activity, "No activity", false, activities,
			"Optional: a recent activity of the officer's this coaching is about."))
		debriefs, err := s.coaching.DebriefChoices(ctx, scope, member == nil)
		if err != nil {
			return nil, err
		}
		debrief := prefill["debrief"]
		if r != nil {
			debrief = r.DebriefID
		}
		fields = append(fields, selectField("debrief_id", "Field debrief it answers", debrief, "No field debrief", false, debriefs,
			"Optional: for feedback on a debrief the officer submitted."))
	}
	text := func(name, label, value, placeholder string) *screensv1.DrawerField {
		return &screensv1.DrawerField{Name: name, Label: label, Kind: "textarea", Value: value, Placeholder: placeholder}
	}
	var subject, strengths, growth, actions, due string
	if r != nil {
		subject, strengths, growth, actions, due = r.Subject, r.Strengths, r.Growth, r.Actions, ""
		if r.FollowUpDue != nil {
			due = r.FollowUpDue.Format(time.DateOnly)
		}
	}
	max := int32(255)
	fields = append(fields,
		&screensv1.DrawerField{Name: "subject", Label: "Subject", Kind: "text", Value: subject, MaxLength: &max,
			Placeholder: "Filled in from the kind and the officer when left empty"},
		text("strengths", "Strengths", strengths, "What the officer did well"),
		text("growth_areas", "Areas to grow", growth, "What to strengthen, and why it matters for schools"),
		text("agreed_actions", "Actions agreed", actions, "What the officer will do, with whom, by when"),
		&screensv1.DrawerField{Name: "follow_up_due", Label: "Follow up by", Kind: "date", Value: due,
			Help: "When you will check the actions agreed. You are reminded on the day."},
	)
	if r == nil || r.Shared == nil {
		fields = append(fields, &screensv1.DrawerField{Name: "share_now", Label: "Share with the officer now", Kind: "checkbox",
			Help: "They are notified and asked to acknowledge it. You can still correct it until they do."})
	}
	return fields, nil
}

func kampalaZone() *time.Location {
	if loc, err := time.LoadLocation("Africa/Kampala"); err == nil {
		return loc
	}
	return time.UTC
}

// recordFacts is _record_facts.
func recordFacts(r *ccelead.Record, officer, author string, forOfficer bool) [][2]string {
	facts := [][2]string{{"Officer", officer}, {"Programme Lead", author}, {"Kind", ccelead.KindLabel(r.Kind)},
		{"Held on", coachDay(&r.Held)}, {"Subject", r.Subject}}
	var ratings []int
	for _, crit := range ccelead.ObservationCriteria {
		if v := r.Ratings[crit[0]]; v != nil && *v != 0 {
			ratings = append(ratings, *v)
		}
	}
	if len(ratings) > 0 {
		for _, crit := range ccelead.ObservationCriteria {
			label := ""
			if v := r.Ratings[crit[0]]; v != nil {
				for _, x := range ccelead.RatingScale {
					if x[0] == fmt.Sprint(*v) {
						label = x[1]
					}
				}
			}
			facts = append(facts, [2]string{crit[1], label})
		}
		sum := 0
		for _, v := range ratings {
			sum += v
		}
		avg := math.RoundToEven(float64(sum)/float64(len(ratings))*10) / 10
		facts = append(facts, [2]string{"Average rating", fmt.Sprintf("%.1f of 4", avg)})
	}
	facts = append(facts, [][2]string{{"Strengths", r.Strengths}, {"Areas to grow", r.Growth}, {"Actions agreed", r.Actions},
		{"Follow up by", coachDay(r.FollowUpDue)}, {"Shared", coachDay(r.Shared)}, {"Acknowledged", coachDay(r.Acknowledged)},
		{"Officer's response", r.Response}, {"Follow-up closed", coachDay(r.FollowUpDone)}}...)
	if !forOfficer {
		facts = append(facts, [2]string{"Follow-up note", r.FollowUpNote})
	}
	return facts
}

func (s *Service) coachingNames(ctx context.Context, r *ccelead.Record) (string, string) {
	var officer, author string
	_ = s.db.QueryRow(ctx, `SELECT COALESCE((SELECT u.name FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE sp.id = $1), ''),
  COALESCE((SELECT name FROM "user" WHERE id = $2), '')`, r.StaffID, r.Author).Scan(&officer, &author)
	return officer, author
}

func (s *Service) coachingDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	if s.coaching == nil || s.existingApp != nil {
		return nil, false, nil
	}
	path, query, _ := strings.Cut(rawPath, "?")
	var d *screensv1.PageDrawer
	var err error
	switch {
	case coachingNew.MatchString(path):
		d, err = s.newCoachingDrawer(ctx, p, queryValues(query), "")
	case coachingShare.MatchString(path):
		d, err = s.shareCoachingDrawer(ctx, p, coachingShare.FindStringSubmatch(path)[1])
	case coachingFollowUp.MatchString(path):
		d, err = s.followUpCoachingDrawer(ctx, p, coachingFollowUp.FindStringSubmatch(path)[1], "")
	case coachingOne.MatchString(path):
		d, err = s.oneCoachingDrawer(ctx, p, coachingOne.FindStringSubmatch(path)[1], "")
	case myCoaching.MatchString(path):
		d, err = s.myCoachingDrawer(ctx, p, myCoaching.FindStringSubmatch(path)[1])
	default:
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

const coachingTitle, coachingSubtitle = "Log coaching", "A one-to-one, observation or feedback for an officer on your team"

func (s *Service) newCoachingDrawer(ctx context.Context, p auth.Principal, prefill map[string]string, problem string) (*screensv1.PageDrawer, error) {
	if !ccelead.IsLead(p) {
		return formDrawer(formSpec{title: coachingTitle, subtitle: coachingSubtitle, empty: "Only the officer's Programme Lead records coaching."}), nil
	}
	team, err := s.coaching.Team(ctx, p)
	if err != nil {
		return nil, err
	}
	if len(team) == 0 {
		return formDrawer(formSpec{title: coachingTitle, subtitle: coachingSubtitle, empty: "No officers are assigned to you yet."}), nil
	}
	member := ccelead.OfficerFor(team, prefill["cceo"])
	kind := prefill["kind"]
	if !ccelead.RecordableKind(kind) {
		kind = ""
	}
	rated := ccelead.RatedKind(kind)
	fields, err := s.coachingFields(ctx, team, member, kind, nil, prefill)
	if err != nil {
		return nil, err
	}
	spec := formSpec{title: coachingTitle, subtitle: coachingSubtitle, action: true, submit: "Record coaching", fields: fields,
		note: "The record stays private to you until you share it with the officer."}
	if rated {
		spec.title, spec.submit = "Record an observation", "Record observation"
		spec.note = "Rate what you saw against the same rubric the Regional Lead uses for trainings, then write what to keep and what to change."
	}
	if member != nil {
		spec.subtitle = "For " + member.Name
	}
	d := formDrawer(spec)
	if problem != "" {
		d.Items = append([]*screensv1.DrawerItem{note(problem, "danger")}, d.Items...)
	}
	return d, nil
}

func (s *Service) oneCoachingDrawer(ctx context.Context, p auth.Principal, id, problem string) (*screensv1.PageDrawer, error) {
	r, err := s.coaching.Visible(ctx, p, id)
	if err != nil {
		return nil, err
	}
	if r == nil {
		return formDrawer(formSpec{title: "Coaching", subtitle: "Performance & coaching", empty: "This coaching record is not in your reach."}), nil
	}
	officer, author := s.coachingNames(ctx, r)
	if !ccelead.IsLead(p) || r.Author != p.UserID || r.Acknowledged != nil {
		empty := "Read only."
		if r.Acknowledged != nil {
			empty = "Acknowledged by the officer, so it can no longer be changed."
		}
		return formDrawer(formSpec{title: r.Subject, subtitle: ccelead.KindLabel(r.Kind), facts: recordFacts(r, officer, author, false), empty: empty}), nil
	}
	team, err := s.coaching.Team(ctx, p)
	if err != nil {
		return nil, err
	}
	member := ccelead.OfficerFor(team, r.StaffID)
	fields, err := s.coachingFields(ctx, team, member, r.Kind, r, nil)
	if err != nil {
		return nil, err
	}
	state := "Draft"
	switch {
	case r.Acknowledged != nil && r.FollowUpDue != nil && r.FollowUpDone == nil:
		state = "Follow-up due"
	case r.Acknowledged != nil:
		state = "Acknowledged"
	case r.Shared != nil:
		state = "Awaiting acknowledgement"
	}
	spec := formSpec{title: r.Subject, subtitle: ccelead.KindLabel(r.Kind) + " · " + officer,
		facts:  [][2]string{{"Officer", officer}, {"State", state}, {"Officer's response", r.Response}},
		action: true, submit: "Save", fields: fields, note: "The record stays private to you until you share it.", noteTone: "info"}
	if r.Shared != nil {
		spec.note, spec.noteTone = "The officer can already read this record; saving tells them it changed.", "warning"
	}
	d := formDrawer(spec)
	if problem != "" {
		d.Items = append([]*screensv1.DrawerItem{note(problem, "danger")}, d.Items...)
	}
	return d, nil
}

func (s *Service) shareCoachingDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	r, err := s.coaching.Visible(ctx, p, id)
	if err != nil {
		return nil, err
	}
	if r == nil {
		return formDrawer(formSpec{title: "Share coaching", subtitle: "Performance & coaching", empty: "This coaching record is not in your reach."}), nil
	}
	officer, author := s.coachingNames(ctx, r)
	refusal := ""
	switch {
	case !(ccelead.IsLead(p) && r.Author == p.UserID):
		refusal = "Only the Programme Lead who wrote this coaching shares it."
	case r.Shared != nil:
		refusal = fmt.Sprintf("Already shared with %s on %s.", officer, coachDay(r.Shared))
	}
	if refusal != "" {
		return formDrawer(formSpec{title: "Share coaching", subtitle: r.Subject, facts: recordFacts(r, officer, author, false), empty: refusal}), nil
	}
	who := officer
	if who == "" {
		who = "the officer"
	}
	return formDrawer(formSpec{title: "Share coaching", subtitle: r.Subject, facts: recordFacts(r, officer, author, true), action: true,
		submit: "Share with " + who,
		note:   "The officer is notified and asked to acknowledge it with a response. You can still correct the record until they do."}), nil
}

func (s *Service) followUpCoachingDrawer(ctx context.Context, p auth.Principal, id, problem string) (*screensv1.PageDrawer, error) {
	r, err := s.coaching.Visible(ctx, p, id)
	if err != nil {
		return nil, err
	}
	const title = "Follow up agreed actions"
	if r == nil {
		return formDrawer(formSpec{title: title, subtitle: "Performance & coaching", empty: "This coaching record is not in your reach."}), nil
	}
	officer, _ := s.coachingNames(ctx, r)
	refusal := ""
	switch {
	case !(ccelead.IsLead(p) && r.Author == p.UserID):
		refusal = "Only the Programme Lead who wrote this coaching follows it up."
	case r.FollowUpDue == nil:
		refusal = "This coaching has no follow-up date."
	case r.FollowUpDone != nil:
		refusal = "Follow-up closed on " + coachDay(r.FollowUpDone) + "."
	}
	facts := [][2]string{{"Officer", officer}, {"Subject", r.Subject}, {"Actions agreed", r.Actions},
		{"Follow up by", coachDay(r.FollowUpDue)}, {"Officer's response", r.Response}}
	if refusal != "" {
		return formDrawer(formSpec{title: title, subtitle: r.Subject, facts: append(facts, [2]string{"Follow-up note", r.FollowUpNote}),
			empty: refusal}), nil
	}
	subtitle := r.Subject
	if officer != "" {
		subtitle = "With " + officer
	}
	d := formDrawer(formSpec{title: title, subtitle: subtitle, facts: facts, action: true, submit: "Close follow-up",
		fields: []*screensv1.DrawerField{{Name: "follow_up_note", Label: "What you found", Kind: "textarea", Required: true,
			Placeholder: "Done, in progress or not started — and what happens next",
			Help:        "Kept in your log; the officer sees that the follow-up was closed."}}})
	if problem != "" {
		d.Items = append([]*screensv1.DrawerItem{note(problem, "danger")}, d.Items...)
	}
	return d, nil
}

func checked(v string) bool {
	v = strings.TrimSpace(strings.ToLower(v))
	return v != "" && v != "false" && v != "off" && v != "0"
}

// coachingSaveInGo is the drawers' saves; served is false for any other path.
func (s *Service) coachingSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest) (*screensv1.SaveDrawerResponse, bool, error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok || s.coaching == nil || s.existingApp != nil {
		return nil, false, nil
	}
	path, query, _ := strings.Cut(message.GetPath(), "?")
	values := message.GetValues()
	refusedWith := func(err error, redraw func(string) (*screensv1.PageDrawer, error)) (*screensv1.SaveDrawerResponse, bool, error) {
		// _refused: the error is said and the drawer closes, as the existing
		// view flashes it and returns to the log.
		var refusal *ccelead.CoachingRefusal
		if errors.As(err, &refusal) {
			_ = redraw
			return &screensv1.SaveDrawerResponse{Error: refusal.Message}, true, nil
		}
		return nil, true, err
	}
	saved := func(message string) (*screensv1.SaveDrawerResponse, bool, error) {
		return &screensv1.SaveDrawerResponse{Saved: true, Message: message, Redirect: teamCoaching}, true, nil
	}
	switch {
	case coachingNew.MatchString(path):
		redraw := func(words string) (*screensv1.PageDrawer, error) {
			prefill := queryValues(query)
			prefill["cceo"], prefill["kind"] = values["cceo_staff_id"], values["kind"]
			return s.newCoachingDrawer(ctx, p, prefill, words)
		}
		id, err := s.coaching.RecordCoaching(ctx, p, values)
		if err != nil {
			return refusedWith(err, redraw)
		}
		if checked(values["share_now"]) {
			if _, err := s.coaching.ShareCoaching(ctx, p, id); err != nil {
				return refusedWith(err, redraw)
			}
			return saved("Coaching recorded and shared with the officer.")
		}
		return saved("Coaching recorded. Share it when the officer should read it.")
	case coachingShare.MatchString(path):
		id := coachingShare.FindStringSubmatch(path)[1]
		if _, err := s.coaching.ShareCoaching(ctx, p, id); err != nil {
			return refusedWith(err, func(words string) (*screensv1.PageDrawer, error) {
				d, err := s.shareCoachingDrawer(ctx, p, id)
				if d != nil {
					d.Items = append([]*screensv1.DrawerItem{note(words, "danger")}, d.Items...)
				}
				return d, err
			})
		}
		return saved("Coaching shared. The officer has been told.")
	case coachingFollowUp.MatchString(path):
		id := coachingFollowUp.FindStringSubmatch(path)[1]
		if err := s.coaching.CompleteFollowUp(ctx, p, id, values["follow_up_note"]); err != nil {
			return refusedWith(err, func(words string) (*screensv1.PageDrawer, error) {
				return s.followUpCoachingDrawer(ctx, p, id, words)
			})
		}
		return saved("Follow-up closed.")
	case myCoaching.MatchString(path):
		id := myCoaching.FindStringSubmatch(path)[1]
		if err := s.coaching.AcknowledgeCoaching(ctx, p, id, values["response"]); err != nil {
			return refusedWith(err, nil)
		}
		return &screensv1.SaveDrawerResponse{Saved: true, Message: "Coaching acknowledged. Your Programme Lead has been told.",
			Redirect: "/my-coaching"}, true, nil
	case coachingOne.MatchString(path) && !coachingNew.MatchString(path):
		id := coachingOne.FindStringSubmatch(path)[1]
		redraw := func(words string) (*screensv1.PageDrawer, error) { return s.oneCoachingDrawer(ctx, p, id, words) }
		r, err := s.coaching.UpdateCoaching(ctx, p, id, values)
		if err != nil {
			return refusedWith(err, redraw)
		}
		if checked(values["share_now"]) && r.Shared == nil {
			if _, err := s.coaching.ShareCoaching(ctx, p, id); err != nil {
				return refusedWith(err, redraw)
			}
			return saved("Coaching saved and shared with the officer.")
		}
		return saved("Coaching saved.")
	}
	return nil, false, nil
}

// myCoachingDrawer is my_coaching_drawer: coaching shared with the officer,
// with the response that acknowledges it while it is unanswered.
func (s *Service) myCoachingDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	r, err := s.coaching.OfficerVisible(ctx, p, id)
	if err != nil {
		return nil, err
	}
	if r == nil {
		return formDrawer(formSpec{title: "Coaching", subtitle: "My performance", empty: "This coaching was not shared with you."}), nil
	}
	officer, author := s.coachingNames(ctx, r)
	subtitle := "Coaching"
	if author != "" {
		subtitle = "From " + author
	}
	facts := recordFacts(r, officer, author, true)
	if r.Acknowledged != nil {
		return formDrawer(formSpec{title: r.Subject, subtitle: subtitle, facts: facts, empty: "Acknowledged."}), nil
	}
	return formDrawer(formSpec{title: r.Subject, subtitle: subtitle, facts: facts, action: true, submit: "Acknowledge coaching",
		fields: []*screensv1.DrawerField{{Name: "response", Label: "Your response", Kind: "textarea", Required: true,
			Placeholder: "What you will keep doing, what you will change, and by when"}}}), nil
}
