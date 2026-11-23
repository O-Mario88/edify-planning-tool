package coreforms

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/projectspage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workplan"
)

const (
	// AdminNotPlanner is ADMIN_IS_NOT_A_PLANNER_MESSAGE.
	AdminNotPlanner = "Planning belongs to the staff member responsible for the school. The Admin role administers the platform and does not schedule field work — ask the school's CCEO to plan it, or switch to your own field role if you hold one."
	// PlanningDenied is require_any_page_permission's words for Planning.
	PlanningDenied = "Access Denied: Your active role does not have permission to view Planning."

	actingRefused   = "This form is not available while you are acting in another role."
	noCatalogueCost = "No single approved Cost Catalogue entry prices this purpose. Ask the Country Director to define one."
	maxPartnerPlans = 6
)

var (
	// planningPageRoles is PAGE_PERMISSIONS for Planning and Visit Requests.
	planningPageRoles = []string{roleAccountant, roleAdmin, roleCCEO, roleCD, roleIA, rolePL, rolePC}
	// schoolActivityTypes is the drawer's direct-school activity types.
	schoolActivityTypes = []string{"school_visit", "follow_up_visit", "coaching_visit", "in_school_support", "donor_visit", "story_gathering_visit",
		"school_invitation", "social_visit", "training_follow_up_visit", "in_school_coaching_visit", "in_school_training",
		"school_improvement_training", "baseline_ssa_visit", "school_visit_ssa_collection"}
	ssaCollectionTypes = []string{"baseline_ssa_visit", "school_visit_ssa_collection", "school_visit"}
	outreachTypes      = []string{"donor_visit", "story_gathering_visit"}
	outreachPurposes   = []string{"donor_visit", "story_gathering"}
	// supportPool is POOL_PURPOSES[SUPPORT_POOL].
	supportPool = []string{"training_follow_up", "in_school_training", "in_school_training_ssa"}
	// fallbackPurposes is _fallback_for_activity_type.
	fallbackPurposes = map[string]string{
		"in_school_training": "in_school_training", "training": "in_school_training", "school_improvement_training": "in_school_training",
		"training_follow_up_visit": "training_follow_up", "donor_visit": "donor_visit", "story_gathering_visit": "story_gathering",
		"school_invitation": "school_invitation", "social_visit": "social_visit", "in_school_coaching_visit": "in_school_coaching",
	}
	participantModes = []string{"direct_total", "per_school", "by_category"}
)

// LeadLine is one SSA intervention above the purpose.
type LeadLine struct{ Label, Value, Tone string }

// PlanNote is a note with a title over its body.
type PlanNote struct{ Title, Text, Tone string }

// LeadItem is one part drawn above Purpose of visit.
type LeadItem struct {
	Heading, Text string
	Line          *LeadLine
	Note          *PlanNote
}

// ExistingPlan is one plan the school already has.
type ExistingPlan struct{ Label, Status, Tone string }

// ExistingPlans is existing_plan_warning.
type ExistingPlans struct {
	Message string
	Plans   []ExistingPlan
}

// PurposeChoice is one purpose of visit.
type PurposeChoice struct {
	Value, Label string
	Disabled     bool
}

// PurposeProfile is what a purpose asks for.
type PurposeProfile struct {
	RequiresParticipants, Schedulable bool
	UnavailableReason                 string
}

// Locks is what the year's used visits grey.
type Locks struct {
	Visit                           map[string]map[string]string
	Order, EveryYear, Reasons       []string
	Training                        map[string]string
	TrainingEveryYear, AllEveryYear bool
}

type yearUse struct {
	year, reason string
	used         bool
}

type profileItem struct {
	kind, code, mode string
	standard         bool
}

// ScheduleForm is _schedule_modal for one school.
type ScheduleForm struct {
	School                             School
	Lead                               []LeadItem
	Existing                           *ExistingPlans
	Purposes                           []PurposeChoice
	InitialPurpose                     string
	OutreachNote                       string
	Locks                              Locks
	Profiles                           map[string]PurposeProfile
	Courses                            []Course
	Selected                           string
	FollowUps                          []FollowUp
	FollowUpRequired                   bool
	FY                                 string
	InitialIntervention                string
	Priorities                         []string
	ActivityType, RecommendationReason string
	Facilitators                       []Choice
	TopLabel                           string
	Stale                              bool
	Responsible, OwnerName             string
	VisitIsYours                       bool
}

