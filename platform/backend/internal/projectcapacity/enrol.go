package projectcapacity

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Add to Project's save (school_views.assign_to_project_flow through
// apps.projects.services.assign_school), with Django absent.

// EnrolForm is the drawer's fields.
type EnrolForm struct {
	ProjectID, ProjectType, ParticipationType, StartDate, SupportArea, CoordinatorID, Notes string
}

// EnrolAnswer is action_result: saved with its message, refused (the drawer's
// error page), or an error the drawer shows beside its fields.
type EnrolAnswer struct {
	Saved                   bool
	Message, Refused, Error string
}

// projectStatusLabels is ProjectStatus' labels.
var projectStatusLabels = map[string]string{
	"proposed": "Proposed", "active": "Active", "under_review": "Under Review", "paused": "Paused",
	"scaling": "Scaling", "closed": "Closed",
}

// countryAssignerRoles is PROJECT_COUNTRY_ASSIGNER_ROLES.
var countryAssignerRoles = []string{"ImpactAssessment", "CountryDirector", "Admin"}

// closedSchoolMessage is lifecycle_service.CLOSED_SCHOOL_MESSAGE.
const closedSchoolMessage = "This school is closed, so it takes no new activities. Its history is on " +
	"the Closed Schools page; reopen the school before planning work there."

type enrolSaver struct {
	pool   *pgxpool.Pool
	push   activities.NoticePush
	live   activities.NoticePublisher
	logger *slog.Logger
}

// WithSaves lets the service save Add to Project.
func (s *Service) WithSaves(pool *pgxpool.Pool, push activities.NoticePush, live activities.NoticePublisher, logger *slog.Logger) *Service {
	s.saves = &enrolSaver{pool: pool, push: push, live: live, logger: logger}
	return s
}

// ssaBand is ssa_score_band's label.
func ssaBand(score float64) string {
	switch {
	case score >= 8.0:
		return "Strong"
	case score >= 6.0:
		return "Improving"
	case score >= 5.0:
		return "Warning"
	}
	return "Critical"
}

type enrolProject struct {
	id, name, status, focus, manager, intervention string
	targets                                        []string
}

type enrolSchool struct {
	id, code, name, schoolType, operational, country, owner, district, cluster string
}

