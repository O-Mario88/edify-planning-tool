package activities

// The Work Plan's "Add Non-School Activity" save with the existing
// application absent (work_plan_views.non_school_activity_action →
// planning.services.schedule_programme_activity → activities.services.create
// for a non-school catalogue item), for an officer's or lead's own
// administrative or field-event activity: the view's defaults, create's
// non-school checks in its order, the row, its catalogue snapshot, its price
// on its own (PriceAloneInTx) and its `activity.scheduled` row, in one
// transaction. A partner or another staff member made responsible, a
// project, an item that names an intervention, a training course, a cost the
// catalogue cannot price and work with no date are handed on.

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
)

const (
	manualActivityPermission = "planning.manualActivity.create"
	couldNotAdd              = "Could not add the activity: "
	chooseApprovedTitle      = "Choose an approved Activity title: "
	itemNotSelectable        = "The selected Activity Catalogue item is inactive, retired, outside its effective dates, or does not exist."
	programmeAdded           = "Activity added to the Work Plan."
	organizationalPriority   = "organizational_priority"
	leadershipException      = "leadership_exception"
	manualWorkPlan           = "manual_work_plan"
	fieldEventType           = "field_event"
	administrativeMapping    = "administrative"
	maxProgrammeSpanDays     = 30
	maxSchoolsReached        = 10000
	maxProgrammeParticipants = 100000
)

// programmeDeliveryModes is _programme_item_metadata's delivery_modes.
var programmeDeliveryModes = map[string]string{
	"in_school_training": "in_school", "cluster_meeting": "cluster", "cluster_training": "cluster",
	"online": "online", "school_visit": "visit", "group": "group", "admin": "admin", "programme_event": "group",
}

// programmeActivityTypes are ProgrammeActivityType's values.
var programmeActivityTypes = []string{"edtech_for_schools", "school_leadership_training", "student_activities",
	"teacher_training", "alumni", "training", "school_visit", "field_event", "youth_camp", "admin", "programme_event"}

// wholeNumber is what Go reads as Python's int() does: digits alone.
var wholeNumber = regexp.MustCompile(`^[0-9]{1,9}$`)

// programmeItem is the catalogue item as the Add reads it.
type programmeItem struct {
	item
	code                                   string
	nonSchool, needsParticipants, multiDay bool
	mapping                                string // the primary active mapping's mode
}

func readProgrammeItem(ctx context.Context, q Querier, idOrCode string, on time.Time) (*programmeItem, error) {
	var it programmeItem
	err := q.QueryRow(ctx, `SELECT `+itemColumns+`, i.stable_code, i.non_school_allowed, i.requires_participant_counts,
  i.multi_day_allowed,
  COALESCE((SELECT m.mapping_mode FROM activity_intervention_mapping m WHERE m.catalogue_item_id = i.id AND m.active
            ORDER BY m.is_primary DESC, m.priority, m.id LIMIT 1), '')
FROM activity_catalogue_item i
WHERE `+effective+` AND (i.id = $2 OR i.stable_code = $2)
ORDER BY i.display_name, i.stable_code LIMIT 1`, on.Format(time.DateOnly), idOrCode).Scan(
		&it.ID, &it.WorkflowKind, &it.DisplayName, &it.ActivityType, &it.DeliveryMethod,
		&it.EvidenceProfile, &it.SalesforceRecordType, &it.CostingProfile, &it.Status,
		&it.StandardSupport, &it.CountsTowardClientVisit, &it.RequiresSchool, &it.RequiresCluster,
		&it.IsTrainingCourse, &it.ParticipantMode, &it.code, &it.nonSchool, &it.needsParticipants, &it.multiDay, &it.mapping)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("activities: reading the programme item: %w", err)
	}
	return &it, nil
}

