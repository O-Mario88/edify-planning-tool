package hrregister

import (
	"context"
	"fmt"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Review stage groups (performance_reviews_view).
var (
	reviewDone        = []string{"closed", "employee_acknowledged", "signed_and_archived"}
	reviewCalibrating = []string{"calibration", "hr_quality_review", "ready_for_slt_calibration"}
)

// performanceReviews is performance_reviews_view for everyone but a
// Programme Lead (whose reviewer's view, _team_performance_reviews, is the
// existing application's still): the reviews of the People records in reach
// for the year asked for (else the operational year) or for no year, whose
// person's name, period, type code or stage code holds the search, by due
// day and name. HR and Admin also see the manager's rating.
func performanceReviews(ctx context.Context, in input) (register, error) {
	if in.principal.ActiveRole == "Program Lead" {
		return register{}, errPassOn
	}
	hr := in.principal.ActiveRole == "HumanResources" || in.principal.ActiveRole == "Admin"
	fy := closedschools.StripSpace(in.query.Get("fy"))
	if fy == "" {
		fy = schooldirectory.OperationalFY(in.now)
	}
	visibleSQL, args := in.reach.visible(nil)
	args = append(args, fy)
	fyArg := len(args)
	searchSQL, args := contains(in.search, args, "u.name", "r.period", "r.review_type", "r.stage")
	rows, err := in.db.Query(ctx, fmt.Sprintf(`
SELECT u.name, r.review_type, r.period, mu.name, r.due_date, r.manager_rating, r.rating, r.stage
FROM hr_performance_review r JOIN staff_profile sp ON sp.id = r.staff_id JOIN "user" u ON u.id = sp.user_id
LEFT JOIN staff_profile mp ON mp.id = r.manager_id LEFT JOIN "user" mu ON mu.id = mp.user_id
WHERE r.staff_id IN %s AND (r.fy = $%d OR r.fy IS NULL) AND %s ORDER BY r.due_date, u.name`, visibleSQL, fyArg, searchSQL), args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the performance reviews: %w", err)
	}
	type review struct {
		name, kind, period, stage string
		manager, managerRating    *string
		rating                    *string
		due                       time.Time
	}
	reviews, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (review, error) {
		var r review
		err := row.Scan(&r.name, &r.kind, &r.period, &r.manager, &r.due, &r.managerRating, &r.rating, &r.stage)
		return r, err
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the performance reviews: %w", err)
	}
	columns := []string{"Team member", "Review", "Manager", "Due"}
	if hr {
		columns = append(columns, "Manager rating")
	}
	reg := register{
		path: "/performance-reviews", title: "Performance Reviews", eyebrow: "Performance and talent",
		description: "FY " + fy + " reviews for the people you oversee: where each one is in the cycle, the manager's rating and " +
			"the final rating once calibrated.",
		columns:    append(columns, "Final rating", "Stage"),
		emptyTitle: "No performance reviews in this scope",
		emptyBody:  defaultEmptyBody,
	}
	if hr {
		reg.primary = &action{label: "Open Performance Cycle", href: "/hr/performance-cycle?fy=" + fy}
	}
	done, overdueCount, calibrating := 0, 0, 0
	for _, r := range reviews {
		finished := slices.Contains(reviewDone, r.stage)
		overdue := !finished && r.due.Before(in.today)
		switch {
		case finished:
			done++
		case overdue:
			overdueCount++
		}
		if slices.Contains(reviewCalibrating, r.stage) {
			calibrating++
		}
		manager := "Not recorded"
		if r.manager != nil {
			manager = *r.manager
		}
		cells := []string{dash(r.name), labelOf(rules.ReviewTypes, r.kind) + " · " + r.period, dash(manager), r.due.Format(time.DateOnly)}
		if hr {
			cells = append(cells, dash(rating(r.managerRating)))
		}
		stage := labelOf(rules.ReviewStages, r.stage)
		if overdue {
			stage = "Overdue"
		}
		reg.rows = append(reg.rows, append(cells, dash(rating(r.rating)), dash(stage)))
	}
	reg.metrics = []metric{
		{"Reviews", count(len(reviews)), "FY " + fy, "info"},
		{"Completed", count(done), "acknowledged or archived", "success"},
		{"Overdue", count(overdueCount), "past due and not complete", "danger"},
		{"Awaiting calibration", count(calibrating), "HR or SLT to calibrate", "warning"},
	}
	return reg, nil
}

// rating is ratings.get(value or "", value): the rating's label, else the
// value as stored, else nothing.
func rating(value *string) string {
	if value == nil {
		return ""
	}
	return labelOf(rules.PerformanceRatings, *value)
}