// openingActivityType is the drawer's recommended_activity_type.
func openingActivityType(kind, ssaStatus string, outreach bool) string {
	chosen := kind
	if chosen == "" {
		chosen = "school_visit"
	}
	allowed := schoolActivityTypes
	if outreach {
		allowed = outreachTypes
		if !slices.Contains(outreachTypes, chosen) {
			chosen = "donor_visit"
		}
	}
	if !slices.Contains(allowed, chosen) {
		chosen = "school_visit"
	}
	if !outreach && ssaStatus != "done" && !slices.Contains(ssaCollectionTypes, chosen) {
		chosen = "baseline_ssa_visit"
	}
	return chosen
}

// fallbackPurpose is normalise_visit_purpose with no purpose given.
func fallbackPurpose(kind string) string {
	if purpose, ok := fallbackPurposes[kind]; ok {
		return purpose
	}
	return "ssa_support"
}

// yearLocks is the drawer's per-year locks on a client school's support visit.
func yearLocks(years []yearUse, hasUniversal bool) Locks {
	locks := Locks{Visit: map[string]map[string]string{}, Training: map[string]string{}}
	for _, year := range years {
		if !year.used {
			continue
		}
		for _, purpose := range supportPool {
			if slices.Contains(TrainingPurposes, purpose) && hasUniversal {
				locks.Training[year.year] = year.reason
				continue
			}
			if locks.Visit[purpose] == nil {
				locks.Visit[purpose] = map[string]string{}
				locks.Order = append(locks.Order, purpose)
			}
			locks.Visit[purpose][year.year] = year.reason
		}
	}
	for _, purpose := range locks.Order {
		held := locks.Visit[purpose]
		if len(years) > 0 && len(held) == len(years) {
			locks.EveryYear = append(locks.EveryYear, purpose)
		}
		for _, year := range years {
			if reason, ok := held[year.year]; ok {
				if !slices.Contains(locks.Reasons, reason) {
					locks.Reasons = append(locks.Reasons, reason)
				}
				break
			}
		}
	}
	locks.AllEveryYear = len(locks.Order) > 0 && len(locks.EveryYear) == len(locks.Order)
	locks.TrainingEveryYear = len(years) > 0 && len(locks.Training) == len(years)
	return locks
}

// purposeProfiles is _purpose_workflow_profiles: the one standard item that
// prices each purpose, else the one item, else no price.
func purposeProfiles(items []profileItem, purposes []Choice, costed func(string) string) map[string]PurposeProfile {
	kinds := schoolprofile.GateRules().Core.PurposeActivityTypes
	profiles := make(map[string]PurposeProfile, len(purposes))
	for _, purpose := range purposes {
		kind, ok := kinds[purpose.Value]
		if !ok {
			kind = "school_visit"
		}
		var same, standard []profileItem
		for _, item := range items {
			if item.kind == costed(kind) {
				same = append(same, item)
				if item.standard {
					standard = append(standard, item)
				}
			}
		}
		var priced *profileItem
		switch {
		case len(standard) == 1:
			priced = &standard[0]
		case len(same) == 1:
			priced = &same[0]
		}
		if priced == nil {
			profiles[purpose.Value] = PurposeProfile{UnavailableReason: noCatalogueCost}
			continue
		}
		profiles[purpose.Value] = PurposeProfile{Schedulable: true, RequiresParticipants: slices.Contains(participantModes, priced.mode)}
	}
	return profiles
}

// existingSummary joins what the school has: "a, b and c".
func existingSummary(parts []string) string {
	if len(parts) == 1 {
		return parts[0]
	}
	return strings.Join(parts[:len(parts)-1], ", ") + " and " + parts[len(parts)-1]
}

func plural(n int, word string) string {
	if n == 1 {
		return "1 " + word
	}
	return strconv.Itoa(n) + " " + word + "s"
}