// programmePlan is the Add, decided before its transaction.
type programmePlan struct {
	p                       auth.Principal
	item                    *programmeItem
	version                 int
	firstVersion            bool
	responsible             string
	scheduled, day          time.Time
	end                     *time.Time
	schools, participants   int
	venue, purpose, outcome string
	districtID              string
	mode                    string
	origin                  Origin
	now                     time.Time
}

// AddProgrammeActivity makes the Add, or refuses it in the existing words,
// or hands it on (ErrHandOn).
func (s *Service) AddProgrammeActivity(ctx context.Context, p auth.Principal, form url.Values, origin Origin) (Answer, error) {
	pl, err := s.prepareProgramme(ctx, p, form, origin)
	if err != nil {
		return Answer{}, err
	}
	id, err := s.writeProgramme(ctx, pl)
	if err != nil {
		return Answer{}, err
	}
	if in(rules.LedgerCreditedTypes, pl.item.WorkflowKind) {
		if err := s.markOwnerYears(ctx, pl.responsible, pl.day); err != nil {
			s.logger.Warn("activities: the target ledger was not marked", "activity", id, "err", err)
		}
	}
	if announcer, ok := s.pricing.(interface {
		Announce(ctx context.Context, activityID string) error
	}); ok {
		_ = announcer.Announce(ctx, id)
	}
	return Answer{ActivityID: id, Message: programmeAdded}, nil
}

// prepareProgramme is the view and create() up to the transaction.
func (s *Service) prepareProgramme(ctx context.Context, p auth.Principal, form url.Values, origin Origin) (*programmePlan, error) {
	if p.InActingAppointment || !rbac.Grants(p.ActiveRole, manualActivityPermission) || rules.CalendarBlocksRefuse {
		return nil, handOn("not a person adding their own programme activity")
	}
	own := p.StaffProfileID
	if own == "" {
		return nil, handOn("no staff profile")
	}
	switch kind := pyStrip(form.Get("responsibility_type")); kind {
	case "", "staff":
	case "partner":
		return nil, handOn("a partner made responsible")
	default:
		return nil, refuse("%s", "Could not add the activity: Select Staff or Partner as the responsible party.")
	}
	if r := pyStrip(form.Get("responsible_staff_id")); r != "" && r != own {
		return nil, handOn("another staff member made responsible")
	}
	if pyStrip(form.Get("project_id")) != "" || pyStrip(form.Get("partner_id")) != "" {
		return nil, handOn("a project or a partner named")
	}
	counts := map[string]int{}
	for _, field := range []string{"expected_participants", "planned_school_count"} {
		raw := form.Get(field)
		if raw == "" {
			continue
		}
		if !wholeNumber.MatchString(raw) {
			return nil, handOn(field + " in another form")
		}
		n, _ := strconv.Atoi(raw)
		counts[field] = n
	}
	start := pyStrip(form.Get("scheduled_date"))
	if !isoDate.MatchString(start) {
		return nil, handOn("work with no date, or a date in another form")
	}
	code := pyStrip(form.Get("catalogue_item_id"))
	local := s.now().In(s.kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	it, err := readProgrammeItem(ctx, s.db, code, today)
	if err != nil {
		return nil, err
	}
	if it == nil {
		return nil, refuse("%s", chooseApprovedTitle+itemNotSelectable)
	}
	if it.IsTrainingCourse || it.mapping != administrativeMapping {
		return nil, handOn("an item that names an intervention or a training")
	}
	mode, ok := programmeDeliveryModes[it.DeliveryMethod]
	if !ok {
		return nil, handOn("an item with another delivery method")
	}
	day, err := time.ParseInLocation(time.DateOnly, start, s.kampala)
	if err != nil {
		return nil, handOn("not a day")
	}
	pl := &programmePlan{
		p: p, responsible: own, day: time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, time.UTC),
		scheduled: time.Date(day.Year(), day.Month(), day.Day(), 9, 0, 0, 0, s.kampala),
		schools:   counts["planned_school_count"], participants: counts["expected_participants"],
		districtID: pyStrip(form.Get("district_id")), mode: mode, origin: origin, now: s.now(),
		outcome: pyStrip(form.Get("expected_outcome")),
	}
	// create(): the item selectable on the day, then the day plannable.
	if pl.item, err = readProgrammeItem(ctx, s.db, it.ID, pl.day); err != nil {
		return nil, err
	}
	if pl.item == nil {
		return nil, refuse("%s", couldNotAdd+itemNotSelectable)
	}
	if pl.day.Before(today) {
		return nil, refuse("%s%s has passed. Schedule work from %s onwards.", couldNotAdd, longDate(pl.day), longDate(today))
	}
	if err := s.programmeChecks(ctx, pl, form); err != nil {
		return nil, err
	}
	version, ok, err := latestVersion(ctx, s.db, pl.item.ID)
	if err != nil {
		return nil, err
	}
	pl.version, pl.firstVersion = version, !ok
	if !ok {
		pl.version = 1
	}
	return pl, nil
}

