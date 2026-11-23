// Package ssadecision implements the Go-owned, PostgreSQL-backed Explainable
// SSA Decision Intelligence Engine (Section 10).
//
// It diagnoses school improvement needs strictly from verified (confirmed) SSA
// assessments across the 8 canonical interventions, compares against previous
// comparable FY SSA records when available, cross-checks active activity
// catalogue mappings, existing scheduled/completed support, Core School
// obligations, and staff capacity, and returns traceable, explainable
// recommendations without ever inventing scores or executing silent writes.
package ssadecision

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// Authenticator authenticates a Bearer Authorization header.
type Authenticator interface {
	Authenticate(ctx context.Context, header string) (auth.Principal, error)
}

// CanonicalInterventions lists the 8 configured Edify SSA interventions.
var CanonicalInterventions = [][2]string{
	{"christlike_behaviour", "Christlike Behaviour"},
	{"exposure_to_word_of_god", "Exposure to the Word of God"},
	{"financial_health", "Financial Health"},
	{"leadership", "Leadership"},
	{"government_requirement", "Government Requirements"},
	{"learning_environment", "Learning Environment"},
	{"teaching_environment", "Teacher's Environment"},
	{"enrolment", "Enrolment"},
}

var interventionLabels = func() map[string]string {
	m := make(map[string]string, len(CanonicalInterventions))
	for _, iv := range CanonicalInterventions {
		m[iv[0]] = iv[1]
	}
	return m
}()

var allowedRoles = map[string]bool{
	"Admin":                 true,
	"CountryDirector":       true,
	"Program Lead":          true,
	"ImpactAssessment":      true,
	"CCEO":                  true,
	"RegionalProgramLead":   true,
	"RegionalVicePresident": true,
	"ProjectCoordinator":    true,
}

// InterventionDiagnosis captures one verified intervention score & trend.
type InterventionDiagnosis struct {
	Code          string   `json:"code"`
	Label         string   `json:"label"`
	Score         float64  `json:"score"`
	PreviousScore *float64 `json:"previous_score,omitempty"`
	Delta         *float64 `json:"delta,omitempty"`
	Severity      string   `json:"severity"` // critical (<4), high (<5.5), moderate (<7), on_track (>=7)
}

// CatalogueOption is an approved activity_catalogue_item mapped to an intervention.
type CatalogueOption struct {
	ID                     string `json:"id"`
	StableCode             string `json:"stable_code"`
	DisplayName            string `json:"display_name"`
	ActivityType           string `json:"activity_type"`
	Intervention           string `json:"intervention"`
	StaffDeliveryAllowed   bool   `json:"staff_delivery_allowed"`
	PartnerDeliveryAllowed bool   `json:"partner_delivery_allowed"`
}

// ExistingActivity summarizes scheduled or completed school support for dedup.
type ExistingActivity struct {
	ID              string `json:"id"`
	ActivityType    string `json:"activity_type"`
	CatalogueItemID string `json:"catalogue_item_id,omitempty"`
	Intervention    string `json:"intervention,omitempty"`
	Status          string `json:"status"`
	PlannedDate     string `json:"planned_date,omitempty"`
	FY              string `json:"fy,omitempty"`
}

// SchoolDecisionInput is the complete authoritative PostgreSQL snapshot for a school.
type SchoolDecisionInput struct {
	SchoolID                string
	EdifySchoolID           string
	SchoolName              string
	District                string
	SchoolType              string
	CurrentFY               string
	HasCurrentConfirmedSSA  bool
	CurrentSSADate          string
	CurrentSSAAverage       float64
	CurrentScores           map[string]float64
	HasPreviousConfirmedSSA bool
	PreviousSSAFY           string
	PreviousSSAAverage      float64
	PreviousScores          map[string]float64
	PendingSSACount         int
	Catalogue               []CatalogueOption
	ExistingActivities      []ExistingActivity
	StaffWeeklyLoad         int
	StaffWeeklyCapacity     int
	CorePackageCompleted    bool
}