func countParts(counts schoolplanning.Counts, noun string) []string {
	var parts []string
	if counts.Planned > 0 {
		parts = append(parts, plural(counts.Planned, "planned "+noun))
	}
	if counts.Awaiting > 0 {
		parts = append(parts, plural(counts.Awaiting, noun)+" awaiting verification")
	}
	if counts.Verified > 0 {
		parts = append(parts, plural(counts.Verified, "completed "+noun))
	}
	return parts
}

// planLabel is one existing plan's line.
func planLabel(label string, day *time.Time) string {
	if day == nil {
		return label
	}
	return label + " · " + day.Format("2 Jan 2006")
}

// existingPlans is existing_plan_warning over the planning horizon.
func (s *Service) existingPlans(ctx context.Context, p auth.Principal, school School, fy string) (*ExistingPlans, error) {
	now := s.now()
	operational, err := strconv.Atoi(fy)
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading the year: %w", err)
	}
	horizon, err := schoolplanning.Horizon(ctx, s.db, p.Country, fy, operational, schooldirectory.FYOptions(now), now)
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading the planning horizon: %w", err)
	}
	badges, counted, err := schoolplanning.ForSchools(ctx, s.db, []string{school.ID}, horizon)
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading the school's plans: %w", err)
	}
	badge := badges[school.ID]
	if badge == nil {
		return nil, nil
	}
	parts := append(countParts(badge.Visits, "visit"), countParts(badge.Trainings, "training")...)
	if len(parts) == 0 {
		return nil, nil
	}
	rows := make([]schoolplanning.Counted, 0, len(counted))
	for _, row := range counted {
		if row.Kind == schoolplanning.KindVisits || row.Kind == schoolplanning.KindTrainings {
			rows = append(rows, row)
		}
	}
	sort.SliceStable(rows, func(i, j int) bool {
		a, b := rows[i].Day, rows[j].Day
		if (a == nil) != (b == nil) {
			return b == nil
		}
		return a != nil && a.Before(*b)
	})
	labels := schoolprofile.ActivityTypeLabels()
	plans := make([]ExistingPlan, len(rows))
	for i, row := range rows {
		label, ok := labels[row.ActivityType]
		if !ok {
			label = row.ActivityType
		}
		status, tone := bucketWords(row.Bucket)
		plans[i] = ExistingPlan{Label: planLabel(label, row.Day), Status: status, Tone: tone}
	}
	return &ExistingPlans{
		Message: "This school already has " + existingSummary(parts) + ". You may continue if this is another required visit, follow-up, intervention, or project activity.",
		Plans:   plans,
	}, nil
}

// bucketWords is _BUCKET_LABELS and _BUCKET_TONES.
func bucketWords(bucket string) (string, string) {
	switch bucket {
	case "planned":
		return "Planned", "planned"
	case "awaiting_verification":
		return "Awaiting Verification", "awaiting"
	case "verified":
		return "Complete", "verified"
	}
	return "Needs Replanning", "replan"
}

// partnerNotice is what the drawer says of a Partner holding the school.
func (s *Service) partnerNotice(ctx context.Context, school School, fy string) (*PlanNote, error) {
	rows, err := s.db.Query(ctx, `SELECT pa.partner_id, COALESCE(p.name, '')
FROM partner_assignment pa JOIN partner p ON p.id = pa.partner_id LEFT JOIN activity sa ON sa.id = pa.scheduled_activity_id
WHERE pa.school_id = $1 AND pa.status IS DISTINCT FROM 'returned_to_staff'
  AND (pa.scheduled_activity_id IS NULL OR (sa.deleted_at IS NULL
    AND NOT COALESCE(sa.status = ANY($2), false) AND sa.fy >= $3))
ORDER BY pa.created_at`, school.ID, []string{"cancelled", "rejected", "deferred", "closed"}, fy)
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading the school's partners: %w", err)
	}
	type holder struct{ id, name string }
	held, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (holder, error) {
		var h holder
		err := row.Scan(&h.id, &h.name)
		return h, err
	})
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading a partner: %w", err)
	}
	if len(held) == 0 {
		return nil, nil
	}
	var ids, names []string
	for _, h := range held {
		if !slices.Contains(ids, h.id) {
			ids, names = append(ids, h.id), append(names, h.name)
		}
	}
	title := "This school is supported by " + names[len(names)-1] + "."
	if len(ids) > 1 {
		title = "This school is supported by more than one Partner (" + strings.Join(names, " / ") + ")."
	}
	plans, err := s.partnerPlans(ctx, school.ID, fy)
	if err != nil {
		return nil, err
	}
	if len(plans) == 0 {
		return &PlanNote{Text: title, Tone: "warning"}, nil
	}
	return &PlanNote{Title: title, Text: strings.Join(plans, " "), Tone: "warning"}, nil
}