// programmeChecks are create()'s non-school checks, in their order, with the
// view's venue and purpose defaults.
func (s *Service) programmeChecks(ctx context.Context, pl *programmePlan, form url.Values) error {
	it := pl.item
	if !it.nonSchool {
		return refuse("%s", couldNotAdd+"Activity must reference a school or cluster. Programme work without one must use an approved non-school Catalogue Activity.")
	}
	if it.needsParticipants && pl.participants == 0 {
		return refuse("%s", couldNotAdd+"Enter the expected participant count — this Activity type is priced and planned per participant.")
	}
	if !slices.Contains(programmeActivityTypes, it.ActivityType) {
		return refuse("%s", couldNotAdd+"Select a valid programme Activity type.")
	}
	if it.WorkflowKind == fieldEventType {
		pl.schools = 0
	} else if pl.schools < 1 || pl.schools > maxSchoolsReached {
		return refuse("%s", couldNotAdd+"Number of schools must be between 1 and 10,000.")
	}
	if it.WorkflowKind != fieldEventType && (pl.participants < 1 || pl.participants > maxProgrammeParticipants) {
		return refuse("%s", couldNotAdd+"Number of participants must be between 1 and 100,000.")
	}
	if raw := pyStrip(form.Get("end_date")); raw != "" {
		if !isoDate.MatchString(raw) {
			return handOn("an end date in another form")
		}
		end, err := time.Parse(time.DateOnly, raw)
		if err != nil {
			return handOn("not an end day")
		}
		switch {
		case end.Before(pl.day):
			return refuse("%s", couldNotAdd+"The end date cannot precede the start date.")
		case !end.Equal(pl.day) && !it.multiDay:
			return refuse("%s", couldNotAdd+"This Activity type is a single-day activity.")
		case end.Sub(pl.day).Hours()/24 > maxProgrammeSpanDays:
			return refuse("%s", couldNotAdd+"A programme Activity may span at most 31 days.")
		}
		if !end.Equal(pl.day) {
			pl.end = &end
		}
	}
	// The view's defaults: the item's name as the purpose, and the venue the
	// destination district's name, else a placeholder.
	pl.purpose = pyStrip(form.Get("purpose"))
	if pl.purpose == "" {
		pl.purpose = it.DisplayName
	}
	pl.venue = pyStrip(form.Get("venue"))
	if pl.venue == "" && pl.districtID != "" {
		if err := s.db.QueryRow(ctx, `SELECT COALESCE(name, '') FROM district WHERE id = $1`, pl.districtID).Scan(&pl.venue); err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return fmt.Errorf("activities: reading the district's name: %w", err)
		}
	}
	if pl.venue == "" {
		pl.venue = "To be confirmed"
	}
	if pl.districtID != "" {
		var known bool
		if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM district WHERE id = $1)`, pl.districtID).Scan(&known); err != nil {
			return fmt.Errorf("activities: reading the district: %w", err)
		}
		if !known {
			pl.districtID = ""
		}
	}
	var duplicate bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity WHERE activity_type = $1 AND planned_date = $2
  AND deleted_at IS NULL AND responsible_staff_id = $3 AND assigned_partner_id IS NULL AND cluster_id IS NULL
  AND school_id IS NULL AND NOT (status = ANY($4)))`,
		it.WorkflowKind, pl.day.Format(time.DateOnly), pl.responsible, []string{"cancelled", "rejected", "deferred"}).Scan(&duplicate); err != nil {
		return fmt.Errorf("activities: reading the day's identical activities: %w", err)
	}
	if duplicate {
		return refuse("%s", couldNotAdd+"An identical activity is already scheduled for this target on this date. Reschedule or edit the existing activity instead of creating a duplicate.")
	}
	return nil
}

