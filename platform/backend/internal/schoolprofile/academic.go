package schoolprofile

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// academicTab is the school's learners: its enrolment and learning results
// this year against last (engine.students, by clusters.outcomes'
// like-for-like reads) and the records behind them.
func (s *Service) academicTab(ctx context.Context, sc school, l lens) ([]*screensv1.PageBlock, error) {
	before := previousFY(l.fy)

	was, hasWas, now, hasNow, err := s.enrolmentYears(ctx, sc.ID, l.fy, before)
	if err != nil {
		return nil, err
	}

	enrolment := 0
	if sc.Enrollment != nil {
		enrolment = *sc.Enrollment
	}
	growth := "0%"
	growthHelper := "0 to 0"
	if hasWas && hasNow {
		growthHelper = intcomma(was) + " to " + intcomma(now)
		if was != 0 {
			g := pyRound(100*float64(now-was)/float64(was), 1)
			growth = pyFloat(g) + "%"
			if g > 0 {
				growth = "+" + growth
			}
		}
	}

	learning, err := s.learning(ctx, sc.ID, l.fy, before)
	if err != nil {
		return nil, err
	}
	results := "0%"
	helper := "previous 0%"
	if learning.after != nil {
		results = pyFloat(*learning.after) + "%"
	}
	if learning.before != nil {
		helper = "previous " + pyFloat(*learning.before) + "%"
	}
	if learning.before != nil && learning.after != nil {
		change := pyRound(*learning.after-*learning.before, 1)
		sign := ""
		if change > 0 {
			sign = "+"
		}
		helper += " · " + sign + pyFloat(change) + " points"
	}

	blocks := []*screensv1.PageBlock{strip("Learners",
		kpi{label: "Enrolment", value: intcomma(enrolment), link: "#profile-records-enrolment", helper: "learners on the school record"},
		kpi{label: "Enrolment Growth", value: growth, link: "#profile-records-enrolment", helper: growthHelper},
		kpi{label: "Learning Results", value: results, link: "#profile-records-learning", helper: helper},
	)}

	// Enrolment: school by school (one school here).
	var wasP, nowP, changeP *int
	if hasWas {
		wasP = &was
	}
	if hasNow {
		nowP = &now
	}
	tone := ""
	if hasWas && hasNow {
		c := now - was
		changeP = &c
		if c > 0 {
			tone = "success"
		} else if c < 0 {
			tone = "danger"
		}
	}
	enrolmentTable := recordTable{
		title:   "Enrolment: school by school",
		summary: recordsSummary(1, l),
		empty:   "No record yet: the figure is 0.",
		footer: "A school is compared only with a figure recorded in both years. On Profile is the enrolment the school's " +
			"record holds now; the profile's Enrolment figure is these added up.",
		columns: [][2]string{{"School ID", ""}, {"School", ""}, {fyLabel(before), "num"}, {fyLabel(l.fy), "num"}, {"Change", "num"}, {"On Profile", "num"}},
		rows: [][]cell{{
			textCell(sc.SchoolID, ""), textCell(sc.Name, "/schools/"+sc.ID),
			optCell(wasP, ""), optCell(nowP, ""), optCell(changeP, tone), optCell(sc.Enrollment, ""),
		}},
	}

	learningTable := recordTable{
		title:   "Learning results: the assessments",
		summary: recordsSummary(len(learning.rows), l),
		empty:   "No record yet: the figure is 0.",
		footer:  "The profile's figure reads confirmed results only, and compares a school only when it has them in both years.",
		columns: [][2]string{{"Date", "date"}, {"School ID", ""}, {"School", ""}, {"Assessment", ""},
			{"Subject · Class", ""}, {"Learners Tested", "num"}, {"Mean Score", "num"}, {"Verification", ""}},
		rows: learning.rows,
	}
	if len(learning.rows) > maxRows {
		return nil, errTooLong
	}
	return append(blocks, enrolmentTable.block(), learningTable.block()), nil
}

// learned is the school's learning results: its weighted share of the marks
// in each year (confirmed results only), and the records of both years.
type learned struct {
	before, after *float64
	rows          [][]cell
}

