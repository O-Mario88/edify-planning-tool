package coreschools

import (
	"context"
	"fmt"
	"slices"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// queueRow is one school of get_planning_queue.
type queueRow struct {
	school
	staff, partner, weakest, next string
	visitsDone, trainingsDone     int
	visitMarks, trainingMarks     []mark
}

// planningQueue is get_planning_queue over the page's schools.
func (pg *page) planningQueue(ctx context.Context) ([]queueRow, error) {
	db, fy := pg.db, pg.fy
	pks, codes := ids(pg.shown)
	plans, err := readPlans(ctx, db, codes, fy)
	if err != nil {
		return nil, err
	}
	staff, err := names(ctx, db, `SELECT sp.user_id, coalesce(u.name, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.user_id IS NOT NULL`)
	if err != nil {
		return nil, err
	}
	partners, err := names(ctx, db, `SELECT id, name FROM partner`)
	if err != nil {
		return nil, err
	}
	assigned := map[string]string{}
	rows, err := db.Query(ctx, `SELECT school_id, partner_id FROM partner_assignment
WHERE school_id = ANY($1) AND status = ANY($2) ORDER BY school_id, created_at DESC`, pks, rules.PartnerUnscheduled)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the waiting hand-overs: %w", err)
	}
	for rows.Next() {
		var school string
		var partner *string
		if err := rows.Scan(&school, &partner); err != nil {
			rows.Close()
			return nil, fmt.Errorf("coreschools: reading a waiting hand-over: %w", err)
		}
		if _, ok := assigned[school]; !ok {
			assigned[school] = ""
			if partner != nil {
				assigned[school] = *partner
			}
		}
	}
	rows.Close()
	// Each school's latest confirmed SSA of the year, then each one's lowest
	// score: read as the existing page reads them (by record, then score),
	// so two equal lowest scores resolve as they do there.
	latest := map[string]string{} // school → record
	lrows, err := db.Query(ctx, `SELECT DISTINCT ON (school_id) school_id, id FROM ssa_record
WHERE school_id = ANY($1) AND fy = $2 AND deleted_at IS NULL AND verification_status = 'confirmed'
ORDER BY school_id, date_of_ssa DESC, created_at DESC`, pks, fy)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the latest assessments: %w", err)
	}
	records := []string{}
	for lrows.Next() {
		var school, record string
		if err := lrows.Scan(&school, &record); err != nil {
			lrows.Close()
			return nil, fmt.Errorf("coreschools: reading a latest assessment: %w", err)
		}
		latest[school] = record
		records = append(records, record)
	}
	lrows.Close()
	lowestOf := map[string]string{} // record → intervention
	srows, err := db.Query(ctx, `SELECT ssa_record_id, intervention FROM ssa_score WHERE ssa_record_id = ANY($1) ORDER BY ssa_record_id, score`, records)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the weakest interventions: %w", err)
	}
	for srows.Next() {
		var record, intervention string
		if err := srows.Scan(&record, &intervention); err != nil {
			srows.Close()
			return nil, fmt.Errorf("coreschools: reading a weakest intervention: %w", err)
		}
		if _, ok := lowestOf[record]; !ok {
			lowestOf[record] = intervention
		}
	}
	srows.Close()
	core := schoolprofile.GateRules().Core
	out := []queueRow{}
	for _, sc := range pg.shown {
		q := queueRow{school: sc, staff: "Unassigned", partner: "Unassigned", weakest: "—"}
		if sc.ownerID != "" {
			q.staff = staff[sc.ownerID]
			if _, ok := staff[sc.ownerID]; !ok {
				q.staff = "Staff Owner"
			}
		}
		if pid, ok := assigned[sc.id]; ok && pid != "" {
			q.partner = partners[pid]
			if _, known := partners[pid]; !known {
				q.partner = "Partner Owner"
			}
		}
		p := plans[sc.code]
		if p != nil {
			for _, s := range p.slots {
				if slices.Contains(rules.SlotDoneWithLegacy, s.status) {
					switch s.kind {
					case "visit":
						q.visitsDone++
					case "training":
						q.trainingsDone++
					}
				}
			}
			q.visitMarks, q.trainingMarks = marks(p.ofKind("visit"), core), marks(p.ofKind("training"), core)
			for _, s := range p.slots {
				if s.owner == "partner" {
					if s.partner != "" {
						q.partner = s.partner
					}
					break
				}
			}
		}
		switch {
		case sc.clusterID == "":
			q.weakest, q.next = "Requires Cluster", "Requires Cluster"
		case latest[sc.id] == "":
			q.weakest, q.next = "Assessment Required", "Assessment Required"
		default:
			if code, ok := lowestOf[latest[sc.id]]; ok {
				q.weakest = interventionLabel(code)
			}
			assessed := p != nil
			var openVisit, openTraining *mark
			for i := range q.visitMarks {
				if q.visitMarks[i].state == "open" {
					openVisit = &q.visitMarks[i]
					break
				}
			}
			for i := range q.trainingMarks {
				if q.trainingMarks[i].state == "open" {
					openTraining = &q.trainingMarks[i]
					break
				}
			}
			switch {
			case !assessed:
				q.next = "Core Assessment"
			case openVisit != nil:
				q.next = openVisit.label + " Visit"
			case openTraining != nil:
				q.next = openTraining.label + " Training"
			case q.visitsDone >= 4 && q.trainingsDone >= 4:
				q.next = "Graduation Review"
			default:
				q.next = "Package planned"
			}
		}
		out = append(out, q)
	}
	return out, nil
}