// Recommendation is a fully explainable programmatic recommendation answering
// all 7 mandatory Section 10 explainability questions.
type Recommendation struct {
	Priority                 string   `json:"priority"` // critical, high, medium, info
	Category                 string   `json:"category"` // ssa_assessment, intervention_support, core_package
	RecommendedIntervention  string   `json:"recommended_intervention"`
	InterventionLabel        string   `json:"intervention_label"`
	RecommendedActivity      string   `json:"recommended_activity"`
	CatalogueItemID          string   `json:"catalogue_item_id,omitempty"`
	CatalogueStableCode      string   `json:"catalogue_stable_code,omitempty"`
	DeliverySuggestion       string   `json:"delivery_suggestion"`
	PriorityReason           string   `json:"priority_reason"`
	VerifiedEvidence         string   `json:"verified_evidence"`
	RelevanceReason          string   `json:"relevance_reason"`
	OutcomeToMonitor         string   `json:"outcome_to_monitor"`
	ConfidenceAndLimitations string   `json:"confidence_and_limitations"`
	MissingEvidence          []string `json:"missing_evidence,omitempty"`
	SuppressedReason         string   `json:"suppressed_reason,omitempty"`
	Suppressed               bool     `json:"suppressed"`
}

// DecisionReport is the structured JSON output returned by the API.
type DecisionReport struct {
	SchoolID               string                  `json:"school_id"`
	EdifySchoolID          string                  `json:"edify_school_id"`
	SchoolName             string                  `json:"school_name"`
	District               string                  `json:"district"`
	SchoolType             string                  `json:"school_type"`
	FY                     string                  `json:"fy"`
	HasCurrentConfirmedSSA bool                    `json:"has_current_confirmed_ssa"`
	CurrentSSADate         string                  `json:"current_ssa_date,omitempty"`
	CurrentSSAAverage      *float64                `json:"current_ssa_average,omitempty"`
	PreviousSSAFY          string                  `json:"previous_ssa_fy,omitempty"`
	PreviousSSAAverage     *float64                `json:"previous_ssa_average,omitempty"`
	OverallDelta           *float64                `json:"overall_delta,omitempty"`
	PendingSSACount        int                     `json:"pending_ssa_count"`
	RiskPriority           string                  `json:"risk_priority"` // critical, high, moderate, low, unassessed
	StrongestIntervention  *InterventionDiagnosis  `json:"strongest_intervention,omitempty"`
	WeakestIntervention    *InterventionDiagnosis  `json:"weakest_intervention,omitempty"`
	Interventions          []InterventionDiagnosis `json:"interventions"`
	Recommendations        []Recommendation        `json:"recommendations"`
	SuppressedItems        []Recommendation        `json:"suppressed_items,omitempty"`
	MissingEvidenceSummary []string                `json:"missing_evidence_summary,omitempty"`
	CorePackageCompleted   bool                    `json:"core_package_completed"`
}

func severityOf(score float64) string {
	switch {
	case score < 4.0:
		return "critical"
	case score < 5.5:
		return "high"
	case score < 7.0:
		return "moderate"
	default:
		return "on_track"
	}
}

func round2(v float64) float64 {
	return math.Round(v*100) / 100
}

func isScheduledStatus(status string) bool {
	switch strings.ToLower(strings.TrimSpace(status)) {
	case "planned", "scheduled", "in_progress", "approved", "submitted_to_pl", "awaiting_ia_verification":
		return true
	default:
		return false
	}
}

func isVerifiedCompleteStatus(status string) bool {
	switch strings.ToLower(strings.TrimSpace(status)) {
	case "completed", "ia_verified", "closed", "accountant_confirmed", "confirmed":
		return true
	default:
		return false
	}
}

func isCoreCohort(schoolType string) bool {
	switch strings.ToLower(strings.TrimSpace(schoolType)) {
	case "core", "core_trained", "core_graduate", "champion":
		return true
	default:
		return false
	}
}