// Enrol makes the save; schoolPK is the school the drawer is for.
func (s *Service) Enrol(ctx context.Context, p auth.Principal, schoolPK string, f EnrolForm, origin activities.Origin) (EnrolAnswer, error) {
	if s.saves == nil {
		return EnrolAnswer{}, errors.New("projectcapacity: no saves")
	}
	if !rbac.Grants(p.ActiveRole, "project.assignSchool") {
		return EnrolAnswer{Refused: "You do not have permission to assign projects."}, nil
	}
	if strings.TrimSpace(f.ProjectID) == "" {
		return EnrolAnswer{Error: "Please select a project."}, nil
	}
	pr, err := s.readEnrolProject(ctx, f.ProjectID)
	if errors.Is(err, pgx.ErrNoRows) {
		return EnrolAnswer{Error: "Not found."}, nil
	}
	if err != nil {
		return EnrolAnswer{}, err
	}
	sc, err := s.readEnrolSchool(ctx, schoolPK)
	if err != nil {
		return EnrolAnswer{}, err
	}
	var already bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM project_school_assignment WHERE project_id = $1 AND school_id = $2)`,
		pr.id, sc.id).Scan(&already); err != nil {
		return EnrolAnswer{}, fmt.Errorf("projectcapacity: reading the enrolment: %w", err)
	}
	if already {
		return EnrolAnswer{Error: "School is already assigned to this project."}, nil
	}
	if !slices.Contains(rules.OpenStatuses, pr.status) {
		return EnrolAnswer{Error: fmt.Sprintf("'%s' is %s — no new schools can be assigned to it.", pr.name,
			strings.ToLower(statusLabel(pr.status)))}, nil
	}
	if refusal, err := s.enrolRefusal(ctx, p, pr, sc); err != nil || refusal != "" {
		return EnrolAnswer{Error: refusal}, err
	}
	matched, err := s.matchedNeed(ctx, pr, sc.id)
	if err != nil {
		return EnrolAnswer{}, err
	}
	holder, err := s.placeHolder(ctx, p, pr.id, sc.id)
	if err != nil {
		return EnrolAnswer{}, err
	}
	intervention := matched
	if intervention == "" {
		intervention = pr.intervention
	}
	baselineRecord, baselineScore, band, classification, err := s.baseline(ctx, sc.id, intervention)
	if err != nil {
		return EnrolAnswer{}, err
	}
	var start any
	if d, err := time.Parse(time.DateOnly, strings.TrimSpace(f.StartDate)); err == nil {
		start = d
	}
	notes := strings.TrimSpace(f.Notes)
	coordinator := strings.TrimSpace(f.CoordinatorID)
	now := s.now()
	id := cuid.New()
	tx, err := s.saves.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return EnrolAnswer{}, fmt.Errorf("projectcapacity: opening the enrolment: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var answer string
	if err := tx.QueryRow(ctx, `SELECT gateway_project_enrol.enrol($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
  $15, $16, $17, $18, $19)`,
		id, pr.id, sc.id, holder, p.UserID, strings.TrimSpace(f.ProjectType), strings.TrimSpace(f.ParticipationType), start,
		strings.TrimSpace(f.SupportArea), notes, matched, notes, baselineRecord, baselineScore, band, classification,
		coordinator, cuid.New(), now).Scan(&answer); err != nil {
		return EnrolAnswer{}, fmt.Errorf("projectcapacity: enrolling: %w", err)
	}
	switch {
	case answer == "already":
		return EnrolAnswer{Error: "School is already assigned to this project."}, nil
	case answer == "no_allocation":
		return EnrolAnswer{Error: fmt.Sprintf("You have no school allocation for %s. Ask its Project Coordinator to set one "+
			"before adding schools.", pr.name)}, nil
	case strings.HasPrefix(answer, "full:"):
		return EnrolAnswer{Error: fmt.Sprintf("Project capacity reached. You have reached your allocation of %s schools for %s. "+
			"No additional schools can be added unless the Project Coordinator increases your allocation.",
			strings.TrimPrefix(answer, "full:"), pr.name)}, nil
	}
	if err := tx.Commit(ctx); err != nil {
		return EnrolAnswer{}, fmt.Errorf("projectcapacity: committing the enrolment: %w", err)
	}
	s.afterEnrol(ctx, p, pr, sc, holder, coordinator, f, origin)
	return EnrolAnswer{Saved: true, Message: sc.name + " assigned to " + pr.name + "."}, nil
}

func statusLabel(status string) string {
	if status == "" {
		return "Active"
	}
	if l, ok := projectStatusLabels[status]; ok {
		return l
	}
	return status
}

func (s *Service) readEnrolProject(ctx context.Context, id string) (enrolProject, error) {
	var pr enrolProject
	err := s.db.QueryRow(ctx, `SELECT id, name, COALESCE(status, ''), COALESCE(school_focus, ''), COALESCE(manager_staff_id, ''),
  COALESCE(intervention, ''), COALESCE(target_interventions, '[]'::jsonb) FROM project WHERE id = $1 AND deleted_at IS NULL`,
		strings.TrimSpace(id)).Scan(&pr.id, &pr.name, &pr.status, &pr.focus, &pr.manager, &pr.intervention, &pr.targets)
	if err != nil {
		return pr, err
	}
	if pr.intervention != "" && !slices.Contains(pr.targets, pr.intervention) {
		pr.targets = append(pr.targets, pr.intervention)
	}
	return pr, nil
}

func (s *Service) readEnrolSchool(ctx context.Context, id string) (enrolSchool, error) {
	var sc enrolSchool
	err := s.db.QueryRow(ctx, `SELECT sc.id, COALESCE(sc.school_id, ''), sc.name, COALESCE(sc.school_type, ''),
  COALESCE(sc.operational_status, ''), COALESCE(r.country, ''), COALESCE(sc.account_owner_id, ''), COALESCE(sc.district_id, ''),
  COALESCE(sc.cluster_id, '')
  FROM school sc LEFT JOIN region r ON r.id = sc.region_id WHERE sc.id = $1 AND sc.deleted_at IS NULL`, id).Scan(
		&sc.id, &sc.code, &sc.name, &sc.schoolType, &sc.operational, &sc.country, &sc.owner, &sc.district, &sc.cluster)
	if err != nil {
		return sc, fmt.Errorf("projectcapacity: reading the school: %w", err)
	}
	return sc, nil
}

// enrolRefusal is assign_school's checks: who may add the school, whether
// the project takes it, and its focus.
func (s *Service) enrolRefusal(ctx context.Context, p auth.Principal, pr enrolProject, sc enrolSchool) (string, error) {
	if !slices.Contains(countryAssignerRoles, p.ActiveRole) {
		scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
		if err != nil {
			return "", fmt.Errorf("projectcapacity: resolving the scope: %w", err)
		}
		if !slices.Contains(scope.SchoolIDs, sc.id) {
			return "You may add only Schools in your own or supervised portfolio.", nil
		}
	}
	if sc.operational == "temporarily_closed" || sc.operational == "permanently_closed" {
		return closedSchoolMessage, nil
	}
	var governed bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM staff_profile WHERE id = $2)
    OR EXISTS (SELECT 1 FROM project_staff_assignment WHERE project_id = $1 AND is_active)`, pr.id, pr.manager).Scan(&governed); err != nil {
		return "", fmt.Errorf("projectcapacity: reading who plans the project: %w", err)
	}
	if !governed {
		return fmt.Sprintf("'%s' has nobody assigned to plan its work, so it cannot take schools. Ask country leadership to "+
			"assign a Project Coordinator.", pr.name), nil
	}
	country, err := s.projectCountry(ctx, pr.id)
	if err != nil {
		return "", err
	}
	if country != "" && sc.country != "" && country != sc.country {
		return fmt.Sprintf("'%s' runs in %s; %s is in %s.", pr.name, country, sc.name, sc.country), nil
	}
	switch {
	case pr.focus == "core" && sc.schoolType != "core":
		return fmt.Sprintf("'%s' is limited to Core Schools; %s is classified as %s.", pr.name, sc.name, schoolTypeLabel(sc.schoolType)), nil
	case pr.focus == "client" && sc.schoolType == "core":
		return fmt.Sprintf("'%s' is limited to Client Schools; %s is Core.", pr.name, sc.name), nil
	}
	return "", nil
}

