package hrforms

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrregister"
)

// CompliancePath is the register the compliance saves return to.
const CompliancePath = "/compliance-register"

// allCountries is compliance_service.ALL_COUNTRIES.
const allCountries = "All"

// dueSoonDays is DUE_SOON_DAYS.
const dueSoonDays = 30

// complianceLabels are ComplianceStatus's labels.
var complianceLabels = map[string]string{"Compliant": "Compliant", "Due Soon": "Due soon", "Expired": "Expired", "Missing": "Missing"}

// RequirementCountries is compliance_requirement_drawer's country options:
// "Every country" first for the organisation's reach, then _country_options.
func (f Forms) RequirementCountries(ctx context.Context, p auth.Principal) ([]Choice, error) {
	names, everything, err := hrregister.PeopleReachCountryOptions(ctx, f.DB, p)
	if err != nil {
		return nil, err
	}
	out := []Choice{}
	if everything {
		out = append(out, Choice{allCountries, "Every country"})
	}
	for _, n := range names {
		out = append(out, Choice{n, n})
	}
	return out, nil
}

// Requirements is _evidence_fields's requirement options: visible_requirements
// as "Name · Country", by country then name.
func (f Forms) Requirements(ctx context.Context, p auth.Principal) ([]Choice, error) {
	where, args, err := f.visibleRequirements(ctx, p)
	if err != nil {
		return nil, err
	}
	rows, err := f.DB.Query(ctx, `SELECT id, name, country FROM hr_compliance_requirement r WHERE `+where+` ORDER BY country, name`, args...)
	if err != nil {
		return nil, fmt.Errorf("hrforms: reading the requirements: %w", err)
	}
	defer rows.Close()
	out := []Choice{}
	for rows.Next() {
		var id, name, country string
		if err := rows.Scan(&id, &name, &country); err != nil {
			return nil, fmt.Errorf("hrforms: reading the requirements: %w", err)
		}
		out = append(out, Choice{id, name + " · " + country})
	}
	return out, rows.Err()
}

// visibleRequirements is visible_requirements: every requirement for the
// organisation's reach; otherwise those for every country and the reach's
// own countries.
func (f Forms) visibleRequirements(ctx context.Context, p auth.Principal) (string, []any, error) {
	countries, everything, err := hrregister.PeopleReachCountries(ctx, f.DB, p)
	if err != nil {
		return "", nil, err
	}
	if everything {
		return "TRUE", nil, nil
	}
	return "(r.country = $1 OR r.country = ANY($2))", []any{allCountries, countries}, nil
}