func (s *Service) partnerPlans(ctx context.Context, schoolID, fy string) ([]string, error) {
	rows, err := s.db.Query(ctx, `SELECT COALESCE(activity_name_snapshot, ''), activity_type, status, planned_date FROM activity
WHERE school_id = $1 AND fy = $2 AND deleted_at IS NULL AND delivery_type = 'partner' AND status = ANY($3)
ORDER BY planned_date, created_at LIMIT $4`, schoolID, fy, schoolplanning.Buckets("planned"), maxPartnerPlans)
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading the partner's plans: %w", err)
	}
	labels := schoolprofile.ActivityTypeLabels()
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (string, error) {
		var name, kind, status string
		var day *time.Time
		if err := row.Scan(&name, &kind, &status, &day); err != nil {
			return "", err
		}
		if name == "" {
			name = labels[kind]
		}
		when := "Not dated"
		if day != nil {
			when = day.Format("2 January 2006")
		}
		return "Existing Partner activity: " + name + " " + strings.ToLower(coreschools.ActivityStatusLabel(status)) + " for " + when + ".", nil
	})
}

// responsibleName is visit_owner_for's name: the school's owner at the
// person's own school, otherwise the person going.
func (s *Service) responsibleName(ctx context.Context, p auth.Principal, school School, own bool) (string, error) {
	actor := p.Name
	if actor == "" {
		actor = "You"
	}
	if !own {
		return actor, nil
	}
	var name *string
	err := s.db.QueryRow(ctx, `SELECT u.name FROM staff_school_assignment a
JOIN staff_profile sp ON sp.id = a.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE a.school_id = $1 ORDER BY a.created_at LIMIT 1`, school.ID).Scan(&name)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("coreforms: reading the school's owner: %w", err)
	}
	if err == nil && name != nil && *name != "" {
		return *name, nil
	}
	owners, err := s.ownerIDs(ctx, school)
	if err != nil {
		return "", err
	}
	if len(owners) == 0 {
		return actor, nil
	}
	var ownerName, raw *string
	err = s.db.QueryRow(ctx, `SELECT u.name, (SELECT account_owner_name_raw FROM school WHERE id = $2)
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1)) ORDER BY sp.id LIMIT 1`, owners, school.ID).Scan(&ownerName, &raw)
	if errors.Is(err, pgx.ErrNoRows) {
		return actor, nil
	}
	if err != nil {
		return "", fmt.Errorf("coreforms: reading the portfolio owner: %w", err)
	}
	switch {
	case ownerName != nil && *ownerName != "":
		return *ownerName, nil
	case raw != nil && *raw != "":
		return *raw, nil
	}
	return "Staff owner", nil
}