// schoolTypeLabel is School.get_school_type_display(): SchoolType's label,
// or the stored value when it names none.
func schoolTypeLabel(t string) string {
	labels := map[string]string{"champion": "Champion", "client": "Client", "core": "Core",
		"core_graduate": "Core Graduate", "core_trained": "Core Trained"}
	if l, ok := labels[t]; ok {
		return l
	}
	return t
}

// matchedNeed is evaluate_school_need: the first target the school's latest
// confirmed SSA scores below 7.
func (s *Service) matchedNeed(ctx context.Context, pr enrolProject, schoolID string) (string, error) {
	if len(pr.targets) == 0 {
		return "", nil
	}
	rows, err := s.db.Query(ctx, `WITH latest AS (
  SELECT id FROM ssa_record WHERE school_id = $1 AND deleted_at IS NULL AND verification_status = 'confirmed'
   ORDER BY date_of_ssa DESC NULLS LAST, created_at DESC LIMIT 1)
SELECT intervention FROM ssa_score WHERE ssa_record_id IN (SELECT id FROM latest) AND COALESCE(score, 0) < 7.0`, schoolID)
	if err != nil {
		return "", fmt.Errorf("projectcapacity: reading the school's SSA: %w", err)
	}
	weak, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return "", err
	}
	for _, t := range pr.targets {
		if slices.Contains(weak, t) {
			return t, nil
		}
	}
	return "", nil
}

// placeHolder is capacity.place_holder: the adder's place, or the school's
// officer's when the adder enrols a team member's school the officer holds
// places for.
func (s *Service) placeHolder(ctx context.Context, p auth.Principal, projectID, schoolID string) (string, error) {
	adder := consumingStaffID(p)
	if adder == "" {
		return "", nil
	}
	rows, err := s.db.Query(ctx, `SELECT staff_id FROM staff_school_assignment WHERE school_id = $1
UNION SELECT account_owner_id FROM school WHERE id = $1 AND account_owner_id IS NOT NULL`, schoolID)
	if err != nil {
		return "", fmt.Errorf("projectcapacity: reading the school's officers: %w", err)
	}
	officers, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return "", err
	}
	if slices.Contains(officers, adder) {
		return adder, nil
	}
	rows, err = s.db.Query(ctx, `SELECT staff_id FROM project_staff_capacity WHERE project_id = $1 AND staff_id = ANY($2) ORDER BY staff_id`,
		projectID, officers)
	if err != nil {
		return "", fmt.Errorf("projectcapacity: reading the officers' allocations: %w", err)
	}
	allocated, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return "", err
	}
	if len(allocated) > 0 {
		return allocated[0], nil
	}
	return adder, nil
}

