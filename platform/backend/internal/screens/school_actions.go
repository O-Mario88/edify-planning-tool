package screens

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// WithSchoolDB attaches the PostgreSQL pool so SchoolActionService,
// PlanningDrawerService (assign + capacity + GET), SchoolDrawerService,
// PageDrawerService GET, and GetDrawerOptions run natively in Go with zero
// Django dependency.
func (s *Service) WithSchoolDB(pool *pgxpool.Pool, now func() time.Time) *Service {
	s.db = pool
	if now == nil {
		now = time.Now
	}
	s.now = now
	return s
}

func (s *Service) clock() time.Time {
	if s.now != nil {
		return s.now().UTC()
	}
	return time.Now().UTC()
}

// nativeForms is whether Go's own drawers and school writes answer. While the
// existing application is configured its forms stay the authority: they carry
// the full field set and rules, and two writers for one record is what the
// cutover plan forbids. Go's answer in that mode would also replace them for
// every client, the app included.
func (s *Service) nativeForms() bool { return s.db != nil && s.existingApp == nil }

// schoolsInReach is whether every school is in the reader's own scope: a role
// that may edit schools may edit only those it can see.
func (s *Service) schoolsInReach(ctx context.Context, p auth.Principal, ids ...string) (bool, error) {
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.clock())
	if err != nil {
		return false, err
	}
	for _, id := range ids {
		// The forms carry a record id or a School ID.
		var recordID string
		err := s.db.QueryRow(ctx, `SELECT id FROM school WHERE (id = $1 OR school_id = $1) AND deleted_at IS NULL LIMIT 1`, id).Scan(&recordID)
		if errors.Is(err, pgx.ErrNoRows) {
			return false, nil
		}
		if err != nil {
			return false, err
		}
		ok, err := schooldirectory.InReach(ctx, s.db, scope, recordID)
		if err != nil || !ok {
			return false, err
		}
	}
	return true, nil
}

func canMutateSchoolAssignment(role string) bool {
	switch role {
	case "CCEO", "Program Lead", "CountryDirector", "ProjectCoordinator", "Admin":
		return true
	default:
		return false
	}
}

func (s *Service) getAddToClusterInGo(ctx context.Context, p auth.Principal, schoolID string) (*screensv1.GetAddToClusterResponse, bool, error) {
	if !s.nativeForms() {
		return nil, false, nil
	}
	if !canMutateSchoolAssignment(p.ActiveRole) {
		return &screensv1.GetAddToClusterResponse{
			Form: &screensv1.AddToClusterForm{Refused: "Your role does not have permission to assign schools to clusters."},
		}, true, nil
	}
	if inReach, err := s.schoolsInReach(ctx, p, schoolID); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	} else if !inReach {
		return &screensv1.GetAddToClusterResponse{
			Form: &screensv1.AddToClusterForm{Refused: "This school is outside your portfolio."},
		}, true, nil
	}
	var sID, sName, districtID, curClusterID, curClusterName string
	err := s.db.QueryRow(ctx, `
SELECT s.id, s.name, COALESCE(s.district_id, ''), COALESCE(s.cluster_id, ''), COALESCE(c.name, '')
  FROM school s
  LEFT JOIN cluster c ON c.id = s.cluster_id AND c.deleted_at IS NULL
 WHERE (s.id = $1 OR s.school_id = $1) AND s.deleted_at IS NULL
 LIMIT 1`, schoolID).Scan(&sID, &sName, &districtID, &curClusterID, &curClusterName)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "School not found.")
	}
	if err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}

	rows, err := s.db.Query(ctx, `
SELECT id, name, COALESCE(district_id, '')
  FROM cluster
 WHERE deleted_at IS NULL AND status = 'active'
 ORDER BY (district_id = $1) DESC, name ASC
 LIMIT 200`, districtID)
	if err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	defer rows.Close()

	var choices []*screensv1.ActionChoice
	var crossDistrict []string
	for rows.Next() {
		var id, name, cDist string
		if scanErr := rows.Scan(&id, &name, &cDist); scanErr == nil {
			choices = append(choices, &screensv1.ActionChoice{
				Value:    id,
				Label:    name,
				Disabled: id == curClusterID,
				Reason:   ternaryStr(id == curClusterID, "Current cluster", ""),
			})
			if districtID != "" && cDist != "" && cDist != districtID {
				crossDistrict = append(crossDistrict, id)
			}
		}
	}

	isChange := curClusterID != ""
	title := fmt.Sprintf("Add %s to cluster", sName)
	submitLabel := "Add to cluster"
	confirmLabel := ""
	if isChange {
		title = fmt.Sprintf("Change cluster for %s", sName)
		submitLabel = "Change cluster"
		confirmLabel = fmt.Sprintf("Move this school out of %s.", curClusterName)
	}
	return &screensv1.GetAddToClusterResponse{
		Form: &screensv1.AddToClusterForm{
			Title:                   title,
			IsChange:                isChange,
			CurrentClusterName:      curClusterName,
			Clusters:                choices,
			CrossDistrictClusterIds: crossDistrict,
			HasSelectableCluster:    len(choices) > 0,
			NewClusterPlaceholder:   "Enter a new cluster name",
			ReasonPlaceholder:       "Reason for cluster assignment or move",
			ConfirmLabel:            confirmLabel,
			SubmitLabel:             submitLabel,
		},
	}, true, nil
}

