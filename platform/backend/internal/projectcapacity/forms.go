package projectcapacity

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	roleAdmin            = "Admin"
	roleImpactAssessment = "ImpactAssessment"
	stageNone            = "none"
	enrolledDayLayout    = "2 Jan 2006"
)

// enrolledZone is settings.TIME_ZONE, the zone an enrolment's day is read in.
var enrolledZone = func() *time.Location {
	zone, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		panic(fmt.Sprintf("projectcapacity: loading the zone: %v", err))
	}
	return zone
}()

// Choice is one option of a form's list.
type Choice struct {
	Value, Label string
	Taken        bool // already allocated: shown, not selectable
}

// SetForm is what project_capacity_set_view draws.
type SetForm struct {
	Projects []Choice
	Project  string // the chosen project, when the reader directs it
	Staff    []Choice
}

func projectChoiceLabel(p project) string {
	if p.Code == "" {
		return p.Name
	}
	return p.Name + " (" + p.Code + ")"
}

// SetCapacityForm is the Set Staff Capacity drawer: the live projects the
// reader directs and, once one is chosen, who may hold places on it.
func (s *Service) SetCapacityForm(ctx context.Context, p auth.Principal, wanted string) (SetForm, error) {
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return SetForm{}, fmt.Errorf("projectcapacity: resolving the reader's scope: %w", err)
	}
	projects, err := s.directed(ctx, p, scope)
	if err != nil {
		return SetForm{}, err
	}
	form := SetForm{Projects: make([]Choice, 0, len(projects))}
	for _, pr := range projects {
		form.Projects = append(form.Projects, Choice{Value: pr.ID, Label: projectChoiceLabel(pr)})
		if pr.ID == wanted {
			form.Project = pr.ID
		}
	}
	if form.Project == "" {
		return form, nil
	}
	form.Staff, err = s.eligibleStaff(ctx, form.Project)
	return form, err
}

// projectCountry is services.project_country: its coordinator's country, else
// the first enrolled school's. "" places it nowhere in particular.
func (s *Service) projectCountry(ctx context.Context, projectID string) (string, error) {
	var country *string
	err := s.db.QueryRow(ctx, `
SELECT sp.country FROM project pr JOIN staff_profile sp ON sp.id = pr.manager_staff_id AND sp.deleted_at IS NULL
 WHERE pr.id = $1`, projectID).Scan(&country)
	if errors.Is(err, pgx.ErrNoRows) {
		err = s.db.QueryRow(ctx, `
SELECT sp.country FROM project_staff_assignment a JOIN staff_profile sp ON sp.id = a.staff_id JOIN "user" u ON u.id = sp.user_id
 WHERE a.project_id = $1 AND a.is_active AND u.roles @> ARRAY[$2]::varchar[] ORDER BY a.id LIMIT 1`,
			projectID, roleProjectCoordinator).Scan(&country)
	}
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("projectcapacity: reading the project's coordinator: %w", err)
	}
	if country != nil && *country != "" {
		return *country, nil
	}
	country = nil
	err = s.db.QueryRow(ctx, `
SELECT r.country FROM project_school_assignment a JOIN school sc ON sc.id = a.school_id LEFT JOIN region r ON r.id = sc.region_id
 WHERE a.project_id = $1 ORDER BY a.id LIMIT 1`, projectID).Scan(&country)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("projectcapacity: reading the project's schools: %w", err)
	}
	if country == nil {
		return "", nil
	}
	return *country, nil
}

// eligibleStaff is capacity.eligible_staff, marking who already holds an
// allocation on the project.
func (s *Service) eligibleStaff(ctx context.Context, projectID string) ([]Choice, error) {
	country, err := s.projectCountry(ctx, projectID)
	if err != nil {
		return nil, err
	}
	rows, err := s.db.Query(ctx, `
SELECT sp.id, COALESCE(u.name, ''),
       EXISTS (SELECT 1 FROM project_staff_capacity c WHERE c.project_id = $1 AND c.staff_id = sp.id)
  FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
 WHERE sp.deleted_at IS NULL AND u.status = 'active' AND u.deleted_at IS NULL AND u.roles && $2::varchar[]
   AND ($3 = '' OR sp.country = $3)
 ORDER BY u.name`, projectID, rules.EligibleStaffRoles, country)
	if err != nil {
		return nil, fmt.Errorf("projectcapacity: reading the eligible staff: %w", err)
	}
	staff, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (Choice, error) {
		var c Choice
		err := row.Scan(&c.Value, &c.Label, &c.Taken)
		return c, err
	})
	if err != nil {
		return nil, fmt.Errorf("projectcapacity: reading a staff member: %w", err)
	}
	return staff, nil
}

// WithdrawForm is what project_withdraw_school_view draws.
type WithdrawForm struct {
	School, Project, Assigned, Holder string
	Block                             *Block
}

// WithdrawalReasons is capacity.WITHDRAWAL_REASONS.
func WithdrawalReasons() [][2]string { return slices.Clone(rules.WithdrawalReasons) }

// enrolmentHolders is whose an enrolment is.
type enrolmentHolders struct{ assignedStaff, assignedBy string }

