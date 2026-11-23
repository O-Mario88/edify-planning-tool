package coreforms

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

const (
	roleAdmin      = "Admin"
	roleCCEO       = "CCEO"
	rolePL         = "Program Lead"
	roleCD         = "CountryDirector"
	roleIA         = "ImpactAssessment"
	rolePC         = "ProjectCoordinator"
	roleAccountant = "Accountant"

	recordDenied = "Access Denied: Your active role or assigned portfolio scope does not permit accessing this record."
	// oversightOnly is OVERSIGHT_ONLY_MESSAGE.
	oversightOnly = "You have read-only supervisory oversight of this record. Operational planning must be completed by the responsible CCEO."
	// schoolClosed is CLOSED_SCHOOL_MESSAGE.
	schoolClosed = "This school is closed, so it takes no new activities. Its history is on the Closed Schools page; reopen the school before planning work there."
	// TrainingRefused is CORE_TRAINING_REFUSED.
	TrainingRefused = "Core trainings are planned by the CCEO or Program Lead responsible for the school. Your role schedules school visits only."
	// AssignRefused is the assign drawer's words for a role that hands nothing over.
	AssignRefused = "You do not have permission to assign to a partner."
)

var (
	// schoolVisitRoles is SCHOOL_VISIT_ROLES.
	schoolVisitRoles = []string{roleCCEO, rolePL, roleCD, roleIA, rolePC}
	// countrySchedulingRoles is COUNTRY_SCHEDULING_ROLES.
	countrySchedulingRoles = []string{roleCD, roleIA, roleAdmin}
	// visitsOnlyRoles is VISIT_ONLY_ROLES.
	visitsOnlyRoles = []string{roleCD, roleIA, roleAccountant}
	// assignRoles is can_assign_to_partner: those who schedule, and the
	// operational admins.
	assignRoles = []string{roleCCEO, rolePL, rolePC, roleAdmin, roleIA}
	// closedStatuses is CLOSED_STATUSES.
	closedStatuses = []string{"temporarily_closed", "permanently_closed"}
)

// ErrNotFound is the school being absent.
var ErrNotFound = errors.New("coreforms: school not found")

// Refusal is a form the reader may not open, in the view's words.
type Refusal struct{ Message string }

func (r *Refusal) Error() string { return r.Message }

// School is what the forms read of a school.
type School struct {
	ID, Code, Name, Type, AccountOwner, ClusterID string
	ssaStatus                                     string
	closed                                        bool
}

func (sc School) gate() visitgate.School {
	return visitgate.School{ID: sc.ID, Code: sc.Code, Name: sc.Name, Type: sc.Type}
}

// Service reads the Core forms.
type Service struct {
	db    Querier
	now   func() time.Time
	gates visitgate.Rules
}

// Querier is the read this package needs from a pool.
type Querier = schooldirectory.Querier

// NewService builds the reader.
func NewService(db Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now, gates: schoolprofile.GateRules()}
}

// SchedulesVisitsOnly is schedules_visits_only: these roles plan no Core training.
func SchedulesVisitsOnly(role string) bool { return slices.Contains(visitsOnlyRoles, role) }

// MayAssign is can_assign_to_partner.
func MayAssign(role string) bool { return slices.Contains(assignRoles, role) }

// mayPlanSchool is may_plan_school: the direct portfolio, or a named country
// scheduling role.
func mayPlanSchool(role string, scope schooldirectory.Scope, schoolID string) bool {
	if slices.Contains(countrySchedulingRoles, role) {
		return true
	}
	if scope.CountryScope || scope.SummaryOnly {
		return false
	}
	return slices.Contains(scope.OwnSchoolIDs, schoolID)
}

func (s *Service) school(ctx context.Context, code string) (School, error) {
	return s.readSchool(ctx, "school_id = $1", code)
}

// schoolByKey is the Schedule drawer's lookup: a record id or a School ID.
func (s *Service) schoolByKey(ctx context.Context, key string) (School, error) {
	return s.readSchool(ctx, "(id = $1 OR school_id = $1)", key)
}

func (s *Service) readSchool(ctx context.Context, where, key string) (School, error) {
	var sc School
	var status string
	err := s.db.QueryRow(ctx, `SELECT id, COALESCE(school_id, ''), name, COALESCE(school_type, ''),
  COALESCE(account_owner_id, ''), COALESCE(cluster_id, ''), COALESCE(operational_status, ''),
  COALESCE(current_fy_ssa_status, '')
FROM school WHERE `+where+` AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1`, key).Scan(
		&sc.ID, &sc.Code, &sc.Name, &sc.Type, &sc.AccountOwner, &sc.ClusterID, &status, &sc.ssaStatus)
	if errors.Is(err, pgx.ErrNoRows) {
		return School{}, ErrNotFound
	}
	if err != nil {
		return School{}, fmt.Errorf("coreforms: reading the school: %w", err)
	}
	sc.closed = slices.Contains(closedStatuses, status)
	return sc, nil
}

func (s *Service) recordVisible(ctx context.Context, p auth.Principal, scope schooldirectory.Scope, schoolID string) (bool, error) {
	visible, err := schooldirectory.RecordVisible(ctx, s.db, p, scope, schoolID, schoolprofile.MayTakeSchools(p.ActiveRole))
	if err != nil {
		return false, fmt.Errorf("coreforms: reading whether the record is visible: %w", err)
	}
	return visible, nil
}

// VisitTarget is get_visit_target_school_or_404.
func (s *Service) VisitTarget(ctx context.Context, p auth.Principal, code string) (School, error) {
	sc, err := s.school(ctx, code)
	if err != nil {
		return School{}, err
	}
	if err := s.mayVisit(ctx, p, sc); err != nil {
		return School{}, err
	}
	return sc, nil
}

// mayVisit is the second half of get_visit_target_school_or_404.
func (s *Service) mayVisit(ctx context.Context, p auth.Principal, sc School) error {
	if !slices.Contains(schoolVisitRoles, p.ActiveRole) {
		scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
		if err != nil {
			return fmt.Errorf("coreforms: resolving the scope: %w", err)
		}
		visible, err := s.recordVisible(ctx, p, scope, sc.ID)
		if err != nil {
			return err
		}
		if !visible {
			return &Refusal{Message: recordDenied}
		}
		if !mayPlanSchool(p.ActiveRole, scope, sc.ID) && p.ActiveRole != roleAccountant {
			return &Refusal{Message: oversightOnly}
		}
	}
	if sc.closed {
		return &Refusal{Message: schoolClosed}
	}
	return nil
}

// Operational is get_operational_school_or_404.
func (s *Service) Operational(ctx context.Context, p auth.Principal, code string) (School, error) {
	sc, err := s.school(ctx, code)
	if err != nil {
		return School{}, err
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return School{}, fmt.Errorf("coreforms: resolving the scope: %w", err)
	}
	visible, err := s.recordVisible(ctx, p, scope, sc.ID)
	if err != nil {
		return School{}, err
	}
	if !visible {
		return School{}, &Refusal{Message: recordDenied}
	}
	if !mayPlanSchool(p.ActiveRole, scope, sc.ID) {
		return School{}, &Refusal{Message: oversightOnly}
	}
	if sc.closed {
		return School{}, &Refusal{Message: schoolClosed}
	}
	return sc, nil
}