func (s *Service) visitLocks(ctx context.Context, p auth.Principal, school School, fy string) (Locks, error) {
	gate, err := s.gateOf(ctx, school, fy)
	if err != nil {
		return Locks{}, err
	}
	if gate.Rule != "client" {
		return yearLocks(nil, false), nil
	}
	uses := []yearUse{{year: fy, used: !gate.StaffCanSchedule, reason: gate.StaffReason}}
	now := s.now().In(schoolplanning.Nairobi)
	upcoming, err := workplan.NextOpenFY(ctx, s.db, p.Country, now, schoolplanning.Nairobi)
	if err != nil {
		return Locks{}, fmt.Errorf("coreforms: reading the next open year: %w", err)
	}
	if upcoming != "" && upcoming != fy {
		next, err := visitgate.Of(ctx, s.db, s.gates, school.gate(), upcoming, fy)
		if err != nil {
			return Locks{}, fmt.Errorf("coreforms: reading next year's visit rule: %w", err)
		}
		uses = append(uses, yearUse{year: upcoming, used: !next.StaffCanSchedule, reason: next.StaffReason})
	}
	var universal bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity_catalogue_item WHERE is_training_course AND universal_training)`).Scan(&universal); err != nil {
		return Locks{}, fmt.Errorf("coreforms: reading the universal trainings: %w", err)
	}
	return yearLocks(uses, universal), nil
}

func (s *Service) readProfiles(ctx context.Context, day time.Time) (map[string]PurposeProfile, error) {
	rows, err := s.db.Query(ctx, `SELECT COALESCE(workflow_kind, ''), stable_code, COALESCE(participant_mode, ''), standard_support