func (s *Service) addToClusterInGo(ctx context.Context, p auth.Principal, req *screensv1.AddToClusterRequest) (*screensv1.AddToClusterResponse, bool, error) {
	if !s.nativeForms() {
		return nil, false, nil
	}
	if !canMutateSchoolAssignment(p.ActiveRole) {
		return &screensv1.AddToClusterResponse{
			Result: &screensv1.SchoolActionResult{Refused: "Your role cannot assign schools to clusters."},
		}, true, nil
	}
	if inReach, err := s.schoolsInReach(ctx, p, req.GetSchoolId()); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	} else if !inReach {
		return &screensv1.AddToClusterResponse{
			Result: &screensv1.SchoolActionResult{Refused: "This school is outside your portfolio."},
		}, true, nil
	}
	cid := strings.TrimSpace(req.GetClusterId())
	newName := strings.TrimSpace(req.GetNewClusterName())
	if req.GetActionType() == "new" {
		cid = ""
	}
	if cid == "" && newName == "" {
		return &screensv1.AddToClusterResponse{
			Result: &screensv1.SchoolActionResult{Error: "Choose an existing cluster or enter a new cluster name."},
		}, true, nil
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	now := s.clock()
	var outCID, outCName, msg string
	if err := tx.QueryRow(ctx,
		`SELECT cluster_id, cluster_name, message FROM gateway_school_actions.assign_school_to_cluster($1,$2,$3,$4,$5,$6,$7)`,
		req.GetSchoolId(), cid, newName, p.UserID, p.ActiveRole, strings.TrimSpace(req.GetReason()), now,
	).Scan(&outCID, &outCName, &msg); err != nil {
		return &screensv1.AddToClusterResponse{
			Result: &screensv1.SchoolActionResult{Error: err.Error()},
		}, true, nil
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action:      "school.cluster_assigned",
		SubjectKind: audit.Text("school"),
		SubjectID:   audit.Text(req.GetSchoolId()),
		ActorID:     audit.Text(p.UserID),
		ActorRole:   audit.Text(p.ActiveRole),
		Success:     true,
		Payload: map[string]any{
			"cluster_id":   outCID,
			"cluster_name": outCName,
			"reason":       strings.TrimSpace(req.GetReason()),
		},
	}, now); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.AddToClusterResponse{
		Result: &screensv1.SchoolActionResult{Saved: true, Message: msg},
	}, true, nil
}

