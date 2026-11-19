package todos

import (
	"context"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
)

// The RVP's and the Country Director's executive rows (todo_service
// _rvp_todos and _strategy_note_todos), and the Country Director's turn of
// the builders other roles share.

const (
	rvpRole = "RegionalVicePresident"
	cdRole  = "CountryDirector"
	// rvpPending is a budget submitted to the RVP.
	rvpPending = "submitted_to_rvp"
	// strategyOpen is an RVP strategy note the Country Director has not
	// acted on.
	strategyOpen = "open"
	// strategyNoteLimit is how many notes the queue lists.
	strategyNoteLimit = 8
	// strategyInstructionLength is how much of a note's instruction its
	// row describes.
	strategyInstructionLength = 180
)

// rvpTodos is _rvp_todos: every General Budget and Country Annual Budget of
// the operational year submitted to the RVP, in every country (the RVP is a
// regional role).
func rvpTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role != rvpRole {
		return nil, nil
	}
	approval := func(id, title, description, linked, url string) todo {
		return todo{ID: id, Title: title, Description: description, Category: "Approvals", Priority: "high",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning", DueLabel: "—", DueTone: "neutral",
			Actionable: true, Linked: linked, ActionLabel: "Review", ActionURL: url, Shape: url, Due: &r.today}
	}
	rows, err := s.db.Query(ctx, `SELECT id, month_key, total_amount, activity_count FROM monthly_work_plan_budget
WHERE fy = $1 AND status = $2 ORDER BY month_key ASC`, r.fy, rvpPending)
	if err != nil {
		return nil, err
	}
	type budget struct {
		id, month  string
		total      int64
		activities int
	}
	budgets, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (budget, error) {
		var b budget
		return b, row.Scan(&b.id, &b.month, &b.total, &b.activities)
	})
	if err != nil {
		return nil, err
	}
	var out []todo
	for _, b := range budgets {
		out = append(out, approval("rvp-mwpb-"+b.id, "Review General Budget "+b.month, "UGX "+thousands(int(b.total))+" across "+
			strconv.Itoa(b.activities)+" plan-backed activities awaits your approval.", "General Budget · "+b.month, "/country-budget/"))
	}
	// An unordered queryset in the existing builder: the order rows were
	// filed in.
	rows, err = s.db.Query(ctx, `SELECT id, fy, total_amount FROM country_annual_budget
WHERE fy = $1 AND status = $2 ORDER BY created_at ASC, id ASC`, r.fy, rvpPending)
	if err != nil {
		return nil, err
	}
	annual, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, fy string
		var total int64
		if err := row.Scan(&id, &fy, &total); err != nil {
			return todo{}, err
		}
		return approval("rvp-annual-"+id, "Review Country Annual Budget FY "+fy, "UGX "+thousands(int(total))+
			" annual baseline awaiting approval — approval locks the baseline.", "Annual Budget · FY "+fy, "/dashboard"), nil
	})
	if err != nil {
		return nil, err
	}
	return append(out, annual...), nil
}

// strategyNoteTodos is _strategy_note_todos: the RVP's open strategy notes
// addressed to the Country Director, or to no one, eight of them.
func strategyNoteTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role != cdRole {
		return nil, nil
	}
	// An unordered queryset in the existing builder: the order notes were
	// written in.
	rows, err := s.db.Query(ctx, `SELECT id, priority_label, scope, instruction, deadline FROM rvp_strategy_note
WHERE status = $1 AND (responsible_cd_id = $2 OR responsible_cd_id IS NULL)
ORDER BY created_at ASC, id ASC LIMIT $3`, strategyOpen, r.p.UserID, strategyNoteLimit)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, label, scope, instruction string
		var deadline *time.Time
		if err := row.Scan(&id, &label, &scope, &instruction, &deadline); err != nil {
			return todo{}, err
		}
		t := todo{ID: "strategy-note-" + id, Title: "Act on RVP guidance — " + label, Description: firstRunes(instruction, strategyInstructionLength),
			Category: "Strategy", Priority: "high", StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
			DueLabel: "—", DueTone: "neutral", Actionable: true, Linked: scope, ActionLabel: "Open",
			ActionURL: "/dashboard", Shape: "/dashboard", Due: &r.today}
		if deadline != nil {
			t.Due = dateOf(*deadline)
			t.DueLabel, t.DueTone = t.Due.Format("Jan 02"), "warning"
		}
		return t, nil
	})
}

// firstRunes is Python's s[:n].
func firstRunes(s string, n int) string {
	runes := []rune(s)
	if len(runes) <= n {
		return s
	}
	return string(runes[:n])
}

// cdOr is cd for the Country Director and other for everyone else.
func cdOr(cd, other builder) builder {
	return func(ctx context.Context, s *Service, r *reader) ([]todo, error) {
		if r.role == cdRole {
			return cd(ctx, s, r)
		}
		return other(ctx, s, r)
	}
}

// directorSSAGuard is collection_todos for the Country Director, the
// fallback verifier of SSA scores an Impact Assessment officer keyed: any
// record awaiting verification passes the reader on.
func directorSSAGuard(ctx context.Context, s *Service, _ *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM ssa_record WHERE deleted_at IS NULL AND verification_status = $1`,
		rules.IA.CollectionRecordPending))
}
