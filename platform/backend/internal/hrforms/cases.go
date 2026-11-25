package hrforms

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrregister"
)

// The register each save returns to.
const (
	SafetyPath      = "/health-safety"
	OffboardingPath = "/offboarding"
	CasesPath       = "/employee-relations"
)

// Severities are ERSeverity's choices.
var Severities = []Choice{{"low", "Low"}, {"medium", "Medium"}, {"high", "High"}, {"critical", "Critical"}}

// IncidentCategories are SafetyIncidentCategory's choices.
var IncidentCategories = []Choice{
	{"injury", "Injury"}, {"road_traffic", "Road traffic incident"}, {"illness", "Work-related illness"},
	{"near_miss", "Near miss"}, {"security", "Security incident"}, {"hazard", "Hazard reported"}, {"other", "Other"},
}

// ExitReasons are ExitReason's choices.
var ExitReasons = []Choice{
	{"resignation", "Resignation"}, {"end_of_contract", "End of contract"}, {"retirement", "Retirement"},
	{"probation_not_confirmed", "Probation not confirmed"}, {"dismissal", "Dismissal"}, {"redundancy", "Redundancy"},
	{"death_in_service", "Death in service"}, {"other", "Other"},
}

// CaseTypes are ERCaseType's choices.
var CaseTypes = []Choice{
	{"disciplinary", "Disciplinary matter"}, {"grievance", "Grievance"}, {"dispute", "Dispute between staff"},
	{"conflict", "Conflict"}, {"harassment", "Harassment concern"}, {"conduct", "Conduct concern"},
	{"whistleblowing", "Whistleblowing"}, {"safeguarding", "Safeguarding referral"},
}

func among(cs []Choice, v string) bool {
	return slices.ContainsFunc(cs, func(c Choice) bool { return c.Value == v })
}

func labelOf(cs []Choice, v string) string {
	for _, c := range cs {
		if c.Value == v {
			return c.Label
		}
	}
	return v
}

// CountryOptions is _country_options.
func (f Forms) CountryOptions(ctx context.Context, p auth.Principal) ([]Choice, error) {
	names, _, err := hrregister.PeopleReachCountryOptions(ctx, f.DB, p)
	if err != nil {
		return nil, err
	}
	out := make([]Choice, 0, len(names))
	for _, n := range names {
		out = append(out, Choice{n, n})
	}
	return out, nil
}

// profile is a live People record found by id (StaffProfile.objects), any
// reach: found is false for none.
func profile(ctx context.Context, tx pgx.Tx, id string) (staff, bool, error) {
	var s staff
	var userID, country *string
	err := tx.QueryRow(ctx, `SELECT sp.id, sp.user_id, COALESCE(u.name, ''), sp.country FROM staff_profile sp
LEFT JOIN "user" u ON u.id = sp.user_id WHERE sp.id = $1 AND sp.deleted_at IS NULL`, id).Scan(&s.id, &userID, &s.name, &country)
	if errors.Is(err, pgx.ErrNoRows) {
		return s, false, nil
	}
	if err != nil {
		return s, false, fmt.Errorf("hrforms: reading the People record: %w", err)
	}
	if userID != nil {
		s.userID = *userID
	}
	if country != nil {
		s.country = *country
	}
	return s, true, nil
}

// assertCountry is the services' _assert_country.
func assertCountry(ctx context.Context, tx pgx.Tx, p auth.Principal, country, what string) error {
	ok, err := hrregister.PeopleReachAllowsCountry(ctx, tx, p, country)
	if err != nil {
		return err
	}
	if !ok {
		return refuse("You may only record " + what + " in the countries you oversee.")
	}
	return nil
}

// pyInt is int() of a form value: surrounding spaces and a sign allowed.
func pyInt(raw string) (int, bool) {
	n, err := strconv.Atoi(strings.TrimSpace(raw))
	return n, err == nil
}

