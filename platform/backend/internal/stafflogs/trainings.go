package stafflogs

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// TrainingsPath is the trainings log.
const TrainingsPath = "/trainings"

const (
	trainingsPageParam   = "trainings_page"
	trainingsPageSize    = 50
	scheduleTrainingHref = "/planning/schedule?action=training"
)

// trainingStatusOptions are the log's status filter, as the template lists them.
var trainingStatusOptions = [][2]string{{"", "All Status"}, {"scheduled", "Scheduled"}, {"completed", "Completed"}}

// training is one row of the log.
type training struct {
	id, status, name       string
	schoolID, schoolName   string
	clusterID, clusterName string
	category, indicator    string
	teachers               int
	planned                *time.Time
}

// ownerIDs is scoping.owner_ids: both ids a person's work is filed under.
func ownerIDs(p auth.Principal) []string {
	out := []string{}
	for _, id := range []string{p.UserID, p.StaffProfileID} {
		if id != "" {
			out = append(out, id)
		}
	}
	return out
}

// readTrainings is trainings_log_view's queryset: the reader's own trainings
// under either id, latest planned first, filtered by status and by school or
// cluster name, the first hundred.
func (s *Service) readTrainings(ctx context.Context, ids []string, status, search string) ([]training, error) {
	args := []any{ids, rules.TrainingTypes, rules.RowLimit}
	where := ""
	if status != "" {
		args = append(args, status)
		where += fmt.Sprintf(" AND a.status = $%d", len(args))
	}
	if search != "" {
		args = append(args, likeContains(search))
		where += fmt.Sprintf(" AND (UPPER(s.name::text) LIKE UPPER($%[1]d) OR UPPER(cl.name::text) LIKE UPPER($%[1]d))", len(args))
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, a.status, COALESCE(a.activity_name_snapshot, ''), COALESCE(s.id, ''), COALESCE(s.name, ''),
  COALESCE(cl.id, ''), COALESCE(cl.name, ''), COALESCE(ci.training_category, ''), COALESCE(ci.ssa_indicator_label, ''),
  COALESCE(a.teachers_attended, 0), a.planned_date
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN cluster cl ON cl.id = a.cluster_id
LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
WHERE a.responsible_staff_id = ANY($1) AND a.activity_type = ANY($2) AND a.deleted_at IS NULL`+where+`
ORDER BY a.planned_date DESC
LIMIT $3`, args...)
	if err != nil {
		return nil, fmt.Errorf("stafflogs: reading the trainings: %w", err)
	}
	defer rows.Close()
	out := []training{}
	for rows.Next() {
		var t training
		if err := rows.Scan(&t.id, &t.status, &t.name, &t.schoolID, &t.schoolName, &t.clusterID, &t.clusterName,
			&t.category, &t.indicator, &t.teachers, &t.planned); err != nil {
			return nil, fmt.Errorf("stafflogs: reading a training: %w", err)
		}
		out = append(out, t)
	}
	return out, rows.Err()
}

// trainings draws the trainings log. The Programme Lead and the CCEO are
// sent elsewhere by the existing page, so theirs is handed on.
func (s *Service) trainings(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	d, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	if !d.Trainings {
		return nil, true, pagegate.ErrNotAvailable
	}
	if slices.Contains(rules.TrainingsRedirected, p.ActiveRole) {
		return nil, false, nil
	}
	status := query.Get("status")
	list, err := s.readTrainings(ctx, ownerIDs(p), status, strings.TrimSpace(query.Get("q")))
	if err != nil {
		return nil, true, err
	}
	completed := 0
	for _, t := range list {
		if slices.Contains(rules.CompletedStatuses, t.status) {
			completed++
		}
	}
	header := &screensv1.PageHeader{Eyebrow: "Planning", Title: "Group Trainings",
		Description: fmt.Sprintf("%d sessions · %d completed", len(list), completed),
		Badges:      []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
	blocks := append([]*screensv1.PageBlock{statusFilter(trainingStatusOptions, status)}, trainingBlocks(list, d, query)...)
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: TrainingsPath}, true, nil
}

// orDefault is a value, or the template's default for an empty one.
func orDefault(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}

// trainingBlocks is the sessions' table (fifty a page) and its pager, or
// the empty card, which the feed reads with the page's Schedule link.
func trainingBlocks(list []training, d role, query url.Values) []*screensv1.PageBlock {
	if len(list) == 0 {
		return []*screensv1.PageBlock{emptyCard("No trainings found", "Schedule your first group training session", scheduleTrainingHref)}
	}
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "Training Session"}, {Label: "Category"},
		{Label: "SSA Association"}, {Label: "Date"}, {Label: "Status"}, {Label: "Attendance"}, {Label: ""}}}
	page := tablepager.Paginate(len(list), trainingsPageSize, query, trainingsPageParam)
	for _, tr := range list[page.Start:page.End] {
		// The session's name over where it is: the school (its School ID
		// written in later, read empty), else the cluster, else nothing.
		where, cell := "Programme activity", &screensv1.PageCell{}
		switch {
		case tr.schoolID != "":
			where = orDefault(tr.schoolName, "School not recorded")
			if d.OpenSchool && tr.schoolName != "" {
				cell.Href = "/schools/" + tr.schoolID
			}
		case tr.clusterID != "":
			where, cell.Href = tr.clusterName+" Cluster", "/clusters/"+tr.clusterID
		}
		cell.Text = orDefault(tr.name, "Training") + " " + where
		when := "—"
		if tr.planned != nil {
			when = djangoDate(*tr.planned)
		}
		attendance := "—"
		if tr.teachers != 0 {
			attendance = strconv.Itoa(tr.teachers) + " teachers"
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell, {Text: orDefault(tr.category, "Legacy training"), Tone: "primary", Badge: true},
			{Text: orDefault(tr.indicator, "—")}, {Text: when}, {Text: statusLabel(tr.status), Tone: "primary", Badge: true},
			{Text: attendance},
			{Actions: []*screensv1.PageAction{{Key: "button", Label: "View →", Primary: true, Enabled: true, Href: "/my-plan/" + tr.id}}},
		}})
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pager := tablepager.Panel(len(list), trainingsPageSize, query, trainingsPageParam); pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks
}
