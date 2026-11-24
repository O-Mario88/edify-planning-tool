package extrawork

import (
	"context"
	"fmt"
	"net/url"
	"time"

	_ "time/tzdata" // the page's days are Kampala's wherever the gateway runs

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers.
const Path = "/extra-work"

// ErrNotAvailable is the page refused to the reader's role, which the
// existing feed answers as a page that is not there.
var ErrNotAvailable = pagegate.ErrNotAvailable

// zone is settings.TIME_ZONE: the zone timezone.localdate() reads today in
// and |date writes a time in.
var zone = mustZone("Africa/Nairobi")

func mustZone(name string) *time.Location {
	z, err := time.LoadLocation(name)
	if err != nil {
		panic("extrawork: " + err.Error())
	}
	return z
}

// Service builds Extra Assigned Work.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
	// saves is Extra Assigned Work's saves (save.go), set only when Go makes them.
	saves *saver
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// Build answers path for p with the page's query. served is false for a
// path this package does not answer.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, ErrNotAvailable
	}
	now := s.now()
	// (request.GET.get("fy") or "").strip() or get_operational_fy()
	fy := closedschools.StripSpace(query.Get("fy"))
	if fy == "" {
		fy = schooldirectory.OperationalFY(now)
	}
	v := view{role: role, fy: fy, query: query, today: dayOf(now.In(zone)), saves: s.Saves()}
	var err error
	if v.mine, err = s.read(ctx, "mine", `assignee_id = $1`, `due_date`, rules.Limits.Mine, p.UserID, fy); err != nil {
		return nil, true, err
	}
	if v.assignedByMe, err = s.read(ctx, "assigned by me", `assigner_id = $1`, `due_date`, rules.Limits.AssignedByMe, p.UserID, fy); err != nil {
		return nil, true, err
	}
	if v.toReview, err = s.read(ctx, "to review", `reviewer_id = $1 AND status = 'submitted'`, `submitted_at`, rules.Limits.ToReview, p.UserID, fy); err != nil {
		return nil, true, err
	}
	// A supervising PL monitors CD assignments on their team (read-only).
	if v.monitoring, err = s.read(ctx, "monitoring", `supervising_pl_id = $1 AND NOT (assigner_id = $1)`, `due_date`, rules.Limits.Monitoring, p.UserID, fy); err != nil {
		return nil, true, err
	}
	if v.summary, err = s.performance(ctx, p.UserID, fy, v.today); err != nil {
		return nil, true, err
	}
	return page(v), true, nil
}

func dayOf(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}

// read is one section's rows of the year: those matching where, in order,
// up to limit.
func (s *Service) read(ctx context.Context, section, where, order string, limit int, user, fy string) ([]assignment, error) {
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT id, title, instruction, assigner_role, assignee_role, due_date, status, return_reason,
       outcome, evidence_note, evidence_uri, contribution_points::text, submitted_at
FROM hr_extra_assignment WHERE %s AND fy = $2 ORDER BY %s LIMIT %d`, where, order, limit), user, fy)
	if err != nil {
		return nil, fmt.Errorf("extrawork: reading %s: %w", section, err)
	}
	out, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (assignment, error) {
		var a assignment
		err := r.Scan(&a.ID, &a.Title, &a.Instruction, &a.AssignerRole, &a.AssigneeRole, &a.Due, &a.Status,
			&a.ReturnReason, &a.Outcome, &a.EvidenceNote, &a.EvidenceURI, &a.Points, &a.SubmittedAt)
		return a, err
	})
	if err != nil {
		return nil, fmt.Errorf("extrawork: reading %s: %w", section, err)
	}
	return out, nil
}

// performance is performance_summary: the reader's year as assignee,
// counted once, and whether the year's scoring policy is approved.
func (s *Service) performance(ctx context.Context, user, fy string, today time.Time) (summary, error) {
	var out summary
	err := s.db.QueryRow(ctx, `
SELECT count(*) FILTER (WHERE status = 'verified'),
       count(*) FILTER (WHERE status = ANY($3)),
       count(*) FILTER (WHERE status = 'submitted'),
       count(*) FILTER (WHERE status = ANY($3) AND due_date < $4::date),
       (sum(contribution_points) FILTER (WHERE status = 'verified'))::text,
       EXISTS (SELECT 1 FROM hr_extra_work_scoring_policy WHERE fy = $2 AND status = 'approved')
FROM hr_extra_assignment WHERE assignee_id = $1 AND fy = $2`,
		user, fy, rules.OpenStatuses, today.Format(time.DateOnly)).Scan(&out.verified, &out.open, &out.submitted, &out.overdue, &out.points, &out.policyApproved)
	if err != nil {
		return out, fmt.Errorf("extrawork: reading the performance lane: %w", err)
	}
	return out, nil
}
