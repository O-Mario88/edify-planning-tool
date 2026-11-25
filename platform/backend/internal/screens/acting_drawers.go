package screens

// Acting Leadership's drawers (apps.frontend.views.acting_views) drawn and
// saved in Go through internal/acting with Django absent: Appoint (choose the
// person and the month, then read what the appointment gives and confirm),
// an appointment's record, Cancel and Change acting month. The rules and
// their words are the acting service's; the web's two-step Appoint keeps its
// review: the first save checks the choice and answers with the statement and
// a confirm box, the second appoints.

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/acting"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// ActingDrawers is internal/acting.Service.
type ActingDrawers interface {
	Options(ctx context.Context, p auth.Principal) (acting.Options, error)
	Preview(ctx context.Context, p auth.Principal, staffID, month string) (acting.Preview, error)
	Appoint(ctx context.Context, p auth.Principal, staffID, month string) (*identityv1.ActingAppointment, error)
	Get(ctx context.Context, p auth.Principal, id string) (*identityv1.ActingAppointment, error)
	Cancel(ctx context.Context, p auth.Principal, id, reason string) (*identityv1.ActingAppointment, error)
	ChangeMonth(ctx context.Context, p auth.Principal, id, month string) (*identityv1.ActingAppointment, error)
	Months() []acting.Month
}

// WithActingDrawers makes Acting Leadership's drawers Go's.
func (s *Service) WithActingDrawers(a ActingDrawers) *Service {
	s.acting = a
	return s
}

const actingPage = "/acting-leadership"

var (
	actingAppoint    = regexp.MustCompile(`^/acting-leadership/appoint$`)
	actingRecord     = regexp.MustCompile(`^/acting-leadership/([A-Za-z0-9]{1,30})$`)
	actingCancel     = regexp.MustCompile(`^/acting-leadership/([A-Za-z0-9]{1,30})/cancel$`)
	actingReschedule = regexp.MustCompile(`^/acting-leadership/([A-Za-z0-9]{1,30})/reschedule$`)
)

const (
	actingNotAllowed = "A Program Lead appoints an Acting Program Lead and a Country Director an Acting Country Director, each working in their own role."
	actingMissing    = "That acting appointment is not one you can open, or it no longer exists."
	actingStays      = "Money and leave approvals, performance reviews, targets, accounts and further acting appointments are not part of an appointment. They stay with you."
)

func factsItem(facts ...*screensv1.PageFact) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: facts}}}
}

func fact(label, value string) *screensv1.PageFact {
	return &screensv1.PageFact{Label: label, Value: value}
}

func textItem(text string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: text}}
}

func actingField(f *screensv1.DrawerField) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: f}}
}

// refusalText is a rule's words when err is the acting service saying no.
func refusalText(err error) (string, bool) {
	var refused *acting.Refused
	if errors.As(err, &refused) {
		return refused.Message, true
	}
	return "", false
}

// actingScope is the drawer's Scope line.
func actingScope(entry acting.Role, country string) string {
	if entry.ScopeType == acting.ScopePLTeam {
		return "My PL Team"
	}
	if country != "" {
		return country
	}
	return "Country"
}

func monthChoices(months []acting.Month) []*screensv1.DrawerOption {
	out := make([]*screensv1.DrawerOption, 0, len(months))
	for _, m := range months {
		out = append(out, &screensv1.DrawerOption{Value: m.Value, Label: m.Label})
	}
	return out
}

func effectiveOf(months []acting.Month, value string) string {
	for _, m := range months {
		if m.Value == value {
			return m.Effective
		}
	}
	return ""
}

