package projectcapacity

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Bulk Add to Project (school_views.bulk_assign_project_view): the School
// Directory's dialog and the drawer the Core Schools list and a cluster's
// roster open, one save, with Django absent.

// The levels of the messages the view queues.
const (
	Success = "success"
	Warning = "warning"
	Error   = "error"
)

// Said is one message the view queues.
type Said struct{ Level, Text string }

// noPermission is the view's refusal without project.assignSchool.
const noPermission = "You do not have permission to assign projects."

// TickedCodes is _ticked_school_codes: repeated or comma-joined values,
// trimmed, each once, in order.
func TickedCodes(values []string) []string {
	out := []string{}
	for _, v := range values {
		for _, code := range strings.Split(v, ",") {
			if code = strings.TrimSpace(code); code != "" && !slices.Contains(out, code) {
				out = append(out, code)
			}
		}
	}
	return out
}

type allocationRow struct{ maximum, assigned int }

func (a allocationRow) remaining() int { return max(a.maximum-a.assigned, 0) }

// selectionRefusal is assert_batch_fits for one allocation and the count of
// new schools that would use it.
func selectionRefusal(project string, a allocationRow, count int) string {
	left := a.remaining()
	if count <= left {
		return ""
	}
	if left == 0 {
		return fmt.Sprintf("Project capacity reached. You have reached your allocation of %d schools for %s. No additional "+
			"schools can be added unless the Project Coordinator increases your allocation.", a.maximum, project)
	}
	plural := "s"
	if left == 1 {
		plural = ""
	}
	return fmt.Sprintf("Capacity exceeded. You can add a maximum of %d more school%s to this project.", left, plural)
}

type skipped struct{ name, reason string }

// bulkMessages are the view's closing messages, in its order.
func bulkMessages(project string, count, duplicates int, refused []skipped) []Said {
	out := []Said{}
	if duplicates > 0 {
		out = append(out, Said{Warning, fmt.Sprintf("Skipped %d school(s) already assigned to this project.", duplicates)})
	}
	if len(refused) > 0 {
		shown := []string{}
		for _, r := range refused[:min(3, len(refused))] {
			shown = append(shown, r.name+": "+r.reason)
		}
		more := ""
		if len(refused) > 3 {
			more = fmt.Sprintf(" and %d more", len(refused)-3)
		}
		out = append(out, Said{Error, fmt.Sprintf("Skipped %d school(s): %s%s.", len(refused), strings.Join(shown, "; "), more)})
	}
	switch {
	case count > 0:
		out = append(out, Said{Success, fmt.Sprintf("Successfully assigned %d school(s) to project '%s'.", count, project)})
	case len(refused) == 0:
		out = append(out, Said{Error, "No new project assignments were made."})
	}
	return out
}

func texts(said []Said, keep func(string) bool) []string {
	out := []string{}
	for _, s := range said {
		if keep(s.Level) {
			out = append(out, s.Text)
		}
	}
	return out
}

// AsDirectory is the feed's run_bulk: the School Directory dialog's answer.
func AsDirectory(said []Said) *screensv1.BulkActionResult {
	errs := texts(said, func(l string) bool { return l == Error })
	warnings := texts(said, func(l string) bool { return l == Warning })
	successes := texts(said, func(l string) bool { return l == Success })
	switch {
	case len(errs) > 0:
		return &screensv1.BulkActionResult{Error: strings.Join(errs, " "), Warnings: warnings}
	case len(successes) > 0:
		return &screensv1.BulkActionResult{Saved: true, Message: strings.Join(successes, " "), Warnings: warnings}
	case len(warnings) > 0:
		return &screensv1.BulkActionResult{Error: strings.Join(warnings, " ")}
	}
	return &screensv1.BulkActionResult{Error: "Nothing was changed."}
}

// AsDrawer is the feed's _saved_outcome for a drawer: saved with the success
// messages, or not with the warnings and errors.
func AsDrawer(said []Said) (bool, string) {
	if ok := texts(said, func(l string) bool { return l == Success }); len(ok) > 0 {
		return true, strings.Join(ok, " ")
	}
	return false, strings.Join(texts(said, func(l string) bool { return l == Warning || l == Error }), " ")
}

// enrollable is enrollable_schools over codes: the reader's schools, the
// team's included, by primary key or School ID, in order.
func (s *Service) enrollable(ctx context.Context, p auth.Principal, codes []string, order string) ([]enrolSchool, error) {
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return nil, fmt.Errorf("projectcapacity: resolving the scope: %w", err)
	}
	var args []any
	arg := func(v any) string { args = append(args, v); return "$" + strconv.Itoa(len(args)) }
	where := schooldirectory.ReadScope(scope, arg)
	c := arg(codes)
	rows, err := s.db.Query(ctx, `SELECT s.id FROM school s WHERE `+where+` AND s.deleted_at IS NULL
  AND (s.id = ANY(`+c+`) OR s.school_id = ANY(`+c+`)) ORDER BY `+order, args...)
	if err != nil {
		return nil, fmt.Errorf("projectcapacity: reading the ticked schools: %w", err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, err
	}
	out := make([]enrolSchool, 0, len(ids))
	for _, id := range ids {
		sc, err := s.readEnrolSchool(ctx, id)
		if err != nil {
			return nil, err
		}
		out = append(out, sc)
	}
	return out, nil
}

