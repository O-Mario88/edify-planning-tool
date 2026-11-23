package screens

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

const (
	maxSchoolsReached       = 10_000
	maxExpectedParticipants = 100_000
	maxVenueLength          = 255
	datePrefillLength       = 10
)

// programmeChoice is a catalogue activity that may be planned away from a
// school. fieldEvent travels as the option's group, as the existing form's
// first data attribute does.
type programmeChoice struct {
	code, name string
	fieldEvent bool
}

// workPlanAddForm is non_school_activity_drawer.
func workPlanAddForm(ctx context.Context, s *Service, _ auth.Principal, req fieldFormRequest) (*screensv1.PageDrawer, error) {
	items, err := s.programmeChoices(ctx, s.now().In(exportDayZone).Format(time.DateOnly))
	if err != nil {
		return nil, err
	}
	districts, err := s.districtChoices(ctx)
	if err != nil {
		return nil, err
	}
	return workPlanAddDrawer(items, districts, workPlanDatePrefill(req.query.Get("date"))), nil
}

// workPlanDatePrefill is (date or "").strip()[:10].
func workPlanDatePrefill(raw string) string {
	runes := []rune(strings.TrimSpace(raw))
	if len(runes) > datePrefillLength {
		runes = runes[:datePrefillLength]
	}
	return string(runes)
}

func (s *Service) programmeChoices(ctx context.Context, today string) ([]programmeChoice, error) {
	rows, err := s.db.Query(ctx, `
SELECT stable_code, display_name, activity_type = 'field_event'
  FROM activity_catalogue_item
 WHERE status = 'active' AND non_school_allowed
   AND (effective_from IS NULL OR effective_from <= $1::date)
   AND (effective_to IS NULL OR effective_to >= $1::date)
 ORDER BY programme_category, display_name`, today)
	if err != nil {
		return nil, fmt.Errorf("screens: reading the programme activities: %w", err)
	}
	items, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (programmeChoice, error) {
		var c programmeChoice
		err := row.Scan(&c.code, &c.name, &c.fieldEvent)
		return c, err
	})
	if err != nil {
		return nil, fmt.Errorf("screens: reading a programme activity: %w", err)
	}
	return items, nil
}

func (s *Service) districtChoices(ctx context.Context) ([]fieldChoice, error) {
	rows, err := s.db.Query(ctx, `SELECT id, name FROM district ORDER BY name`)
	if err != nil {
		return nil, fmt.Errorf("screens: reading the districts: %w", err)
	}
	districts, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (fieldChoice, error) {
		var c fieldChoice
		err := row.Scan(&c.id, &c.name)
		return c, err
	})
	if err != nil {
		return nil, fmt.Errorf("screens: reading a district: %w", err)
	}
	return districts, nil
}

// workPlanAddDrawer is non_school_activity_drawer.html.
func workPlanAddDrawer(items []programmeChoice, districts []fieldChoice, startDate string) *screensv1.PageDrawer {
	activities := make([]*screensv1.DrawerOption, 0, len(items)+1)
	activities = append(activities, &screensv1.DrawerOption{Label: "Select an approved activity"})
	for _, item := range items {
		activities = append(activities, &screensv1.DrawerOption{
			Value: item.code, Label: item.name, Group: strconv.FormatBool(item.fieldEvent),
		})
	}
	interventions := append([]*screensv1.DrawerOption{{Label: "Select the intervention being followed up"}},
		choiceOptions(ssaInterventionChoices)...)
	places := make([]*screensv1.DrawerOption, 0, len(districts)+1)
	places = append(places, &screensv1.DrawerOption{Label: "My own district"})
	for _, district := range districts {
		places = append(places, &screensv1.DrawerOption{Value: district.id, Label: district.name})
	}
	return &screensv1.PageDrawer{
		Title:       "Plan field event",
		HasRequired: true,
		SubmitLabel: "Add to my plan",
		CancelLabel: "Cancel",
		CanSubmit:   true,
		Items: []*screensv1.DrawerItem{
			formField(&screensv1.DrawerField{Name: "catalogue_item_id", Label: "Activity", Kind: "select", Required: true,
				Help: "Training category: · SSA intervention:", Options: activities}),
			formField(&screensv1.DrawerField{Name: "focus_intervention", Label: "Follow-up intervention", Kind: "select", Options: interventions}),
			formField(&screensv1.DrawerField{Name: "scheduled_date", Label: "Start date", Kind: "date", Value: startDate, Required: true}),
			formField(&screensv1.DrawerField{Name: "end_date", Label: "End date (multi-day events only)", Kind: "date"}),
			formField(&screensv1.DrawerField{Name: "district_id", Label: "District", Kind: "select", Options: places}),
			formField(&screensv1.DrawerField{Name: "venue", Label: "Venue", Kind: "text", Placeholder: "e.g. Kampala Serena", MaxLength: proto.Int32(maxVenueLength)}),
			formField(&screensv1.DrawerField{Name: "planned_school_count", Label: "Schools reached", Kind: "number",
				Min: proto.Float64(1), Max: proto.Float64(maxSchoolsReached)}),
			formField(&screensv1.DrawerField{Name: "expected_participants", Label: "Participants * (if the activity feeds or hosts people)", Kind: "number",
				Min: proto.Float64(1), Max: proto.Float64(maxExpectedParticipants)}),
			textLine("Cost preview"),
			textLine("Enter dates and participants to preview the catalogue cost."),
			textLine("It appears in My Plan, the Work Plan and the Calendar, and its catalogue cost enters your fund request and budget."),
		},
	}
}