FROM activity_catalogue_item
WHERE status = 'active' AND (effective_from IS NULL OR effective_from <= $1) AND (effective_to IS NULL OR effective_to >= $1)
ORDER BY stable_code`, day.Format(time.DateOnly))
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading the purpose profiles: %w", err)
	}
	items, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (profileItem, error) {
		var item profileItem
		err := row.Scan(&item.kind, &item.code, &item.mode, &item.standard)
		return item, err
	})
	if err != nil {
		return nil, fmt.Errorf("coreforms: reading a purpose profile: %w", err)
	}
	return purposeProfiles(items, staffPurposes, activities.CostedKind), nil
}

// ScheduleFor opens a school's Schedule Visit form. Key is its record id or
// School ID. Nothing is written.
func (s *Service) ScheduleFor(ctx context.Context, p auth.Principal, key string, interventions [][2]string) (ScheduleForm, error) {
	if p.InActingAppointment {
		return ScheduleForm{}, &Refusal{Message: actingRefused}
	}
	if !slices.Contains(planningPageRoles, p.ActiveRole) {
		return ScheduleForm{}, &Refusal{Message: PlanningDenied}
	}
	if p.ActiveRole == roleAdmin {
		return ScheduleForm{}, &Refusal{Message: AdminNotPlanner}
	}
	school, err := s.schoolByKey(ctx, key)
	if err != nil {
		return ScheduleForm{}, err
	}
	if err := s.mayVisit(ctx, p, school); err != nil {
		return ScheduleForm{}, err
	}
	now := s.now()
	fy := schooldirectory.OperationalFY(now)
	names := namesOf(interventions)
	day := s.localDay()
	typeLabels := schoolprofile.ActivityTypeLabels()
	outreach := slices.Contains(s.gates.OutreachOnlyTypes, school.Type)
	form := ScheduleForm{School: school, FY: fy}

	if form.Locks, err = s.visitLocks(ctx, p, school, fy); err != nil {
		return ScheduleForm{}, err
	}
	need, err := activities.SchoolNeed(ctx, s.db, school.ID, school.ClusterID, now)
	if err != nil {
		return ScheduleForm{}, fmt.Errorf("coreforms: reading the school's need: %w", err)
	}
	form.Priorities, form.Stale = need.Priorities, need.Stale
	if len(need.Priorities) > 0 {
		form.TopLabel = names[need.Priorities[0]]
	}
	recommendation, ssaLine, err := s.recommendation(ctx, school, fy, day, need, typeLabels)
	if err != nil {
		return ScheduleForm{}, err
	}
	var first *Suggestion
	if !outreach {
		first = recommendation.First
	}
	kind := ""
	if first != nil {
		kind = first.WorkflowKind
		form.Selected, form.RecommendationReason = first.ID, first.Reason
	}
	form.ActivityType = openingActivityType(kind, school.ssaStatus, outreach)
	form.InitialIntervention = openingFocus(need.Priorities, first)
	form.Purposes, form.InitialPurpose = purposeChoices(form.Locks, outreach, fallbackPurpose(form.ActivityType))
	if err := s.fillChoices(ctx, p, &form, outreach, names, day, typeLabels); err != nil {
		return ScheduleForm{}, err
	}
	if err := s.fillResponsible(ctx, p, &form); err != nil {
		return ScheduleForm{}, err
	}
	notice, err := s.partnerNotice(ctx, school, fy)
	if err != nil {
		return ScheduleForm{}, err
	}
	form.Lead = leadItems(notice, form.OwnerName, recommendation, need, names, ssaLine)
	return form, nil
}

// fillChoices reads what the form offers beyond its recommendation.
func (s *Service) fillChoices(ctx context.Context, p auth.Principal, form *ScheduleForm, outreach bool, names map[string]string, day time.Time, typeLabels map[string]string) error {
	var err error
	school := form.School
	if outreach {
		label, ok := s.gates.SchoolTypeLabels[school.Type]
		if !ok {
			label = "Programme"
		}
		form.OutreachNote = school.Name + " is a " + label + " school: it receives no training or assessment, and is planned only for a Donor Visit or a Content/Story Collection visit."
	} else {
		if form.Courses, err = s.courses(ctx, names, day); err != nil {
			return err
		}
		if form.FollowUps, err = s.followUps(ctx, school, form.FY, names, typeLabels); err != nil {
			return err
		}
	}
	if form.Profiles, err = s.readProfiles(ctx, day); err != nil {
		return err
	}
	if form.FollowUpRequired, err = activities.FollowUpNeedsTraining(ctx, s.db, p.Country, form.FY); err != nil {
		return fmt.Errorf("coreforms: reading the year's follow-up rule: %w", err)
	}
	if form.Facilitators, err = s.facilitators(ctx); err != nil {
		return err
	}
	form.Existing, err = s.existingPlans(ctx, p, school, form.FY)
	return err
}

// fillResponsible is who the visit belongs to, and who must approve it.
func (s *Service) fillResponsible(ctx context.Context, p auth.Principal, form *ScheduleForm) error {
	var err error
	if p.ActiveRole == roleAccountant {
		if form.OwnerName, err = s.approvalOwner(ctx, form.School, p.UserID, p.StaffProfileID); err != nil {
			return err
		}
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return fmt.Errorf("coreforms: resolving the scope: %w", err)
	}
	own := slices.Contains(scope.OwnSchoolIDs, form.School.ID)
	form.VisitIsYours = form.OwnerName == "" && !own
	form.Responsible, err = s.responsibleName(ctx, p, form.School, own && form.OwnerName == "")
	return err
}

// recommendation reads the catalogue's answer and the line dating the SSA.
func (s *Service) recommendation(ctx context.Context, school School, fy string, day time.Time, need activities.NeedSummary, typeLabels map[string]string) (Recommendation, string, error) {
	items, mappings, err := s.readCatalogue(ctx, school.ID, fy, day, s.now())
	if err != nil {
		return Recommendation{}, "", err
	}
	source, err := s.latestSource(ctx, school.ID, typeLabels)
	if err != nil {
		return Recommendation{}, "", err
	}
	var date time.Time
	err = s.db.QueryRow(ctx, `SELECT date_of_ssa FROM ssa_record
