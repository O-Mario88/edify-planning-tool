package policycompliance

import (
	"context"
	"fmt"
	"net/url"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrregister"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/policy-compliance"

// Service answers the page from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// Build answers /policy-compliance; every other path is not this page's.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	scopeSQL, args, ok, err := s.scope(ctx, p)
	if err != nil {
		return nil, true, err
	}
	if !ok {
		// _scope_user_ids refuses every other role (Forbidden): the feed's
		// API answers it with a 403.
		return nil, true, pagegate.ErrForbidden
	}
	if role.Comments {
		waiting, err := s.commentsWaiting(ctx, p)
		if err != nil {
			return nil, true, err
		}
		if waiting {
			return nil, false, nil
		}
	}
	f := filters{Document: query.Get("document"), State: query.Get("state"), Role: query.Get("role")}
	where, args := f.where(scopeSQL, args)
	r, err := s.report(ctx, where, args)
	if err != nil {
		return nil, true, err
	}
	options, err := s.policies(ctx)
	if err != nil {
		return nil, true, err
	}
	return page(role, r, f, options, query), true, nil
}

// scope is _scope_user_ids as a condition on the acknowledgement `a`'s
// user: Admin and the RVP read everyone; Human Resources their people reach;
// a Country Director the live People records of their country (none
// without one); a Programme Lead their supervisees. ok is false for any
// other role, which the service refuses.
func (s *Service) scope(ctx context.Context, p auth.Principal) (string, []any, bool, error) {
	switch p.ActiveRole {
	case "Admin", "RegionalVicePresident":
		return "TRUE", nil, true, nil
	case "HumanResources":
		reachSQL, args, all, err := hrregister.PeopleReachProfiles(ctx, s.db, p, nil)
		if err != nil {
			return "", nil, false, fmt.Errorf("policycompliance: reading the people reach: %w", err)
		}
		if all {
			return "TRUE", nil, true, nil
		}
		return `a.user_id IN (SELECT sp.user_id FROM staff_profile sp WHERE sp.deleted_at IS NULL AND sp.user_id IS NOT NULL AND ` + reachSQL + `)`, args, true, nil
	case "CountryDirector":
		var country *string
		err := s.db.QueryRow(ctx, `SELECT country FROM staff_profile WHERE user_id = $1 LIMIT 1`, p.UserID).Scan(&country)
		if err != nil && err != pgx.ErrNoRows {
			return "", nil, false, fmt.Errorf("policycompliance: reading the director's country: %w", err)
		}
		if country == nil || *country == "" {
			return "FALSE", nil, true, nil
		}
		return `a.user_id IN (SELECT user_id FROM staff_profile WHERE deleted_at IS NULL AND user_id IS NOT NULL AND country = $1)`, []any{*country}, true, nil
	case "Program Lead", "ProgramLead":
		var staff string
		err := s.db.QueryRow(ctx, `SELECT id FROM staff_profile WHERE user_id = $1 LIMIT 1`, p.UserID).Scan(&staff)
		if err == pgx.ErrNoRows {
			return "FALSE", nil, true, nil
		}
		if err != nil {
			return "", nil, false, fmt.Errorf("policycompliance: reading the lead's People record: %w", err)
		}
		return `a.user_id IN (SELECT su.user_id FROM staff_supervisor_assignment l JOIN staff_profile su ON su.id = l.supervisee_id
  WHERE l.supervisor_id = $1 AND su.user_id IS NOT NULL)`, []any{staff}, true, nil
	}
	return "", nil, false, nil
}

// commentsWaiting is whether CommentService.queue holds a comment for the
// reader: any comment not archived, a Country Director's only those whose
// author's country is the principal's own `country` (the account has none,
// so only comments with no country).
func (s *Service) commentsWaiting(ctx context.Context, p auth.Principal) (bool, error) {
	sql := `SELECT EXISTS (SELECT 1 FROM document_comment WHERE status <> 'archived')`
	if p.ActiveRole == "CountryDirector" {
		sql = `SELECT EXISTS (SELECT 1 FROM document_comment WHERE status <> 'archived' AND author_country = '')`
	}
	var waiting bool
	if err := s.db.QueryRow(ctx, sql).Scan(&waiting); err != nil {
		return false, fmt.Errorf("policycompliance: reading the comment queue: %w", err)
	}
	return waiting, nil
}

