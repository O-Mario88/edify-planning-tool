package activities

import (
	"context"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The Core Schools training form (core_schools_views.core_schedule_training_action):
// one priced training, in a slot of the package, with no companion visit.
const (
	coreTrainingDateRefusal = "Please choose a valid planned date and training slot."
	coreTrainingNoCourse    = "Select a training from the Training Catalogue."
	coreTrainingNoProfile   = "The standard In-school Training profile must be active before a Core training can be scheduled."
)

// coreTrainingRoles plan the package's trainings; the visit-only roles are
// refused and anyone else is handed on.
var (
	coreTrainingRoles  = []string{"CCEO", "Program Lead"}
	coreVisitOnlyRoles = []string{"CountryDirector", "ImpactAssessment", "Accountant"}
)

var coreTrainingFields = map[string]bool{
	"csrfmiddlewaretoken": true, "school_id": true, "catalogue_item_id": true, "training_number": true,
	"scheduled_date": true, "training_purpose": true, "focus_intervention": true, "facilitating_partner_id": true,
	"responsible_staff_id": true, "recommendation_reason": true, "expected_participants": true,
	"duration_hours": true, "delivery_type": true,
}

// CoreTrainingRequest is the Core training form as posted.
type CoreTrainingRequest struct {
	SchoolCode, CourseID, TrainingNumber, Date, Goal string
	Focus, Facilitator, Responsible, RecReason       string
}

// CoreTrainingRequestFromForm reads the form; false when Go does not take it.
func CoreTrainingRequestFromForm(schoolCode string, form url.Values) (CoreTrainingRequest, bool) {
	for name, values := range form {
		if coreTrainingFields[name] {
			continue
		}
		for _, value := range values {
			if strings.TrimSpace(value) != "" {
				return CoreTrainingRequest{}, false
			}
		}
	}
	text := func(name string) string { return strings.TrimSpace(form.Get(name)) }
	return CoreTrainingRequest{
		SchoolCode: strings.TrimSpace(schoolCode), CourseID: text("catalogue_item_id"), TrainingNumber: text("training_number"),
		Date: text("scheduled_date"), Goal: text("training_purpose"), Focus: text("focus_intervention"),
		Facilitator: text("facilitating_partner_id"), Responsible: text("responsible_staff_id"),
		RecReason: form.Get("recommendation_reason"),
	}, true
}

func coreLoneTrainingBooked(number int) string {
	return fmt.Sprintf("Core Training T%d scheduled successfully.", number)
}

func coreLoneUniversalBooked(course string) string {
	return course + " scheduled. It is on top of the package's four trainings."
}

// ScheduleCoreTraining makes the Core training form's save, or refuses it in
// the existing words, or hands it on (ErrHandOn).
func (s *Service) ScheduleCoreTraining(ctx context.Context, p auth.Principal, req CoreTrainingRequest, origin Origin) (Answer, error) {
	if s.requests == nil || p.InActingAppointment || p.StaffProfileID == "" {
		return Answer{}, handOn("not a person Go saves the Core training form for")
	}
	if in(coreVisitOnlyRoles, p.ActiveRole) {
		return Answer{}, &Refusal{Message: coreTrainingRefused, Forbidden: true}
	}
	if !in(coreTrainingRoles, p.ActiveRole) || req.Facilitator != "" || req.Responsible != "" {
		return Answer{}, handOn("a facilitator, a named person, or a role Go does not take here")
	}
	now := s.now()
	today := dateOnly(now.In(s.kampala))
	refusal, found, err := s.requests.OperationalRefusal(ctx, p, req.SchoolCode)
	if err != nil {
		return Answer{}, fmt.Errorf("activities: reading the school's door: %w", err)
	}
	if !found {
		return Answer{}, handOn("no such school")
	}
	if refusal != "" {
		return Answer{}, &Refusal{Message: refusal, Forbidden: true}
	}
	sc, err := schoolByIDOrCode(ctx, s.db, req.SchoolCode)
	if err != nil {
		return Answer{}, err
	}
	if sc == nil || sc.Code != req.SchoolCode || !in(rules.Gate.CoreRuleTypes, sc.Type) {
		return Answer{}, handOn("not a Core school by its code")
	}
	if req.CourseID == "" {
		return Answer{}, refuse(coreTrainingNoCourse)
	}
	c, err := offeredCourse(ctx, s.db, req.CourseID, today)
	if err != nil {
		return Answer{}, err
	}
	if c == nil {
		return Answer{}, refuse(notOffered)
	}
	focus, taken := c.focus()
	if !taken || c.conflicts() {
		return Answer{}, handOn("a course Go does not take (its intervention mapping or kind)")
	}
	profile, err := resolveForKind(ctx, s.db, rules.Pair.TrainingKind, today)
	if err != nil {
		return Answer{}, err
	}
	if profile == nil {
		return Answer{}, refuse(coreTrainingNoProfile)
	}
	number, day, err := s.coreTrainingSlotAndDay(req)
	if err != nil {
		return Answer{}, err
	}
	planID, err := s.routeCorePair(ctx, *sc, *c, day, now)
	if err != nil {
		return Answer{}, err
	}
	if planID == "" && !c.Universal {
		return Answer{}, refuse(noActivePackage)
	}
	pl, err := s.pairTraining(ctx, p, Request{Goal: req.Goal, RecReason: strings.TrimSpace(req.RecReason)}, origin,
		now, today, day, *sc, p.StaffProfileID, "", *c, focus, profile.ID)
	if err != nil {
		return Answer{}, err
	}
	if pl.ownerUID, err = fundingOwner(ctx, s.db, p.StaffProfileID, p.UserID); err != nil {
		return Answer{}, err
	}
	if pl.verdict, err = s.pricing.DayCheck(ctx, pl.row.probe()); err != nil {
		return Answer{}, err
	}
	if pl.verdict.Refusal != "" && pl.verdict.Stage == "preview" {
		return Answer{}, &Refusal{Message: pl.verdict.Refusal}
	}
	if !pl.verdict.Pooled && pl.verdict.Refusal == "" {
		return Answer{}, handOn("the day does not pool the training")
	}
	pl.ceilingCourse, pl.doorAudit = c.ID, auditCoreTraining
	pl.row.noOutcomeField = true
	if planID != "" {
		pl.core = &coreBooking{planID: planID, route: corePackageTraining, preferred: number, course: c}
	}
	rowID, err := s.write(ctx, pl)
	if err != nil {
		return Answer{}, err
	}
	s.afterCommit(ctx, pl, rowID)
	booked := coreLoneUniversalBooked(c.Name)
	if pl.core != nil {
		booked = coreLoneTrainingBooked(pl.core.slotNumber)
	}
	return s.coreDoorAnswer(ctx, pl, booked, nil)
}

// coreTrainingSlotAndDay is the form's one refusal for either being unreadable.
func (s *Service) coreTrainingSlotAndDay(req CoreTrainingRequest) (int, time.Time, error) {
	number, err := coreSlotNumber(req.TrainingNumber)
	if err != nil {
		return 0, time.Time{}, refuse(coreTrainingDateRefusal)
	}
	if req.Date != "" && !isoDate.MatchString(req.Date) {
		return 0, time.Time{}, handOn("a date in another form")
	}
	day, err := time.ParseInLocation(time.DateOnly, req.Date, s.kampala)
	if err != nil {
		return 0, time.Time{}, refuse(coreTrainingDateRefusal)
	}
	return number, day, nil
}