// ReportIncident is incident_report with report_incident: HR only, the
// employee affected (if named) found, a country (the employee's when none is
// chosen) the reader oversees, a known category and severity, a day not in
// the future, a description and whole days lost; then the incident and its
// audit row. It says the view's sentence.
func (f Forms) ReportIncident(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error) {
	on, err := day(values["incident_date"])
	if err != nil {
		return "", err
	}
	var said string
	err = f.write(ctx, func(tx pgx.Tx) error {
		if err := assertHR(p); err != nil {
			return err
		}
		var affected *staff
		if id := strings.TrimSpace(values["affected_staff_id"]); id != "" {
			s, found, err := profile(ctx, tx, id)
			if err != nil {
				return err
			}
			if !found {
				return refuse("That employee was not found.")
			}
			affected = &s
		}
		country := strings.TrimSpace(values["country"])
		if country == "" && affected != nil {
			country = affected.country
		}
		if country == "" {
			return refuse("Choose the country the incident happened in.")
		}
		if err := assertCountry(ctx, tx, p, country, "incidents"); err != nil {
			return err
		}
		category := values["category"]
		if !among(IncidentCategories, category) {
			return refuse("Choose what kind of incident this was.")
		}
		severity := values["severity"]
		if severity == "" {
			severity = "medium"
		}
		if !among(Severities, severity) {
			return refuse("Choose a severity from the list.")
		}
		if on == nil {
			return refuse("Record the date of the incident.")
		}
		if on.After(f.today()) {
			return refuse("An incident cannot be dated in the future.")
		}
		description := strings.TrimSpace(values["description"])
		if description == "" {
			return refuse("Describe what happened.")
		}
		lost := 0
		if raw := values["days_lost"]; raw != "" {
			n, ok := pyInt(raw)
			if !ok {
				return refuse("Days lost must be a whole number.")
			}
			lost = max(n, 0)
		}
		var affectedID any
		if affected != nil {
			affectedID = affected.id
		}
		now, id := f.now(), cuid.New()
		if _, err := tx.Exec(ctx, `INSERT INTO hr_safety_incident (id, created_at, updated_at, country, incident_date, location, category,
  severity, description, immediate_action, corrective_action, days_lost, status, closed_at, affected_staff_id, reported_by_id)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9, '', $10, 'reported', NULL, $11, $12)`,
			id, now, country, *on, strings.TrimSpace(values["location"]), category, severity, description,
			strings.TrimSpace(values["immediate_action"]), lost, affectedID, nullable(p.UserID)); err != nil {
			return fmt.Errorf("hrforms: reporting the incident: %w", err)
		}
		said = labelOf(IncidentCategories, category) + " reported."
		return auditRow(ctx, tx, "hr.safety_incident_reported", "safety_incident", id, p,
			map[string]any{"category": category, "severity": severity, "country": country}, o, now)
	})
	return said, err
}

// StartOffboarding is offboarding_start with open_offboarding: the employee
// and the handover owner found (any reach), HR only, someone the reader
// oversees, never oneself, a last working day, a known reason, a handover
// owner other than the employee, not already offboarded; then the plan
// (made or moved) and its audit row. It says the view's sentence.
func (f Forms) StartOffboarding(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error) {
	var said string
	err := f.write(ctx, func(tx pgx.Tx) error {
		s, found, err := profile(ctx, tx, values["staff_id"])
		if err != nil {
			return err
		}
		handover, hasHandover, err := profile(ctx, tx, values["handover_owner_id"])
		if err != nil {
			return err
		}
		last, err := day(values["last_working_day"])
		if err != nil {
			return err
		}
		if assertHR(p) != nil {
			return refuse("Only HR may complete an offboarding.")
		}
		if !found {
			return refuse("Choose the employee who is leaving.")
		}
		if ok, err := hrregister.PeopleReachAllowsCountry(ctx, tx, p, s.country); err != nil {
			return err
		} else if !ok {
			return refuse("You may only offboard staff in the countries you oversee.")
		}
		if s.userID != "" && s.userID == p.UserID {
			return refuse("You cannot start your own offboarding.")
		}
		if last == nil {
			return refuse("Record the last working day.")
		}
		reason := values["exit_reason"]
		if !among(ExitReasons, reason) {
			return refuse("Choose why the employee is leaving.")
		}
		if hasHandover && handover.id == s.id {
			return refuse("The handover owner must be someone else.")
		}
		var planID, status string
		err = tx.QueryRow(ctx, `SELECT id, status FROM hr_offboarding WHERE staff_id = $1 FOR UPDATE`, s.id).Scan(&planID, &status)
		fresh := errors.Is(err, pgx.ErrNoRows)
		if err != nil && !fresh {
			return fmt.Errorf("hrforms: reading the offboarding: %w", err)
		}
		if !fresh && status == "Closed" {
			return refuse("This employee has already been offboarded.")
		}
		var owner any
		if hasHandover {
			owner = handover.id
		}
		now := f.now()
		if fresh {
			planID = cuid.New()
			_, err = tx.Exec(ctx, `INSERT INTO hr_offboarding (id, created_at, updated_at, status, last_working_day, clearance_completed,
  handover_owner_id, staff_id, exit_note, exit_reason) VALUES ($1, $2, $2, 'Initiated', $3, FALSE, $4, $5, $6, $7)`,
				planID, now, *last, owner, s.id, values["note"], reason)
		} else {
			_, err = tx.Exec(ctx, `UPDATE hr_offboarding SET updated_at = $2, last_working_day = $3, exit_reason = $4, exit_note = $5,
  handover_owner_id = $6 WHERE id = $1`, planID, now, *last, reason, values["note"], owner)
		}
		if err != nil {
			return fmt.Errorf("hrforms: starting the offboarding: %w", err)
		}
		said = "Offboarding started for " + s.name + "."
		return auditRow(ctx, tx, "hr.offboarding_opened", "offboarding_plan", planID, p, map[string]any{
			"staffId": s.id, "lastWorkingDay": last.Format("2006-01-02"), "exitReason": reason, "handoverOwnerId": owner,
		}, o, now)
	})
	return said, err
}