// queue is the Core Planning Queue tab.
func (pg *page) queue(ctx context.Context) ([]*screensv1.PageBlock, error) {
	rows, err := pg.planningQueue(ctx)
	if err != nil {
		return nil, err
	}
	if len(rows) == 0 {
		return []*screensv1.PageBlock{textPanel("⭐", "All core schools are fully planned.")}, nil
	}
	cols := []*screensv1.PageColumn{}
	for _, c := range []string{"School ID", "School", "Ownership", "Weakest Intervention", "Progress"} {
		cols = append(cols, &screensv1.PageColumn{Label: c})
	}
	cols = append(cols, &screensv1.PageColumn{Label: "Actions", Numeric: true})
	t := &screensv1.PageTable{Columns: cols}
	for _, q := range rows {
		code := ""
		if q.code == "" {
			code = "—"
		}
		weakest := &screensv1.PageCell{Text: q.weakest, Tone: "primary", Badge: true}
		if q.weakest == "Requires Cluster" || q.weakest == "Assessment Required" {
			weakest = &screensv1.PageCell{Text: "—"}
		}
		region := q.regionName
		if region == "" {
			region = "—"
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: code}, {Text: q.name + " " + region, Href: "/schools/" + q.code},
			{Text: "S " + q.staff + " P " + q.partner}, weakest,
			{Text: progressText("Visits", q.visitMarks, q.visitsDone) + " " + progressText("Trainings", q.trainingMarks, q.trainingsDone)},
			{Text: nextAction(q.next)},
		}})
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pg.pages > 1 {
		blocks = append(blocks, pg.queuePager())
	}
	return blocks, nil
}

// progressText is a progress line: its marks run together, then the count.
func progressText(kind string, ms []mark, finished int) string {
	labels := ""
	for _, m := range ms {
		labels += m.label
	}
	parts := []string{kind}
	if labels != "" {
		parts = append(parts, labels)
	}
	return strings.Join(append(parts, fmt.Sprintf("%d/4", finished)), " ")
}

// nextAction is the row's one control, as its words read.
func nextAction(next string) string {
	switch next {
	case "Requires Cluster":
		return "Cluster required"
	case "Assessment Required":
		return "Upload Assessment"
	case "Package planned":
		return "Package planned"
	case "Graduation Review", "Core Assessment":
		return "Review SSA"
	}
	slot := string([]rune(next)[:min(2, len([]rune(next)))])
	if strings.Contains(next, "Visit") {
		return "Schedule Visit (" + slot + ")"
	}
	return "Schedule Training (" + slot + ")"
}

// queuePager is the queue's Previous and Next as the feed reads them.
func (pg *page) queuePager() *screensv1.PageBlock {
	f := pg.f
	href := func(n int) string {
		return fmt.Sprintf("/core-schools?page=%d&fy=%s&region=%s&district=%s&staff=%s&partner=%s&school_type_filter=%s&ssa_status=%s&partner_assigned=%s",
			n, pg.fy, f.region, f.district, f.staff, f.partner, f.schoolType, f.ssaStatus, f.partnerAssigned)
	}
	prev := &screensv1.PagePagerPage{Label: "Previous"}
	if pg.number > 1 {
		prev.Href = href(pg.number - 1)
	}
	next := &screensv1.PagePagerPage{Label: "Next"}
	if pg.number < pg.pages {
		next.Href = href(pg.number + 1)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Pager{Pager: &screensv1.PagePager{Pages: []*screensv1.PagePagerPage{prev, next}}}}
}