// appointChoose is the drawer's first step.
func appointChoose(o acting.Options, appointee, month, problem string) *screensv1.PageDrawer {
	d := &screensv1.PageDrawer{Title: "Appoint " + o.Entry.ShortLabel}
	if len(o.Candidates) == 0 {
		why := "No Program Lead is recorded in your country yet, so there is nobody to appoint."
		if o.Entry.ScopeType == acting.ScopePLTeam {
			why = "No CCEO is recorded under you yet, so there is nobody to appoint."
		}
		d.Items = append(d.Items, note(why, "warning"))
		d.CancelLabel = "Close"
		return d
	}
	if month == "" && len(o.Months) > 0 {
		// The usual appointment is made ahead, for next month.
		month = o.Months[0].Value
		if len(o.Months) > 1 {
			month = o.Months[1].Value
		}
	}
	if problem != "" {
		d.Items = append(d.Items, note(problem, "danger"))
	}
	role := o.Entry.AppointeeRole
	people := []*screensv1.DrawerOption{{Value: "", Label: "Choose a " + role}}
	for _, c := range o.Candidates {
		people = append(people, &screensv1.DrawerOption{Value: c.StaffID, Label: c.Name})
	}
	help := "The Program Leads of your country."
	if o.Entry.ScopeType == acting.ScopePLTeam {
		help = "The CCEOs who report to you."
	}
	d.Items = append(d.Items,
		actingField(&screensv1.DrawerField{Name: "appointee", Label: role, Kind: "select", Required: true, Value: appointee,
			Options: people, Help: help}),
		actingField(&screensv1.DrawerField{Name: "month", Label: "Acting Month", Kind: "select", Required: true, Value: month,
			Options: monthChoices(o.Months)}),
		factsItem(fact("Scope", actingScope(o.Entry, "")), fact("Effective", effectiveOf(o.Months, month))),
	)
	d.HasRequired, d.CanSubmit, d.SubmitLabel, d.CancelLabel = true, true, "Appoint "+o.Entry.ShortLabel, "Cancel"
	return d
}

// appointReview is the drawer's second step: what the appointment gives,
// and the box that confirms it.
func appointReview(o acting.Options, pv acting.Preview, appointee, month, country string) *screensv1.PageDrawer {
	d := appointChoose(o, appointee, month, "")
	d.Items = []*screensv1.DrawerItem{
		factsItem(fact(o.Entry.AppointeeRole, pv.AppointeeName), fact("Acting role", o.Entry.Label),
			fact("Acting month", pv.MonthLabel), fact("Scope", actingScope(o.Entry, country)), fact("Effective", pv.Effective)),
		note(pv.Statement, "info"),
		textItem(actingStays),
		d.Items[0], d.Items[1],
		actingField(&screensv1.DrawerField{Name: "confirm", Label: "I have read this and confirm the appointment", Kind: "checkbox",
			Required: true}),
	}
	d.SubmitLabel = "Confirm Appointment"
	return d
}

func (s *Service) actingDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	if s.acting == nil || s.existingApp != nil {
		return nil, false, nil
	}
	path, query, _ := strings.Cut(rawPath, "?")
	switch {
	case actingAppoint.MatchString(path):
		o, err := s.acting.Options(ctx, p)
		if _, refused := refusalText(err); refused {
			return &screensv1.GetDrawerResponse{Drawer: &screensv1.PageDrawer{Title: "Appoint an acting leader",
				Items: []*screensv1.DrawerItem{note(actingNotAllowed, "warning")}, CancelLabel: "Close"}}, true, nil
		}
		if err != nil {
			return nil, true, err
		}
		values := queryValues(query)
		return &screensv1.GetDrawerResponse{Drawer: appointChoose(o, values["appointee"], values["month"], "")}, true, nil
	case actingCancel.MatchString(path):
		return s.actingRecordDrawer(ctx, p, actingCancel.FindStringSubmatch(path)[1], "cancel", "", "")
	case actingReschedule.MatchString(path):
		return s.actingRecordDrawer(ctx, p, actingReschedule.FindStringSubmatch(path)[1], "reschedule", queryValues(query)["month"], "")
	case actingRecord.MatchString(path):
		return s.actingRecordDrawer(ctx, p, actingRecord.FindStringSubmatch(path)[1], "record", "", "")
	}
	return nil, false, nil
}

