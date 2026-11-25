package iapages

// The evidence beyond the SSA a report freezes
// (apps.impact.evidence_services.outcome_evidence): student learning year on
// year, discipleship practice beside reviewed change stories, and EdTech
// rollout from each deployment's latest confirmed check. Only confirmed
// records count; pending ones are counted as awaiting verification.

import (
	"context"
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	minLearners       = 10
	learningRuleLabel = "Any change (no approved threshold)"
)

// percentage is apps.core.metrics.ratio.percentage.
func percentage(part, whole float64) any {
	if whole == 0 {
		return nil
	}
	return pyRoundInt(part / whole * 100)
}

func pyRound1(x float64) float64 { return math.RoundToEven(x*10) / 10 }

type learningRow struct {
	school, fy, kind, grade, subject, status string
	tested                                   int
	mean, max                                *float64
	proficient                               *int
}

type learningSide struct {
	learners, scoreLearners, proficient, proficientLearners int
	scoreWeight                                             float64
}

func (sd *learningSide) measure() (*float64, *float64) {
	if sd == nil {
		return nil, nil
	}
	var score, prof *float64
	if sd.scoreLearners > 0 {
		v := pyRound1(sd.scoreWeight / float64(sd.scoreLearners))
		score = &v
	}
	if sd.proficientLearners > 0 {
		v := pyRound1(100 * float64(sd.proficient) / float64(sd.proficientLearners))
		prof = &v
	}
	return score, prof
}

type learningComparison struct {
	school, state, classification string
}

// learningComparisons is evidence_services.learning_comparisons, as far as
// outcome_evidence reads it.
func learningComparisons(rows []learningRow, fy string) []learningComparison {
	n, _ := strconv.Atoi(fy)
	prev := strconv.Itoa(n - 1)
	type key struct{ school, kind, grade, subject string }
	pools, order := map[key]map[string]*learningSide{}, []key{}
	norm := func(t string) string { return strings.Join(strings.Fields(strings.ToLower(t)), " ") }
	for _, r := range rows {
		if r.status != "confirmed" || (r.fy != fy && r.fy != prev) {
			continue
		}
		k := key{r.school, r.kind, norm(r.grade), norm(r.subject)}
		if pools[k] == nil {
			pools[k] = map[string]*learningSide{}
			order = append(order, k)
		}
		sd := pools[k][r.fy]
		if sd == nil {
			sd = &learningSide{}
			pools[k][r.fy] = sd
		}
		sd.learners += r.tested
		if r.mean != nil && r.max != nil && *r.max != 0 {
			sd.scoreWeight += *r.mean / *r.max * 100 * float64(r.tested)
			sd.scoreLearners += r.tested
		}
		if r.proficient != nil {
			sd.proficient += *r.proficient
			sd.proficientLearners += r.tested
		}
	}
	out := []learningComparison{}
	for _, k := range order {
		before, after := pools[k][prev], pools[k][fy]
		c := learningComparison{school: k.school}
		sb, pb := before.measure()
		sa, pa := after.measure()
		var change *float64
		switch {
		case before == nil || after == nil:
			c.state = "one_year"
		case before.learners < minLearners || after.learners < minLearners:
			c.state = "withheld"
		case sb != nil && sa != nil:
			v := pyRound1(*sa - *sb)
			change, c.state = &v, "compared"
		case pb != nil && pa != nil:
			v := pyRound1(*pa - *pb)
			change, c.state = &v, "compared"
		default:
			c.state = "not_comparable"
		}
		if c.state == "compared" {
			switch {
			case *change > 0:
				c.classification = "improved"
			case *change < 0:
				c.classification = "declined"
			default:
				c.classification = "no_change"
			}
		}
		out = append(out, c)
	}
	return out
}