WHERE school_id = $1 AND deleted_at IS NULL AND verification_status = 'confirmed'
ORDER BY date_of_ssa DESC, created_at DESC LIMIT 1`, school.ID).Scan(&date)
	hasRecord := err == nil
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return Recommendation{}, "", fmt.Errorf("coreforms: reading the latest SSA: %w", err)
	}
	ranked := make([]rankedSSA, len(need.Ranked))
	for i, row := range need.Ranked {
		ranked[i] = rankedSSA{Need: Need{Code: row.Intervention, Label: row.Label, Score: row.Score}, Band: row.Band}
	}
	line := ""
	if hasRecord {
		line = projectspage.DjangoDateTime(date.In(schoolplanning.Nairobi)) + " · Confirmed"
	}
	return recommendFrom(recommendInput{items: items, mappings: mappings, ranked: ranked, hasRecord: hasRecord, source: source}), line, nil
}

func openingFocus(priorities []string, first *Suggestion) string {
	if len(priorities) > 0 {
		return priorities[0]
	}
	if first != nil {
		return first.Target
	}
	return ""
}

// purposeChoices is the Purpose of visit list and what it opens on.
func purposeChoices(locks Locks, outreach bool, recommended string) ([]PurposeChoice, string) {
	var choices []PurposeChoice
	for _, purpose := range staffPurposes {
		if outreach && !slices.Contains(outreachPurposes, purpose.Value) {
			continue
		}
		choice := PurposeChoice{Value: purpose.Value, Label: purpose.Label}
		if slices.Contains(locks.EveryYear, purpose.Value) {
			choice.Disabled, choice.Label = true, purpose.Label+" — not available this year"
		}
		choices = append(choices, choice)
	}
	if outreach {
		return choices, "donor_visit"
	}
	if slices.Contains(locks.EveryYear, recommended) {
		return choices, ""
	}
	return choices, recommended
}

// leadItems is what the drawer draws above Purpose of visit, in order.
func leadItems(notice *PlanNote, owner string, rec Recommendation, need activities.NeedSummary, names map[string]string, ssaLine string) []LeadItem {
	var items []LeadItem
	if notice != nil {
		items = append(items, LeadItem{Note: notice})
	}
	if owner != "" {
		items = append(items, LeadItem{Note: &PlanNote{Tone: "warning",
			Text: "This school is in " + owner + "’s portfolio. " + owner + " approves this visit before it lands on your plan and budget."}})
	}
	if !rec.HasSSA {
		return append(items, LeadItem{Note: &PlanNote{Title: "Top priority: complete SSA",
			Text: "This school has no applicable verified SSA, so no intervention score is shown.", Tone: "warning"}})
	}
	lines := recommendedLines(need.Ranked, names)
	if len(lines) > 0 {
		items = append(items, LeadItem{Heading: "Recommended interventions"})
		for i := range lines {
			items = append(items, LeadItem{Line: &lines[i]})
		}
		items = append(items, LeadItem{Text: ssaLine})
	} else {
		top := rec.Priority
		items = append(items, LeadItem{Heading: "SSA priority"},
			LeadItem{Text: top.Label + " (" + pyFloat(top.Score) + "/10 · " + top.Band + ")"}, LeadItem{Text: ssaLine})
	}
	if rec.Unmet != nil {
		items = append(items, LeadItem{Note: unmetNote(rec.Unmet)})
	}
	return items
}

// recommendedLines is the drawer's "performing poorly" list: of the four most
// urgent, up to three that are not Strong.
func recommendedLines(ranked []activities.RankedNeed, names map[string]string) []LeadLine {
	var lines []LeadLine
	for _, row := range ranked[:min(recommendedCount, len(ranked))] {
		if row.Band == "Strong" || row.Band == "No SSA" {
			continue
		}
		label, ok := names[row.Intervention]
		if !ok {
			label = row.Intervention
		}
		lines = append(lines, LeadLine{Label: label, Value: "(" + pyFloat(row.Score) + "/10 · " + row.Band + ")", Tone: "danger"})
		if len(lines) == 3 {
			break
		}
	}
	return lines
}

func unmetNote(unmet *UnmetNeed) *PlanNote {
	first := "The trainings listed address lower-ranked needs."
	if !unmet.StandardAvailable {
		first += " No standard support is available for it here either."
	}
	body := []string{first}
	if unmet.StandardAvailable {
		body = append(body, "To act on "+unmet.Label+" here, choose a purpose below and set Focus intervention to it. No Project required.")
	}
	var groups []string
	for _, group := range unmet.Groups {
		reason := strings.ToUpper(group.Reason[:1]) + group.Reason[1:]
		groups = append(groups, "· "+reason+": "+strings.Join(group.Names, ", ")+" — "+group.Route+".")
	}
	if len(groups) > 0 {
		body = append(body, strings.Join(groups, " "))
	}
	return &PlanNote{Title: "Top need not covered by the trainings below", Text: strings.Join(body, " "), Tone: "warning"}
}