// Evaluate runs the deterministic, explainable SSA Decision Intelligence Engine
// over an authoritative school snapshot.
func Evaluate(in SchoolDecisionInput) DecisionReport {
	rep := DecisionReport{
		SchoolID:               in.SchoolID,
		EdifySchoolID:          in.EdifySchoolID,
		SchoolName:             in.SchoolName,
		District:               in.District,
		SchoolType:             in.SchoolType,
		FY:                     in.CurrentFY,
		HasCurrentConfirmedSSA: in.HasCurrentConfirmedSSA,
		CurrentSSADate:         in.CurrentSSADate,
		PendingSSACount:        in.PendingSSACount,
		CorePackageCompleted:   in.CorePackageCompleted,
	}

	if in.PendingSSACount > 0 {
		rep.MissingEvidenceSummary = append(rep.MissingEvidenceSummary,
			fmt.Sprintf("%d SSA record(s) are pending independent verification and are excluded from confirmed diagnosis.", in.PendingSSACount))
	}

	capacityConstrained := in.StaffWeeklyCapacity > 0 && in.StaffWeeklyLoad >= in.StaffWeeklyCapacity

	// Case A: No confirmed current-FY SSA -> never invent scores; recommend SSA collection/verification.
	if !in.HasCurrentConfirmedSSA || len(in.CurrentScores) == 0 {
		rep.RiskPriority = "unassessed"
		missing := []string{fmt.Sprintf("No confirmed FY %s SSA record exists for this school.", in.CurrentFY)}
		if in.PendingSSACount > 0 {
			missing = append(missing, fmt.Sprintf("%d unverified SSA submission(s) await independent confirmation.", in.PendingSSACount))
		}
		rep.MissingEvidenceSummary = append(rep.MissingEvidenceSummary, missing...)

		action := "Schedule Baseline / Current-FY SSA Collection Visit"
		if in.PendingSSACount > 0 {
			action = "Complete Independent Verification of Pending SSA Record"
		}
		rec := Recommendation{
			Priority:                 "high",
			Category:                 "ssa_assessment",
			RecommendedIntervention:  "ssa_assessment",
			InterventionLabel:        "School Self-Assessment (SSA)",
			RecommendedActivity:      action,
			DeliverySuggestion:       "staff",
			PriorityReason:           fmt.Sprintf("School lacks a verified FY %s SSA baseline; programmatic interventions require verified diagnostic evidence.", in.CurrentFY),
			VerifiedEvidence:         "0 confirmed current-FY SSA records in PostgreSQL.",
			RelevanceReason:          "Collecting or verifying the 8-intervention SSA establishes an authoritative baseline before assigning targeted training or coaching.",
			OutcomeToMonitor:         fmt.Sprintf("Confirmed FY %s SSA across all 8 Edify interventions.", in.CurrentFY),
			ConfidenceAndLimitations: "High procedural certainty; intervention-specific needs cannot be diagnosed until SSA is verified.",
			MissingEvidence:          missing,
		}
		if hasExistingSSAPlan(in.ExistingActivities) {
			rec.Suppressed = true
			rec.SuppressedReason = "An SSA collection activity is already scheduled for this school in the current FY."
			rep.SuppressedItems = append(rep.SuppressedItems, rec)
		} else {
			rep.Recommendations = append(rep.Recommendations, rec)
		}
		appendCoreObligation(&rep, in, capacityConstrained)
		return rep
	}

	avg := round2(in.CurrentSSAAverage)
	rep.CurrentSSAAverage = &avg
	if in.HasPreviousConfirmedSSA {
		prev := round2(in.PreviousSSAAverage)
		delta := round2(avg - prev)
		rep.PreviousSSAFY = in.PreviousSSAFY
		rep.PreviousSSAAverage = &prev
		rep.OverallDelta = &delta
	} else {
		rep.MissingEvidenceSummary = append(rep.MissingEvidenceSummary, "No previous comparable FY confirmed SSA exists for year-over-year trend comparison.")
	}

	// Build sorted diagnosis across all 8 canonical interventions.
	var diags []InterventionDiagnosis
	for _, iv := range CanonicalInterventions {
		code, label := iv[0], iv[1]
		score, ok := in.CurrentScores[code]
		if !ok || math.IsNaN(score) || math.IsInf(score, 0) {
			rep.MissingEvidenceSummary = append(rep.MissingEvidenceSummary, fmt.Sprintf("Missing verified score for intervention %s.", label))
			continue
		}
		d := InterventionDiagnosis{
			Code:     code,
			Label:    label,
			Score:    round2(score),
			Severity: severityOf(score),
		}
		if in.HasPreviousConfirmedSSA {
			if pv, hasPrev := in.PreviousScores[code]; hasPrev && !math.IsNaN(pv) && !math.IsInf(pv, 0) {
				pvR := round2(pv)
				dl := round2(d.Score - pvR)
				d.PreviousScore = &pvR
				d.Delta = &dl
			}
		}
		diags = append(diags, d)
	}
	sort.SliceStable(diags, func(i, j int) bool {
		if diags[i].Score != diags[j].Score {
			return diags[i].Score < diags[j].Score
		}
		return diags[i].Code < diags[j].Code
	})
	rep.Interventions = diags
	if len(diags) > 0 {
		weak := diags[0]
		strong := diags[len(diags)-1]
		rep.WeakestIntervention = &weak
		rep.StrongestIntervention = &strong
	}

	// Overall risk priority: never let a high average mask a single critical intervention!
	switch {
	case rep.WeakestIntervention != nil && rep.WeakestIntervention.Score < 4.0:
		rep.RiskPriority = "critical"
	case avg < 5.0 || (rep.WeakestIntervention != nil && rep.WeakestIntervention.Score < 5.5):
		rep.RiskPriority = "high"
	case avg < 7.0:
		rep.RiskPriority = "moderate"
	default:
		rep.RiskPriority = "low"
	}

	// Map catalogue options by intervention code.
	catByIV := map[string][]CatalogueOption{}
	for _, c := range in.Catalogue {
		key := strings.ToLower(strings.TrimSpace(c.Intervention))
		catByIV[key] = append(catByIV[key], c)
	}

	// Generate recommendations for weak interventions (< 7.0), prioritized lowest score first.
	for _, d := range diags {
		if d.Score >= 7.0 {
			continue
		}
		options := catByIV[d.Code]
		var chosen *CatalogueOption
		if len(options) > 0 {
			chosen = &options[0]
		}

		delivery := "staff"
		capNote := "Within standard staff weekly capacity."
		if capacityConstrained {
			if chosen != nil && chosen.PartnerDeliveryAllowed {
				delivery = "partner"
				capNote = fmt.Sprintf("Assigned officer is at weekly capacity (%d/%d activities); partner or cluster group delivery is recommended.", in.StaffWeeklyLoad, in.StaffWeeklyCapacity)
			} else {
				capNote = fmt.Sprintf("Assigned officer is at weekly capacity (%d/%d activities); coordinate schedule slot or cluster session with Program Lead.", in.StaffWeeklyLoad, in.StaffWeeklyCapacity)
			}
		}

		trendText := "No previous comparable FY SSA record available."
		if d.PreviousScore != nil && d.Delta != nil {
			switch {
			case *d.Delta < 0:
				trendText = fmt.Sprintf("Declined %.2f pts from FY %s (%.2f → %.2f).", math.Abs(*d.Delta), in.PreviousSSAFY, *d.PreviousScore, d.Score)
			case *d.Delta > 0:
				trendText = fmt.Sprintf("Improved +%.2f pts from FY %s (%.2f → %.2f), but still below 7.0 target.", *d.Delta, in.PreviousSSAFY, *d.PreviousScore, d.Score)
			default:
				trendText = fmt.Sprintf("Unchanged since FY %s (%.2f).", in.PreviousSSAFY, d.Score)
			}
		}

		actName := fmt.Sprintf("Targeted %s School Support Visit", d.Label)
		catID, catCode := "", ""
		confidence := "Grounded in confirmed FY " + in.CurrentFY + " SSA scores; " + capNote
		var missing []string
		if chosen != nil {
			actName = chosen.DisplayName
			catID = chosen.ID
			catCode = chosen.StableCode
		} else {
			missing = append(missing, fmt.Sprintf("No active catalogue item explicitly mapped to %s; defaulting to targeted school support visit.", d.Code))
		}
		if !in.HasPreviousConfirmedSSA {
			missing = append(missing, "No prior-year comparable SSA for longitudinal trend verification.")
		}

		priority := "medium"
		switch d.Severity {
		case "critical":
			priority = "critical"
		case "high":
			priority = "high"
		}

		rec := Recommendation{
			Priority:                 priority,
			Category:                 "intervention_support",
			RecommendedIntervention:  d.Code,
			InterventionLabel:        d.Label,
			RecommendedActivity:      actName,
			CatalogueItemID:          catID,
			CatalogueStableCode:      catCode,
			DeliverySuggestion:       delivery,
			PriorityReason:           fmt.Sprintf("%s scored %.2f/10 (%s priority) in FY %s. %s", d.Label, d.Score, d.Severity, in.CurrentFY, trendText),
			VerifiedEvidence:         fmt.Sprintf("Confirmed FY %s SSA (%s): %s = %.2f/10 (overall %.2f/10).", in.CurrentFY, in.CurrentSSADate, d.Label, d.Score, avg),
			RelevanceReason:          fmt.Sprintf("%s directly targets the verified %s gap identified in the school's SSA.", actName, d.Label),
			OutcomeToMonitor:         fmt.Sprintf("Subsequent verified SSA improvement in %s (target >= 7.0/10); completion alone does not imply score gain.", d.Label),
			ConfidenceAndLimitations: confidence,
			MissingEvidence:          missing,
		}

		if supReason := duplicateSupportReason(in.ExistingActivities, d.Code, catID); supReason != "" {
			rec.Suppressed = true
			rec.SuppressedReason = supReason
			rep.SuppressedItems = append(rep.SuppressedItems, rec)
			continue
		}
		rep.Recommendations = append(rep.Recommendations, rec)
		if len(rep.Recommendations) >= 3 {
			break
		}
	}

	appendCoreObligation(&rep, in, capacityConstrained)
	return rep
}

