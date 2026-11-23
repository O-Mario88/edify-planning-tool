package screens

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"golang.org/x/text/cases"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// fieldChoice is a record offered by a form.
type fieldChoice struct{ id, name string }

// projectCatalogueChoice is an Activity Catalogue item a project may deliver.
type projectCatalogueChoice struct{ id, name, code, delivery string }

var (
	// deliveryMethodLabels is DeliveryMethod.choices.
	deliveryMethodLabels = map[string]string{
		"in_school_training": "In-school Training",
		"cluster_meeting":    "Cluster Meeting",
		"cluster_training":   "Cluster Training",
		"online":             "Online",
		"school_visit":       "School Visit",
		"group":              "Group",
		"admin":              "Admin",
		"programme_event":    "Programme Event",
	}
	// ssaInterventionChoices is SsaIntervention.choices.
	ssaInterventionChoices = [][2]string{
		{"christlike_behaviour", "Christlike Behaviour"},
		{"exposure_to_word_of_god", "Exposure to the Word of God"},
		{"financial_health", "Financial Health"},
		{"leadership", "Leadership"},
		{"government_requirement", "Government Requirements"},
		{"learning_environment", "Learning Environment"},
		{"teaching_environment", "Teacher's Environment"},
		{"enrolment", "Enrolment"},
	}
	projectCategoryChoices = [][2]string{
		{"", "Choose…"},
		{"intervention_specific", "Intervention Specific"},
		{"pilot", "Pilot"},
		{"selective_limited", "Selective Limited"},
	}
	projectFocusChoices = [][2]string{
		{"all", "Client and Core Schools"},
		{"client", "Client Schools"},
		{"core", "Core Schools"},
	}
)

const (
	projectInterventionHelp = "Choose at least one. Choose General when the project does not work on one SSA intervention. A project on General alone (Alumni, for example) is not measured by the SSA: its activities are offered at every school it enrols, and they do not use a school's support visit or its Core package."
	projectCatalogueHelp    = "Only these activities will be available in Project Planning."
	projectPartnerHelp      = "The partners delivering this project. Handing its work to another partner asks for a reason. Leave empty to allow any partner."
)

// projectCreateForm is project_create_drawer_view: the catalogue items in
// effect today that a project may deliver, and the partners who may take new
// work.
func projectCreateForm(ctx context.Context, s *Service, _ auth.Principal, _ fieldFormRequest) (*screensv1.PageDrawer, error) {
	catalogue, err := s.projectCatalogueChoices(ctx, s.now().In(exportDayZone).Format(time.DateOnly))
	if err != nil {
		return nil, err
	}
	partners, err := s.assignablePartnerChoices(ctx)
	if err != nil {
		return nil, err
	}
	return projectCreateDrawer(catalogue, partners), nil
}

func (s *Service) projectCatalogueChoices(ctx context.Context, today string) ([]projectCatalogueChoice, error) {
	rows, err := s.db.Query(ctx, `
SELECT id, display_name, stable_code, delivery_method
  FROM activity_catalogue_item
 WHERE status = 'active' AND project_delivery_allowed
   AND (effective_from IS NULL OR effective_from <= $1::date)
   AND (effective_to IS NULL OR effective_to >= $1::date)
 ORDER BY display_name`, today)
	if err != nil {
		return nil, fmt.Errorf("screens: reading the project catalogue: %w", err)
	}
	items, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (projectCatalogueChoice, error) {
		var c projectCatalogueChoice
		err := row.Scan(&c.id, &c.name, &c.code, &c.delivery)
		return c, err
	})
	if err != nil {
		return nil, fmt.Errorf("screens: reading a catalogue item: %w", err)
	}
	return items, nil
}

// assignablePartnerChoices is assignable_partners: active, not a Loan Partner
// and not on hold, sorted ignoring case as the project drawers show them.
func (s *Service) assignablePartnerChoices(ctx context.Context) ([]fieldChoice, error) {
	rows, err := s.db.Query(ctx, `
SELECT id, name
  FROM partner
 WHERE deleted_at IS NULL AND active_status
   AND partner_role IS DISTINCT FROM 'loan'
   AND id NOT IN (SELECT partner_id FROM partner_hold WHERE lifted_at IS NULL)
 ORDER BY name`)
	if err != nil {
		return nil, fmt.Errorf("screens: reading the assignable partners: %w", err)
	}
	partners, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (fieldChoice, error) {
		var c fieldChoice
		err := row.Scan(&c.id, &c.name)
		return c, err
	})
	if err != nil {
		return nil, fmt.Errorf("screens: reading a partner: %w", err)
	}
	return sortedFieldChoices(partners), nil
}

