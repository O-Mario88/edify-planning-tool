package myplan

import (
	"context"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// ListSchool is one school of a readiness list (planning_monitor.SchoolState
// as readiness_list.html reads it), with its visit gate's Assign door.
type ListSchool struct {
	ID, Code, Name, Type, District, ClusterID, ClusterName string
	Clustered                                              bool
	StaffVisits                                            int
	HasPartner, TrainingDone, GroupTraining                bool
	InSchoolTraining, Meeting, NeedsTraining, InProject    bool
	CanAssign                                              bool
}

// ReadinessListReader reads the schools behind a readiness figure for the
// reader's year (planningmonitor.OwnList): those page picks, the list's
// length, and false for a role that plans no visits.
type ReadinessListReader func(ctx context.Context, db schooldirectory.Querier, p auth.Principal, fy string, now time.Time,
	key string, page func(total int) (lo, hi int)) ([]ListSchool, int, bool, error)

// WithReadinessList attaches the reader of the schools behind a readiness
// figure (?list=).
func (s *Service) WithReadinessList(read ReadinessListReader) *Service {
	s.readinessList = read
	return s
}

// ListDoors are what a listed school's Actions menu may offer a role
// (list_actions.offer): Schedule, Assign to partner, Withdraw from Partner,
// and moving or cancelling the staff work planned there.
type ListDoors struct {
	Schedule bool `json:"schedule"`
	Assign   bool `json:"assign"`
	Withdraw bool `json:"withdraw"`
	Move     bool `json:"move"`
}

// listRow is a listed school with what its menu offers (RowActions).
type listRow struct {
	school     ListSchool
	activities []string
	withdraw   string
}

// readinessListBlock is _readiness_list and readiness_list.html: the
// reader's schools behind key, 50 a page, each with its Actions menu. ok is
// false when a row would draw no menu (the feed's "No action available").
func (s *Service) readinessListBlock(ctx context.Context, p auth.Principal, fy, key string, query url.Values,
	now time.Time) (*screensv1.PageBlock, bool, error) {
	var pg tablepager.Page
	schools, total, ok, err := s.readinessList(ctx, s.db, p, fy, now, key, func(n int) (int, int) {
		pg = tablepager.Paginate(n, planTablePageSize, query, "list_page")
		return pg.Start, pg.End
	})
	if err != nil || !ok {
		return nil, ok, err
	}
	rows, err := s.listActions(ctx, p, fy, schools)
	if err != nil {
		return nil, true, err
	}
	doors := rules.Readiness.ListDoors[p.ActiveRole]
	table := emptyReadinessList(key).GetTable()
	table.Subtitle = comma(total) + " school" + pluralS(total) + " · Close list"
	if len(rows) > 0 {
		table.Rows = nil
	}
	for _, r := range rows {
		row, drawn := r.pageRow(doors)
		if !drawn {
			return nil, false, nil
		}
		table.Rows = append(table.Rows, row)
	}
	if pg.Pager != nil {
		table.Pager, table.Footnote = pg.Pager, pg.Pager.Summary
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}}, true, nil
}

// listActions is list_actions.offer's reads for the page's schools: the
// reader's open staff work at each, and the first hand-over a Partner still
// holds.
func (s *Service) listActions(ctx context.Context, p auth.Principal, fy string, schools []ListSchool) ([]listRow, error) {
	rows := make([]listRow, len(schools))
	ids := make([]string, len(schools))
	at := map[string]int{}
	for i, sc := range schools {
		rows[i].school, ids[i], at[sc.ID] = sc, sc.ID, i
	}
	if len(schools) == 0 {
		return rows, nil
	}
	doors := rules.Readiness.ListDoors[p.ActiveRole]
	if doors.Move {
		res, err := s.db.Query(ctx, `SELECT a.id, a.school_id FROM activity a WHERE a.school_id = ANY($1)
  AND a.deleted_at IS NULL AND a.fy = $2 AND a.delivery_type = 'staff' AND a.status = ANY($3)
  AND a.responsible_staff_id = ANY($4) ORDER BY a.planned_date, a.id`,
			ids, fy, rules.Readiness.OpenStaffStatuses, ownerIDs(p))
		if err != nil {
			return nil, fmt.Errorf("myplan: reading a list's open staff work: %w", err)
		}
		for res.Next() {
			var id, school string
			if err := res.Scan(&id, &school); err != nil {
				res.Close()
				return nil, fmt.Errorf("myplan: reading a list's open staff work: %w", err)
			}
			rows[at[school]].activities = append(rows[at[school]].activities, id)
		}
		res.Close()
		if err := res.Err(); err != nil {
			return nil, fmt.Errorf("myplan: reading a list's open staff work: %w", err)
		}
	}
	if doors.Withdraw {
		res, err := s.db.Query(ctx, `SELECT school_id, id FROM partner_assignment WHERE school_id = ANY($1)
  AND status = ANY($2) ORDER BY created_at`, ids, rules.Readiness.OpenHandoverStatuses)
		if err != nil {
			return nil, fmt.Errorf("myplan: reading a list's hand-overs: %w", err)
		}
		for res.Next() {
			var school, id string
			if err := res.Scan(&school, &id); err != nil {
				res.Close()
				return nil, fmt.Errorf("myplan: reading a list's hand-overs: %w", err)
			}
			if r := &rows[at[school]]; r.withdraw == "" {
				r.withdraw = id
			}
		}
		res.Close()
		if err := res.Err(); err != nil {
			return nil, fmt.Errorf("myplan: reading a list's hand-overs: %w", err)
		}
	}
	return rows, nil
}

