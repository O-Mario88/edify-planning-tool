package ssadecision

import (
	"strings"
	"testing"
)

func baseCatalogue() []CatalogueOption {
	return []CatalogueOption{
		{ID: "cat-lead", StableCode: "LEAD-101", DisplayName: "School Leadership Improvement Training", ActivityType: "training", Intervention: "leadership", StaffDeliveryAllowed: true, PartnerDeliveryAllowed: true},
		{ID: "cat-fin", StableCode: "FIN-101", DisplayName: "Financial Health & Sustainability Coaching", ActivityType: "training", Intervention: "financial_health", StaffDeliveryAllowed: true, PartnerDeliveryAllowed: true},
		{ID: "cat-teach", StableCode: "TCH-101", DisplayName: "Teaching Environment Coaching Visit", ActivityType: "school_visit", Intervention: "teaching_environment", StaffDeliveryAllowed: true, PartnerDeliveryAllowed: false},
	}
}

func fullScores(def float64, overrides map[string]float64) map[string]float64 {
	m := map[string]float64{}
	for _, iv := range CanonicalInterventions {
		m[iv[0]] = def
	}
	for k, v := range overrides {
		m[k] = v
	}
	return m
}

func TestSSADecisionAll10ControlledScenarios(t *testing.T) {
	// 1. Severe Leadership weakness (< 4.0)
	t.Run("1_severe_leadership_weakness", func(t *testing.T) {
		rep := Evaluate(SchoolDecisionInput{
			SchoolID: "s1", EdifySchoolID: "UG-001", SchoolName: "Hope Primary", SchoolType: "client", CurrentFY: "2027",
			HasCurrentConfirmedSSA: true, CurrentSSADate: "2026-10-15", CurrentSSAAverage: 5.8,
			CurrentScores: fullScores(6.5, map[string]float64{"leadership": 2.4}),
			Catalogue:     baseCatalogue(),
		})
		if rep.RiskPriority != "critical" || len(rep.Recommendations) == 0 {
			t.Fatalf("expected critical risk + recommendation, got %+v", rep)
		}
		top := rep.Recommendations[0]
		if top.RecommendedIntervention != "leadership" || top.CatalogueItemID != "cat-lead" || top.Priority != "critical" {
			t.Fatalf("unexpected top rec: %+v", top)
		}
		if top.PriorityReason == "" || top.VerifiedEvidence == "" || top.RelevanceReason == "" || top.OutcomeToMonitor == "" || top.ConfidenceAndLimitations == "" {
			t.Fatalf("missing explainability fields: %+v", top)
		}
	})

	// 2. Severe Financial Health weakness
	t.Run("2_severe_financial_health_weakness", func(t *testing.T) {
		rep := Evaluate(SchoolDecisionInput{
			SchoolID: "s2", SchoolType: "client", CurrentFY: "2027",
			HasCurrentConfirmedSSA: true, CurrentSSADate: "2026-10-15", CurrentSSAAverage: 5.5,
			CurrentScores: fullScores(6.2, map[string]float64{"financial_health": 2.1}),
			Catalogue:     baseCatalogue(),
		})
		if rep.Recommendations[0].RecommendedIntervention != "financial_health" || rep.Recommendations[0].CatalogueItemID != "cat-fin" {
			t.Fatalf("expected financial_health rec, got %+v", rep.Recommendations[0])
		}
	})

	// 3. Strong overall SSA (>= 7.5) but ONE critical intervention (< 4.0)
	t.Run("3_strong_overall_with_one_critical_intervention", func(t *testing.T) {
		rep := Evaluate(SchoolDecisionInput{
			SchoolID: "s3", SchoolType: "client", CurrentFY: "2027",
			HasCurrentConfirmedSSA: true, CurrentSSADate: "2026-10-15", CurrentSSAAverage: 7.9,
			CurrentScores: fullScores(8.6, map[string]float64{"leadership": 3.1}),
			Catalogue:     baseCatalogue(),
		})
		if rep.RiskPriority != "critical" {
			t.Fatalf("high overall average must not mask single critical intervention: got %s", rep.RiskPriority)
		}
		if len(rep.Recommendations) != 1 || rep.Recommendations[0].RecommendedIntervention != "leadership" {
			t.Fatalf("expected exact 1 critical leadership rec, got %+v", rep.Recommendations)
		}
	})

	// 4. Missing current-FY confirmed SSA -> recommend SSA collection, never invent scores
	t.Run("4_missing_current_fy_ssa", func(t *testing.T) {
		rep := Evaluate(SchoolDecisionInput{
			SchoolID: "s4", SchoolType: "client", CurrentFY: "2027",
			HasCurrentConfirmedSSA: false,
		})
		if rep.RiskPriority != "unassessed" || rep.CurrentSSAAverage != nil {
			t.Fatalf("expected unassessed with nil average, got %+v", rep)
		}
		if len(rep.Recommendations) == 0 || rep.Recommendations[0].Category != "ssa_assessment" {
			t.Fatalf("expected ssa_assessment recommendation, got %+v", rep.Recommendations)
		}
	})

	// 5. Conflicting/unconfirmed pending SSA records -> excluded from verified diagnosis
	t.Run("5_pending_unconfirmed_ssa_excluded", func(t *testing.T) {
		rep := Evaluate(SchoolDecisionInput{
			SchoolID: "s5", SchoolType: "client", CurrentFY: "2027",
			HasCurrentConfirmedSSA: false, PendingSSACount: 2,
		})
		if rep.PendingSSACount != 2 || !strings.Contains(rep.Recommendations[0].RecommendedActivity, "Verification") {
			t.Fatalf("expected pending verification prompt, got %+v", rep)
		}
	})

	// 6. Recently completed/verified training -> duplicate suppressed
	t.Run("6_recently_completed_training_suppressed", func(t *testing.T) {
		rep := Evaluate(SchoolDecisionInput{
			SchoolID: "s6", SchoolType: "client", CurrentFY: "2027",
			HasCurrentConfirmedSSA: true, CurrentSSADate: "2026-10-15", CurrentSSAAverage: 7.5,
			CurrentScores: fullScores(8.2, map[string]float64{"leadership": 3.5}),
			Catalogue:     baseCatalogue(),
			ExistingActivities: []ExistingActivity{
				{ID: "act-done", CatalogueItemID: "cat-lead", Intervention: "leadership", Status: "ia_verified", FY: "2027"},
			},
		})
		if len(rep.Recommendations) != 0 || len(rep.SuppressedItems) != 1 {
			t.Fatalf("expected leadership rec suppressed as already verified: recs=%d sup=%d", len(rep.Recommendations), len(rep.SuppressedItems))
		}
	})

	// 7. Already scheduled support -> duplicate suppressed
	t.Run("7_already_scheduled_support_suppressed", func(t *testing.T) {
		rep := Evaluate(SchoolDecisionInput{
			SchoolID: "s7", SchoolType: "client", CurrentFY: "2027",
			HasCurrentConfirmedSSA: true, CurrentSSADate: "2026-10-15", CurrentSSAAverage: 7.5,
			CurrentScores: fullScores(8.2, map[string]float64{"financial_health": 3.2}),
			Catalogue:     baseCatalogue(),
			ExistingActivities: []ExistingActivity{
				{ID: "act-plan", CatalogueItemID: "cat-fin", Intervention: "financial_health", Status: "scheduled", PlannedDate: "2026-11-30", FY: "2027"},
			},
		})
		if len(rep.Recommendations) != 0 || len(rep.SuppressedItems) != 1 || !strings.Contains(rep.SuppressedItems[0].SuppressedReason, "Already scheduled") {
			t.Fatalf("expected scheduled duplicate suppressed, got %+v", rep.SuppressedItems)
		}
	})

	// 8. Staff capacity constraint -> recommends partner delivery when allowed
	t.Run("8_staff_capacity_constraint_suggests_partner", func(t *testing.T) {
		rep := Evaluate(SchoolDecisionInput{
			SchoolID: "s8", SchoolType: "client", CurrentFY: "2027",
			HasCurrentConfirmedSSA: true, CurrentSSADate: "2026-10-15", CurrentSSAAverage: 6.0,
			CurrentScores:       fullScores(7.5, map[string]float64{"leadership": 3.0}),
			Catalogue:           baseCatalogue(),
			StaffWeeklyLoad:     14,
			StaffWeeklyCapacity: 12,
		})
		if rep.Recommendations[0].DeliverySuggestion != "partner" {
			t.Fatalf("expected partner delivery suggestion under staff overload, got %+v", rep.Recommendations[0])
		}
	})

	// 9. Core School package obligation not yet fulfilled
	t.Run("9_core_package_obligation_surfaced", func(t *testing.T) {
		rep := Evaluate(SchoolDecisionInput{
			SchoolID: "s9", SchoolType: "core", CurrentFY: "2027",
			HasCurrentConfirmedSSA: true, CurrentSSADate: "2026-10-15", CurrentSSAAverage: 8.2,
			CurrentScores:        fullScores(8.2, nil),
			CorePackageCompleted: false,
		})
		if len(rep.Recommendations) != 1 || rep.Recommendations[0].Category != "core_package" {
			t.Fatalf("expected core_package obligation recommendation, got %+v", rep.Recommendations)
		}
	})

	// 10. Improving vs declining comparable FY SSA trajectory
	t.Run("10_improving_vs_declining_comparable_ssa", func(t *testing.T) {
		rep := Evaluate(SchoolDecisionInput{
			SchoolID: "s10", SchoolType: "client", CurrentFY: "2027",
			HasCurrentConfirmedSSA: true, CurrentSSADate: "2026-10-20", CurrentSSAAverage: 6.2,
			CurrentScores:           fullScores(7.2, map[string]float64{"leadership": 3.5, "enrolment": 6.5}),
			HasPreviousConfirmedSSA: true, PreviousSSAFY: "2026", PreviousSSAAverage: 6.8,
			PreviousScores: fullScores(7.0, map[string]float64{"leadership": 5.5, "enrolment": 5.0}),
			Catalogue:      baseCatalogue(),
		})
		if rep.OverallDelta == nil || *rep.OverallDelta != -0.6 {
			t.Fatalf("expected overall delta -0.6, got %v", rep.OverallDelta)
		}
		if !strings.Contains(rep.Recommendations[0].PriorityReason, "Declined 2.00 pts") {
			t.Fatalf("expected exact decline explanation, got %q", rep.Recommendations[0].PriorityReason)
		}
	})
}
