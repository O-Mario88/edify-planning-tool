package coreschools

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// work is one of a programme school's activities of the year (school_work).
type work struct {
	name, status string
	day          *time.Time
}

// programmeSchools are a programme type's schools of the lens, filtered as
// programme_sections filters them, by name.
func (pg *page) programmeSchools(ctx context.Context, kind string) ([]school, error) {
	f := pg.f
	if (f.partner != "" && f.partner != "All") || f.partnerAssigned == "assigned" {
		// Programme schools take no partner hand-overs.
		return nil, nil
	}
	a := &sqlArgs{}
	parts := []string{lensClause(pg.scope, pg.oversight, a), "s.deleted_at IS NULL", "s.school_type = " + a.arg(kind)}
	if f.q != "" {
		p := a.arg(likeArg(f.q))
		parts = append(parts, fmt.Sprintf(`(s.name ILIKE %[1]s OR s.school_id ILIKE %[1]s OR d.name ILIKE %[1]s OR s.account_owner_name_raw ILIKE %[1]s)`, p))
	}
	for _, c := range []struct{ value, column string }{
		{f.region, "s.region_id"}, {f.district, "s.district_id"}, {f.staff, "s.account_owner_id"},
		{f.schoolType, "s.school_type"}, {f.ssaStatus, "s.current_fy_ssa_status"},
	} {
		if c.value != "" && c.value != "All" {
			parts = append(parts, c.column+" = "+a.arg(c.value))
		}
	}
	rows, err := pg.db.Query(ctx, "SELECT "+schoolColumns+" "+schoolJoins+" WHERE "+strings.Join(parts, " AND ")+" ORDER BY s.name, s.id", a.list...)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the programme schools: %w", err)
	}
	defer rows.Close()
	out := []school{}
	for rows.Next() {
		sc, err := scanSchool(rows)
		if err != nil {
			return nil, fmt.Errorf("coreschools: reading a programme school: %w", err)
		}
		out = append(out, sc)
	}
	return out, rows.Err()
}

// schoolWork is school_work: each school's live visits and trainings of the
// year, its own and the cluster sessions it is invited to or attended, by
// date.
func (pg *page) schoolWork(ctx context.Context, pks []string) (map[string][]work, error) {
	out := map[string][]work{}
	if len(pks) == 0 {
		return out, nil
	}
	types := append(append([]string{}, rules.VisitTypes...), rules.TrainingTypes...)
	rows, err := pg.db.Query(ctx, `
WITH invited AS (
  SELECT activity_id, school_id FROM cluster_activity_attendance WHERE school_id = ANY($1) AND (invited OR attended))
SELECT a.id, a.school_id, coalesce(a.activity_type, ''), a.planned_date, coalesce(a.status, ''),
       coalesce((SELECT array_agg(i.school_id) FROM invited i WHERE i.activity_id = a.id), '{}')
FROM activity a
WHERE (a.school_id = ANY($1) OR a.id IN (SELECT activity_id FROM invited))
  AND a.deleted_at IS NULL AND a.fy = $2 AND a.activity_type = ANY($3) AND NOT (a.status = ANY($4))
ORDER BY a.planned_date, a.id`, pks, pg.fy, types, rules.WorkExcluded)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the programme schools' work: %w", err)
	}
	defer rows.Close()
	own := map[string]bool{}
	for _, id := range pks {
		own[id] = true
	}
	for rows.Next() {
		var id, kind, status string
		var schoolID *string
		var day *time.Time
		var invited []string
		if err := rows.Scan(&id, &schoolID, &kind, &day, &status, &invited); err != nil {
			return nil, fmt.Errorf("coreschools: reading a programme school's work: %w", err)
		}
		targets := map[string]bool{}
		for _, s := range invited {
			targets[s] = true
		}
		if schoolID != nil && own[*schoolID] {
			targets[*schoolID] = true
		}
		name := rules.ActivityTypeLabels[kind]
		if name == "" {
			name = kind
		}
		label := rules.ActivityStatusLabels[status]
		if label == "" {
			label = status
		}
		for s := range targets {
			out[s] = append(out[s], work{name: name, status: label, day: day})
		}
	}
	return out, rows.Err()
}