func (s *Service) getAddToProjectInGo(ctx context.Context, p auth.Principal, schoolID string) (*screensv1.GetAddToProjectResponse, bool, error) {
	if !s.nativeForms() {
		return nil, false, nil
	}
	if !canMutateSchoolAssignment(p.ActiveRole) {
		return &screensv1.GetAddToProjectResponse{
			Form: &screensv1.AddToProjectForm{Refused: "Your role does not have permission to enroll schools in projects."},
		}, true, nil
	}
	if inReach, err := s.schoolsInReach(ctx, p, schoolID); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	} else if !inReach {
		return &screensv1.GetAddToProjectResponse{
			Form: &screensv1.AddToProjectForm{Refused: "This school is outside your portfolio."},
		}, true, nil
	}
	var sID, sName string
	err := s.db.QueryRow(ctx, `
SELECT id, name FROM school WHERE (id = $1 OR school_id = $1) AND deleted_at IS NULL LIMIT 1`, schoolID).Scan(&sID, &sName)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "School not found.")
	}
	if err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}

	rows, err := s.db.Query(ctx, `
SELECT pr.id, pr.name,
       EXISTS(SELECT 1 FROM project_school_assignment psa WHERE psa.project_id = pr.id AND psa.school_id = $1)
  FROM project pr
 WHERE pr.deleted_at IS NULL AND pr.status IN ('active', 'open', 'in_progress')
 ORDER BY pr.name ASC
 LIMIT 150`, sID)
	if err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	defer rows.Close()
	var projects []*screensv1.ActionChoice
	for rows.Next() {
		var id, name string
		var enrolled bool
		if scanErr := rows.Scan(&id, &name, &enrolled); scanErr == nil {
			projects = append(projects, &screensv1.ActionChoice{
				Value:    id,
				Label:    name,
				Disabled: enrolled,
				Reason:   ternaryStr(enrolled, "Already enrolled", ""),
			})
		}
	}

	coordRows, err := s.db.Query(ctx, `
SELECT sp.id, COALESCE(u.name, sp.id)
  FROM staff_profile sp
  LEFT JOIN "user" u ON u.id = sp.user_id
 WHERE sp.deleted_at IS NULL
 ORDER BY u.name ASC
 LIMIT 150`)
	var coords []*screensv1.ActionChoice
	if err == nil {
		for coordRows.Next() {
			var id, name string
			if scanErr := coordRows.Scan(&id, &name); scanErr == nil {
				coords = append(coords, &screensv1.ActionChoice{Value: id, Label: name})
			}
		}
		coordRows.Close()
	}

	emptyNotice := ""
	if len(projects) == 0 {
		emptyNotice = "No projects are currently open for enrolment."
	}
	return &screensv1.GetAddToProjectResponse{
		Form: &screensv1.AddToProjectForm{
			Title:    fmt.Sprintf("Add %s to project", sName),
			Projects: projects,
			SupportTypes: []*screensv1.ActionChoice{
				{Value: "direct", Label: "Direct support"},
				{Value: "partner", Label: "Partner-led"},
				{Value: "blended", Label: "Blended"},
			},
			Coordinators: coords,
			FocusAreas: []*screensv1.ActionChoice{
				{Value: "leadership", Label: "School Leadership"},
				{Value: "teaching", Label: "Teaching & Learning"},
				{Value: "edtech", Label: "Education Technology"},
				{Value: "finance", Label: "Financial Sustainability"},
			},
			EmptyNotice: emptyNotice,
		},
	}, true, nil
}

