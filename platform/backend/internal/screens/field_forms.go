package screens

import (
	"context"
	"fmt"
	"slices"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/mypd"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
)

// The field operations forms, opened from Go while the existing application
// is absent (docs/migration/189). Each answers with the fields, wording and
// refusals of the view it replaces.

const roleHR = "HumanResources"

// fieldFormPages is PAGE_PERMISSIONS for the pages these forms belong to.
var fieldFormPages = map[string][]string{
	"core_schools":                {rbac.CCEO, rbac.ProgramLead, roleIA, roleCD, roleAccountant, rbac.Admin},
	"my_professional_development": {rbac.CCEO, rbac.ProgramLead, roleCD, roleRVP, roleIA, roleAccountant, roleHR, rolePC, rbac.Admin},
}

// fieldForm is one form: the page that gates it and how it is drawn.
type fieldForm struct {
	path, page string
	build      func(context.Context, *Service, auth.Principal) (*screensv1.PageDrawer, error)
}

var fieldForms = []fieldForm{
	{path: "/core-schools/strategy-playbook", page: "core_schools",
		build: func(context.Context, *Service, auth.Principal) (*screensv1.PageDrawer, error) {
			return strategyPlaybookDrawer(), nil
		}},
	{path: "/my-professional-development/allocation-history", page: "my_professional_development",
		build: allocationHistoryDrawer},
}

func fieldFormFor(path string) (fieldForm, bool) {
	path = strings.TrimSuffix(path, "/")
	for _, form := range fieldForms {
		if form.path == path {
			return form, true
		}
	}
	return fieldForm{}, false
}

// refusal is require_page_permission's check and words. An acting
// appointment's withheld pages are not decided here, so it is refused rather
// than guessed.
func (f fieldForm) refusal(p auth.Principal) string {
	if p.InActingAppointment {
		return "This form is not available while you are acting in another role."
	}
	if slices.Contains(fieldFormPages[f.page], p.ActiveRole) {
		return ""
	}
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
func (s *Service) fieldFormInGo(ctx context.Context, p auth.Principal, path string) (*screensv1.GetDrawerResponse, bool, error) {
	form, ok := fieldFormFor(path)
	if !ok {
		return nil, false, nil
	}
	if why := form.refusal(p); why != "" {
		return &screensv1.GetDrawerResponse{Refusal: why}, true, nil
	}
	drawer, err := form.build(ctx, s, p)
	if err != nil {
		return nil, true, fmt.Errorf("screens: drawing %s: %w", form.path, err)
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

const noAllocationHistory = "Your Professional Development allocation history will appear here once your first financial year's allocation is set."

// allocationHistoryDrawer is allocation_history_drawer.html over the person's
// own years.
func allocationHistoryDrawer(ctx context.Context, s *Service, p auth.Principal) (*screensv1.PageDrawer, error) {
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