// filters are the page's own query: each read as sent, only when given.
type filters struct{ Document, State, Role string }

func (f filters) where(scope string, args []any) (string, []any) {
	where := "d.status = ANY($" + fmt.Sprint(len(args)+1) + ") AND " + scope
	args = append(args, rules.ReadableStatuses)
	for _, c := range []struct{ col, value string }{{"a.document_id", f.Document}, {"a.state", f.State}, {"a.role_at_acknowledgement", f.Role}} {
		if c.value != "" {
			args = append(args, c.value)
			where += fmt.Sprintf(" AND %s = $%d", c.col, len(args))
		}
	}
	return where, args
}

// ack is one acknowledgement as the table writes it.
type ack struct {
	User, Role, Policy, State string
	Version                   int
	FirstOpened               time.Time
	Active, Required          int
	Offline                   bool
}

// report is what PolicyComplianceService.report counts and lists.
type report struct {
	Rows                                        []ack
	Required, Pending, Declined, Accepted, Late int
}

func (s *Service) report(ctx context.Context, where string, args []any) (report, error) {
	var r report
	today := s.now().In(zone).Format(time.DateOnly)
	countArgs := append(append([]any{}, args...), today)
	err := s.db.QueryRow(ctx, fmt.Sprintf(`
SELECT count(*), count(*) FILTER (WHERE a.state = 'pending'), count(*) FILTER (WHERE a.state = 'disagreed'),
  count(*) FILTER (WHERE a.state = 'agreed'), count(*) FILTER (WHERE a.state = 'pending' AND a.due_date < $%d::date)
FROM document_acknowledgement a JOIN document_asset d ON d.id = a.document_id WHERE %s`, len(countArgs), where), countArgs...).
		Scan(&r.Required, &r.Pending, &r.Declined, &r.Accepted, &r.Late)
	if err != nil {
		return r, fmt.Errorf("policycompliance: counting the acknowledgements: %w", err)
	}
	rowArgs := append(append([]any{}, args...), rules.RowLimit)
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT COALESCE(u.name, a.user_id), COALESCE(a.role_at_acknowledgement, ''), d.title, v.version_number, a.created_at,
  a.active_reading_seconds, d.required_reading_minutes * 60, a.offline_attestation, a.state
FROM document_acknowledgement a JOIN document_asset d ON d.id = a.document_id JOIN document_version v ON v.id = a.version_id
LEFT JOIN "user" u ON u.id = a.user_id
WHERE %s ORDER BY a.created_at DESC LIMIT $%d`, where, len(rowArgs)), rowArgs...)
	if err != nil {
		return r, fmt.Errorf("policycompliance: reading the acknowledgements: %w", err)
	}
	r.Rows, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (ack, error) {
		var a ack
		err := row.Scan(&a.User, &a.Role, &a.Policy, &a.Version, &a.FirstOpened, &a.Active, &a.Required, &a.Offline, &a.State)
		return a, err
	})
	if err != nil {
		return r, fmt.Errorf("policycompliance: reading the acknowledgements: %w", err)
	}
	return r, nil
}

// option is a policy the filter offers.
type option struct{ ID, Title string }

// policies are the readable documents an acknowledgement is required for,
// by title (DocumentAsset's ordering).
func (s *Service) policies(ctx context.Context) ([]option, error) {
	rows, err := s.db.Query(ctx, `SELECT id, title FROM document_asset WHERE acknowledgement_required AND status = ANY($1) ORDER BY title`, rules.ReadableStatuses)
	if err != nil {
		return nil, fmt.Errorf("policycompliance: reading the policies: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (option, error) {
		var o option
		err := row.Scan(&o.ID, &o.Title)
		return o, err
	})
}
