package hrregister

import (
	"context"
	"fmt"
	"slices"

	"github.com/jackc/pgx/v5"
)

// finishedStages are the stages an application leaves selection at.
var finishedStages = []string{"hired", "rejected", "withdrawn"}

// candidatePipeline is candidate_pipeline_view: the applications to the
// vacancies of the reach's countries whose candidate's name or email,
// vacancy's role or stage code holds the search, the last changed first.
// An application still in selection carries its next step's drawer ("Hire"
// once the offer is accepted, "Next step" before). The figures count the
// searched applications by stage.
func candidatePipeline(ctx context.Context, in input) (register, error) {
	scopeSQL, args := in.reach.byCountry("v.country", nil)
	searchSQL, args := contains(in.search, args, "c.name", "c.email", "v.role", "a.stage")
	rows, err := in.db.Query(ctx, fmt.Sprintf(`
SELECT a.id, c.name, v.role, v.country, a.stage, (a.updated_at AT TIME ZONE 'UTC')::date::text
FROM hr_application a JOIN hr_candidate c ON c.id = a.candidate_id JOIN hr_vacancy v ON v.id = a.vacancy_id
WHERE %s AND %s ORDER BY a.updated_at DESC`, scopeSQL, searchSQL), args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the applications: %w", err)
	}
	type application struct{ id, candidate, role, country, stage, updated string }
	apps, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (application, error) {
		var a application
		err := row.Scan(&a.id, &a.candidate, &a.role, &a.country, &a.stage, &a.updated)
		return a, err
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the applications: %w", err)
	}
	reg := register{
		path: "/candidate-pipeline", title: "Candidate Pipeline", eyebrow: "Staffing and recruiting",
		description: "Every candidate against the vacancies you oversee, by selection stage, from application to hire.",
		columns:     []string{"Candidate", "Vacancy", "Country", "Stage", "Updated"},
		actions:     []action{{"Record a candidate", "/candidate-pipeline/new"}},
		emptyTitle:  "No candidate applications yet",
		emptyBody:   "Record a candidate against an open vacancy to start selection.",
	}
	inSelection, screening, interviews, offers, hired := 0, 0, 0, 0, 0
	for _, a := range apps {
		switch a.stage {
		case "screening":
			screening++
		case "interview", "assessment", "reference_check":
			interviews++
		case "offer", "accepted":
			offers++
		case "hired":
			hired++
		}
		var next []action
		if !slices.Contains(finishedStages, a.stage) {
			inSelection++
			label := "Next step"
			if a.stage == "accepted" {
				label = "Hire"
			}
			next = []action{{label, "/candidate-pipeline/" + a.id}}
		}
		reg.rows = append(reg.rows, []string{dash(a.candidate), dash(a.role), dash(a.country), dash(labelOf(rules.ApplicationStages, a.stage)), dash(a.updated)})
		reg.rowActions = append(reg.rowActions, next)
	}
	reg.metrics = []metric{
		{"Applications", count(inSelection), "still in selection", "info"},
		{"Screening", count(screening), "in early assessment", "info"},
		{"Interviews", count(interviews), "interview, assessment or references", "info"},
		{"Offers", count(offers), "made or accepted", "info"},
		{"Hired", count(hired), "provisioned employees", "success"},
	}
	return reg, nil
}
