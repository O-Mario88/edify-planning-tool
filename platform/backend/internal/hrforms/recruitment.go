package hrforms

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrregister"
)

// The registers the recruitment saves return to.
const (
	RecruitmentPath = "/recruitment"
	PipelinePath    = "/candidate-pipeline"
)

// Vacancy kinds and employment types the request offers.
var (
	VacancyKinds    = []Choice{{"replacement", "Replacement"}, {"new_role", "New role"}}
	EmploymentTypes = []Choice{{"Full-time", "Full-time"}, {"Part-time", "Part-time"},
		{"Fixed-term contract", "Fixed-term contract"}, {"Consultant", "Consultant"}}
)

// assertRecruiter is recruitment_service._assert_recruiter.
func assertRecruiter(p auth.Principal) error {
	if assertHR(p) != nil {
		return refuse("Only HR may manage recruitment.")
	}
	return nil
}

// assertInCountry is _assert_in_country: the organisation's reach anywhere;
// otherwise a reach with countries, the country among them.
func assertInCountry(ctx context.Context, tx pgx.Tx, p auth.Principal, country string) error {
	countries, everything, err := hrregister.PeopleReachCountries(ctx, tx, p)
	if err != nil || everything {
		return err
	}
	if len(countries) == 0 {
		return refuse("Your staff profile has no country.")
	}
	for _, c := range countries {
		if c == country && country != "" {
			return nil
		}
	}
	return refuse("You may only manage recruitment for " + strings.Join(countries, ", ") + ".")
}

