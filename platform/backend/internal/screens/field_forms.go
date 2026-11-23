package screens

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"slices"
	"strings"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/mypd"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerassigned"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
)

// The field operations forms, opened from Go while the existing application
// is absent (docs/migration/189). Each answers with the fields, wording and
// refusals of the view it replaces.

const roleHR = "HumanResources"

// everyStaffAndPartnerRole is ALL_ROLES. A Cluster Leader is not one of them.
var everyStaffAndPartnerRole = []string{rbac.Admin, rbac.CCEO, rbac.ProgramLead, roleCD, roleIA, roleRVP, roleRPL, roleHR,
	roleAccountant, "PartnerAdmin", "PartnerFieldOfficer", rolePC, "BusinessTransformationOfficer", "MfiPartnerAdmin", "MfiLoanOfficer"}

// fieldFormPages is PAGE_PERMISSIONS for the pages these forms belong to.
var fieldFormPages = map[string][]string{
	"core_schools":                {rbac.CCEO, rbac.ProgramLead, roleIA, roleCD, roleAccountant, rbac.Admin},
	"my_professional_development": {rbac.CCEO, rbac.ProgramLead, roleCD, roleRVP, roleIA, roleAccountant, roleHR, rolePC, rbac.Admin},
	"partner_detail":              everyStaffAndPartnerRole,
	"projects":                    {rbac.Admin, rbac.CCEO, roleCD, roleIA, rbac.ProgramLead, rolePC},
}

// fieldFormRequest is what a form is opened with: the record in its address
// and the page's query.
type fieldFormRequest struct {
	id    string
	query url.Values
}

// fieldForm is one form: its address (fixed, or a pattern capturing the
// record's id), the page that gates it and how it is drawn.
type fieldForm struct {
	path                    string
	address                 *regexp.Regexp
	page                    string
	withheldFromTeamMembers bool   // MEMBER_WITHHELD_PAGES holds the page
	permission              string // a grant the view asks for after the page
	permissionRefusal       string // and its words when the role lacks it
	build                   func(context.Context, *Service, auth.Principal, fieldFormRequest) (*screensv1.PageDrawer, error)
}

var fieldForms = []fieldForm{
	{path: "/core-schools/strategy-playbook", page: "core_schools",
		build: func(context.Context, *Service, auth.Principal, fieldFormRequest) (*screensv1.PageDrawer, error) {
			return strategyPlaybookDrawer(), nil
		}},
	{path: "/my-professional-development/allocation-history", page: "my_professional_development",
		build: allocationHistoryDrawer},
	{address: regexp.MustCompile(`^/partners/([^/]+)/members/drawer$`), page: "partner_detail",
		withheldFromTeamMembers: true, build: partnerMemberForm},
	{path: "/projects/create", page: "projects", permission: "project.configurePriorities",
		permissionRefusal: "Only a Special Project Coordinator, Impact Assessment, the Country Director, or Admin may create Projects.",
		build:             projectCreateForm},
	{path: "/work-plan/add", permission: "planning.manualActivity.create",
		permissionRefusal: "You do not have permission to add non-school programme activities.",
		build:             workPlanAddForm},
}

func fieldFormFor(path string) (fieldForm, bool) {
	path = strings.TrimSuffix(path, "/")
	for _, form := range fieldForms {
		if form.path == path || (form.address != nil && form.address.MatchString(path)) {
			return form, true
		}
	}
	return fieldForm{}, false
}

// recordID is the record named in the form's address, if it has one.
func (f fieldForm) recordID(path string) string {
	if f.address == nil {
		return ""
	}
	if m := f.address.FindStringSubmatch(strings.TrimSuffix(path, "/")); m != nil {
		return m[1]
	}
	return ""
}

// refusal is require_page_permission's check and words. An acting
// appointment's withheld pages are not decided here, so it is refused rather
// than guessed.
func (f fieldForm) refusal(p auth.Principal) string {
	if p.InActingAppointment {
		return "This form is not available while you are acting in another role."
	}
	if f.page != "" && !slices.Contains(fieldFormPages[f.page], p.ActiveRole) {
		return f.pageDenied()
	}
	if f.permission != "" && !rbac.Grants(p.ActiveRole, f.permission) {
		return f.permissionRefusal
	}
	return ""
}

func (f fieldForm) pageDenied() string {
	return "Access Denied: Your active role does not have permission to view " + pageTitle(f.page) + "."
}

// pageTitle is page_name.replace("_", " ").title().
func pageTitle(page string) string {
	words := strings.Split(page, "_")
	for i, word := range words {
		if word != "" {
			words[i] = strings.ToUpper(word[:1]) + word[1:]
		}
	}
	return strings.Join(words, " ")
}

// fieldFormInGo answers a field form's path; served is false for any other.
func (s *Service) fieldFormInGo(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.GetDrawerResponse, bool, error) {
	parsed, err := url.Parse(rawPath)
	if err != nil {
		return nil, false, nil
	}
	form, ok := fieldFormFor(parsed.Path)
	if !ok {
		return nil, false, nil
	}
	if why := form.refusal(p); why != "" {
		return &screensv1.GetDrawerResponse{Refusal: why}, true, nil
	}
	if form.withheldFromTeamMembers {
		member, err := partnerassigned.IsTeamMember(ctx, s.db, p)
		if err != nil {
			return nil, true, err
		}
		if member {
			return &screensv1.GetDrawerResponse{Refusal: form.pageDenied()}, true, nil
		}
	}
	drawer, err := form.build(ctx, s, p, fieldFormRequest{id: form.recordID(parsed.Path), query: parsed.Query()})
	if err != nil {
		return nil, true, err
	}
	return &screensv1.GetDrawerResponse{Drawer: drawer}, true, nil
}