// baseline is _capture_baseline: the latest confirmed reading of the
// intervention, or nothing to measure against yet.
func (s *Service) baseline(ctx context.Context, schoolID, intervention string) (record string, score *float64, band, classification string, err error) {
	if intervention == "" {
		return "", nil, "", "insufficient_evidence", nil
	}
	var v float64
	err = s.db.QueryRow(ctx, `SELECT r.id, sc.score::float8 FROM ssa_score sc JOIN ssa_record r ON r.id = sc.ssa_record_id
 WHERE r.school_id = $1 AND r.verification_status = 'confirmed' AND sc.intervention = $2 AND r.date_of_ssa IS NOT NULL
   AND sc.score IS NOT NULL AND sc.score BETWEEN 0 AND 10
 ORDER BY r.date_of_ssa DESC LIMIT 1`, schoolID, intervention).Scan(&record, &v)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil, "", "insufficient_evidence", nil
	}
	if err != nil {
		return "", nil, "", "", fmt.Errorf("projectcapacity: reading the baseline: %w", err)
	}
	return record, &v, ssaBand(v), "not_yet_measurable", nil
}

// afterEnrol is the audit rows and the coordinator's notice; none blocks it.
func (s *Service) afterEnrol(ctx context.Context, p auth.Principal, pr enrolProject, sc enrolSchool, holder, coordinator string,
	f EnrolForm, origin activities.Origin) {
	s.enrolAudit(ctx, p, "project.school_added", "School", sc.id, "", map[string]any{
		"projectId": pr.id, "project": pr.name, "school": sc.name, "staffId": nilIfEmpty(holder),
		"previous": map[string]any{"enrolled": false}, "new": map[string]any{"enrolled": true},
	}, origin)
	target := pr.manager
	if target == "" {
		target = coordinator
	}
	if target != "" {
		var user string
		_ = s.db.QueryRow(ctx, `SELECT COALESCE(user_id, '') FROM staff_profile WHERE id = $1`, target).Scan(&user)
		if user != "" {
			if err := activities.SendNotices(ctx, s.saves.pool, s.saves.push, s.saves.live, s.saves.logger, s.now(), pr.id, p.UserID, origin,
				activities.Notice{Title: "New project school added", Body: sc.name + " joined " + pr.name + ". Plan the project's work for it.",
					Event: "project_school_added", Category: "project", ContextType: "Project", Priority: "normal"},
				[]activities.NoticeTo{{UserID: user, Route: "/projects/" + pr.id, Label: "Plan Project Activities"}}); err != nil {
				s.saves.logger.Warn("projectcapacity: the coordinator was not told", "project", pr.id, "err", err)
			}
		}
	}
	s.enrolAudit(ctx, p, "school.assign_project", "School", sc.id, strings.TrimSpace(f.Notes), map[string]any{
		"project_id": pr.id, "project_name": pr.name, "project_type": strings.TrimSpace(f.ProjectType),
		"participation_type": strings.TrimSpace(f.ParticipationType), "support_area": strings.TrimSpace(f.SupportArea),
		"coordinator_staff_id": target, "previous": map[string]any{"enrolled": false},
		"new": map[string]any{"enrolled": true, "projectId": pr.id, "schoolOwnerId": nilIfEmpty(sc.owner),
			"districtId": nilIfEmpty(sc.district), "clusterId": nilIfEmpty(sc.cluster)},
	}, origin)
}

func nilIfEmpty(v string) any {
	if v == "" {
		return nil
	}
	return v
}

func (s *Service) enrolAudit(ctx context.Context, p auth.Principal, action, kind, id, reason string, payload map[string]any,
	origin activities.Origin) {
	tx, err := s.saves.pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: action, SubjectKind: audit.Text(kind), SubjectID: audit.Text(id),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true, Reason: audit.Text(reason),
		IPAddress: audit.Text(origin.IP), UserAgent: audit.Text(origin.UserAgent), CorrelationID: audit.Text(origin.CorrelationID),
		Payload: payload,
	}, s.now()); err != nil {
		s.saves.logger.Warn("projectcapacity: an audit row was not written", "action", action, "err", err)
		return
	}
	_ = tx.Commit(ctx)
}
