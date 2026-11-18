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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// VisitsPath is the visits log.
const VisitsPath = "/visits"

const (
	visitsPageParam = "visits_page"
	visitsPageSize  = 50
	scheduleHref    = "/planning/schedule?action=visit"
)

// statusOptions are the log's status filter, as the template lists them.
var statusOptions = [][2]string{{"", "All Status"}, {"scheduled", "Scheduled"}, {"completed", "Completed"},
	{"started", "In Progress"}, {"cancelled", "Cancelled"}}

// Service builds the logs.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the logs over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// visit is one row of the log.
type visit struct {
	id, kind, status       string
	schoolID, schoolName   string
	clusterID, clusterName string
	planned                *time.Time
}

// likeContains is Django's icontains argument.
func likeContains(text string) string {
	return "%" + strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`).Replace(text) + "%"
}

// readVisits is visits_log_view's queryset: the reader's own visits (by user
// id), latest planned first, filtered by status and by school or cluster
// name, the first hundred.
func (s *Service) readVisits(ctx context.Context, userID, status, search string) ([]visit, error) {
	args := []any{userID, rules.VisitTypes, rules.RowLimit}
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
SELECT a.id, a.activity_type, a.status, COALESCE(s.id, ''), COALESCE(s.name, ''), COALESCE(cl.id, ''), COALESCE(cl.name, ''),
  a.planned_date
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN cluster cl ON cl.id = a.cluster_id
WHERE a.responsible_staff_id = $1 AND a.activity_type = ANY($2) AND a.deleted_at IS NULL`+where+`
ORDER BY a.planned_date DESC
LIMIT $3`, args...)
	if err != nil {
		return nil, fmt.Errorf("stafflogs: reading the visits: %w", err)
	}
	defer rows.Close()
	out := []visit{}
	for rows.Next() {
		var v visit
		if err := rows.Scan(&v.id, &v.kind, &v.status, &v.schoolID, &v.schoolName, &v.clusterID, &v.clusterName,
			&v.planned); err != nil {
			return nil, fmt.Errorf("stafflogs: reading a visit: %w", err)
		}
		out = append(out, v)
	}
	return out, rows.Err()
}

// Build answers the logs; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != VisitsPath {
		return nil, false, nil
	}
	d, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	if !d.Visits {
		return nil, true, pagegate.ErrNotAvailable
	}
	status := query.Get("status")
	visits, err := s.readVisits(ctx, p.UserID, status, strings.TrimSpace(query.Get("q")))
	if err != nil {
		return nil, true, err
	}
	completed, pending := 0, 0
	for _, v := range visits {
		if slices.Contains(rules.CompletedStatuses, v.status) {
			completed++
		}
		if slices.Contains(rules.NotFinishedStatuses, v.status) {
			pending++
		}
	}
	header := &screensv1.PageHeader{Eyebrow: "Planning", Title: "School Visits",
		Description: fmt.Sprintf("%d visits · %d completed · %d pending", len(visits), completed, pending),
		Badges:      []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
	blocks := append([]*screensv1.PageBlock{statusFilter(status)}, visitBlocks(visits, d, query)...)
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: VisitsPath}, true, nil
}

// statusFilter is the status select, with the option chosen (none, when the
// status asked is not one of them).
func statusFilter(status string) *screensv1.PageBlock {
	f := &screensv1.PageFilter{Name: "status", Label: "Status"}
	for _, o := range statusOptions {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
		if o[0] == status {
			f.Value = status
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{f}}}}
}

// djangoDate is a date as a template prints one (DATE_FORMAT "N j, Y").
func djangoDate(t time.Time) string {
	months := [...]string{"Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."}
	return months[t.Month()-1] + " " + strconv.Itoa(t.Day()) + ", " + strconv.Itoa(t.Year())
}

// visitBlocks is the visits' table (fifty a page) and its pager, or the
// empty card, which the feed reads with the page's Schedule link.
func visitBlocks(visits []visit, d role, query url.Values) []*screensv1.PageBlock {
	if len(visits) == 0 {
		text := func(t string) *screensv1.PagePanelItem {
			return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
		}
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Badges: []*screensv1.PageBadge{},
			Items: []*screensv1.PagePanelItem{text("No visits found"), text("Schedule your first school visit to get started"),
				{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
					{Text: "Schedule", Href: scheduleHref}}}}}}}}}}
	}
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "School ID"}, {Label: "School"}, {Label: "Type"},
		{Label: "Date"}, {Label: "Status"}, {Label: ""}}}
	page := tablepager.Paginate(len(visits), visitsPageSize, query, visitsPageParam)
	for _, v := range visits[page.Start:page.End] {
		// The School ID is written in after the page is drawn; the feed
		// reads its place as empty.
		code, school, cluster := "—", "No school", "—"
		cell := &screensv1.PageCell{}
		if v.schoolID != "" {
			code, school = "", v.schoolName
			if d.OpenSchool {
				cell.Href = "/schools/" + v.schoolID
			}
		}
		if v.clusterID != "" {
			cluster = v.clusterName
			if cell.Href == "" {
				cell.Href = "/clusters/" + v.clusterID
			}
		}
		cell.Text = school + " " + cluster
		when := "—"
		if v.planned != nil {
			when = djangoDate(*v.planned)
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: code}, cell, {Text: statusLabel(v.kind), Tone: "primary", Badge: true}, {Text: when},
			{Text: statusLabel(v.status), Tone: "primary", Badge: true},
			{Actions: []*screensv1.PageAction{{Key: "button", Label: "View →", Primary: true, Enabled: true, Href: "/my-plan/" + v.id}}},
		}})
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pager := tablepager.Panel(len(visits), visitsPageSize, query, visitsPageParam); pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks
}