func appendCoreObligation(rep *DecisionReport, in SchoolDecisionInput, capacityConstrained bool) {
	if !isCoreCohort(in.SchoolType) || in.CorePackageCompleted {
		return
	}
	note := "Core school support package is an annual programme obligation."
	if capacityConstrained {
		note += fmt.Sprintf(" Staff weekly load (%d/%d) requires PL scheduling coordination.", in.StaffWeeklyLoad, in.StaffWeeklyCapacity)
	}
	rep.Recommendations = append(rep.Recommendations, Recommendation{
		Priority:                 "high",
		Category:                 "core_package",
		RecommendedIntervention:  "core_package",
		InterventionLabel:        "Core School Support Package",
		RecommendedActivity:      "Core School Visit / Training Package Completion",
		DeliverySuggestion:       "staff",
		PriorityReason:           fmt.Sprintf("School is classified as %s and has not yet completed its FY %s Core support package.", in.SchoolType, in.CurrentFY),
		VerifiedEvidence:         fmt.Sprintf("PostgreSQL school_type=%s; verified FY %s Core package incomplete.", in.SchoolType, in.CurrentFY),
		RelevanceReason:          "Core schools require scheduled support visits and training delivery to progress toward Core Trained / Core Graduate milestones.",
		OutcomeToMonitor:         "Verified completion of annual Core School visits, trainings, and follow-up SSA.",
		ConfidenceAndLimitations: note,
	})
}

