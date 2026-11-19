package hrregister

import (
	"context"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
)

// payReviewDays is how far ahead "Pay reviews due" looks.
const payReviewDays = 30

// compensationBenefits is compensation_benefits_view: the compensation
// records of the People records in reach whose person's name, salary band,
// pension scheme or status holds the search, by name. Amounts and bank
// details are never read: they stay inside each record's drawer.
func compensationBenefits(ctx context.Context, in input) (register, error) {
	visibleSQL, args := in.reach.visible(nil)
	searchSQL, args := contains(in.search, args, "u.name", "c.salary_band", "c.pension_scheme", "c.status")
	rows, err := in.db.Query(ctx, fmt.Sprintf(`
SELECT c.staff_id, u.name, sp.country, c.salary_band, c.medical_cover, c.pension_scheme, c.next_review_date, c.status
FROM hr_compensation c JOIN staff_profile sp ON sp.id = c.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE c.staff_id IN %s AND %s ORDER BY u.name`, visibleSQL, searchSQL), args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the compensation records: %w", err)
	}
	type record struct {
		staff, name, country, cover, pension, status string
		band                                         *string
		review                                       *time.Time
	}
	records, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (record, error) {
		var r record
		err := row.Scan(&r.staff, &r.name, &r.country, &r.band, &r.cover, &r.pension, &r.review, &r.status)
		return r, err
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the compensation records: %w", err)
	}
	reachSQL, margs := in.reach.profiles(nil)
	var missing int
	if err := in.db.QueryRow(ctx, fmt.Sprintf(`
SELECT count(*) FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.deleted_at IS NULL AND %s AND NOT (sp.onboarding_state = 'exited')
  AND NOT EXISTS (SELECT 1 FROM hr_compensation c WHERE c.staff_id = sp.id)`, reachSQL), margs...).Scan(&missing); err != nil {
		return register{}, fmt.Errorf("hrregister: counting the people without a compensation record: %w", err)
	}
	reg := register{
		path: "/compensation-benefits", primary: &action{label: "People Directory", href: "/staff"}, title: "Compensation & Benefits", eyebrow: "Rewards and wellbeing",
		description: "Salary bands, medical cover, pension and review dates for the people you oversee. Amounts and bank details " +
			"stay inside each record.",
		columns:    []string{"Team member", "Country", "Salary band", "Medical cover", "Pension", "Next review", "Status"},
		actions:    []action{{label: "Add a record", drawer: "/compensation-benefits/new"}},
		emptyTitle: "No compensation profiles in this scope",
		emptyBody:  "Add a record to capture an employee's band, benefits and review date.",
	}
	soon := in.today.AddDate(0, 0, payReviewDays)
	approved, inReview, due := 0, 0, 0
	for _, r := range records {
		switch r.status {
		case "Approved":
			approved++
		case "HR Review":
			inReview++
		}
		review := ""
		if r.review != nil {
			review = r.review.Format(time.DateOnly)
			if !r.review.After(soon) {
				due++
			}
		}
		pension := r.pension
		if pension == "" {
			pension = "None recorded"
		}
		reg.rows = append(reg.rows, []string{dash(r.name), dash(r.country), dash(deref(r.band)), dash(labelOf(rules.MedicalCovers, r.cover)),
			pension, dash(review), dash(labelOf(rules.CompensationStatuses, r.status))})
		reg.rowActions = append(reg.rowActions, []action{{label: "Update", drawer: "/compensation-benefits/" + r.staff}})
	}
	reg.metrics = []metric{
		{"Compensation profiles", count(len(records)), "configured records", "info"},
		{"Approved", count(approved), "completed HR review", "success"},
		{"In review", count(inReview), "requiring HR action", "warning"},
		{"Pay reviews due", count(due), "pay reviews due in 30 days", "info"},
		{"Missing profiles", count(missing), "current staff without a record", "warning"},
	}
	return reg, nil
}