func (s *Service) learning(ctx context.Context, schoolID, fy, before string) (learned, error) {
	var out learned
	rows, err := s.db.Query(ctx, `
SELECT r.assessed_on, COALESCE(sch.school_id, ''), COALESCE(sch.name, ''), COALESCE(r.assessment_type, ''),
  COALESCE(r.subject, ''), COALESCE(r.grade_level, ''), r.learners_tested, r.mean_score::float8, r.max_score::float8,
  COALESCE(r.verification_status, ''), r.fy
FROM impact_learning_result r LEFT JOIN school sch ON sch.id = r.school_id
WHERE r.school_id = $1 AND r.fy = ANY($2) AND r.deleted_at IS NULL
ORDER BY r.assessed_on DESC, sch.name, r.id`, schoolID, []string{fy, before})
	if err != nil {
		return out, fmt.Errorf("schoolprofile: reading learning results: %w", err)
	}
	type sums struct{ weighted, learners float64 }
	totals := map[string]*sums{}
	out.rows, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) ([]cell, error) {
		var on *time.Time
		var code, name, kind, subject, grade, verification, year string
		var tested *int32
		var mean, maximum *float64
		if err := row.Scan(&on, &code, &name, &kind, &subject, &grade, &tested, &mean, &maximum, &verification, &year); err != nil {
			return nil, err
		}
		// clusters.outcomes._school_scores: confirmed, with a mark and a
		// maximum, weighted by the learners tested.
		if verification == "confirmed" && mean != nil && maximum != nil && *maximum > 0 && tested != nil && *tested > 0 {
			t := totals[year]
			if t == nil {
				t = &sums{}
				totals[year] = t
			}
			share := *mean / *maximum * 100
			t.weighted += share * float64(*tested)
			t.learners += float64(*tested)
		}
		date := cell{text: "—"}
		if on != nil {
			date = cell{text: jMY(*on)}
		}
		parts := []string{}
		for _, p := range []string{subject, grade} {
			if p != "" {
				parts = append(parts, p)
			}
		}
		var testedP *int
		if tested != nil {
			n := int(*tested)
			testedP = &n
		}
		shareCell := cell{text: "—"}
		if mean != nil && maximum != nil && *maximum != 0 {
			shareCell = cell{text: pyFloat(pyRound(*mean*100 / *maximum, 1)) + "%"}
		}
		return []cell{date, textCell(code, ""), textCell(name, "/schools/"+schoolID), textCell(status(kind), ""),
			textCell(joinDot(parts), ""), optCell(testedP, ""), shareCell, textCell(status(verification), "")}, nil
	})
	if err != nil {
		return out, err
	}
	pct := func(year string) *float64 {
		t := totals[year]
		if t == nil || t.learners == 0 {
			return nil
		}
		v := pyRound(t.weighted/t.learners, 1)
		return &v
	}
	// A school is compared only with results in both years.
	if b, a := pct(before), pct(fy); b != nil && a != nil {
		out.before, out.after = b, a
	}
	return out, nil
}

func joinDot(parts []string) string {
	out := ""
	for i, p := range parts {
		if i > 0 {
			out += " · "
		}
		out += p
	}
	return out
}

// enrolmentYears is the enrolment recorded for the school in the year
// before and in the year (SchoolEnrollmentHistory), the latest recording of
// a year speaking for it.
func (s *Service) enrolmentYears(ctx context.Context, schoolID, fy, before string) (was int, hasWas bool, now int, hasNow bool, err error) {
	years := map[string]int{}
	rows, err := s.db.Query(ctx, `
SELECT fy, enrollment FROM school_enrollment_history
WHERE school_id = $1 AND fy = ANY($2) ORDER BY fy, recorded_at`, schoolID, []string{fy, before})
	if err != nil {
		return 0, false, 0, false, fmt.Errorf("schoolprofile: reading enrolment history: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var year string
		var n *int32
		if err := rows.Scan(&year, &n); err != nil {
			return 0, false, 0, false, err
		}
		if n != nil {
			years[year] = int(*n)
		} else {
			delete(years, year)
		}
	}
	was, hasWas = years[before]
	now, hasNow = years[fy]
	return was, hasWas, now, hasNow, rows.Err()
}
