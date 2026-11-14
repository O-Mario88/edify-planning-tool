package hrregister

import (
	"context"
	"encoding/json"
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// pyRound1 is Python's round(x, 1): the nearest one-decimal value to x's
// exact binary value, ties to even.
func pyRound1(x float64) float64 {
	r, _ := strconv.ParseFloat(strconv.FormatFloat(x, 'f', 1, 64), 64)
	return r
}

// pyStr1 is str() of a one-decimal float as Python writes it ("4.0").
func pyStr1(x float64) string { return strconv.FormatFloat(x, 'f', 1, 64) }

// surveyResult is survey_results: how many answered and, once enough have,
// the overall score (the mean of each statement's mean, each to one
// decimal, the result to one decimal).
type surveyResult struct {
	count   int
	shown   bool
	overall *float64
}

func results(answers []map[string]any) surveyResult {
	r := surveyResult{count: len(answers)}
	if r.count < rules.PulseMinResponses {
		return r
	}
	r.shown = true
	totals := []float64{}
	for _, key := range rules.PulseQuestions {
		sum, n := 0.0, 0
		for _, a := range answers {
			if v, ok := a[key].(float64); ok && v != 0 {
				sum += v
				n++
			}
		}
		if n > 0 {
			totals = append(totals, pyRound1(sum/float64(n)))
		}
	}
	if len(totals) > 0 {
		sum := 0.0
		for _, t := range totals {
			sum += t
		}
		overall := pyRound1(sum / float64(len(totals)))
		r.overall = &overall
	}
	return r
}

// pulseSurveys is pulse_surveys_view: the surveys, the latest opening
// first, whose every country the reach allows (a survey of no country is
// everyone's), each with how many answered and the overall score once five
// have; the register has no search.
func pulseSurveys(ctx context.Context, in input) (register, error) {
	rows, err := in.db.Query(ctx, `
SELECT s.id, s.title, s.countries::text, s.opens_on, s.closes_on, s.status,
       COALESCE((SELECT json_agg(r.scores) FROM hr_pulse_response r WHERE r.survey_id = s.id), '[]')::text
FROM hr_pulse_survey s ORDER BY s.opens_on DESC`)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the pulse surveys: %w", err)
	}
	type survey struct {
		id, title, countriesJSON, status, answersJSON string
		opens, closes                                 time.Time
	}
	surveys, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (survey, error) {
		var s survey
		err := row.Scan(&s.id, &s.title, &s.countriesJSON, &s.opens, &s.closes, &s.status, &s.answersJSON)
		return s, err
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the pulse surveys: %w", err)
	}
	reg := register{
		path: "/pulse-surveys", title: "Staff Pulse Surveys", eyebrow: "Rewards and wellbeing",
		description: "Short anonymous surveys on purpose, support, workload, recognition and growth, to find what demotivates " +
			"staff before it costs a resignation. Results show only once five people have answered.",
		columns:    []string{"Survey", "Countries", "Open", "Responses", "Score", "Status"},
		actions:    []action{{label: "Open a survey", drawer: "/pulse-surveys/new"}},
		emptyTitle: "No pulse survey yet",
		emptyBody:  "Open a survey to hear from staff anonymously.",
	}
	open := 0
	var latest *float64
	for _, s := range surveys {
		var countries []string
		if err := json.Unmarshal([]byte(s.countriesJSON), &countries); err != nil {
			return register{}, fmt.Errorf("hrregister: reading survey %s's countries: %w", s.id, err)
		}
		if !slices.ContainsFunc(countries, func(c string) bool { return !in.reach.allows(c) }) {
			var answers []map[string]any
			if err := json.Unmarshal([]byte(s.answersJSON), &answers); err != nil {
				return register{}, fmt.Errorf("hrregister: reading survey %s's answers: %w", s.id, err)
			}
			res := results(answers)
			if latest == nil && res.shown {
				latest = res.overall
			}
			if s.status == "open" {
				open++
			}
			score := "Too few to show"
			if res.shown {
				score = "None of 5"
				if res.overall != nil {
					score = pyStr1(*res.overall) + " of 5"
				}
			}
			reg.rows = append(reg.rows, []string{dash(s.title), dash(strings.Join(countries, ", ")),
				s.opens.Format("02 Jan") + " to " + s.closes.Format("02 Jan 2006"), count(res.count), score,
				dash(labelOf(rules.PulseStatuses, s.status))})
			reg.rowActions = append(reg.rowActions, []action{{label: "Results", drawer: "/pulse-surveys/" + s.id}})
		}
	}
	morale := "—"
	if latest != nil {
		morale = pyStr1(*latest) + " of 5"
	}
	reg.metrics = []metric{
		{"Open surveys", count(open), "collecting answers", "info"},
		{"Latest morale score", morale, "average across the five statements", "success"},
	}
	return reg, nil
}

// allows is PeopleReach.allows_country.
func (r reach) allows(country string) bool {
	switch r.kind {
	case reachAll:
		return true
	case reachCountries:
		return country != "" && slices.Contains(r.countries, country)
	}
	return false
}
