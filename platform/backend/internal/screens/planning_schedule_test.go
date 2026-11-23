package screens

import (
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreforms"
)

func scheduleForm() coreforms.ScheduleForm {
	return coreforms.ScheduleForm{
		School: coreforms.School{Code: "1006", Name: "Goma"}, FY: "2027", TopLabel: "Teacher's Environment",
		Purposes:       []coreforms.PurposeChoice{{Value: "ssa_support", Label: "SSA Support"}, {Value: "training_follow_up", Label: "Training Follow Up — not available this year", Disabled: true}},
		InitialPurpose: "ssa_support", ActivityType: "school_visit", RecommendationReason: "Why", Selected: "item1",
		InitialIntervention: "leadership", Priorities: []string{"leadership"}, FollowUpRequired: true, Responsible: "Paul N.",
		Courses:      []coreforms.Course{{ID: "c1", Label: "Budgeting", Code: "B", Category: "Finance", Indicator: "Fees", Intervention: "financial_health", InterventionLabel: "Financial Health", Universal: true, CertifiedAllowed: true, PriorityTitles: []string{"Accountants"}}},
		FollowUps:    []coreforms.FollowUp{{ID: "a1", Label: "Budgeting · 9 Oct", InterventionLabel: "Financial Health"}},
		Facilitators: []coreforms.Choice{{Value: "p1", Label: "Build Africa"}},
		Profiles:     map[string]coreforms.PurposeProfile{"ssa_support": {Schedulable: true}, "social_visit": {UnavailableReason: "No price"}},
		Locks: coreforms.Locks{Visit: map[string]map[string]string{"training_follow_up": {"2027": "Used."}}, Order: []string{"training_follow_up"},
			EveryYear: []string{"training_follow_up"}, Reasons: []string{"Used."}, Training: map[string]string{"2027": "Used."}, TrainingEveryYear: true, AllEveryYear: true},
		Lead: []coreforms.LeadItem{{Heading: "Recommended interventions"}, {Line: &coreforms.LeadLine{Label: "Leadership", Value: "(4.0/10 · Critical)", Tone: "danger"}},
			{Text: "Nov. 9, 2026 · Confirmed"}, {Note: &coreforms.PlanNote{Title: "T", Text: "B", Tone: "warning"}}},
		Existing: &coreforms.ExistingPlans{Message: "Has plans.", Plans: []coreforms.ExistingPlan{{Label: "School Visit · 9 Nov 2026", Status: "Planned", Tone: "planned"}}},
	}
}

func TestTheScheduleDrawerCarriesTheRealChoices(t *testing.T) {
	drawer := planningScheduleDrawer(scheduleForm())
	if drawer.GetKind() != "schedule" || drawer.GetTitle() != "Schedule visit for Goma" || drawer.GetSubmitLabel() != "Schedule visit" {
		t.Fatalf("head: %v", drawer)
	}
	if got := drawer.GetPurposes()[1]; !got.GetDisabled() || got.GetValue() != "training_follow_up" {
		t.Fatalf("purpose: %v", got)
	}
	if len(drawer.GetInterventions()) != len(ssaInterventionChoices) || drawer.GetInterventions()[0].GetValue() != "christlike_behaviour" {
		t.Fatalf("interventions: %v", drawer.GetInterventions())
	}
	training := drawer.GetTrainings()[0]
	if training.GetSsaIntervention() != "financial_health" || !training.GetUniversal() || !training.GetCertifiedAgencyDeliveryAllowed() || training.GetPriorityTitles()[0] != "Accountants" {
		t.Fatalf("training: %v", training)
	}
	if drawer.GetFacilitators()[0].GetValue() != "" || drawer.GetFacilitators()[0].GetLabel() != "Staff" {
		t.Fatalf("facilitators: %v", drawer.GetFacilitators())
	}
	if drawer.GetHidden()["school_id"] != "1006" || drawer.GetHidden()["require_catalogue"] != "yes" {
		t.Fatalf("hidden: %v", drawer.GetHidden())
	}
	if drawer.GetVisitLocks()["training_follow_up"].GetByYear()["2027"] != "Used." || drawer.GetTrainingLocks()["2027"] != "Used." || !drawer.GetTrainingLockedEveryYear() {
		t.Fatalf("locks: %v", drawer.GetVisitLocks())
	}
	if p := drawer.GetProfiles()["social_visit"]; p.GetSchedulable() || p.GetUnavailableReason() != "No price" {
		t.Fatalf("profile: %v", p)
	}
}

func TestTheScheduleDrawerSaysWhyInItsOwnWords(t *testing.T) {
	drawer := planningScheduleDrawer(scheduleForm())
	captions := drawer.GetCaptions()
	if captions["lockStatic"] != "Used." || captions["lockTail"] != "Donor, content gathering, invitation and social visits can still be scheduled." {
		t.Fatalf("lock: %q %q", captions["lockStatic"], captions["lockTail"])
	}
	if captions["deviationNamed"] != "The verified SSA does not rank this intervention among the school's priorities (Teacher's Environment is first)." {
		t.Fatalf("deviation: %q", captions["deviationNamed"])
	}
	if captions["responsible"] != "Paul N." || captions["responsibleHelp"] != "Assigned from this school’s portfolio owner." {
		t.Fatalf("responsible: %q %q", captions["responsible"], captions["responsibleHelp"])
	}
	if drawer.GetExistingPlans().GetNote().GetTitle() != "This school already has plans this year" || drawer.GetExistingPlans().GetButtons()["follow-up"] != "Plan as Follow-Up" {
		t.Fatalf("existing: %v", drawer.GetExistingPlans())
	}
	if len(drawer.GetLead()) != 4 || drawer.GetLead()[1].GetLine().GetValue() != "(4.0/10 · Critical)" || drawer.GetLead()[3].GetNote().GetTitle() != "T" {
		t.Fatalf("lead: %v", drawer.GetLead())
	}
}

func TestAVisitAwaitingApprovalAsksWhy(t *testing.T) {
	form := scheduleForm()
	form.OwnerName = "Paul N."
	drawer := planningScheduleDrawer(form)
	if !drawer.GetHasJustification() || drawer.GetCaptions()["justificationPlaceholder"] != "Why you, rather than Paul N.?" || drawer.GetLabels()["visit_justification"] != "Why you need to visit this school" {
		t.Fatalf("justification: %v", drawer.GetCaptions())
	}
	if got := drawer.GetCaptions()["responsibleHelp"]; got != "You are the one visiting. Paul N. is asked to approve, not to go." {
		t.Fatalf("help: %q", got)
	}
	form.OwnerName, form.VisitIsYours = "", true
	if got := planningScheduleDrawer(form).GetCaptions()["responsibleHelp"]; got != "This school is in someone else’s portfolio, so the visit lands on your plan and in your budget." {
		t.Fatalf("yours: %q", got)
	}
}