// mayPlan is may_plan_school for a school of the direct lens.
func (pg *page) mayPlan(sc school) bool {
	switch {
	case contains(rules.CountrySchedulingRoles, pg.p.ActiveRole):
		return true
	case pg.scope.CountryScope || pg.scope.SummaryOnly:
		return false
	}
	return contains(pg.scope.OwnSchoolIDs, sc.id)
}

// programme is the Core Trained, Core Graduate and Champion tables.
func (pg *page) programme(ctx context.Context) ([]*screensv1.PageBlock, error) {
	gates := schoolprofile.GateRules()
	horizon, err := schoolplanning.Horizon(ctx, pg.db, pg.p.Country, pg.fy, mustAtoi(pg.operational), schooldirectory.FYOptions(pg.now), pg.now)
	if err != nil {
		return nil, err
	}
	blocks := []*screensv1.PageBlock{}
	for _, t := range rules.ProgrammeTypes {
		kind, label := t[0], t[1]
		outreach := contains(rules.OutreachOnlyTypes, kind)
		list, err := pg.programmeSchools(ctx, kind)
		if err != nil {
			return nil, err
		}
		total := len(list)
		shown := list[:min(len(list), pg.perPage)]
		pks, _ := ids(shown)
		badges, _, err := schoolplanning.ForSchools(ctx, pg.db, pks, horizon)
		if err != nil {
			return nil, err
		}
		work, err := pg.schoolWork(ctx, pks)
		if err != nil {
			return nil, err
		}
		scores, err := latestConfirmedScores(ctx, pg.db, pks, pg.fy)
		if err != nil {
			return nil, err
		}
		clusters, err := names(ctx, pg.db, `SELECT id, name FROM cluster WHERE id = ANY($1) AND deleted_at IS NULL`, clusterIDs(shown))
		if err != nil {
			return nil, err
		}
		owners, err := staffNames(ctx, pg.db, shown)
		if err != nil {
			return nil, err
		}
		heads := []string{"School ID", "School name", "District", "Visit plan status"}
		if !outreach {
			heads = append(heads, "Training plan status")
		}
		heads = append(heads, "Planned activities", "Actions")
		cols := []*screensv1.PageColumn{}
		for _, h := range heads {
			cols = append(cols, &screensv1.PageColumn{Label: h})
		}
		table := &screensv1.PageTable{Title: fmt.Sprintf("%s Schools (%d)", label, total), Columns: cols}
		for _, sc := range shown {
			gate, err := visitgate.Of(ctx, pg.db, gates, visitgate.School{ID: sc.id, Code: sc.code, Name: sc.name, Type: sc.schoolType},
				pg.fy, pg.operational)
			if err != nil {
				return nil, err
			}
			b := badges[sc.id]
			if b == nil {
				b = &schoolplanning.Badges{}
			}
			visit := &screensv1.PageCell{Text: clusterpage.JoinedChips(b.VisitChips()), Pills: clusterpage.ChipPills(b.VisitChips())}
			if lock := gate.LockLabel(gates); lock != "" {
				visit.Text += lock + ": " + gate.StaffReason
				visit.Pills = append(visit.Pills, &screensv1.PageBadge{Text: lock + ": " + gate.StaffReason, Tone: "closed", Title: gate.StaffReason})
			}
			district := sc.districtName
			if district == "" {
				district = "—"
			}
			districtCell := &screensv1.PageCell{Text: district}
			if sc.districtID != "" && sc.districtName != "" {
				districtCell.Href = "/districts/" + sc.districtID
			}
			cells := []*screensv1.PageCell{{Text: sc.code}, {Text: sc.name, Href: "/schools/" + sc.code}, districtCell, visit}
			if !outreach {
				cells = append(cells, &screensv1.PageCell{Text: clusterpage.JoinedChips(b.TrainingChips(), b.ClusterMeetingChips()),
					Pills: clusterpage.ChipPills(b.TrainingChips(), b.ClusterMeetingChips())})
			}
			lines := []string{}
			for _, w := range work[sc.id] {
				day := "Awaiting schedule"
				if w.day != nil {
					day = fmt.Sprintf("%d %s", w.day.Day(), w.day.Format("Jan 2006"))
				}
				lines = append(lines, w.name+" · "+day+" · "+w.status)
			}
			planned := "None planned"
			if len(lines) > 0 {
				planned = strings.Join(lines, " ")
			}
			action := &screensv1.PageCell{Text: "View", Href: "/schools/" + sc.code}
			if !pg.oversight && pg.mayPlan(sc) {
				action = &screensv1.PageCell{Text: "Schedule"}
			}
			orDash := func(v string) string {
				if v == "" {
					return "—"
				}
				return v
			}
			clusterName := "Not assigned"
			clusterHref := ""
			if sc.clusterID != "" {
				if cn, ok := clusters[sc.clusterID]; ok && cn != "" {
					clusterName = cn
					if pg.door.OpenClusters {
						clusterHref = "/clusters/" + sc.clusterID
					}
				}
			}
			staffName := owners[sc.ownerID]
			if staffName == "" {
				staffName = orDash(sc.ownerRaw)
			}
			staffHref := ""
			if sc.ownerID != "" {
				staffHref = "/staff/" + sc.ownerID
			}
			enrolment := "0"
			if sc.enrollment != nil {
				enrolment = strconv.Itoa(*sc.enrollment)
			}
			ssaText := "Not assessed"
			var groups []schooldirectory.SSAGroup
			hasScores := false
			if scScores, ok := scores[sc.id]; ok {
				groups, hasScores = schooldirectory.SSAGroups(scScores)
				if avg, _ := schooldirectory.SSAAverage(scScores); avg != nil {
					ssaText = clusterpage.ScoreText(*avg) + "/10"
				}
			}
			ssaItems := []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: "Latest confirmed assessment · FY " + pg.fy}}}
			if hasScores {
				ssaItems = append(ssaItems, clusterpage.ScoreGroupItems(groups)...)
			} else {
				ssaItems = append(ssaItems, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: "No confirmed SSA scores are available yet."}})
			}
			districtFact := &screensv1.PageFact{Label: "District", Value: district}
			if sc.districtID != "" && sc.districtName != "" {
				districtFact.Href = "/districts/" + sc.districtID
			}
			row := &screensv1.PageRow{
				Cells: append(cells, &screensv1.PageCell{Text: planned}, action),
				Details: []*screensv1.PageFact{
					districtFact,
					{Label: "Shipping Address", Value: orDash(sc.shipping)},
					{Label: "School Type", Value: label},
					{Label: "Cluster", Value: clusterName, Href: clusterHref},
					{Label: "Enrollment", Value: enrolment},
					{Label: "Phone", Value: orDash(sc.phone)},
					{Label: "Primary Contact", Value: orDash(sc.contact)},
					{Label: "Staff Name", Value: staffName, Href: staffHref},
					{Label: "SSA", Value: ssaText},
				},
				DetailsHref: "/schools/" + sc.code,
				DetailBlocks: []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
					Title: "Intervention scores", Subtitle: "SSA detail", Items: ssaItems,
				}}}},
			}
			if pg.tick {
				row.PickId = sc.code
			}
			table.Rows = append(table.Rows, row)
		}
		if len(shown) == 0 {
			table.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No " + strings.ToLower(label) + " schools in this portfolio."}}}}
		} else {
			pg.programmeRows = true
		}
		if total > pg.perPage {
			// The section's own Previous / Page / Next, which the feed reads
			// as an empty pager.
			table.Pager = &screensv1.PagePager{}
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}})
	}
	return blocks, nil
}

func mustAtoi(s string) int {
	n, _ := strconv.Atoi(s)
	return n
}