// writeProgramme is the transaction: the row, priced on its own, and its
// `activity.scheduled` row.
func (s *Service) writeProgramme(ctx context.Context, pl *programmePlan) (string, error) {
	pricer, ok := s.pricing.(AlonePricer)
	if !ok {
		return "", handOn("no pricing for work on its own")
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return "", fmt.Errorf("activities: opening the Add: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if pl.firstVersion {
		if err := establishVersion(ctx, tx, pl.item.ID, pl.now); err != nil {
			return "", err
		}
	}
	id := cuid.New()
	if err := insertProgramme(ctx, tx, id, pl); err != nil {
		return "", err
	}
	err = pricer.PriceAloneInTx(ctx, tx, id, pl.p.UserID, pl.p.ActiveRole, pl.costInputs(ctx, tx, id))
	if errors.Is(err, errCostMissing) || errors.Is(err, errReferenceCard) {
		return "", handOn("a cost the catalogue cannot price yet, or a regional card to price against")
	}
	if err != nil {
		return "", err
	}
	role := pl.p.ActiveRole
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "activity.scheduled", SubjectKind: audit.Text("Activity"), SubjectID: audit.Text(id),
		ActorID: audit.Text(pl.p.UserID), ActorRole: &role, Success: true,
		Payload: map[string]any{
			"activity_type": pl.item.WorkflowKind, "catalogue_item": pl.item.ID, "catalogue_version": pl.version,
			"school_id": nil, "cluster_id": nil, "project_id": nil, "fy": fyOf(pl.day),
			"planned_date": pl.day.Format(time.DateOnly), "delivery_type": "staff", "executor_type": "staff",
			"focus_intervention": "",
		},
		IPAddress: nilIfEmpty(pl.origin.IP), UserAgent: nilIfEmpty(pl.origin.UserAgent),
		CorrelationID: nilIfEmpty(pl.origin.CorrelationID),
	}, s.now()); err != nil {
		return "", fmt.Errorf("activities: writing the scheduled row: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return "", fmt.Errorf("activities: committing the Add: %w", err)
	}
	return id, nil
}

// costInputs is the snapshot's calculation_inputs as _costing_input builds
// them for this row.
func (pl *programmePlan) costInputs(ctx context.Context, tx pgx.Tx, id string) map[string]any {
	inputs := map[string]any{
		"activityType": pl.item.WorkflowKind, "catalogueItemId": pl.item.ID, "costingProfile": pl.item.CostingProfile,
		"days": 1, "deliveryType": "staff", "facilitated": false, "fy": fyOf(pl.day),
		"leadersAttended": nil, "nights": nil, "otherParticipants": nil, "teachersAttended": nil,
		"photocopyCopies": 0, "photocopyPages": 0, "printingPages": 0, "projectId": nil,
		"plannedDate": pl.day.Format(time.DateOnly), "expectedParticipants": nilIfZero(pl.participants),
	}
	if pl.end != nil {
		inputs["days"] = int(pl.end.Sub(pl.day).Hours()/24) + 1
	}
	if in, err := pricingInput(ctx, tx, id); err == nil {
		inputs["accommodationKey"], inputs["districtType"] = in.AccommodationKey, in.DistrictType
	}
	return inputs
}

