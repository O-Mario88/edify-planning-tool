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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/perfconversation"
)

// RecoveryPath is the register the recommendation returns to.
const RecoveryPath = "/recovery-plans"

// RecoveryCauses are RecoveryCause's choices.
var RecoveryCauses = []Choice{
	{"capacity", "Capacity — portfolio beyond capacity"}, {"workload", "Workload — competing demands"}, {"skill", "Skill gap"},
	{"availability", "Availability — leave or absence"}, {"data_quality", "Data quality — work done but not credited"},
	{"manager_support", "Manager support"}, {"conduct", "Conduct"}, {"other", "Other"},
}

// oversight is review_authority.is_oversight.
func oversight(p auth.Principal) bool {
	return p.ActiveRole == "HumanResources" || p.ActiveRole == "Human Resources" || p.ActiveRole == "Admin"
}

// ownProfile is the reader's People record (user.staff_profile).
func ownProfile(ctx context.Context, q interface {
	QueryRow(context.Context, string, ...any) pgx.Row
}, p auth.Principal) (string, error) {
	if p.StaffProfileID != "" {
		return p.StaffProfileID, nil
	}
	var id string
	err := q.QueryRow(ctx, `SELECT id FROM staff_profile WHERE user_id = $1 ORDER BY deleted_at NULLS FIRST LIMIT 1`, p.UserID).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	return id, err
}

// RecoveryPeople is recovery_new_drawer's employee options: HR and the
// Admin pick from their reach ("Name · Country"); anyone else from
// _reviewee_profiles, the people they review (never themself, still
// employed), by name.
func (f Forms) RecoveryPeople(ctx context.Context, p auth.Principal) ([]Choice, error) {
	if oversight(p) {
		return f.PeopleOptions(ctx, p)
	}
	return f.reviewees(ctx, p, "")
}

// reviewees is _reviewee_profiles (only id when id is set).
func (f Forms) reviewees(ctx context.Context, p auth.Principal, only string) ([]Choice, error) {
	me, err := ownProfile(ctx, f.DB, p)
	if err != nil || me == "" {
		return []Choice{}, err
	}
	roles := perfconversation.ReviewedRoles(p.ActiveRole)
	if len(roles) == 0 {
		return []Choice{}, nil
	}
	args := []any{me, roles}
	where := ""
	if only != "" {
		args = append(args, only)
		where = " AND sp.id = $3"
	}
	rows, err := f.DB.Query(ctx, `
SELECT sp.id, u.name FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $1) AND u.active_role = ANY($2)
  AND sp.id <> $1 AND sp.deleted_at IS NULL AND u.deleted_at IS NULL AND sp.onboarding_state IS DISTINCT FROM 'exited'`+where+`
ORDER BY u.name, sp.id LIMIT 500`, args...)
	if err != nil {
		return nil, fmt.Errorf("hrforms: reading the people reviewed: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (Choice, error) {
		var c Choice
		return c, r.Scan(&c.Value, &c.Label)
	})
	return out, err
}

// RecommendPlan is recovery_recommend with performance_engine.recommend_pip:
// the employee in the reader's reach (and, outside HR, one they review);
// never oneself; outside HR only the employee's reviewer; a reason; then a
// draft formal plan and its audit row. It says the view's sentence.
func (f Forms) RecommendPlan(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error) {
	notFound := "Choose someone you review."
	if oversight(p) {
		notFound = "Choose an employee you oversee."
	}
	var said string
	err := f.write(ctx, func(tx pgx.Tx) error {
		s, err := f.staffInReach(ctx, tx, p, values["staff_id"])
		if err != nil {
			return err
		}
		if s == nil {
			return refuse(notFound)
		}
		if !oversight(p) {
			mine, err := f.reviewees(ctx, p, s.id)
			if err != nil {
				return err
			}
			if len(mine) == 0 {
				return refuse(notFound)
			}
		}
		cause := values["cause"]
		if cause == "" {
			cause = "other"
		}
		start, err := day(values["start_date"])
		if err != nil {
			return err
		}
		if s.userID != "" && s.userID == p.UserID {
			return refuse("You cannot recommend a performance plan for yourself.")
		}
		if !oversight(p) {
			var role string
			if err := tx.QueryRow(ctx, `SELECT COALESCE(active_role, '') FROM "user" WHERE id = $1`, s.userID).Scan(&role); err != nil &&
				!errors.Is(err, pgx.ErrNoRows) {
				return fmt.Errorf("hrforms: reading the employee's role: %w", err)
			}
			me, err := ownProfile(ctx, tx, p)
			if err != nil {
				return err
			}
			ok, err := perfconversation.Reviews(ctx, tx, s.id, role, me, f.now())
			if err != nil {
				return err
			}
			if !ok {
				return refuse("Only the employee's reviewer or HR may recommend a formal plan.")
			}
		}
		reason := values["reason"]
		if strings.TrimSpace(reason) == "" {
			return refuse("A PIP recommendation needs its reason recorded.")
		}
		on := f.today()
		if start != nil {
			on = *start
		}
		now, id := f.now(), cuid.New()
		if _, err := tx.Exec(ctx, `INSERT INTO hr_pip_plan (id, created_at, updated_at, status, cause, action_plan, start_date, end_date,
  staff_id, cause_evidence, plan_type, recommended_by_id) VALUES ($1, $2, $2, 'draft', $3, '(to be agreed at activation)', $4, $4, $5, $6, 'formal', $7)`,
			id, now, cause, on, s.id, reason, nullable(p.UserID)); err != nil {
			return fmt.Errorf("hrforms: recommending the plan: %w", err)
		}
		said = "Formal plan recommended for " + s.name + ". It waits for HR authorisation."
		return auditRow(ctx, tx, "hr.pip_recommended", "PerformanceImprovementPlan", id, p, map[string]any{"reason": reason}, o, now)
	})
	return said, err
}
