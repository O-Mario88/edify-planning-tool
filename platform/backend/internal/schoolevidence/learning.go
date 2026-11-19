package schoolevidence

import (
	"context"
	"fmt"
	"math"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// result is one learning result as the page reads it.
type result struct {
	id, schoolID, school, fy, assessment, grade, subject string
	assessed                                             time.Time
	learners                                             int
	mean, max                                            *string
	proficient                                           *int
	recordedBy, status, reason, country                  string
	recorder                                             *string
}

// gFloat is Python's format(x, "g") of a one-decimal float.
func gFloat(x float64) string { return strconv.FormatFloat(x, 'g', -1, 64) }

// register is the Learning results register: the reader's results of the
// year (and state, and subject), newest first, fifty a page.
func (s *Service) register(ctx context.Context, r *reader, query url.Values) ([]*screensv1.PageBlock, error) {
	args := append([]any{}, r.args...)
	arg := func(v any) string {
		args = append(args, v)
		return "$" + strconv.Itoa(len(args))
	}
	where := "l.deleted_at IS NULL AND " + r.schools + " AND l.fy = " + arg(r.fy)
	if r.status != "" {
		where += " AND l.verification_status = " + arg(r.status)
	}
	if r.subject != "" {
		where += " AND UPPER(l.subject) = UPPER(" + arg(r.subject) + ")"
	}
	from := ` FROM impact_learning_result l JOIN school s ON s.id = l.school_id WHERE ` + where
	var total int
	if err := s.db.QueryRow(ctx, `SELECT count(*)`+from, args...).Scan(&total); err != nil {
		return nil, fmt.Errorf("schoolevidence: counting the learning results: %w", err)
	}
	number, pages := closedschools.PageOf(query.Get("register_page"), total, pageSize)
	limit, offset := arg(pageSize), arg((number-1)*pageSize)
	rows, err := s.db.Query(ctx, `
SELECT l.id, l.school_id, s.name, l.fy, l.assessment_type, l.grade_level, l.subject, l.assessed_on, l.learners_tested,
  l.mean_score::text, l.max_score::text, l.learners_proficient, l.recorded_by_user_id, l.verification_status,
  COALESCE(l.return_reason, ''), COALESCE(l.country, ''),
  (SELECT u.name FROM "user" u WHERE u.id = l.recorded_by_user_id AND u.deleted_at IS NULL)`+from+`
ORDER BY l.assessed_on DESC, l.created_at DESC LIMIT `+limit+` OFFSET `+offset, args...)
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the learning results: %w", err)
	}
	results, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (result, error) {
		var x result
		err := row.Scan(&x.id, &x.schoolID, &x.school, &x.fy, &x.assessment, &x.grade, &x.subject, &x.assessed, &x.learners,
			&x.mean, &x.max, &x.proficient, &x.recordedBy, &x.status, &x.reason, &x.country, &x.recorder)
		return x, err
	})
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the learning results: %w", err)
	}
	cells := [][]*screensv1.PageCell{}
	for _, x := range results {
		parts := []string{}
		if x.mean != nil {
			mean := "mean " + *x.mean
			if x.max != nil {
				mean += " of " + *x.max
			}
			parts = append(parts, mean)
		}
		if x.proficient != nil {
			parts = append(parts, strconv.Itoa(*x.proficient)+" proficient")
		}
		v := verdict{recordedBy: x.recordedBy, status: x.status, reason: x.reason, country: x.country, recorder: x.recorder}
		tail, err := v.cells(ctx, r, learning, x.id)
		if err != nil {
			return nil, err
		}
		cells = append(cells, append([]*screensv1.PageCell{
			cell(x.school, ""), cell(label(rules.AssessmentTypes, x.assessment), ""), cell(x.grade+" · "+x.subject, ""),
			cell(x.assessed.Format("2 Jan 2006"), ""), cell(strconv.Itoa(x.learners), ""), cell(strings.Join(parts, " · "), ""),
		}, tail...))
	}
	return table("Learning results", []string{"School", "Assessment", "Class · subject", "Assessed", "Learners", "Result", "Recorded by", "Status"},
		cells, len(cells) > 0, total, number, pages, "register_page", "No learning results recorded",
		"Record a class result, upload a CSV, or ask field staff to record results from a OneTest visit.", query), nil
}