func orNull(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// RequestVacancy is vacancy_request with request_vacancy: HR only, a country
// (the reader's own when none is chosen) they recruit in, a role; then the
// vacancy, pending approval, and its audit row. It says the view's sentence.
func (f Forms) RequestVacancy(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error) {
	target, err := day(values["target_start_date"])
	if err != nil {
		return "", err
	}
	var said string
	err = f.write(ctx, func(tx pgx.Tx) error {
		if err := assertRecruiter(p); err != nil {
			return err
		}
		country := values["country"]
		if country == "" {
			if country, err = viewerCountry(ctx, tx, p); err != nil {
				return err
			}
		}
		country = strings.TrimSpace(country)
		if country == "" {
			return refuse("A country is required.")
		}
		if err := assertInCountry(ctx, tx, p, country); err != nil {
			return err
		}
		role := strings.TrimSpace(values["role"])
		if role == "" {
			return refuse("A role is required.")
		}
		employment := values["employment_type"]
		if employment == "" {
			employment = "Full-time"
		}
		kind := values["replacement_or_new_role"]
		if kind == "" {
			kind = "new_role"
		}
		var start any
		if target != nil {
			start = *target
		}
		now, id := f.now(), cuid.New()
		if _, err := tx.Exec(ctx, `INSERT INTO hr_vacancy (id, created_at, updated_at, country, department, role, employment_type,
  reason_for_vacancy, replacement_or_new_role, required_skills, target_start_date, approved_salary_band, budget_source, status,
  approved_by_id, reporting_manager_id, approved_at, closed_at, decision_reason, requested_by_id)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'pending_approval', NULL, NULL, NULL, NULL, NULL, $13)`,
			id, now, country, strings.TrimSpace(values["department"]), role, employment, values["reason"], kind,
			values["required_skills"], start, orNull(values["salary_band"]), orNull(values["budget_source"]), nullable(p.UserID)); err != nil {
			return fmt.Errorf("hrforms: requesting the vacancy: %w", err)
		}
		said = role + " vacancy submitted for approval."
		return auditRow(ctx, tx, "hr.vacancy_requested", "vacancy", id, p, map[string]any{"role": role}, o, now)
	})
	return said, err
}

// OpenVacancies is application_record_drawer's options: the open vacancies
// in the reader's reach (scope_by_country) as "Role · Country", by country
// then role, the first 200.
func (f Forms) OpenVacancies(ctx context.Context, p auth.Principal) ([]Choice, error) {
	countries, everything, err := hrregister.PeopleReachCountries(ctx, f.DB, p)
	if err != nil {
		return nil, err
	}
	where, args := "FALSE", []any{}
	switch {
	case everything:
		where = "TRUE"
	case len(countries) > 0:
		where, args = "country = ANY($1)", []any{countries}
	}
	rows, err := f.DB.Query(ctx, `SELECT id, role || ' · ' || country FROM hr_vacancy WHERE status = 'open' AND `+where+`
ORDER BY country, role LIMIT 200`, args...)
	if err != nil {
		return nil, fmt.Errorf("hrforms: reading the open vacancies: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (Choice, error) {
		var c Choice
		return c, r.Scan(&c.Value, &c.Label)
	})
}

// RecordApplication is application_record with record_application: HR only,
// the vacancy found, in a country they recruit in, open; a name and email;
// the candidate found by email or made (consent stamped when given); not
// already applied; then the application and its audit row. It says the
// view's sentence.
func (f Forms) RecordApplication(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error) {
	var said string
	err := f.write(ctx, func(tx pgx.Tx) error {
		if err := assertRecruiter(p); err != nil {
			return err
		}
		var vacancy, country, status string
		err := tx.QueryRow(ctx, `SELECT id, country, status FROM hr_vacancy WHERE id = $1`, values["vacancy_id"]).Scan(&vacancy, &country, &status)
		if errors.Is(err, pgx.ErrNoRows) {
			return refuse("Vacancy not found.")
		}
		if err != nil {
			return fmt.Errorf("hrforms: reading the vacancy: %w", err)
		}
		if err := assertInCountry(ctx, tx, p, country); err != nil {
			return err
		}
		if status != "open" {
			return refuse("This vacancy is not open for applications.")
		}
		email := strings.ToLower(strings.TrimSpace(values["email"]))
		name := strings.TrimSpace(values["name"])
		if email == "" || name == "" {
			return refuse("A candidate name and email are required.")
		}
		now := f.now()
		var candidate, candidateName string
		err = tx.QueryRow(ctx, `SELECT id, name FROM hr_candidate WHERE email = $1`, email).Scan(&candidate, &candidateName)
		if errors.Is(err, pgx.ErrNoRows) {
			candidate, candidateName = cuid.New(), name
			var consent any
			if checked(values["consent"]) {
				consent = now
			}
			if _, err := tx.Exec(ctx, `INSERT INTO hr_candidate (id, created_at, updated_at, name, email, phone, skills, talent_pool_notes,
  consent_given_at, retention_until) VALUES ($1, $2, $2, $3, $4, $5, $6, NULL, $7, NULL)`,
				candidate, now, name, email, orNull(strings.TrimSpace(values["phone"])), values["skills"], consent); err != nil {
				return fmt.Errorf("hrforms: recording the candidate: %w", err)
			}
		} else if err != nil {
			return fmt.Errorf("hrforms: reading the candidate: %w", err)
		}
		var applied bool
		if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM hr_application WHERE vacancy_id = $1 AND candidate_id = $2)`,
			vacancy, candidate).Scan(&applied); err != nil {
			return fmt.Errorf("hrforms: reading the applications: %w", err)
		}
		if applied {
			return refuse("This candidate has already applied for this vacancy.")
		}
		id := cuid.New()
		if _, err := tx.Exec(ctx, `INSERT INTO hr_application (id, created_at, updated_at, stage, status_notes, candidate_id, vacancy_id)
VALUES ($1, $2, $2, 'applied', NULL, $3, $4)`, id, now, candidate, vacancy); err != nil {
			return fmt.Errorf("hrforms: recording the application: %w", err)
		}
		said = candidateName + " recorded as applied."
		return auditRow(ctx, tx, "hr.application_recorded", "application", id, p,
			map[string]any{"vacancyId": vacancy, "candidateId": candidate}, o, now)
	})
	return said, err
}
