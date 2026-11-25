package screens

// The HR programmes' forms (apps.frontend.views.hr_programme_views) drawn and
// saved in Go through internal/hrforms with Django absent, as the shared HR
// form drawer (partials/hr/form_drawer.html) draws them. A role whose page
// refuses the form, or a reader in an acting appointment, is handed on.

import (
	"context"
	"errors"
	"log/slog"
	"strconv"
	"strings"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrforms"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
)

// HRForms is internal/hrforms.Forms.
type HRForms interface {
	PeopleOptions(ctx context.Context, p auth.Principal) ([]hrforms.Choice, error)
	Recognise(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error)
	RequirementCountries(ctx context.Context, p auth.Principal) ([]hrforms.Choice, error)
	Requirements(ctx context.Context, p auth.Principal) ([]hrforms.Choice, error)
	AddRequirement(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error)
	RecordEvidence(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error)
	PulseCountries(ctx context.Context, p auth.Principal) ([]string, error)
	OpenPulse(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error)
	CountryOptions(ctx context.Context, p auth.Principal) ([]hrforms.Choice, error)
	ReportIncident(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error)
	StartOffboarding(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error)
	OpenCase(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error)
}

// WithHRForms makes the HR programmes' forms Go's.
func (s *Service) WithHRForms(f HRForms) *Service {
	s.hrForms = f
	return s
}

const (
	recognitionNew        = "/recognition/new"
	complianceRequirement = "/compliance-register/requirement"
	complianceEvidence    = "/compliance-register/new"
	pulseNew              = "/pulse-surveys/new"
	incidentNew           = "/health-safety/new"
	offboardingNew        = "/offboarding/new"
	caseNew               = "/employee-relations/new"
)

// hrFormPath is the form's path when Go answers it for p.
func (s *Service) hrFormPath(p auth.Principal, raw string) (string, bool) {
	if s.hrForms == nil || s.existingApp != nil || hrforms.HandsOn(p) {
		return "", false
	}
	path, _, _ := strings.Cut(raw, "?")
	switch path {
	case recognitionNew, complianceRequirement, complianceEvidence, pulseNew, incidentNew, offboardingNew, caseNew:
	default:
		return "", false
	}
	return path, pageaccess.CanOpen(p.ActiveRole, false, path)
}

func hrChoices(cs []hrforms.Choice) []*screensv1.DrawerOption {
	out := make([]*screensv1.DrawerOption, 0, len(cs))
	for _, c := range cs {
		out = append(out, &screensv1.DrawerOption{Value: c.Value, Label: c.Label})
	}
	return out
}

// hrSelect is a select _field with its blank option first.
func hrSelect(name, label, blank string, required bool, cs []hrforms.Choice) *screensv1.DrawerField {
	options := append([]*screensv1.DrawerOption{{Value: "", Label: blank}}, hrChoices(cs)...)
	return &screensv1.DrawerField{Name: name, Label: label, Kind: "select", Required: required, Options: options}
}

// selectValue chooses v where the select offers it: a browser selects no
// option for a value none carries, and the feed reads the select as blank.
func selectValue(f *screensv1.DrawerField, v string) {
	for _, o := range f.GetOptions() {
		if o.GetValue() == v {
			f.Value = v
			return
		}
	}
}