func hasExistingSSAPlan(acts []ExistingActivity) bool {
	for _, a := range acts {
		if strings.Contains(strings.ToLower(a.ActivityType), "ssa") && isScheduledStatus(a.Status) {
			return true
		}
	}
	return false
}

func duplicateSupportReason(acts []ExistingActivity, ivCode, catID string) string {
	for _, a := range acts {
		matchesIV := strings.EqualFold(a.Intervention, ivCode) || (catID != "" && a.CatalogueItemID == catID)
		if !matchesIV {
			continue
		}
		if isScheduledStatus(a.Status) {
			return fmt.Sprintf("Already scheduled (%s on %s, status=%s); duplicate recommendation suppressed.", a.ID, a.PlannedDate, a.Status)
		}
		if isVerifiedCompleteStatus(a.Status) {
			return fmt.Sprintf("Support already delivered/verified in current FY (%s, status=%s); awaiting next SSA to measure impact.", a.ID, a.Status)
		}
	}
	return ""
}

// Service serves PostgreSQL-backed explainable SSA recommendations over HTTP.
type Service struct {
	pool *pgxpool.Pool
	now  func() time.Time
}

// NewService creates an SSA decision intelligence service over pool.
func NewService(pool *pgxpool.Pool, now func() time.Time) *Service {
	if now == nil {
		now = time.Now
	}
	return &Service{pool: pool, now: now}
}