// side is one year's pool of a comparison (learning_comparisons).
type side struct {
	learners, scoreLearners, proficient, proficientLearners int
	scoreWeight                                             float64
	grade, subject                                          string
}

func (sd *side) measure() (score, proficient *float64) {
	if sd == nil {
		return nil, nil
	}
	if sd.scoreLearners != 0 {
		v := schooldirectory.PyRound1(sd.scoreWeight / float64(sd.scoreLearners))
		score = &v
	}
	if sd.proficientLearners != 0 {
		v := schooldirectory.PyRound1(100 * float64(sd.proficient) / float64(sd.proficientLearners))
		proficient = &v
	}
	return score, proficient
}

func norm(t string) string { return strings.Join(strings.Fields(strings.ToLower(t)), " ") }

// comparison is one school's class and subject, last year against this.
type comparison struct {
	school, assessment, grade, subject, state, measure, classification string
	before, after                                                      *side
	change                                                             float64
}

// summary is learning_summary: the reader's confirmed results of last year
// and this pooled by school, assessment, class and subject, compared where
// both years hold enough learners, by state, school and subject.
func (s *Service) summary(ctx context.Context, r *reader, query url.Values) ([]*screensv1.PageBlock, error) {
	n, _ := strconv.Atoi(r.fy)
	prev := strconv.Itoa(n - 1)
	args := append([]any{}, r.args...)
	args = append(args, r.fy, prev)
	// _learning_rows: the model's order (-assessed_on, school_id) gives the
	// pools their first rows.
	rows, err := s.db.Query(ctx, `
SELECT l.school_id, s.name, l.fy, l.assessment_type, l.grade_level, l.subject, l.learners_tested, l.mean_score::float8, l.max_score::float8,
  l.learners_proficient, l.verification_status
FROM impact_learning_result l JOIN school s ON s.id = l.school_id
WHERE l.deleted_at IS NULL AND `+r.schools+` AND (l.verification_status = 'pending' OR l.fy IN ($`+strconv.Itoa(len(args)-1)+`, $`+strconv.Itoa(len(args))+`))
ORDER BY l.assessed_on DESC, l.school_id`, args...)
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the results to compare: %w", err)
	}
	type key struct{ school, assessment, grade, subject string }
	pools := map[key]map[string]*side{}
	order := []key{}
	names := map[string]string{}
	for rows.Next() {
		var school, name, fy, assessment, grade, subject, status string
		var learners int
		var mean, max *float64
		var proficient *int
		if err := rows.Scan(&school, &name, &fy, &assessment, &grade, &subject, &learners, &mean, &max, &proficient, &status); err != nil {
			rows.Close()
			return nil, fmt.Errorf("schoolevidence: reading the results to compare: %w", err)
		}
		if r.subject != "" && norm(subject) != norm(r.subject) {
			continue
		}
		if status != "confirmed" || (fy != r.fy && fy != prev) {
			continue
		}
		names[school] = name
		k := key{school, assessment, norm(grade), norm(subject)}
		if _, ok := pools[k]; !ok {
			pools[k] = map[string]*side{}
			order = append(order, k)
		}
		sd, ok := pools[k][fy]
		if !ok {
			sd = &side{grade: grade, subject: subject}
			pools[k][fy] = sd
		}
		sd.learners += learners
		if mean != nil && max != nil && *max != 0 {
			sd.scoreWeight += *mean / *max * 100 * float64(learners)
			sd.scoreLearners += learners
		}
		if proficient != nil {
			sd.proficient += *proficient
			sd.proficientLearners += learners
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the results to compare: %w", err)
	}
	comparisons := []comparison{}
	for _, k := range order {
		before, after := pools[k][prev], pools[k][r.fy]
		labelled := after
		if labelled == nil {
			labelled = before
		}
		c := comparison{school: names[k.school], assessment: k.assessment, grade: labelled.grade, subject: labelled.subject,
			before: before, after: after}
		sb, pb := before.measure()
		sa, pa := after.measure()
		switch {
		case before == nil || after == nil:
			c.state = "one_year"
		case before.learners < rules.MinLearners || after.learners < rules.MinLearners:
			c.state = "withheld"
		case sb != nil && sa != nil:
			c.state, c.measure, c.change = "compared", "score", schooldirectory.PyRound1(*sa-*sb)
		case pb != nil && pa != nil:
			c.state, c.measure, c.change = "compared", "proficient", schooldirectory.PyRound1(*pa-*pb)
		default:
			c.state = "not_comparable"
		}
		if c.state == "compared" {
			switch {
			case c.change > 0:
				c.classification = "improved"
			case c.change < 0:
				c.classification = "declined"
			default:
				c.classification = "no_change"
			}
		}
		if c.school == "" {
			c.school = "School"
		}
		comparisons = append(comparisons, c)
	}
	rank := map[string]int{"compared": 0, "withheld": 1, "not_comparable": 2, "one_year": 3}
	sort.SliceStable(comparisons, func(i, j int) bool {
		a, b := comparisons[i], comparisons[j]
		if rank[a.state] != rank[b.state] {
			return rank[a.state] < rank[b.state]
		}
		if a.school != b.school {
			return a.school < b.school
		}
		return a.subject < b.subject
	})
	number, pages := closedschools.PageOf(query.Get("summary_page"), len(comparisons), pageSize)
	cells := [][]*screensv1.PageCell{}
	for _, c := range comparisons[(number-1)*pageSize : min(number*pageSize, len(comparisons))] {
		change, tone := "Not comparable (different measures)", "neutral"
		switch c.state {
		case "compared":
			unit := "pp proficient"
			if c.measure == "score" {
				unit = "pp"
			}
			sign := ""
			if c.change > 0 || (c.change == 0 && !math.Signbit(c.change)) {
				sign = "+"
			}
			change = sign + gFloat(c.change) + unit
			tone = map[string]string{"improved": "success", "declined": "danger"}[c.classification]
			if tone == "" {
				tone = "neutral"
			}
		case "withheld":
			change = "Withheld (fewer than " + strconv.Itoa(rules.MinLearners) + " learners)"
		case "one_year":
			change = "One year only"
		}
		cells = append(cells, []*screensv1.PageCell{
			cell(c.school, ""), cell(label(rules.AssessmentTypes, c.assessment), ""), cell(c.grade+" · "+c.subject, ""),
			cell(sideText(c.before), ""), cell(sideText(c.after), ""), cell(change, tone),
		})
	}
	return table("Year on year: FY"+prev+" against FY"+r.fy, []string{"School", "Assessment", "Class · subject", "FY" + prev, "FY" + r.fy, "Change"},
		cells, false, len(comparisons), number, pages, "summary_page", "No confirmed results to compare",
		"Once results for the same class and subject are confirmed in two years, they are compared here.", query), nil
}

// sideText is one year's side as the summary writes it.
func sideText(sd *side) string {
	if sd == nil {
		return "Not measured"
	}
	score, proficient := sd.measure()
	parts := []string{}
	if score != nil {
		parts = append(parts, gFloat(*score)+"%")
	}
	if proficient != nil {
		parts = append(parts, gFloat(*proficient)+"% proficient")
	}
	shown := strings.Join(parts, " · ")
	if shown == "" {
		shown = "recorded"
	}
	return shown + " (" + strconv.Itoa(sd.learners) + " learners)"
}
