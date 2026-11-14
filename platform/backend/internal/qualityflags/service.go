package qualityflags

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/quality-checks"

const (
	roleAdmin            = "Admin"
	roleCountryDirector  = "CountryDirector"
	roleProgrammeLead    = "Program Lead"
	roleImpactAssessment = "ImpactAssessment"
)

// Service answers the page from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// Build answers /quality-checks; every other path is not this page's.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	where, args, err := s.visible(ctx, p)
	if err != nil {
		return nil, true, err
	}
	flags, err := s.flags(ctx, where, args)
	if err != nil {
		return nil, true, err
	}
	var leads []lead
	if role.Raises {
		if leads, err = s.programmeLeads(ctx, p); err != nil {
			return nil, true, err
		}
	}
	return page(p, role, flags, leads, query), true, nil
}

// visible is flags_visible_to, narrowed for Impact Assessment as the view
// narrows it, as a WHERE clause on cd_flag `f`.
func (s *Service) visible(ctx context.Context, p auth.Principal) (string, []any, error) {
	switch {
	case p.ActiveRole == roleImpactAssessment:
		// The service bounds the flags to the raisers whose People record is
		// in the reader's country; the view again, to the live records of the
		// reader's scope country.
		var profile *string
		err := s.db.QueryRow(ctx, `SELECT country FROM staff_profile WHERE user_id = $1 LIMIT 1`, p.UserID).Scan(&profile)
		if err != nil && err != pgx.ErrNoRows {
			return "", nil, fmt.Errorf("qualityflags: reading the reader's country: %w", err)
		}
		scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
		if err != nil {
			return "", nil, fmt.Errorf("qualityflags: resolving the reader's scope: %w", err)
		}
		where, args := "TRUE", []any{}
		if country := strings.TrimSpace(deref(profile)); country != "" {
			args = append(args, country)
			where += " AND f.raised_by_user_id IN (SELECT user_id FROM staff_profile WHERE country = $1)"
		}
		if scope.Country != "" {
			args = append(args, scope.Country)
			where += fmt.Sprintf(" AND f.raised_by_user_id IN (SELECT user_id FROM staff_profile WHERE country = $%d AND deleted_at IS NULL)", len(args))
		}
		return where, args, nil
	case slices.Contains(rules.MonitorRoles, p.ActiveRole):
		return "TRUE", nil, nil
	case p.UserID == "":
		return "FALSE", nil, nil
	case p.ActiveRole == roleCountryDirector:
		return "f.raised_by_user_id = $1", []any{p.UserID}, nil
	case p.ActiveRole == roleProgrammeLead:
		return "f.assigned_to_user_id = $1", []any{p.UserID}, nil
	}
	return "FALSE", nil, nil
}

// flag is a cd_flag row as the register writes it.
type flag struct {
	ID, RaisedBy, AssignedTo, Category, Note, Priority, Status string
	ScopeName, RaisedByName, RecommendedAction, DueDate        *string
	ResolutionNote, Assignee                                   *string
	CreatedAt                                                  time.Time
}

func (s *Service) flags(ctx context.Context, where string, args []any) ([]flag, error) {
	args = append(args, rules.Limit)
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT f.id, f.raised_by_user_id, f.assigned_to_user_id, f.category, f.note, f.priority, f.status,
       f.scope_name, f.raised_by_name, f.recommended_action, f.due_date, f.resolution_note,
       (SELECT u.name FROM "user" u WHERE u.id = f.assigned_to_user_id), f.created_at
FROM cd_flag f WHERE %s ORDER BY f.created_at DESC LIMIT $%d`, where, len(args)), args...)
	if err != nil {
		return nil, fmt.Errorf("qualityflags: reading the flags: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (flag, error) {
		var f flag
		err := r.Scan(&f.ID, &f.RaisedBy, &f.AssignedTo, &f.Category, &f.Note, &f.Priority, &f.Status,
			&f.ScopeName, &f.RaisedByName, &f.RecommendedAction, &f.DueDate, &f.ResolutionNote, &f.Assignee, &f.CreatedAt)
		return f, err
	})
	if err != nil {
		return nil, fmt.Errorf("qualityflags: reading the flags: %w", err)
	}
	return out, nil
}

// lead is one Programme Lead the form may assign a flag to.
type lead struct{ ID, Name string }

// programmeLeads is flag_services.program_leads: the active Programme Leads,
// a Country Director's bounded to their country, by name.
func (s *Service) programmeLeads(ctx context.Context, p auth.Principal) ([]lead, error) {
	where, args := "", []any{}
	if p.ActiveRole == roleCountryDirector {
		scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
		if err != nil {
			return nil, fmt.Errorf("qualityflags: resolving the reader's scope: %w", err)
		}
		if scope.CountryScope && scope.Country != "" {
			args = append(args, scope.Country)
			where = " AND u.id IN (SELECT user_id FROM staff_profile WHERE country = $1)"
		}
	}
	args = append(args, roleProgrammeLead)
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT u.id, u.name FROM "user" u
WHERE u.deleted_at IS NULL AND u.status = 'active' AND u.roles @> ARRAY[$%d]::varchar[]%s
ORDER BY u.name`, len(args), where), args...)
	if err != nil {
		return nil, fmt.Errorf("qualityflags: reading the Programme Leads: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (lead, error) {
		var l lead
		err := r.Scan(&l.ID, &l.Name)
		return l, err
	})
	if err != nil {
		return nil, fmt.Errorf("qualityflags: reading the Programme Leads: %w", err)
	}
	return out, nil
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