// readOnlyDrawer is a form that only informs. The existing reader marks every
// drawer as having required information, so this one does too.
func readOnlyDrawer(title string, items []*screensv1.DrawerItem) *screensv1.PageDrawer {
	return &screensv1.PageDrawer{Title: title, HasRequired: true, CancelLabel: "Cancel", Items: items}
}

func headingLine(text string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Heading{Heading: text}}
}

func textLine(text string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: text}}
}

// strategyPlaybookDrawer is strategy_playbook_drawer.html.
func strategyPlaybookDrawer() *screensv1.PageDrawer {
	return readOnlyDrawer("Core strategy playbook", []*screensv1.DrawerItem{
		headingLine("The Core program rule"),
		textLine("Every core school is assigned an annual support plan consisting of 4 on-site support visits (V1–V4) and 4 interactive training workshops (T1–T4)."),
		headingLine("Operational phase guide"),
		textLine("Phase 1: SSA assessment and V1 Complete the SSA assessment to isolate the two weakest focus areas. Schedule Visit 1 focusing on primary bottlenecks."),
		textLine("Phase 2: Training blocks (T1 and T2) Assemble school teams for target development workshops. Facilitate group exercises for classroom and leadership coaching."),
		textLine("Phase 3: Partner collaboration (V2 and V3) Assign specialized interventions to verified partners to leverage specific expertise in Reading Fluency or EdTech setup."),
		textLine("Phase 4: Impact assessment and graduation Execute follow-up SSA. Verify evidence to clear accountability. Advance qualifying core schools to Champion status."),
	})
}

// partnerMemberForm is partner_member_drawer: a partner that is gone is not found.
func partnerMemberForm(ctx context.Context, s *Service, _ auth.Principal, req fieldFormRequest) (*screensv1.PageDrawer, error) {
	var name string
	err := s.db.QueryRow(ctx, `SELECT name FROM partner WHERE id = $1 AND deleted_at IS NULL`, req.id).Scan(&name)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "This was not found, or it is not yours to view.")
	}
	if err != nil {
		return nil, fmt.Errorf("screens: reading the partner: %w", err)
	}
	return partnerMemberDrawer(name, req.query.Get("name")), nil
}

// partnerMemberDrawer is member_drawer.html. The name arrives filled in when
// the press came from a person already named on the partner's deliveries.
func partnerMemberDrawer(partner, name string) *screensv1.PageDrawer {
	return &screensv1.PageDrawer{
		Title:       "Add to the " + partner + " roster",
		HasRequired: true,
		SubmitLabel: "Add to roster",
		CancelLabel: "Cancel",
		CanSubmit:   true,
		Items: []*screensv1.DrawerItem{
			hintedField("name", "Name", "text", name, "e.g. Grace Nakato", true),
			{Kind: &screensv1.DrawerItem_Field{Field: &screensv1.DrawerField{
				Name: "role", Label: "Role", Kind: "select", Value: "staff",
				Options: []*screensv1.DrawerOption{{Value: "staff", Label: "Staff"}, {Value: "volunteer", Label: "Volunteer"}},
			}}},
			hintedField("title", "Title", "text", "", "e.g. Literacy trainer", false),
			hintedField("phone", "Phone", "text", "", "+256 700 000 000", false),
			hintedField("email", "Email", "email", "", "name@partner.org", false),
		},
	}
}

func hintedField(name, label, kind, value, placeholder string, required bool) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: &screensv1.DrawerField{
		Name: name, Label: label, Kind: kind, Value: value, Placeholder: placeholder, Required: required,
	}}}
}

const noAllocationHistory = "Your Professional Development allocation history will appear here once your first financial year's allocation is set."

// allocationHistoryDrawer is allocation_history_drawer.html over the person's
// own years.
func allocationHistoryDrawer(ctx context.Context, s *Service, p auth.Principal, _ fieldFormRequest) (*screensv1.PageDrawer, error) {
	years, err := mypd.AllocationHistory(ctx, s.db, p.UserID)
	if err != nil {
		return nil, err
	}
	return readOnlyDrawer("PD allocation history", allocationHistoryItems(years)), nil
}

func allocationHistoryItems(years []mypd.HistoryYear) []*screensv1.DrawerItem {
	if len(years) == 0 {
		return []*screensv1.DrawerItem{{Kind: &screensv1.DrawerItem_Block{Block: &screensv1.PageBlock{
			Kind: &screensv1.PageBlock_Empty{Empty: noAllocationHistory},
		}}}}
	}
	items := make([]*screensv1.DrawerItem, 0, len(years)*2)
	for _, year := range years {
		items = append(items, headingLine("FY "+year.FY), &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{
			Facts: []*screensv1.PageFact{
				{Label: "Allocation", Value: year.Allocation},
				{Label: "Committed", Value: year.Committed},
				{Label: "Accounted", Value: year.Accounted},
				{Label: "Remaining", Value: year.Remaining},
			},
		}}})
	}
	return items
}