func (s *Service) addToProjectInGo(ctx context.Context, p auth.Principal, req *screensv1.AddToProjectRequest) (*screensv1.AddToProjectResponse, bool, error) {
	if !s.nativeForms() {
		return nil, false, nil
	}
	if !canMutateSchoolAssignment(p.ActiveRole) {
		return &screensv1.AddToProjectResponse{
			Result: &screensv1.SchoolActionResult{Refused: "Your role cannot enroll schools in projects."},
		}, true, nil
	}
	if inReach, err := s.schoolsInReach(ctx, p, req.GetSchoolId()); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	} else if !inReach {
		return &screensv1.AddToProjectResponse{
			Result: &screensv1.SchoolActionResult{Refused: "This school is outside your portfolio."},
		}, true, nil
	}
	if strings.TrimSpace(req.GetProjectId()) == "" {
		return &screensv1.AddToProjectResponse{
			Result: &screensv1.SchoolActionResult{Error: "Select a project first."},
		}, true, nil
	}
	var startDate any = nil
	if raw := strings.TrimSpace(req.GetStartDate()); raw != "" {
		if d, err := time.Parse(time.DateOnly, raw); err == nil {
			startDate = d
		}
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	now := s.clock()
	var asgID, msg string
	var already bool
	if err := tx.QueryRow(ctx,
		`SELECT assignment_id, already_enrolled, message FROM gateway_school_actions.assign_school_to_project($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`,
		req.GetSchoolId(), req.GetProjectId(), req.GetProjectType(), req.GetParticipationType(),
		startDate, req.GetSupportArea(), req.GetCoordinatorId(), req.GetNotes(),
		p.UserID, p.ActiveRole, now,
	).Scan(&asgID, &already, &msg); err != nil {
		return &screensv1.AddToProjectResponse{
			Result: &screensv1.SchoolActionResult{Error: err.Error()},
		}, true, nil
	}
	if !already {
		if _, err := audit.Append(ctx, tx, audit.Entry{
			Action:      "school.project_enrolled",
			SubjectKind: audit.Text("school"),
			SubjectID:   audit.Text(req.GetSchoolId()),
			ActorID:     audit.Text(p.UserID),
			ActorRole:   audit.Text(p.ActiveRole),
			Success:     true,
			Payload: map[string]any{
				"project_id":    req.GetProjectId(),
				"assignment_id": asgID,
			},
		}, now); err != nil {
			return nil, true, apierr.Internal(ctx, s.logger, err)
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.AddToProjectResponse{
		Result: &screensv1.SchoolActionResult{Saved: true, Message: msg},
	}, true, nil
}

func (s *Service) bulkAssignClusterInGo(ctx context.Context, p auth.Principal, req *screensv1.BulkAssignClusterRequest) (*screensv1.BulkAssignClusterResponse, bool, error) {
	if !s.nativeForms() {
		return nil, false, nil
	}
	if !canMutateSchoolAssignment(p.ActiveRole) {
		return &screensv1.BulkAssignClusterResponse{
			Result: &screensv1.BulkActionResult{Error: "Your role cannot bulk-assign schools to clusters."},
		}, true, nil
	}
	if inReach, err := s.schoolsInReach(ctx, p, req.GetSchoolIds()...); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	} else if !inReach {
		return &screensv1.BulkAssignClusterResponse{
			Result: &screensv1.BulkActionResult{Error: "This school is outside your portfolio."},
		}, true, nil
	}
	if strings.TrimSpace(req.GetClusterId()) == "" || len(req.GetSchoolIds()) == 0 {
		return &screensv1.BulkAssignClusterResponse{
			Result: &screensv1.BulkActionResult{Error: "Select at least one school and a target cluster."},
		}, true, nil
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	assigned := 0
	var warnings []string
	now := s.clock()
	for _, sid := range req.GetSchoolIds() {
		var outCID, outCName, msg string
		if err := tx.QueryRow(ctx,
			`SELECT cluster_id, cluster_name, message FROM gateway_school_actions.assign_school_to_cluster($1,$2,'',$3,$4,'Bulk assignment',$5)`,
			sid, req.GetClusterId(), p.UserID, p.ActiveRole, now,
		).Scan(&outCID, &outCName, &msg); err != nil {
			warnings = append(warnings, fmt.Sprintf("%s: %v", sid, err))
			continue
		}
		if _, err := audit.Append(ctx, tx, audit.Entry{
			Action:      "school.cluster_assigned",
			SubjectKind: audit.Text("school"),
			SubjectID:   audit.Text(sid),
			ActorID:     audit.Text(p.UserID),
			ActorRole:   audit.Text(p.ActiveRole),
			Success:     true,
			Payload: map[string]any{
				"cluster_id":   outCID,
				"cluster_name": outCName,
				"reason":       "Bulk assignment",
			},
		}, now); err != nil {
			return nil, true, apierr.Internal(ctx, s.logger, err)
		}
		assigned++
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.BulkAssignClusterResponse{
		Result: &screensv1.BulkActionResult{
			Saved:    assigned > 0,
			Message:  fmt.Sprintf("Assigned %d school(s) to cluster.", assigned),
			Warnings: warnings,
		},
	}, true, nil
}

func (s *Service) bulkAssignProjectInGo(ctx context.Context, p auth.Principal, req *screensv1.BulkAssignProjectRequest) (*screensv1.BulkAssignProjectResponse, bool, error) {
	if !s.nativeForms() {
		return nil, false, nil
	}
	if !canMutateSchoolAssignment(p.ActiveRole) {
		return &screensv1.BulkAssignProjectResponse{
			Result: &screensv1.BulkActionResult{Error: "Your role cannot bulk-enroll schools in projects."},
		}, true, nil
	}
	if inReach, err := s.schoolsInReach(ctx, p, req.GetSchoolIds()...); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	} else if !inReach {
		return &screensv1.BulkAssignProjectResponse{
			Result: &screensv1.BulkActionResult{Error: "This school is outside your portfolio."},
		}, true, nil
	}
	if strings.TrimSpace(req.GetProjectId()) == "" || len(req.GetSchoolIds()) == 0 {
		return &screensv1.BulkAssignProjectResponse{
			Result: &screensv1.BulkActionResult{Error: "Select at least one school and a target project."},
		}, true, nil
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	defer func() { _ = tx.Rollback(ctx) }()

	assigned := 0
	var warnings []string
	now := s.clock()
	for _, sid := range req.GetSchoolIds() {
		var asgID, msg string
		var already bool
		if err := tx.QueryRow(ctx,
			`SELECT assignment_id, already_enrolled, message FROM gateway_school_actions.assign_school_to_project($1,$2,'','','','',NULL,'Bulk assignment',$3,$4,$5)`,
			sid, req.GetProjectId(), p.UserID, p.ActiveRole, now,
		).Scan(&asgID, &already, &msg); err != nil {
			warnings = append(warnings, fmt.Sprintf("%s: %v", sid, err))
			continue
		}
		if already {
			warnings = append(warnings, msg)
			continue
		}
		if _, err := audit.Append(ctx, tx, audit.Entry{
			Action:      "school.project_enrolled",
			SubjectKind: audit.Text("school"),
			SubjectID:   audit.Text(sid),
			ActorID:     audit.Text(p.UserID),
			ActorRole:   audit.Text(p.ActiveRole),
			Success:     true,
			Payload: map[string]any{
				"project_id":    req.GetProjectId(),
				"assignment_id": asgID,
			},
		}, now); err != nil {
			return nil, true, apierr.Internal(ctx, s.logger, err)
		}
		assigned++
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, true, apierr.Internal(ctx, s.logger, err)
	}
	return &screensv1.BulkAssignProjectResponse{
		Result: &screensv1.BulkActionResult{
			Saved:    assigned > 0 || len(warnings) > 0,
			Message:  fmt.Sprintf("Enrolled %d school(s) in project.", assigned),
			Warnings: warnings,
		},
	}, true, nil
}

func ternaryStr(cond bool, a, b string) string {
	if cond {
		return a
	}
	return b
}