func queryValues(query string) map[string]string {
	out := map[string]string{}
	parsed, err := url.ParseQuery(query)
	if err != nil {
		return out
	}
	for k, v := range parsed {
		if len(v) > 0 {
			out[k] = strings.TrimSpace(v[0])
		}
	}
	return out
}

// actingSummary is _summary.html.
func actingSummary(a *identityv1.ActingAppointment) *screensv1.DrawerItem {
	return factsItem(fact("Person", a.GetAppointeeName()+" · "+a.GetAppointeeRole()), fact("Acting role", a.GetLabel()),
		fact("Scope", a.GetScopeLabel()), fact("Effective", a.GetEffectiveLabel()), fact("Status", a.GetStateLabel()))
}

func (s *Service) actingRecordDrawer(ctx context.Context, p auth.Principal, id, kind, month, problem string) (*screensv1.GetDrawerResponse, bool, error) {
	a, err := s.acting.Get(ctx, p, id)
	if _, refused := refusalText(err); refused || (err == nil && a == nil) {
		return &screensv1.GetDrawerResponse{Drawer: &screensv1.PageDrawer{Title: "Appointment not found",
			Items: []*screensv1.DrawerItem{note(actingMissing, "warning")}, CancelLabel: "Close"}}, true, nil
	}
	if err != nil {
		return nil, true, err
	}
	d := &screensv1.PageDrawer{}
	if problem != "" {
		d.Items = append(d.Items, note(problem, "danger"))
	}
	d.Items = append(d.Items, actingSummary(a))
	switch kind {
	case "record":
		d.Title = a.GetLabel() + " · " + a.GetMonthLabel()
		lines := []*screensv1.PageFact{fact("Appointed by", a.GetAppointedByName()+" · "+a.GetAppointedByRole())}
		if a.GetCancelledByName() != "" {
			lines = append(lines, fact("Cancelled by", a.GetCancelledByName()))
		}
		if a.GetCancelReason() != "" {
			lines = append(lines, fact("Reason", a.GetCancelReason()))
		}
		d.Items = append(d.Items, factsItem(lines...))
		d.CancelLabel = "Close"
	case "cancel":
		d.Title = "Cancel acting appointment"
		if !a.GetCanCancel() {
			d.Items = append(d.Items, note("This appointment cannot be cancelled: it has ended, was already cancelled, or is not yours to cancel.", "warning"))
			d.CancelLabel = "Close"
			break
		}
		consequence := fmt.Sprintf("%s will not become %s in %s. The appointment stays in History.", a.GetAppointeeName(),
			a.GetShortLabel(), a.GetMonthLabel())
		if a.GetState() == "active" {
			consequence = fmt.Sprintf("%s loses %s access at once and returns to working as %s. The appointment stays in History.",
				a.GetAppointeeName(), a.GetShortLabel(), a.GetAppointeeRole())
		}
		max := int32(500)
		d.Items = append(d.Items,
			actingField(&screensv1.DrawerField{Name: "reason", Label: "Reason", Kind: "textarea", MaxLength: &max,
				Help: "Kept on the record with your name and the time."}),
			note(consequence, "warning"))
		d.CanSubmit, d.SubmitLabel, d.CancelLabel = true, "Cancel appointment", "Keep appointment"
	case "reschedule":
		d.Title = "Change acting month"
		if !a.GetCanChangeMonth() {
			d.Items = append(d.Items, note("Only the leader who made an appointment can change it, and only before it begins. An appointment that has begun is cancelled and a new one made.", "warning"))
			d.CancelLabel = "Close"
			break
		}
		months := s.acting.Months()
		if month == "" {
			month = a.GetMonth()
		}
		help := ""
		if e := effectiveOf(months, month); e != "" {
			help = "Effective " + e + "."
		}
		d.Items = append(d.Items,
			actingField(&screensv1.DrawerField{Name: "month", Label: "Acting Month", Kind: "select", Required: true, Value: month,
				Options: monthChoices(months), Help: help}),
			textItem("The month this appointment was first made for stays on its record."))
		d.HasRequired, d.CanSubmit, d.SubmitLabel, d.CancelLabel = true, true, "Save month", "Cancel"
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

// actingSaveInGo is the drawers' saves; served is false for any other path.
func (s *Service) actingSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest) (*screensv1.SaveDrawerResponse, bool, error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok || s.acting == nil || s.existingApp != nil {
		return nil, false, nil
	}
	path := message.GetPath()
	if i := strings.IndexByte(path, '?'); i >= 0 {
		path = path[:i]
	}
	values := message.GetValues()
	get := func(name string) string { return strings.TrimSpace(values[name]) }
	switch {
	case actingAppoint.MatchString(path):
		return s.appointSave(ctx, p, get("appointee"), get("month"), get("confirm"))
	case actingCancel.MatchString(path):
		id := actingCancel.FindStringSubmatch(path)[1]
		a, err := s.acting.Cancel(ctx, p, id, get("reason"))
		if words, refused := refusalText(err); refused {
			drawer, _, derr := s.actingRecordDrawer(ctx, p, id, "cancel", "", words)
			if derr != nil {
				return nil, true, derr
			}
			return &screensv1.SaveDrawerResponse{Drawer: drawer.GetDrawer()}, true, nil
		}
		if err != nil {
			return nil, true, err
		}
		return &screensv1.SaveDrawerResponse{Saved: true, Redirect: actingPage, Message: fmt.Sprintf(
			"%s's %s appointment for %s is cancelled.", a.GetAppointeeName(), a.GetShortLabel(), a.GetMonthLabel())}, true, nil
	case actingReschedule.MatchString(path):
		id := actingReschedule.FindStringSubmatch(path)[1]
		a, err := s.acting.ChangeMonth(ctx, p, id, get("month"))
		if words, refused := refusalText(err); refused {
			drawer, _, derr := s.actingRecordDrawer(ctx, p, id, "reschedule", get("month"), words)
			if derr != nil {
				return nil, true, derr
			}
			return &screensv1.SaveDrawerResponse{Drawer: drawer.GetDrawer()}, true, nil
		}
		if err != nil {
			return nil, true, err
		}
		return &screensv1.SaveDrawerResponse{Saved: true, Redirect: actingPage, Message: fmt.Sprintf(
			"%s's %s appointment is now for %s.", a.GetAppointeeName(), a.GetShortLabel(), a.GetMonthLabel())}, true, nil
	}
	return nil, false, nil
}

// appointSave is acting_appoint_view's POST: review, then confirm.
func (s *Service) appointSave(ctx context.Context, p auth.Principal, appointee, month, confirm string) (*screensv1.SaveDrawerResponse, bool, error) {
	o, err := s.acting.Options(ctx, p)
	if words, refused := refusalText(err); refused {
		return &screensv1.SaveDrawerResponse{Error: words}, true, nil
	}
	if err != nil {
		return nil, true, err
	}
	again := func(words string) (*screensv1.SaveDrawerResponse, bool, error) {
		return &screensv1.SaveDrawerResponse{Drawer: appointChoose(o, appointee, month, words)}, true, nil
	}
	if confirm == "" || confirm == "false" || confirm == "off" {
		pv, err := s.acting.Preview(ctx, p, appointee, month)
		if words, refused := refusalText(err); refused {
			return again(words)
		}
		if err != nil {
			return nil, true, err
		}
		return &screensv1.SaveDrawerResponse{Drawer: appointReview(o, pv, appointee, month, "")}, true, nil
	}
	a, err := s.acting.Appoint(ctx, p, appointee, month)
	if words, refused := refusalText(err); refused {
		return again(words)
	}
	if err != nil {
		return nil, true, err
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Redirect: actingPage,
		Message: fmt.Sprintf("%s is %s for %s.", a.GetAppointeeName(), a.GetLabel(), a.GetMonthLabel())}, true, nil
}