func nilIfZero(n int) any {
	if n == 0 {
		return nil
	}
	return n
}

// insertProgramme is create()'s row and apply_catalogue_snapshot for a
// non-school administrative item.
func insertProgramme(ctx context.Context, tx pgx.Tx, id string, pl *programmePlan) error {
	it := pl.item
	var sfType any
	switch it.SalesforceRecordType {
	case "TRAINING":
		sfType = "training"
	case "VISIT":
		sfType = "visit"
	}
	var end any
	if pl.end != nil {
		end = pl.end.Format(time.DateOnly)
	}
	columns := []struct {
		name  string
		value any
	}{
		{"id", id}, {"created_at", pl.now}, {"updated_at", pl.now}, {"activity_type", it.WorkflowKind},
		{"fy", fyOf(pl.day)}, {"quarter", quarterOf(pl.day)}, {"delivery_type", "staff"}, {"executor_type", "staff"},
		{"status", "scheduled"}, {"evidence_status", "none"}, {"ia_verification_status", "pending"},
		{"payment_status", "none"}, {"reschedule_count", 0}, {"est_cost_cents", 0}, {"cost_missing", false},
		{"environment", "production"}, {"source", "manual_upload"}, {"responsible_staff_id", pl.responsible},
		{"scheduled_date", pl.scheduled}, {"planned_date", pl.day.Format(time.DateOnly)},
		{"planned_month", int(pl.day.Month())}, {"planned_week", min(5, (pl.day.Day()-1)/7+1)},
		{"end_date", end}, {"secondary_focus_interventions", []string{}}, {"activity_purpose_text", pl.purpose},
		{"expected_outcome", pl.outcome}, {"expected_participants", nilIfZero(pl.participants)},
		{"ssa_collection_expected", false}, {"attended_school_ids", []string{}}, {"salesforce_activity_type", sfType},
		{"catalogue_item_id", it.ID}, {"catalogue_version", pl.version}, {"activity_name_snapshot", it.DisplayName},
		{"activity_type_snapshot", it.ActivityType}, {"delivery_method_snapshot", it.DeliveryMethod},
		{"evidence_profile_snapshot", optString(it.EvidenceProfile)}, {"costing_profile_snapshot", optString(it.CostingProfile)},
		{"salesforce_record_type_snapshot", optString(it.SalesforceRecordType)},
		{"recommendation_reason", ""}, {"recommendation_source", []byte(`{}`)}, {"override_reason", ""},
		{"ssa_alignment", ""}, {"ssa_deviation_reason", ""}, {"planning_source", manualWorkPlan},
		{"activity_context_type", "organization"}, {"support_rationale", organizationalPriority}, {"venue", truncateRunes(pl.venue, 255)},
		{"programme_activity_type", it.ActivityType}, {"programme_delivery_mode", pl.mode},
		{"planned_school_count", pl.schools}, {"event_district_id", optString(pl.districtID)},
		{"primary_driver_type", leadershipException}, {"primary_driver_id", ""}, {"driver_reason", organizationalPriority},
		{"delivery_contact_name", ""}, {"approval_owner_id", ""}, {"owner_decision_note", ""}, {"visit_justification", ""},
		{"partner_date_set_by", ""}, {"meeting_kind", ""},
	}
	names := make([]string, len(columns))
	marks := make([]string, len(columns))
	values := make([]any, len(columns))
	for i, c := range columns {
		names[i], marks[i], values[i] = c.name, fmt.Sprintf("$%d", i+1), c.value
	}
	if _, err := tx.Exec(ctx, "INSERT INTO activity ("+strings.Join(names, ", ")+") VALUES ("+strings.Join(marks, ", ")+")", values...); err != nil {
		return fmt.Errorf("activities: inserting the programme activity: %w", err)
	}
	return nil
}