func (s *Service) enrolled(ctx context.Context, projectID, schoolID string) (bool, error) {
	var already bool
	err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM project_school_assignment WHERE project_id = $1 AND school_id = $2)`,
		projectID, schoolID).Scan(&already)
	return already, err
}

// selectionFits is assert_selection_fits: each allocation the new schools
// would use holds them all, or the first that does not refuses.
func (s *Service) selectionFits(ctx context.Context, p auth.Principal, pr enrolProject, fresh []enrolSchool) (string, error) {
	order, counts := []string{}, map[string]int{}
	for _, sc := range fresh {
		holder, err := s.placeHolder(ctx, p, pr.id, sc.id)
		if err != nil {
			return "", err
		}
		if holder == "" {
			continue
		}
		if counts[holder] == 0 {
			order = append(order, holder)
		}
		counts[holder]++
	}
	for _, staff := range order {
		var a allocationRow
		err := s.db.QueryRow(ctx, `SELECT c.max_schools, (SELECT count(*) FROM project_school_assignment pa
  WHERE pa.project_id = c.project_id AND pa.assigned_staff_id = c.staff_id)
FROM project_staff_capacity c WHERE c.project_id = $1 AND c.staff_id = $2`, pr.id, staff).Scan(&a.maximum, &a.assigned)
		if errors.Is(err, pgx.ErrNoRows) {
			continue
		}
		if err != nil {
			return "", fmt.Errorf("projectcapacity: reading an allocation: %w", err)
		}
		if refusal := selectionRefusal(pr.name, a, counts[staff]); refusal != "" {
			return refusal, nil
		}
	}
	return "", nil
}

// BulkEnrol is bulk_assign_project_view's POST: the messages it queues.
func (s *Service) BulkEnrol(ctx context.Context, p auth.Principal, codes []string, projectID, reason string, origin activities.Origin) ([]Said, error) {
	if s.saves == nil {
		return nil, errors.New("projectcapacity: no saves")
	}
	if !rbac.Grants(p.ActiveRole, "project.assignSchool") {
		return []Said{{Error, noPermission}}, nil
	}
	projectID, reason = strings.TrimSpace(projectID), strings.TrimSpace(reason)
	if len(codes) == 0 || projectID == "" {
		return []Said{{Error, "Failed to perform assignment: missing fields."}}, nil
	}
	pr, err := s.readEnrolProject(ctx, projectID)
	if errors.Is(err, pgx.ErrNoRows) {
		return []Said{{Error, "Not found."}}, nil
	}
	if err != nil {
		return nil, err
	}
	if !slices.Contains(rules.OpenStatuses, pr.status) {
		return []Said{{Error, fmt.Sprintf("'%s' is %s — no new schools can be assigned to it.", pr.name,
			strings.ToLower(statusLabel(pr.status)))}}, nil
	}
	schools, err := s.enrollable(ctx, p, codes, "s.created_at DESC")
	if err != nil {
		return nil, err
	}
	fresh := []enrolSchool{}
	for _, sc := range schools {
		already, err := s.enrolled(ctx, pr.id, sc.id)
		if err != nil {
			return nil, err
		}
		if !already {
			fresh = append(fresh, sc)
		}
	}
	if refusal, err := s.selectionFits(ctx, p, pr, fresh); err != nil || refusal != "" {
		return []Said{{Error, refusal}}, err
	}
	count, duplicates, refused := 0, 0, []skipped{}
	for _, sc := range schools {
		already, err := s.enrolled(ctx, pr.id, sc.id)
		if err != nil {
			return nil, err
		}
		if already {
			duplicates++
			continue
		}
		answer, holder, err := s.assignSchool(ctx, p, pr, sc, EnrolForm{ProjectID: pr.id, Notes: reason})
		if err != nil {
			return nil, err
		}
		if !answer.Saved {
			refused = append(refused, skipped{sc.name, answer.Error})
			continue
		}
		s.enrolAudit(ctx, p, "project.school_added", "School", sc.id, "", map[string]any{
			"projectId": pr.id, "project": pr.name, "school": sc.name, "staffId": nilIfEmpty(holder),
			"previous": map[string]any{"enrolled": false}, "new": map[string]any{"enrolled": true},
		}, origin)
		count++
	}
	if count > 0 {
		s.enrolAudit(ctx, p, "school.bulk_assign_project", "Project", pr.id, reason, map[string]any{
			"projectName": pr.name, "assigned": count, "skipped": len(refused), "duplicates": duplicates,
		}, origin)
	}
	return bulkMessages(pr.name, count, duplicates, refused), nil
}

// BulkSchool is a ticked school the drawer lists.
type BulkSchool struct{ ID, Code, Name string }

// BulkChoices is bulk_assign_project_drawer_view's read: the ticked schools
// in reach by name, how many were left out, and whether the reader may add
// schools at all.
func (s *Service) BulkChoices(ctx context.Context, p auth.Principal, codes []string) ([]BulkSchool, int, string, error) {
	if !rbac.Grants(p.ActiveRole, "project.assignSchool") {
		return nil, 0, noPermission, nil
	}
	schools, err := s.enrollable(ctx, p, codes, "s.name")
	if err != nil {
		return nil, 0, "", err
	}
	out := make([]BulkSchool, 0, len(schools))
	for _, sc := range schools {
		out = append(out, BulkSchool{ID: sc.id, Code: sc.code, Name: sc.name})
	}
	return out, len(codes) - len(out), "", nil
}
