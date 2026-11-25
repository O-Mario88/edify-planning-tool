package hrforms

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pydecimal"
)

// CompensationPath is the register the save returns to.
const CompensationPath = "/compensation-benefits"

// The compensation form's choices.
var (
	Currencies           = []Choice{{"UGX", "UGX"}, {"KES", "KES"}, {"RWF", "RWF"}, {"TZS", "TZS"}, {"USD", "USD"}}
	MedicalCovers        = []Choice{{"none", "No medical cover"}, {"individual", "Individual"}, {"family", "Employee and family"}}
	CompensationStatuses = []Choice{{"HR Review", "In HR review"}, {"Approved", "Approved"}}
)

// amount is rewards_wellbeing_service._amount: commas dropped, blank is
// zero, a number not below zero.
func amount(raw, label string) (pydecimal.Decimal, error) {
	raw = strings.TrimSpace(strings.ReplaceAll(raw, ",", ""))
	if raw == "" {
		return pydecimal.Zero(), nil
	}
	d, err := pydecimal.Parse(raw)
	if err != nil {
		return d, refuse(label + " must be a number.")
	}
	if d.Sign() < 0 {
		return d, refuse(label + " cannot be negative.")
	}
	return d, nil
}

type compensation struct {
	id, currency, medical, pension, other, status string
	band                                          *string
	base, allowances                              pydecimal.Decimal
	effective, review                             *time.Time
}

func sameDay(a, b *time.Time) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	return a.Equal(*b)
}

func sameText(a, b *string) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	return *a == *b
}

// SaveCompensation is compensation_save with save_compensation: the employee
// in the reader's reach, both days readable; HR only, a country the reader
// oversees, never oneself, a known status and medical cover; the record
// found or made with its defaults (get_or_create), each field set where it
// differs, the amounts read last; then the record saved (the amounts
// rounded by the column, as the existing save leaves them to PostgreSQL:
// half away from zero) and an audit row
// naming the fields that changed, never the amounts. It says the view's
// sentence.
func (f Forms) SaveCompensation(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error) {
	var said string
	err := f.write(ctx, func(tx pgx.Tx) error {
		s, err := f.staffInReach(ctx, tx, p, values["staff_id"])
		if err != nil {
			return err
		}
		if s == nil {
			return refuse("Choose an employee you oversee.")
		}
		effective, err := day(values["effective_date"])
		if err != nil {
			return err
		}
		review, err := day(values["next_review_date"])
		if err != nil {
			return err
		}
		if err := assertHR(p); err != nil {
			return err
		}
		if err := assertCountry(ctx, tx, p, s.country, "compensation"); err != nil {
			return err
		}
		if s.userID != "" && s.userID == p.UserID {
			return refuse("You cannot set your own compensation.")
		}
		status := values["status"]
		if status == "" {
			status = "HR Review"
		}
		if !among(CompensationStatuses, status) {
			return refuse("Choose a status from the list.")
		}
		medical := values["medical_cover"]
		if medical == "" {
			medical = "none"
		}
		if !among(MedicalCovers, medical) {
			return refuse("Choose the medical cover from the list.")
		}
		now := f.now()
		var c compensation
		var base, allowances string
		err = tx.QueryRow(ctx, `SELECT id, salary_band, currency, base_salary::text, allowances::text, medical_cover, pension_scheme,
  other_benefits, effective_date, next_review_date, status FROM hr_compensation WHERE staff_id = $1 FOR UPDATE`, s.id).
			Scan(&c.id, &c.band, &c.currency, &base, &allowances, &c.medical, &c.pension, &c.other, &c.effective, &c.review, &c.status)
		created := errors.Is(err, pgx.ErrNoRows)
		switch {
		case created:
			// get_or_create: the model's defaults, written at once.
			c = compensation{id: cuid.New(), currency: "UGX", medical: "none", status: "HR Review",
				base: pydecimal.Zero(), allowances: pydecimal.Zero()}
			if _, err := tx.Exec(ctx, `INSERT INTO hr_compensation (id, created_at, updated_at, salary_band, base_salary, allowances,
  benefits_tier, bank_name, account_number, status, staff_id, currency, effective_date, medical_cover, next_review_date, other_benefits,
  pension_scheme) VALUES ($1, $2, $2, NULL, 0, 0, NULL, NULL, NULL, 'HR Review', $3, 'UGX', NULL, 'none', NULL, '', '')`,
				c.id, now, s.id); err != nil {
				return fmt.Errorf("hrforms: making the compensation record: %w", err)
			}
		case err != nil:
			return fmt.Errorf("hrforms: reading the compensation record: %w", err)
		default:
			if c.base, err = pydecimal.Parse(base); err != nil {
				return err
			}
			if c.allowances, err = pydecimal.Parse(allowances); err != nil {
				return err
			}
		}
		var band *string
		if b := strings.TrimSpace(values["salary_band"]); b != "" {
			band = &b
		}
		currency := values["currency"]
		if currency == "" {
			currency = "UGX"
		}
		currency = strings.ToUpper(strings.TrimSpace(currency))
		if r := []rune(currency); len(r) > 8 {
			currency = string(r[:8])
		}
		newBase, err := amount(values["base_salary"], "Base salary")
		if err != nil {
			return err
		}
		newAllowances, err := amount(values["allowances"], "Allowances")
		if err != nil {
			return err
		}
		pension, other := strings.TrimSpace(values["pension_scheme"]), strings.TrimSpace(values["other_benefits"])
		changed := []any{}
		mark := func(field string, differs bool) {
			if differs {
				changed = append(changed, field)
			}
		}
		mark("salary_band", !sameText(c.band, band))
		mark("currency", c.currency != currency)
		mark("base_salary", c.base.Cmp(newBase) != 0)
		mark("allowances", c.allowances.Cmp(newAllowances) != 0)
		mark("medical_cover", c.medical != medical)
		mark("pension_scheme", c.pension != pension)
		mark("other_benefits", c.other != other)
		mark("effective_date", !sameDay(c.effective, effective))
		mark("next_review_date", !sameDay(c.review, review))
		mark("status", c.status != status)
		slices.SortFunc(changed, func(a, b any) int { return strings.Compare(a.(string), b.(string)) })
		if _, err := tx.Exec(ctx, `UPDATE hr_compensation SET updated_at = $2, salary_band = $3, currency = $4, base_salary = $5::numeric,
  allowances = $6::numeric, medical_cover = $7, pension_scheme = $8, other_benefits = $9, effective_date = $10, next_review_date = $11,
  status = $12 WHERE id = $1`, c.id, now, band, currency, newBase.String(), newAllowances.String(), medical,
			pension, other, effective, review, status); err != nil {
			return fmt.Errorf("hrforms: saving the compensation record: %w", err)
		}
		action := "hr.compensation_updated"
		if created {
			action = "hr.compensation_created"
		}
		said = "Compensation saved for " + s.name + "."
		return auditRow(ctx, tx, action, "compensation_record", c.id, p, map[string]any{"staffId": s.id, "fieldsChanged": changed}, o, now)
	})
	return said, err
}