// pageRow is one row of readiness_list.html as the feed reads it; false when
// the row has no menu.
func (r listRow) pageRow(d ListDoors) (*screensv1.PageRow, bool) {
	sc := r.school
	ref := sc.Code
	if ref == "" {
		ref = sc.ID
	}
	name := closedschools.PyCollapse(sc.Name)
	url := "/schools/" + ref
	menu := func(key, label, href string, drawer bool) *screensv1.PageAction {
		return &screensv1.PageAction{Key: key, Label: label, Enabled: true, Href: href, Drawer: drawer}
	}
	var actions []*screensv1.PageAction
	if d.Schedule {
		actions = append(actions, menu("menu", "Schedule", "/planning/schedule-modal?school_id="+ref, true))
	}
	assign := d.Assign && sc.CanAssign
	if assign {
		actions = append(actions, menu("menu", "Assign to partner", "/planning/assign-partner-modal?school_id="+ref, true))
	}
	switch n := len(r.activities); {
	case n == 1:
		actions = append(actions,
			menu("menu", "Reschedule", "/my-plan/"+r.activities[0]+"/reschedule-drawer", true),
			menu("danger", "Cancel staff activity", "/my-plan/"+r.activities[0]+"/cancel-drawer", true))
	case n > 1:
		joined := strings.Join(r.activities, ",")
		actions = append(actions,
			menu("menu", "Reschedule "+strconv.Itoa(n)+" activities", "/activity-selection/reschedule?ids="+joined, true),
			menu("danger", "Cancel "+strconv.Itoa(n)+" staff activities", "/activity-selection/cancel?ids="+joined, true))
	}
	if r.withdraw != "" {
		actions = append(actions, menu("danger", "Withdraw from Partner", "/partner-oversight/withdraw?assignment_id="+r.withdraw, true))
	}
	// RowActions.any: a greyed Schedule or Assign counts, though the feed
	// draws neither (it has no address).
	if !(d.Schedule || d.Assign || len(r.activities) > 0 || r.withdraw != "") {
		return nil, false
	}
	actions = append(actions, menu("menu", "Open school", url, false))

	code := &screensv1.PageCell{Text: dash}
	if sc.Code != "" {
		code.Text = sc.Code
	}
	cluster := &screensv1.PageCell{Text: "Not clustered", Tone: "warning"}
	if sc.Clustered && sc.ClusterID != "" {
		cluster = &screensv1.PageCell{Text: orDefault(closedschools.PyCollapse(sc.ClusterName), "Cluster"), Href: "/clusters/" + sc.ClusterID}
	}
	row := &screensv1.PageRow{Cells: []*screensv1.PageCell{
		code, {Text: name, Href: url}, {Text: listSchoolType(sc.Type)}, {Text: orDefault(sc.District, dash)},
		cluster, listVisitCell(sc), listTrainingCell(sc), listProjectCell(sc), {Actions: actions},
	}}
	if len(r.activities) > 0 || assign {
		row.PickId, row.PickLabel = ref, "Select "+name
	}
	return row, true
}

func listSchoolType(t string) string {
	switch t {
	case "core":
		return "Core"
	case "core_trained":
		return "Core Trained"
	case "core_graduate":
		return "Core Graduate"
	case "champion":
		return "Champion"
	}
	return "Client"
}

func listVisitCell(sc ListSchool) *screensv1.PageCell {
	switch {
	case sc.StaffVisits > 0:
		text := strconv.Itoa(sc.StaffVisits) + " staff"
		if sc.HasPartner {
			text += " + Partner"
		}
		return &screensv1.PageCell{Text: text, Tone: "info"}
	case sc.HasPartner:
		return &screensv1.PageCell{Text: "Partner", Tone: "info"}
	}
	return &screensv1.PageCell{Text: "Not planned", Tone: "danger"}
}

func listTrainingCell(sc ListSchool) *screensv1.PageCell {
	switch {
	case sc.TrainingDone:
		return &screensv1.PageCell{Text: "Trained", Tone: "success"}
	case sc.GroupTraining:
		return &screensv1.PageCell{Text: "Group training", Tone: "info"}
	case sc.InSchoolTraining:
		return &screensv1.PageCell{Text: "In-school", Tone: "info"}
	case sc.Meeting:
		return &screensv1.PageCell{Text: "Cluster meeting only", Tone: "warning"}
	case !sc.NeedsTraining:
		return &screensv1.PageCell{Text: "Not required"}
	}
	return &screensv1.PageCell{Text: "Not planned", Tone: "danger"}
}

func listProjectCell(sc ListSchool) *screensv1.PageCell {
	if sc.InProject {
		return &screensv1.PageCell{Text: "Yes"}
	}
	return &screensv1.PageCell{Text: dash}
}
