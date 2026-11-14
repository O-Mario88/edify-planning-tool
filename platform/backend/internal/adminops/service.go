package adminops

import (
	"context"
	"fmt"
	"net/url"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The registers' paths.
const (
	SupportPath     = "/admin-ops/support"
	IncidentsPath   = "/admin-ops/incidents"
	MaintenancePath = "/admin-ops/maintenance"
	RepairPath      = "/data-repair"
	MyPlanPath      = "/admin-ops/my-plan"
	PlanningPath    = "/admin-ops/planning"
)

// Service answers the registers from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the registers over db.
func NewService(db schooldirectory.Querier) *Service { return &Service{db: db, now: time.Now} }

// Build answers the three registers; every other path is not theirs.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	page, ok := rules.Pages[path]
	if !ok {
		return nil, false, nil
	}
	if !page.Roles[p.ActiveRole].Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	switch path {
	case SupportPath:
		return s.support(ctx, query.Get("status"))
	case IncidentsPath:
		return s.incidents(ctx, query.Get("status"))
	case RepairPath:
		if query.Get("repair") != "" {
			// A dry run writes an audit row (DataRepairService.dry_run): the
			// existing application answers it.
			return nil, false, nil
		}
		return repairPage(), true, nil
	case MyPlanPath:
		return s.myPlan(ctx)
	case PlanningPath:
		return s.planning(ctx, query)
	}
	return s.maintenance(ctx)
}

// ticket is an admin_support_ticket row as the queue writes it.
type ticket struct {
	ID, Reference, Title, Category, Status, ReporterRole, Route string
	CreatedAt                                                   time.Time
}

func (s *Service) support(ctx context.Context, status string) (*screensv1.GetPageResponse, bool, error) {
	var untriaged, open int
	if err := s.db.QueryRow(ctx, `SELECT count(*) FILTER (WHERE status = $1), count(*) FILTER (WHERE NOT status = ANY($2))
FROM admin_support_ticket`, rules.UntriagedTicketStatus, rules.ClosedTicketStatuses).Scan(&untriaged, &open); err != nil {
		return nil, true, fmt.Errorf("adminops: counting the tickets: %w", err)
	}
	// status is filtered as sent (`if status:`), never stripped.
	rows, err := s.db.Query(ctx, `
SELECT id, reference, title, category, status, reporter_role, route, created_at FROM admin_support_ticket
WHERE $1 = '' OR status = $1 ORDER BY created_at DESC LIMIT $2`, status, rules.Limits.Tickets)
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the tickets: %w", err)
	}
	tickets, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (ticket, error) {
		var t ticket
		err := r.Scan(&t.ID, &t.Reference, &t.Title, &t.Category, &t.Status, &t.ReporterRole, &t.Route, &t.CreatedAt)
		return t, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the tickets: %w", err)
	}
	return supportPage(tickets, untriaged, open), true, nil
}

// incident is an admin_system_incident row as the list writes it.
type incident struct {
	ID, Title, Severity, Status, Route, Component string
	LastDetectedAt                                time.Time
}

func (s *Service) incidents(ctx context.Context, status string) (*screensv1.GetPageResponse, bool, error) {
	rows, err := s.db.Query(ctx, `
SELECT id, title, severity, status, affected_route, affected_component, last_detected_at FROM admin_system_incident
WHERE $1 = '' OR status = $1 ORDER BY last_detected_at DESC LIMIT $2`, status, rules.Limits.Incidents)
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the incidents: %w", err)
	}
	incidents, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (incident, error) {
		var i incident
		err := r.Scan(&i.ID, &i.Title, &i.Severity, &i.Status, &i.Route, &i.Component, &i.LastDetectedAt)
		return i, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the incidents: %w", err)
	}
	return incidentsPage(incidents), true, nil
}

// template is a recurring maintenance template; work an open maintenance
// work item.
type template struct {
	Name, Category      string
	Frequency, Estimate int
	NextDue             time.Time
}

type work struct {
	Reference, Title, Status string
	Scheduled                *time.Time
}

func (s *Service) maintenance(ctx context.Context) (*screensv1.GetPageResponse, bool, error) {
	rows, err := s.db.Query(ctx, `
SELECT name, category, frequency_days, estimated_minutes, next_due_date FROM admin_maintenance_template ORDER BY next_due_date`)
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the maintenance templates: %w", err)
	}
	templates, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (template, error) {
		var t template
		err := r.Scan(&t.Name, &t.Category, &t.Frequency, &t.Estimate, &t.NextDue)
		return t, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the maintenance templates: %w", err)
	}
	rows, err = s.db.Query(ctx, `
SELECT reference, title, status, scheduled_date FROM admin_ops_work_item
WHERE category = ANY($1) AND status <> $2 ORDER BY created_at DESC LIMIT $3`,
		rules.MaintenanceCategories, rules.DoneWorkItemStatus, rules.Limits.MaintenanceWork)
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the maintenance work: %w", err)
	}
	open, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (work, error) {
		var w work
		err := r.Scan(&w.Reference, &w.Title, &w.Status, &w.Scheduled)
		return w, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the maintenance work: %w", err)
	}
	return maintenancePage(templates, open), true, nil
}