// outcomeEvidence is evidence_services.outcome_evidence for the year fy.
func (s *Service) outcomeEvidence(ctx context.Context, scope schooldirectory.Scope, fy string) (map[string]any, error) {
	schools := "FALSE"
	args := []any{}
	if !scope.SummaryOnly {
		schools = schooldirectory.AnalyticsReach(scope, &args)
	}
	in := "(SELECT s.id FROM school s WHERE " + schools + ")"
	n, _ := strconv.Atoi(fy)
	prev := strconv.Itoa(n - 1)
	one := 1.0

	largs := append(append([]any{}, args...), fy, prev)
	rows, err := s.db.Query(ctx, fmt.Sprintf(`SELECT school_id, fy, assessment_type, COALESCE(grade_level, ''), COALESCE(subject, ''),
  learners_tested, mean_score::float8, max_score::float8, learners_proficient, verification_status
FROM impact_learning_result WHERE deleted_at IS NULL AND school_id IN %s
  AND (verification_status = 'pending' OR fy IN ($%d, $%d))`, in, len(largs)-1, len(largs)), largs...)
	if err != nil {
		return nil, fmt.Errorf("iapages: the learning results: %w", err)
	}
	learning := []learningRow{}
	for rows.Next() {
		var r learningRow
		if err := rows.Scan(&r.school, &r.fy, &r.kind, &r.grade, &r.subject, &r.tested, &r.mean, &r.max, &r.proficient, &r.status); err != nil {
			rows.Close()
			return nil, fmt.Errorf("iapages: a learning result: %w", err)
		}
		learning = append(learning, r)
	}
	rows.Close()
	comparisons := learningComparisons(learning, fy)
	compared, comparedSchools := 0, map[string]bool{}
	improved, declined, withheld := 0, 0, 0
	for _, c := range comparisons {
		switch c.state {
		case "compared":
			compared++
			comparedSchools[c.school] = true
			if c.classification == "improved" {
				improved++
			}
			if c.classification == "declined" {
				declined++
			}
		case "withheld":
			withheld++
		}
	}
	confirmedThisYear, pending := 0, 0
	for _, r := range learning {
		if r.status == "confirmed" && r.fy == fy {
			confirmedThisYear++
		}
		if r.status == "pending" {
			pending++
		}
	}
	learningOut := map[string]any{"comparisons": compared, "schools": len(comparedSchools), "improved": improved,
		"declined": declined, "withheld": withheld, "confirmed_this_year": confirmedThisYear, "pending": pending,
		"grade": evidenceGrade(len(comparedSchools), &one, nil), "rule_label": learningRuleLabel, "min_learners": minLearners,
		"improved_pct": percentage(float64(improved), float64(compared)), "declined_pct": percentage(float64(declined), float64(compared))}

	dargs := append(append([]any{}, args...), fy)
	rows, err = s.db.Query(ctx, fmt.Sprintf(`SELECT school_id, verification_status, discipleship_groups_active, learners_in_groups,
  learners_enrolled, spiritual_lead_in_post FROM impact_discipleship_record
WHERE deleted_at IS NULL AND school_id IN %s AND (verification_status = 'pending' OR (fy = $%d AND verification_status = 'confirmed'))
ORDER BY school_id, observed_on DESC, created_at DESC`, in, len(dargs)), dargs...)
	if err != nil {
		return nil, fmt.Errorf("iapages: the discipleship records: %w", err)
	}
	type disc struct {
		groups, inGroups, enrolled *int
		lead                       *bool
	}
	latest, order := map[string]disc{}, []string{}
	dpending := 0
	for rows.Next() {
		var school, status string
		var d disc
		if err := rows.Scan(&school, &status, &d.groups, &d.inGroups, &d.enrolled, &d.lead); err != nil {
			rows.Close()
			return nil, fmt.Errorf("iapages: a discipleship record: %w", err)
		}
		if status == "pending" {
			dpending++
		}
		if status == "confirmed" {
			if _, seen := latest[school]; !seen {
				latest[school] = d
				order = append(order, school)
			}
		}
	}
	rows.Close()
	withGroups, withLead, inSum, enrolledSum := 0, 0, 0, 0
	for _, school := range order {
		d := latest[school]
		if d.groups != nil && *d.groups > 0 {
			withGroups++
		}
		if d.lead != nil && *d.lead {
			withLead++
		}
		if d.inGroups != nil && d.enrolled != nil && *d.enrolled != 0 {
			inSum += *d.inGroups
			enrolledSum += *d.enrolled
		}
	}
	stories, err := s.storyCounts(ctx, scope, fy)
	if err != nil {
		return nil, err
	}
	discipleshipOut := map[string]any{"schools": len(latest), "with_groups": withGroups,
		"with_groups_pct": percentage(float64(withGroups), float64(len(latest))), "with_lead": withLead,
		"with_lead_pct":          percentage(float64(withLead), float64(len(latest))),
		"learners_in_groups_pct": percentage(float64(inSum), float64(enrolledSum)), "pending": dpending,
		"stories_approved": stories[0], "stories_waiting": stories[1], "grade": evidenceGrade(len(latest), &one, nil)}

	rows, err = s.db.Query(ctx, fmt.Sprintf(`SELECT d.school_id, d.quantity, d.verification_status, d.learners_with_access,
  c.checked_on, c.units_functional, c.teachers_using, c.learners_using,
  (SELECT count(DISTINCT p.id) FROM impact_edtech_check p WHERE p.deployment_id = d.id AND p.verification_status = 'pending' AND p.deleted_at IS NULL)
FROM impact_edtech_deployment d
LEFT JOIN LATERAL (SELECT checked_on, units_functional, teachers_using, learners_using FROM impact_edtech_check c
  WHERE c.deployment_id = d.id AND c.verification_status = 'confirmed' AND c.deleted_at IS NULL
  ORDER BY c.checked_on DESC, c.created_at DESC LIMIT 1) c ON TRUE
WHERE d.deleted_at IS NULL AND d.school_id IN %s`, in), args...)
	if err != nil {
		return nil, fmt.Errorf("iapages: the EdTech deployments: %w", err)
	}
	deployments, units, checked, unitsChecked, functional, teachers, learnersUsing, access, epending := 0, 0, 0, 0, 0, 0, 0, 0, 0
	confirmedSchools, checkedSchools := map[string]bool{}, map[string]bool{}
	for rows.Next() {
		var school, status string
		var quantity, pendingChecks int
		var withAccess, unitsFunctional, teachersUsing, learnersUsingN *int
		var checkedOn *time.Time
		if err := rows.Scan(&school, &quantity, &status, &withAccess, &checkedOn, &unitsFunctional, &teachersUsing, &learnersUsingN, &pendingChecks); err != nil {
			rows.Close()
			return nil, fmt.Errorf("iapages: an EdTech deployment: %w", err)
		}
		if status == "pending" {
			epending++
		}
		epending += pendingChecks
		if status != "confirmed" {
			continue
		}
		deployments++
		units += quantity
		confirmedSchools[school] = true
		if checkedOn == nil {
			continue
		}
		checked++
		unitsChecked += quantity
		checkedSchools[school] = true
		for _, x := range []struct {
			into *int
			v    *int
		}{{&functional, unitsFunctional}, {&teachers, teachersUsing}, {&learnersUsing, learnersUsingN}, {&access, withAccess}} {
			if x.v != nil {
				*x.into += *x.v
			}
		}
	}
	rows.Close()
	edtechOut := map[string]any{"deployments": deployments, "schools": len(confirmedSchools), "units": units, "checked": checked,
		"units_functional": functional, "units_checked": unitsChecked, "functional_pct": percentage(float64(functional), float64(unitsChecked)),
		"teachers_using": teachers, "learners_using": learnersUsing, "learners_with_access": access, "pending": epending,
		"grade": evidenceGrade(len(checkedSchools), &one, nil)}
	return map[string]any{"fy": fy, "learning": learningOut, "discipleship": discipleshipOut, "edtech": edtechOut}, nil
}

// storyCounts is evidence_services._story_counts: approved spiritual
// formation stories of the year, and stories waiting for review.
func (s *Service) storyCounts(ctx context.Context, scope schooldirectory.Scope, fy string) ([2]int, error) {
	args := []any{}
	where := storyReach(scope, &args)
	start, end := fyBounds(fy)
	args = append(args, start, end, rules.SpiritualDomains)
	n := len(args)
	var out [2]int
	err := s.db.QueryRow(ctx, fmt.Sprintf(`SELECT
  count(*) FILTER (WHERE m.status = 'approved' AND m.story_date >= $%d::date AND m.story_date < $%d::date
    AND (m.intervention = ANY($%d) OR m.outcome_area IN (
      SELECT a.code FROM impact_outcome_area_domain d JOIN impact_outcome_area a ON a.id = d.area_id WHERE d.intervention = ANY($%d)))),
  count(*) FILTER (WHERE m.status = 'submitted')
FROM mscs_story m LEFT JOIN school s ON s.id = m.school_id WHERE %s`, n-2, n-1, n, n, where), args...).Scan(&out[0], &out[1])
	if err != nil {
		return out, fmt.Errorf("iapages: counting the change stories: %w", err)
	}
	return out, nil
}