// sortedFieldChoices is sorted(key=name.casefold()): a new list, stable for
// names that fold alike.
func sortedFieldChoices(choices []fieldChoice) []fieldChoice {
	fold := cases.Fold()
	sorted := slices.Clone(choices)
	slices.SortStableFunc(sorted, func(a, b fieldChoice) int {
		return strings.Compare(fold.String(a.name), fold.String(b.name))
	})
	return sorted
}

func choiceOptions(choices [][2]string) []*screensv1.DrawerOption {
	options := make([]*screensv1.DrawerOption, 0, len(choices))
	for _, choice := range choices {
		options = append(options, &screensv1.DrawerOption{Value: choice[0], Label: choice[1]})
	}
	return options
}

func formField(field *screensv1.DrawerField) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: field}}
}

// projectCreateDrawer is create_project_drawer.html.
func projectCreateDrawer(catalogue []projectCatalogueChoice, partners []fieldChoice) *screensv1.PageDrawer {
	interventions := append(slices.Clone(ssaInterventionChoices), [2]string{"general", "General"})
	catalogueOptions := make([]*screensv1.DrawerOption, 0, len(catalogue))
	for _, item := range catalogue {
		delivery, known := deliveryMethodLabels[item.delivery]
		if !known {
			delivery = item.delivery
		}
		catalogueOptions = append(catalogueOptions, &screensv1.DrawerOption{
			Value: item.id, Label: item.name, Detail: item.code + " · " + delivery,
		})
	}
	partnerOptions := make([]*screensv1.DrawerOption, 0, len(partners))
	for _, partner := range partners {
		partnerOptions = append(partnerOptions, &screensv1.DrawerOption{Value: partner.id, Label: partner.name})
	}
	return &screensv1.PageDrawer{
		Title:       "Create special project",
		HasRequired: true,
		SubmitLabel: "Create proposed project",
		CancelLabel: "Cancel",
		CanSubmit:   true,
		Items: []*screensv1.DrawerItem{
			formField(&screensv1.DrawerField{Name: "name", Label: "Project name", Kind: "text", Required: true, MaxLength: proto.Int32(255)}),
			formField(&screensv1.DrawerField{Name: "code", Label: "Stable project code", Kind: "text", Placeholder: "SP-…", MaxLength: proto.Int32(64)}),
			formField(&screensv1.DrawerField{Name: "category", Label: "Category", Kind: "select", Required: true, Options: choiceOptions(projectCategoryChoices)}),
			formField(&screensv1.DrawerField{Name: "schoolFocus", Label: "School focus", Kind: "select", Value: "all", Required: true, Options: choiceOptions(projectFocusChoices)}),
			formField(&screensv1.DrawerField{Name: "budgetCeilingUgx", Label: "Budget ceiling (UGX)", Kind: "number", Min: proto.Float64(0), Step: proto.Float64(1)}),
			formField(&screensv1.DrawerField{Name: "measurementStartFy", Label: "Measurement start FY", Kind: "text", Placeholder: "2027"}),
			formField(&screensv1.DrawerField{Name: "measurementEndFy", Label: "Measurement end FY", Kind: "text", Placeholder: "2028"}),
			formField(&screensv1.DrawerField{Name: "targetInterventions", Label: "Target interventions", Kind: "checklist", Help: projectInterventionHelp, Options: choiceOptions(interventions)}),
			formField(&screensv1.DrawerField{Name: "catalogueItemIds", Label: "Approved Activity Catalogue items", Kind: "checklist", Help: projectCatalogueHelp, Options: catalogueOptions}),
			formField(&screensv1.DrawerField{Name: "partnerIds", Label: "Project partners", Kind: "checklist", Help: projectPartnerHelp, Options: partnerOptions}),
		},
	}
}