func hrDrawerFor(ctx context.Context, f HRForms, p auth.Principal, path string, query map[string]string) (*screensv1.PageDrawer, error) {
	switch path {
	case incidentNew, offboardingNew, caseNew:
		return peopleFormDrawer(ctx, f, p, path)
	case pulseNew:
		countries, err := f.PulseCountries(ctx, p)
		if err != nil {
			return nil, err
		}
		statements := []string{}
		for i, q := range hrforms.PulseQuestions {
			statements = append(statements, "("+strconv.Itoa(i+1)+") "+q)
		}
		fields := []*screensv1.DrawerField{{Name: "title", Label: "Title", Kind: "text", Required: true, MaxLength: length(255),
			Placeholder: "e.g. Quarter 1 staff pulse"}}
		for _, c := range countries {
			fields = append(fields, &screensv1.DrawerField{Name: hrforms.PulseCountryField(c), Label: "Survey staff in " + c, Kind: "checkbox", Value: "1"})
		}
		fields = append(fields, &screensv1.DrawerField{Name: "closes_on", Label: "Closes on", Kind: "date", Required: true})
		return formDrawer(formSpec{title: "Open a pulse survey", subtitle: "Five anonymous statements, answered from 1 to 5", action: true,
			submit: "Open and notify staff", fields: fields,
			note: "Staff in the chosen countries are notified. Answers are anonymous, and results show only once five people have answered. " +
				"The statements: " + strings.Join(statements, " ")}), nil
	case complianceRequirement:
		countries, err := f.RequirementCountries(ctx, p)
		if err != nil {
			return nil, err
		}
		return formDrawer(formSpec{title: "Add a requirement", subtitle: "An employment-law obligation every employee must meet",
			action: true, submit: "Add requirement", fields: []*screensv1.DrawerField{
				hrSelect("country", "Country", "Choose the country", true, countries),
				{Name: "name", Label: "Requirement", Kind: "text", Required: true, MaxLength: length(255),
					Placeholder: "e.g. Signed employment contract"},
				{Name: "description", Label: "What satisfies it", Kind: "textarea",
					Placeholder: "The law or regulation, and the evidence expected"},
				{Name: "is_mandatory", Label: "Mandatory for every employee", Kind: "checkbox", Value: "1"},
			}}), nil
	case complianceEvidence:
		people, err := f.PeopleOptions(ctx, p)
		if err != nil {
			return nil, err
		}
		requirements, err := f.Requirements(ctx, p)
		if err != nil {
			return nil, err
		}
		staff := hrSelect("staff_id", "Employee", "Choose the employee", true, people)
		selectValue(staff, query["staff"])
		requirement := hrSelect("requirement_id", "Requirement", "Choose the requirement", true, requirements)
		selectValue(requirement, query["requirement"])
		return formDrawer(formSpec{title: "Record evidence", subtitle: "An employee's evidence against a requirement", action: true,
			submit: "Save", note: "The status follows the evidence and its expiry date.", fields: []*screensv1.DrawerField{
				staff, requirement,
				{Name: "document_url", Label: "Link to the evidence", Kind: "text", MaxLength: length(512),
					Placeholder: "Where the signed document is filed"},
				{Name: "expiry_date", Label: "Expires on", Kind: "date"},
				{Name: "verified", Label: "I have checked the evidence", Kind: "checkbox"},
			}}), nil
	case recognitionNew:
		people, err := f.PeopleOptions(ctx, p)
		if err != nil {
			return nil, err
		}
		return formDrawer(formSpec{title: "Recognise someone", subtitle: "Name good work, and why it mattered", action: true,
			submit: "Record recognition", fields: []*screensv1.DrawerField{
				hrSelect("staff_id", "Employee", "Choose the employee", true, people),
				hrSelect("category", "Recognised for", "Choose a category", true, hrforms.RecognitionCategories),
				{Name: "citation", Label: "Citation", Kind: "textarea", Required: true, MaxLength: length(2000),
					Placeholder: "What they did, and the difference it made"},
				{Name: "awarded_on", Label: "Date", Kind: "date"},
			}}), nil
	}
	return nil, nil
}

func (s *Service) hrFormDrawerInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	path, ok := s.hrFormPath(p, rawPath)
	if !ok {
		return nil, false, nil
	}
	_, query, _ := strings.Cut(rawPath, "?")
	d, err := hrDrawerFor(ctx, s.hrForms, p, path, queryValues(query))
	if err != nil || d == nil {
		return nil, err != nil, err
	}
	return &screensv1.GetDrawerResponse{Drawer: d}, true, nil
}

// hrFormSaveInGo is the forms' saves: the service's refusal is said (the view
// flashes it and returns to the register), a save says the view's words.
func (s *Service) hrFormSaveInGo(ctx context.Context, message *screensv1.SaveDrawerRequest, o activities.Origin) (*screensv1.SaveDrawerResponse, bool, error) {
	p, signed := auth.PrincipalFrom(ctx)
	if !signed {
		return nil, false, nil
	}
	path, ok := s.hrFormPath(p, message.GetPath())
	if !ok {
		return nil, false, nil
	}
	var words, back string
	var err error
	switch path {
	case recognitionNew:
		var name string
		name, err = s.hrForms.Recognise(ctx, p, message.GetValues(), o)
		words, back = name+" recognised.", hrforms.RecognitionPath
	case complianceRequirement:
		var name string
		name, err = s.hrForms.AddRequirement(ctx, p, message.GetValues(), o)
		words, back = "Requirement added: "+name+".", hrforms.CompliancePath
	case complianceEvidence:
		words, err = s.hrForms.RecordEvidence(ctx, p, message.GetValues(), o)
		back = hrforms.CompliancePath
	case incidentNew:
		words, err = s.hrForms.ReportIncident(ctx, p, message.GetValues(), o)
		back = hrforms.SafetyPath
	case offboardingNew:
		words, err = s.hrForms.StartOffboarding(ctx, p, message.GetValues(), o)
		back = hrforms.OffboardingPath
	case caseNew:
		words, err = s.hrForms.OpenCase(ctx, p, message.GetValues(), o)
		back = hrforms.CasesPath
	case pulseNew:
		var title string
		title, err = s.hrForms.OpenPulse(ctx, p, message.GetValues(), o)
		words, back = title+" is open and staff have been notified.", hrforms.PulsePath
	}
	var refusal *hrforms.Refusal
	switch {
	case errors.As(err, &refusal):
		return &screensv1.SaveDrawerResponse{Error: refusal.Message}, true, nil
	case errors.Is(err, hrforms.ErrHandOn):
		return nil, false, nil
	case err != nil:
		if s.logger != nil {
			s.logger.ErrorContext(ctx, "the Go HR form save failed", slog.String("path", path), slog.String("error", err.Error()))
		}
		return nil, true, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonInternal, "This could not be saved.")
	}
	return &screensv1.SaveDrawerResponse{Saved: true, Message: words, Redirect: back}, true, nil
}