// AnalyzeSchool loads the authoritative PostgreSQL state for schoolID and
// evaluates explainable SSA recommendations for fy.
func (s *Service) AnalyzeSchool(ctx context.Context, p auth.Principal, schoolID, fy string) (*DecisionReport, error) {
	if !allowedRoles[p.ActiveRole] {
		return nil, errors.New("ssadecision: forbidden")
	}
	now := s.now().UTC()
	if strings.TrimSpace(fy) == "" {
		fy = operationalFY(now)
	}
	prevFY := ""
	if n, err := strconv.Atoi(fy); err == nil {
		prevFY = strconv.Itoa(n - 1)
	}

	countryID := ""
	if p.Country != nil {
		countryID = strings.TrimSpace(p.Country.ID)
	}

	var in SchoolDecisionInput
	in.CurrentFY = fy
	in.CurrentScores = map[string]float64{}
	in.PreviousScores = map[string]float64{}
	in.StaffWeeklyCapacity = 12

	var ownerStaffID string
	q := `SELECT s.id, COALESCE(s.school_id, ''), s.name, COALESCE(d.name, ''), COALESCE(s.school_type, 'client'), COALESCE(s.account_owner_id, '')
FROM school s
LEFT JOIN district d ON d.id = s.district_id
WHERE s.deleted_at IS NULL AND (s.id = $1 OR lower(COALESCE(s.school_id, '')) = lower($1))`
	args := []any{strings.TrimSpace(schoolID)}
	if countryID != "" {
		args = append(args, []string{countryID})
		q += ` AND ` + country.SchoolIn("s", "$2")
	}
	q += ` LIMIT 1`
	if err := s.pool.QueryRow(ctx, q, args...).Scan(&in.SchoolID, &in.EdifySchoolID, &in.SchoolName, &in.District, &in.SchoolType, &ownerStaffID); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, pgx.ErrNoRows
		}
		return nil, err
	}

	// Count pending/unverified SSA records for transparency.
	_ = s.pool.QueryRow(ctx, `SELECT count(*) FROM ssa_record WHERE school_id = $1 AND deleted_at IS NULL AND verification_status <> 'confirmed'`, in.SchoolID).Scan(&in.PendingSSACount)

	// Load latest confirmed SSA for current FY.
	if recID, dt, avg, ok := s.loadConfirmedSSA(ctx, in.SchoolID, fy); ok {
		in.HasCurrentConfirmedSSA = true
		in.CurrentSSADate = dt
		in.CurrentSSAAverage = avg
		in.CurrentScores = s.loadScores(ctx, recID)
	}
	// Load latest confirmed SSA for previous comparable FY.
	if prevFY != "" {
		if recID, _, avg, ok := s.loadConfirmedSSA(ctx, in.SchoolID, prevFY); ok {
			in.HasPreviousConfirmedSSA = true
			in.PreviousSSAFY = prevFY
			in.PreviousSSAAverage = avg
			in.PreviousScores = s.loadScores(ctx, recID)
		}
	}

	// Load active catalogue items mapped to interventions.
	if cRows, err := s.pool.Query(ctx, `
SELECT i.id, COALESCE(i.stable_code, ''), i.display_name, COALESCE(i.activity_type, ''),
       COALESCE(m.intervention, ''), i.staff_delivery_allowed, i.partner_delivery_allowed
FROM activity_catalogue_item i
JOIN activity_intervention_mapping m ON m.catalogue_item_id = i.id AND m.active
WHERE i.status = 'active'
ORDER BY m.is_primary DESC, m.priority ASC, i.display_name ASC`); err == nil {
		for cRows.Next() {
			var c CatalogueOption
			if cRows.Scan(&c.ID, &c.StableCode, &c.DisplayName, &c.ActivityType, &c.Intervention, &c.StaffDeliveryAllowed, &c.PartnerDeliveryAllowed) == nil {
				in.Catalogue = append(in.Catalogue, c)
			}
		}
		cRows.Close()
	}

	// Load existing current-FY school activities for deduplication & Core package check.
	if aRows, err := s.pool.Query(ctx, `
SELECT a.id, COALESCE(a.activity_type, ''), COALESCE(a.catalogue_item_id, ''),
       COALESCE(m.intervention, ''), COALESCE(a.status, ''), COALESCE(a.planned_date::text, ''), COALESCE(a.fy, '')
FROM activity a
LEFT JOIN activity_intervention_mapping m ON m.catalogue_item_id = a.catalogue_item_id AND m.active AND m.is_primary
WHERE a.deleted_at IS NULL AND a.school_id = $1 AND a.fy = $2
ORDER BY a.planned_date DESC NULLS LAST`, in.SchoolID, fy); err == nil {
		verifiedCoreVisits := 0
		for aRows.Next() {
			var ea ExistingActivity
			if aRows.Scan(&ea.ID, &ea.ActivityType, &ea.CatalogueItemID, &ea.Intervention, &ea.Status, &ea.PlannedDate, &ea.FY) == nil {
				in.ExistingActivities = append(in.ExistingActivities, ea)
				if isVerifiedCompleteStatus(ea.Status) {
					verifiedCoreVisits++
				}
			}
		}
		aRows.Close()
		in.CorePackageCompleted = verifiedCoreVisits >= 2
	}

	if ownerStaffID != "" {
		weekStart := now.AddDate(0, 0, -int(now.Weekday()))
		weekEnd := weekStart.AddDate(0, 0, 6)
		_ = s.pool.QueryRow(ctx, `
SELECT count(*) FROM activity
WHERE deleted_at IS NULL AND responsible_staff_id = $1
  AND planned_date BETWEEN $2::date AND $3::date
  AND status NOT IN ('cancelled', 'rejected', 'deferred', 'not_planned')`,
			ownerStaffID, weekStart.Format("2006-01-02"), weekEnd.Format("2006-01-02")).Scan(&in.StaffWeeklyLoad)
	}

	report := Evaluate(in)
	return &report, nil
}