// viewerCountry is _country(principal): the country on the reader's own
// People record (user.staff_profile, deleted or not).
func viewerCountry(ctx context.Context, tx pgx.Tx, p auth.Principal) (string, error) {
	var country *string
	err := tx.QueryRow(ctx, `SELECT country FROM staff_profile WHERE user_id = $1 ORDER BY deleted_at NULLS FIRST LIMIT 1`, p.UserID).Scan(&country)
	if errors.Is(err, pgx.ErrNoRows) || country == nil {
		return "", nil
	}
	return *country, err
}

// OpenCase is er_open with open_case: HR only, described, a known type and
// severity, the subject and complainant found (any reach) and different, a
// dispute naming both; a country (the subject's, else the reader's own) the
// reader oversees; then the case, submitted and owned by the reader, and its
// audit row (never the narrative). It says the view's sentence.
func (f Forms) OpenCase(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error) {
	hearing, err := day(values["hearing_date"])
	if err != nil {
		return "", err
	}
	var said string
	err = f.write(ctx, func(tx pgx.Tx) error {
		if assertHR(p) != nil {
			return refuse("Only HR may manage employee-relations cases.")
		}
		description := strings.TrimSpace(values["description"])
		if description == "" {
			return refuse("A description is required to open a case.")
		}
		kind := values["case_type"]
		if kind == "" {
			return refuse("A case type is required.")
		}
		if !among(CaseTypes, kind) {
			return refuse("Choose a case type from the list.")
		}
		severity := values["severity"]
		if severity == "" {
			severity = "medium"
		}
		if !among(Severities, severity) {
			return refuse("Choose a severity from the list.")
		}
		var subject, complainant *staff
		if id := strings.TrimSpace(values["subject_staff_id"]); id != "" {
			s, found, err := profile(ctx, tx, id)
			if err != nil {
				return err
			}
			if !found {
				return refuse("That employee was not found.")
			}
			subject = &s
		}
		if id := strings.TrimSpace(values["complainant_staff_id"]); id != "" {
			s, found, err := profile(ctx, tx, id)
			if err != nil {
				return err
			}
			if !found {
				return refuse("The complainant was not found.")
			}
			if subject != nil && s.id == subject.id {
				return refuse("The complainant and the subject must be different people.")
			}
			complainant = &s
		}
		if kind == "dispute" && (subject == nil || complainant == nil) {
			return refuse("A dispute names both parties: the subject and the complainant.")
		}
		country := strings.TrimSpace(values["country"])
		if country == "" && subject != nil {
			country = subject.country
		}
		if country == "" {
			if country, err = viewerCountry(ctx, tx, p); err != nil {
				return err
			}
		}
		if country == "" {
			return refuse("A country is required to scope this case.")
		}
		if ok, err := hrregister.PeopleReachAllowsCountry(ctx, tx, p, country); err != nil {
			return err
		} else if !ok {
			return refuse("You may only open cases in the countries you oversee.")
		}
		var subjectID, complainantID, hearingDay any
		if subject != nil {
			subjectID = subject.id
		}
		if complainant != nil {
			complainantID = complainant.id
		}
		if hearing != nil {
			hearingDay = *hearing
		}
		now, id := f.now(), cuid.New()
		if _, err := tx.Exec(ctx, `INSERT INTO hr_relations_case (id, created_at, updated_at, case_type, severity, status, description,
  findings, is_confidential, case_owner_id, action_taken, appeal_note, closed_at, country, investigator_id, opened_at, raised_by_id,
  retention_until, subject_staff_id, complainant_staff_id, hearing_date, sanction)
VALUES ($1, $2, $2, $3, $4, 'submitted', $5, NULL, $6, $7, NULL, NULL, NULL, $8, NULL, $2, $7, NULL, $9, $10, $11, '')`,
			id, now, kind, severity, description, checked(values["is_confidential"]), nullable(p.UserID), country,
			subjectID, complainantID, hearingDay); err != nil {
			return fmt.Errorf("hrforms: opening the case: %w", err)
		}
		said = labelOf(CaseTypes, kind) + " case opened and awaiting triage."
		return auditRow(ctx, tx, "hr.er_case_opened", "employee_relations_case", id, p, map[string]any{
			"caseType": kind, "status": "submitted", "severity": severity, "hasSubject": subject != nil,
		}, o, now)
	})
	return said, err
}