// AddRequirement is compliance_requirement_add with add_requirement: HR only,
// named, a country the reader may set (every country the Admin's alone), not
// already there under any case; then the requirement and its audit row. It
// says the requirement's name.
func (f Forms) AddRequirement(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error) {
	if err := assertCompliance(p); err != nil {
		return "", err
	}
	name := strings.TrimSpace(values["name"])
	if name == "" {
		return "", refuse("Name the requirement.")
	}
	country := strings.TrimSpace(values["country"])
	if country == "" {
		return "", refuse("Choose the country the requirement applies in.")
	}
	err := f.write(ctx, func(tx pgx.Tx) error {
		_, everything, err := hrregister.PeopleReachCountryOptions(ctx, tx, p)
		if err != nil {
			return err
		}
		if country == allCountries {
			if !everything {
				return refuse("Only an Admin sets a requirement for every country.")
			}
		} else if ok, err := hrregister.PeopleReachAllowsCountry(ctx, tx, p, country); err != nil {
			return err
		} else if !ok {
			return refuse("You may only set requirements for the countries you oversee.")
		}
		var exists bool
		if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM hr_compliance_requirement WHERE country = $1 AND UPPER(name::text) = UPPER($2::text))`,
			country, name).Scan(&exists); err != nil {
			return fmt.Errorf("hrforms: reading the requirements: %w", err)
		}
		if exists {
			return refuse("That requirement already exists for this country.")
		}
		var description any
		if d := strings.TrimSpace(values["description"]); d != "" {
			description = d
		}
		mandatory := checked(values["is_mandatory"])
		now, id := f.now(), cuid.New()
		if _, err := tx.Exec(ctx, `INSERT INTO hr_compliance_requirement (id, created_at, updated_at, country, name, description, is_mandatory)
VALUES ($1, $2, $2, $3, $4, $5, $6)`, id, now, country, name, description, mandatory); err != nil {
			return fmt.Errorf("hrforms: adding the requirement: %w", err)
		}
		return auditRow(ctx, tx, "hr.compliance_requirement_added", "compliance_requirement", id, p,
			map[string]any{"country": country, "mandatory": mandatory}, o, now)
	})
	return name, err
}

// assertCompliance is compliance_service._assert_hr.
func assertCompliance(p auth.Principal) error {
	if assertHR(p) != nil {
		return refuse("Only HR may manage employment compliance.")
	}
	return nil
}

// derivedStatus is derived_status.
func derivedStatus(expiry *time.Time, hasEvidence bool, today time.Time) string {
	switch {
	case !hasEvidence:
		return "Missing"
	case expiry != nil && expiry.Before(today):
		return "Expired"
	case expiry != nil && !expiry.After(today.AddDate(0, 0, dueSoonDays)):
		return "Due Soon"
	}
	return "Compliant"
}

// RecordEvidence is compliance_evidence_save with record_evidence: the
// employee in reach, the requirement; HR only, staff the reader oversees, a
// requirement for every country or the employee's; then the record made or
// moved (a link kept when none is given, the status derived, the checker
// stamped when checked) and its audit row. It says the view's sentence.
func (f Forms) RecordEvidence(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error) {
	var said string
	err := f.write(ctx, func(tx pgx.Tx) error {
		s, err := f.staffInReach(ctx, tx, p, values["staff_id"])
		if err != nil {
			return err
		}
		if s == nil {
			return refuse("Choose an employee you oversee.")
		}
		var reqID, reqName, reqCountry string
		err = tx.QueryRow(ctx, `SELECT id, name, country FROM hr_compliance_requirement WHERE id = $1`, values["requirement_id"]).
			Scan(&reqID, &reqName, &reqCountry)
		missing := errors.Is(err, pgx.ErrNoRows)
		if err != nil && !missing {
			return fmt.Errorf("hrforms: reading the requirement: %w", err)
		}
		expiry, err := day(values["expiry_date"])
		if err != nil {
			return err
		}
		if err := assertCompliance(p); err != nil {
			return err
		}
		if missing {
			return refuse("Choose the employee and the requirement.")
		}
		if ok, err := hrregister.PeopleReachAllowsCountry(ctx, tx, p, s.country); err != nil {
			return err
		} else if !ok {
			return refuse("You may only record compliance for staff you oversee.")
		}
		if reqCountry != allCountries && reqCountry != s.country {
			return refuse("That requirement applies in " + reqCountry + ", not " + pyStr(s.country) + ".")
		}
		link := strings.TrimSpace(values["document_url"])
		verified := checked(values["verified"])
		var id string
		var stored *string
		err = tx.QueryRow(ctx, `SELECT id, document_url FROM hr_employee_compliance_record WHERE staff_id = $1 AND requirement_id = $2 FOR UPDATE`,
			s.id, reqID).Scan(&id, &stored)
		fresh := errors.Is(err, pgx.ErrNoRows)
		if err != nil && !fresh {
			return fmt.Errorf("hrforms: reading the record: %w", err)
		}
		var document *string
		switch {
		case link != "":
			document = &link
		case stored != nil:
			document = stored
		}
		status := derivedStatus(expiry, (document != nil && *document != "") || verified, f.today())
		now := f.now()
		if fresh {
			id = cuid.New()
			var by, at any
			if verified {
				by, at = nullable(p.UserID), now
			}
			if _, err := tx.Exec(ctx, `INSERT INTO hr_employee_compliance_record (id, created_at, updated_at, staff_id, requirement_id, status,
  document_url, expiry_date, verified_by_id, verified_at) VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9)`,
				id, now, s.id, reqID, status, document, expiry, by, at); err != nil {
				return fmt.Errorf("hrforms: recording the evidence: %w", err)
			}
		} else {
			if _, err := tx.Exec(ctx, `UPDATE hr_employee_compliance_record SET updated_at = $2, status = $3, document_url = $4, expiry_date = $5,
  verified_by_id = CASE WHEN $6 THEN $7 ELSE verified_by_id END, verified_at = CASE WHEN $6 THEN $2 ELSE verified_at END WHERE id = $1`,
				id, now, status, document, expiry, verified, nullable(p.UserID)); err != nil {
				return fmt.Errorf("hrforms: recording the evidence: %w", err)
			}
		}
		said = s.name + ": " + reqName + " is " + strings.ToLower(complianceLabels[status]) + "."
		return auditRow(ctx, tx, "hr.compliance_evidence_recorded", "employee_compliance_record", id, p,
			map[string]any{"staffId": s.id, "requirementId": reqID, "status": status, "verified": verified}, o, now)
	})
	return said, err
}

func nullable(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// pyStr is str() of an optional text: None for a missing country.
func pyStr(s string) string {
	if s == "" {
		return "None"
	}
	return s
}

// checked is a ticked box as the form posts it (bool(data.get(name))): the
// app sends an unticked box as empty, "false", "off" or "0".
func checked(v string) bool {
	v = strings.TrimSpace(strings.ToLower(v))
	return v != "" && v != "false" && v != "off" && v != "0"
}