// peopleFormDrawer is the incident, offboarding and case drawers: each picks
// people from the reader's reach.
func peopleFormDrawer(ctx context.Context, f HRForms, p auth.Principal, path string) (*screensv1.PageDrawer, error) {
	people, err := f.PeopleOptions(ctx, p)
	if err != nil {
		return nil, err
	}
	countries := []hrforms.Choice{}
	if path != offboardingNew {
		if countries, err = f.CountryOptions(ctx, p); err != nil {
			return nil, err
		}
	}
	severity := hrSelect("severity", "Severity", "", true, hrforms.Severities)
	severity.Options, severity.Value = severity.Options[1:], "medium"
	switch path {
	case incidentNew:
		return formDrawer(formSpec{title: "Report an incident", subtitle: "An injury, road traffic incident, near miss or hazard",
			action: true, submit: "Report incident", fields: []*screensv1.DrawerField{
				hrSelect("category", "What happened", "Choose the kind of incident", true, hrforms.IncidentCategories),
				{Name: "incident_date", Label: "Date", Kind: "date", Required: true},
				hrSelect("affected_staff_id", "Employee affected", "No one was hurt", false, people),
				hrSelect("country", "Country", "The employee's country", false, countries),
				{Name: "location", Label: "Where", Kind: "text", MaxLength: length(255), Placeholder: "School, road, office…"},
				severity,
				{Name: "days_lost", Label: "Working days lost", Kind: "number", Min: proto.Float64(0), Step: proto.Float64(1)},
				{Name: "description", Label: "Description", Kind: "textarea", Required: true, MaxLength: length(5000)},
				{Name: "immediate_action", Label: "Immediate action taken", Kind: "textarea"},
			}}), nil
	case offboardingNew:
		return formDrawer(formSpec{title: "Start an offboarding",
			subtitle: "Record an exit, why it is happening, and who takes over the work", action: true, submit: "Start offboarding",
			note: "The account stays active until you close the offboarding, and it cannot close while schools, activities or " +
				"direct reports still point at the person.",
			fields: []*screensv1.DrawerField{
				hrSelect("staff_id", "Employee leaving", "Choose the employee", true, people),
				{Name: "last_working_day", Label: "Last working day", Kind: "date", Required: true},
				hrSelect("exit_reason", "Reason for leaving", "Choose a reason", true, hrforms.ExitReasons),
				hrSelect("handover_owner_id", "Handover owner", "Name later", false, people),
				{Name: "note", Label: "Exit note", Kind: "textarea"},
			}}), nil
	}
	return formDrawer(formSpec{title: "Open a case", subtitle: "Disciplinary matters, grievances, disputes and investigations",
		action: true, submit: "Open case",
		note: "Cases are confidential by default: only the case owner and the investigator see a confidential case's details. " +
			"Opening one is recorded in the HR audit log.",
		fields: []*screensv1.DrawerField{
			hrSelect("case_type", "Case type", "Choose a case type", true, hrforms.CaseTypes),
			hrSelect("subject_staff_id", "Employee the case concerns", "No named individual (e.g. a whistleblowing report)", false, people),
			hrSelect("complainant_staff_id", "Complainant or other party", "None recorded", false, people),
			severity,
			hrSelect("country", "Country", "The employee's country", false, countries),
			{Name: "hearing_date", Label: "Hearing or meeting date", Kind: "date"},
			{Name: "description", Label: "What has been reported", Kind: "textarea", Required: true, MaxLength: length(5000),
				Placeholder: "Facts as reported, dates, and who raised it"},
			{Name: "is_confidential", Label: "Keep this case confidential", Kind: "checkbox", Value: "1"},
		}}), nil
}