func (s *Service) loadConfirmedSSA(ctx context.Context, schoolID, fy string) (id, dateStr string, avg float64, ok bool) {
	var dt time.Time
	err := s.pool.QueryRow(ctx, `
SELECT id, date_of_ssa, COALESCE(average_score, 0)
FROM ssa_record
WHERE school_id = $1 AND fy = $2 AND deleted_at IS NULL AND verification_status = 'confirmed'
ORDER BY date_of_ssa DESC
LIMIT 1`, schoolID, fy).Scan(&id, &dt, &avg)
	if err != nil {
		return "", "", 0, false
	}
	return id, dt.UTC().Format("2006-01-02"), avg, true
}

func (s *Service) loadScores(ctx context.Context, recID string) map[string]float64 {
	out := map[string]float64{}
	rows, err := s.pool.Query(ctx, `SELECT intervention, score FROM ssa_score WHERE ssa_record_id = $1`, recID)
	if err != nil {
		return out
	}
	defer rows.Close()
	for rows.Next() {
		var iv string
		var score float64
		if rows.Scan(&iv, &score) == nil {
			out[strings.ToLower(strings.TrimSpace(iv))] = score
		}
	}
	return out
}

// RegisterHTTP mounts GET /api/v1/schools/{id}/ssa-recommendations.
func (s *Service) RegisterHTTP(mux *http.ServeMux, auther Authenticator) {
	mux.HandleFunc("GET /api/v1/schools/{id}/ssa-recommendations", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeDecisionJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in first."})
			return
		}
		if !allowedRoles[p.ActiveRole] {
			writeDecisionJSON(w, http.StatusForbidden, map[string]string{"error": "Your role cannot view school SSA recommendations."})
			return
		}
		schoolID := strings.TrimSpace(r.PathValue("id"))
		if schoolID == "" {
			writeDecisionJSON(w, http.StatusBadRequest, map[string]string{"error": "School ID is required."})
			return
		}
		fy := strings.TrimSpace(r.URL.Query().Get("fy"))
		rep, err := s.AnalyzeSchool(r.Context(), p, schoolID, fy)
		if err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				writeDecisionJSON(w, http.StatusNotFound, map[string]string{"error": "School not found in your country."})
				return
			}
			writeDecisionJSON(w, http.StatusInternalServerError, map[string]string{"error": "Could not evaluate SSA recommendations."})
			return
		}
		writeDecisionJSON(w, http.StatusOK, rep)
	})
}

func operationalFY(now time.Time) string {
	if now.Month() >= time.October {
		return strconv.Itoa(now.Year() + 1)
	}
	return strconv.Itoa(now.Year())
}

func writeDecisionJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