// heldBy is may_withdraw's first half: the staff member whose allocation the
// enrolment uses, or who added it.
func (e enrolmentHolders) heldBy(p auth.Principal) bool {
	own := p.StaffProfileID
	return own != "" && (e.assignedStaff == own || e.assignedBy == own || e.assignedBy == p.UserID)
}

// stageOf is capacity._stage_of.
func stageOf(status, evidence string) string {
	statuses := rules.WithdrawalStatuses
	switch {
	case slices.Contains(statuses["not_work"], status):
		return stageNone
	case slices.Contains(statuses["completed"], status):
		return "completed"
	case slices.Contains(statuses["evidence"], status) || evidence == "uploaded" || evidence == "accepted":
		return "evidence"
	case slices.Contains(statuses["started"], status):
		return "started"
	}
	return "planned"
}

// blockFor is capacity.withdrawal_block: the furthest stage the school's
// project work has reached, or a partner holding it.
func blockFor(stages []string, handedOver bool) *Block {
	furthest := 0
	for _, stage := range stages {
		furthest = max(furthest, slices.Index(rules.WithdrawalStageOrder, stage))
	}
	if stage := rules.WithdrawalStageOrder[furthest]; stage != stageNone {
		block := rules.WithdrawalBlocks[stage]
		return &block
	}
	if handedOver {
		block := rules.WithdrawalBlocks["partner"]
		return &block
	}
	return nil
}

// WithdrawSchoolForm is the Withdraw School drawer, or nil when this reader
// may not take the enrolment out of its project.
func (s *Service) WithdrawSchoolForm(ctx context.Context, p auth.Principal, enrolmentID string) (*WithdrawForm, error) {
	var form WithdrawForm
	var holders enrolmentHolders
	var projectID, schoolID string
	var enrolled time.Time
	err := s.db.QueryRow(ctx, `
SELECT a.project_id, a.school_id, COALESCE(a.assigned_staff_id, ''), COALESCE(a.assigned_by, ''), a.created_at,
       sc.name, pr.name, COALESCE(u.name, '')
  FROM project_school_assignment a
  JOIN project pr ON pr.id = a.project_id AND pr.deleted_at IS NULL
  JOIN school sc ON sc.id = a.school_id
  LEFT JOIN staff_profile sp ON sp.id = a.assigned_staff_id
  LEFT JOIN "user" u ON u.id = sp.user_id
 WHERE a.id = $1`, enrolmentID).Scan(&projectID, &schoolID, &holders.assignedStaff, &holders.assignedBy, &enrolled,
		&form.School, &form.Project, &form.Holder)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("projectcapacity: reading the enrolment: %w", err)
	}
	if !holders.heldBy(p) {
		directs, err := s.directsProject(ctx, p, projectID)
		if err != nil {
			return nil, err
		}
		if !directs {
			return nil, nil
		}
	}
	form.Assigned = enrolled.In(enrolledZone).Format(enrolledDayLayout)
	if holders.assignedStaff != "" {
		form.Assigned += " · " + form.Holder
	} else {
		form.Holder = ""
	}
	form.Block, err = s.withdrawalBlock(ctx, projectID, schoolID)
	if err != nil {
		return nil, err
	}
	return &form, nil
}

// directsProject is authority.directs_project_work.
func (s *Service) directsProject(ctx context.Context, p auth.Principal, projectID string) (bool, error) {
	if p.ActiveRole == roleAdmin || p.ActiveRole == roleImpactAssessment {
		return true, nil
	}
	if p.ActiveRole != roleProjectCoordinator {
		return false, nil
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return false, fmt.Errorf("projectcapacity: resolving the reader's scope: %w", err)
	}
	clause, extra, reads := readableClause(p, scope, 2)
	if !reads {
		return false, nil
	}
	var directs bool
	err = s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM project p WHERE p.deleted_at IS NULL AND p.id = $1`+clause+`)`,
		append([]any{projectID}, extra...)...).Scan(&directs)
	if err != nil {
		return false, fmt.Errorf("projectcapacity: reading whether the reader runs the project: %w", err)
	}
	return directs, nil
}

func (s *Service) withdrawalBlock(ctx context.Context, projectID, schoolID string) (*Block, error) {
	rows, err := s.db.Query(ctx, `SELECT COALESCE(status, ''), COALESCE(evidence_status, '') FROM activity
 WHERE project_id = $1 AND school_id = $2 AND deleted_at IS NULL`, projectID, schoolID)
	if err != nil {
		return nil, fmt.Errorf("projectcapacity: reading the school's project work: %w", err)
	}
	stages, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (string, error) {
		var status, evidence string
		err := row.Scan(&status, &evidence)
		return stageOf(strings.TrimSpace(status), evidence), err
	})
	if err != nil {
		return nil, fmt.Errorf("projectcapacity: reading a piece of project work: %w", err)
	}
	var handedOver bool
	err = s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM partner_assignment
 WHERE project_id = $1 AND school_id = $2 AND status IS DISTINCT FROM $3)`, projectID, schoolID, rules.PartnerReturnedStatus).Scan(&handedOver)
	if err != nil {
		return nil, fmt.Errorf("projectcapacity: reading the school's partner work: %w", err)
	}
	return blockFor(stages, handedOver), nil
}
