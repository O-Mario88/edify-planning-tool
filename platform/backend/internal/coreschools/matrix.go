package coreschools

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// slot is one of a package's slots.
type slot struct {
	kind, status, owner, partner, intervention, activity string
	seq                                                  int
}

// plan is a school's package for the year.
type plan struct {
	id, school         string
	visitsTarget       int
	trainingsTarget    int
	baseline, followUp *float64
	slots              []slot
}

// readPlans is each school's package for fy (by School ID) with its slots.
func readPlans(ctx context.Context, db schooldirectory.Querier, codes []string, fy string) (map[string]*plan, error) {
	rows, err := db.Query(ctx, `
SELECT id, school_id, coalesce(visits_target, 0), coalesce(trainings_target, 0), baseline_average, follow_up_average
FROM core_plan WHERE school_id = ANY($1) AND fy = $2`, codes, fy)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the packages: %w", err)
	}
	out, byID, ids := map[string]*plan{}, map[string]*plan{}, []string{}
	for rows.Next() {
		p := &plan{}
		if err := rows.Scan(&p.id, &p.school, &p.visitsTarget, &p.trainingsTarget, &p.baseline, &p.followUp); err != nil {
			rows.Close()
			return nil, fmt.Errorf("coreschools: reading a package: %w", err)
		}
		out[p.school] = p
		byID[p.id] = p
		ids = append(ids, p.id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("coreschools: reading the packages: %w", err)
	}
	srows, err := db.Query(ctx, `
SELECT core_plan_id, coalesce(activity_type, ''), coalesce(sequence_number, 0), coalesce(status, ''), coalesce(owner, ''),
       coalesce(assigned_partner_name, ''), coalesce(intervention, ''), coalesce(activity_id, '')
FROM core_activity_slot WHERE core_plan_id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the package slots: %w", err)
	}
	defer srows.Close()
	for srows.Next() {
		var pid string
		var s slot
		if err := srows.Scan(&pid, &s.kind, &s.seq, &s.status, &s.owner, &s.partner, &s.intervention, &s.activity); err != nil {
			return nil, fmt.Errorf("coreschools: reading a package slot: %w", err)
		}
		byID[pid].slots = append(byID[pid].slots, s)
	}
	return out, srows.Err()
}

// ofKind are a package's slots of a kind, by their sequence.
func (p *plan) ofKind(kind string) []slot {
	if p == nil {
		return nil
	}
	out := []slot{}
	for _, s := range p.slots {
		if s.kind == kind {
			out = append(out, s)
		}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].seq < out[j].seq })
	return out
}

func (p *plan) slotAt(kind string, seq int) *slot {
	for _, s := range p.ofKind(kind) {
		if s.seq == seq {
			return &s
		}
	}
	return nil
}

// mark is one of package_marks: a slot's label and state.
type mark struct{ label, state string }

func marks(slots []slot, core visitgate.CoreRules) []mark {
	out := []mark{}
	for _, s := range slots {
		letter := map[string]string{"visit": "V", "training": "T"}[s.kind]
		if letter == "" {
			letter = "A"
		}
		out = append(out, mark{label: letter + strconv.Itoa(s.seq), state: core.SlotState(s.status)})
	}
	return out
}

func done(ms []mark) int {
	n := 0
	for _, m := range ms {
		if m.state == "done" {
			n++
		}
	}
	return n
}

// row is one school of the matrix (get_matrix_data's row, as the template
// reads it).
type row struct {
	school
	clusterName, staffName, assessment, nextMissing  string
	partnerCount, extraGroupTrainings                int
	visits, trainings, visitsTarget, trainingsTarget int
	visitsDone, trainingsDone                        int
	packageComplete, available                       bool
	blockedReason                                    string
	gate                                             visitgate.Gate
	ssaAverage                                       *float64
	ssaGroups                                        []schooldirectory.SSAGroup
	hasScores                                        bool
}

// matrixRows is get_matrix_data over the page's schools.
func (pg *page) matrixRows(ctx context.Context, list []school) ([]row, error) {
	db, fy := pg.db, pg.fy
	pks, codes := ids(list)
	plans, err := readPlans(ctx, db, codes, fy)
	if err != nil {
		return nil, err
	}
	scores, err := latestConfirmedScores(ctx, db, pks, fy)
	if err != nil {
		return nil, err
	}
	cells, err := assessmentCells(ctx, db, pks, fy)
	if err != nil {
		return nil, err
	}
	clusters, err := names(ctx, db, `SELECT id, name FROM cluster WHERE id = ANY($1) AND deleted_at IS NULL`, clusterIDs(list))
	if err != nil {
		return nil, err
	}
	staff, err := staffNames(ctx, db, list)
	if err != nil {
		return nil, err
	}
	partners, err := counts(ctx, db, `SELECT school_id, count(*) FROM partner_assignment
WHERE school_id = ANY($1) AND status IS DISTINCT FROM $2 GROUP BY school_id`, pks, rules.PartnerReturnedToStaff)
	if err != nil {
		return nil, err
	}
	extra, err := extraGroupTrainings(ctx, db, list, plans, fy)
	if err != nil {
		return nil, err
	}
	gateRules := schoolprofile.GateRules()
	core := gateRules.Core
	out := []row{}
	for _, sc := range list {
		r := row{school: sc, assessment: cells[sc.id], partnerCount: partners[sc.id], extraGroupTrainings: extra[sc.id]}
		r.clusterName = "—"
		if sc.clusterID != "" {
			if n, ok := clusters[sc.clusterID]; ok {
				r.clusterName = n
			}
		}
		r.staffName = staff[sc.ownerID]
		if r.staffName == "" {
			r.staffName = sc.ownerRaw
		}
		if r.staffName == "" {
			r.staffName = "Unassigned"
		}
		if s, ok := scores[sc.id]; ok {
			r.ssaGroups, r.hasScores = schooldirectory.SSAGroups(s)
			r.ssaAverage, _ = schooldirectory.SSAAverage(s)
		}
		p := plans[sc.code]
		r.available = p != nil
		vm, tm := marks(p.ofKind("visit"), core), marks(p.ofKind("training"), core)
		r.visitsDone, r.trainingsDone = done(vm), done(tm)
		r.visitsTarget, r.trainingsTarget = 4, 4
		if p != nil {
			for _, s := range p.slots {
				if core.SlotTaken(s.status) {
					switch s.kind {
					case "visit":
						r.visits++
					case "training":
						r.trainings++
					}
				}
			}
			if p.visitsTarget != 0 {
				r.visitsTarget = p.visitsTarget
			}
			if p.trainingsTarget != 0 {
				r.trainingsTarget = p.trainingsTarget
			}
			r.packageComplete = r.visits >= r.visitsTarget && r.trainings >= r.trainingsTarget
			if r.packageComplete {
				r.blockedReason = "Package complete"
			}
		} else {
			r.blockedReason = "Core package unavailable"
		}
		r.nextMissing = "All Packages are Complete"
		for seq := 1; seq <= 4; seq++ {
			name := rules.SlotOrdinals[strconv.Itoa(seq)]
			if v := p.slotAtOrNil("visit", seq); v == nil || !core.SlotTaken(v.status) {
				r.nextMissing = "Missing " + name + " Visit"
				break
			}
			if t := p.slotAtOrNil("training", seq); t == nil || !core.SlotTaken(t.status) {
				r.nextMissing = "Missing " + name + " Training"
				break
			}
		}
		if r.gate, err = visitgate.Of(ctx, db, gateRules, visitgate.School{ID: sc.id, Code: sc.code, Name: sc.name, Type: sc.schoolType},
			fy, pg.operational); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, nil
}

func (p *plan) slotAtOrNil(kind string, seq int) *slot {
	if p == nil {
		return nil
	}
	return p.slotAt(kind, seq)
}

func clusterIDs(list []school) []string {
	out := []string{}
	for _, sc := range list {
		if sc.clusterID != "" {
			out = append(out, sc.clusterID)
		}
	}
	return out
}

// names reads an id → name map.
func names(ctx context.Context, db schooldirectory.Querier, query string, args ...any) (map[string]string, error) {
	rows, err := db.Query(ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading names: %w", err)
	}
	defer rows.Close()
	out := map[string]string{}
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("coreschools: reading a name: %w", err)
		}
		out[id] = name
	}
	return out, rows.Err()
}

// counts reads an id → count map.
func counts(ctx context.Context, db schooldirectory.Querier, query string, args ...any) (map[string]int, error) {
	rows, err := db.Query(ctx, query, args...)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading counts: %w", err)
	}
	defer rows.Close()
	out := map[string]int{}
	for rows.Next() {
		var id string
		var n int
		if err := rows.Scan(&id, &n); err != nil {
			return nil, fmt.Errorf("coreschools: reading a count: %w", err)
		}
		out[id] = n
	}
	return out, rows.Err()
}

// staffNames are the owners' names, by People record and by account alike.
func staffNames(ctx context.Context, db schooldirectory.Querier, list []school) (map[string]string, error) {
	owners := []string{}
	for _, sc := range list {
		if sc.ownerID != "" {
			owners = append(owners, sc.ownerID)
		}
	}
	out := map[string]string{}
	if len(owners) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `
SELECT sp.id, coalesce(sp.user_id, ''), coalesce(u.name, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1))`, owners)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the owners: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, user, name string
		if err := rows.Scan(&id, &user, &name); err != nil {
			return nil, fmt.Errorf("coreschools: reading an owner: %w", err)
		}
		if user != "" && name != "" {
			out[id], out[user] = name, name
		}
	}
	return out, rows.Err()
}

// latestConfirmedScores are each school's latest confirmed SSA of fy's
// scores.
func latestConfirmedScores(ctx context.Context, db schooldirectory.Querier, pks []string, fy string) (map[string][]schooldirectory.SSAScore, error) {
	rows, err := db.Query(ctx, `
WITH latest AS (
  SELECT DISTINCT ON (school_id) id, school_id FROM ssa_record
  WHERE school_id = ANY($1) AND fy = $2 AND deleted_at IS NULL AND verification_status = 'confirmed'
  ORDER BY school_id, date_of_ssa DESC, created_at DESC)
SELECT l.school_id, sc.intervention, sc.score FROM latest l LEFT JOIN ssa_score sc ON sc.ssa_record_id = l.id`, pks, fy)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the latest assessments: %w", err)
	}
	defer rows.Close()
	out := map[string][]schooldirectory.SSAScore{}
	for rows.Next() {
		var school string
		var intervention *string
		var score *float64
		if err := rows.Scan(&school, &intervention, &score); err != nil {
			return nil, fmt.Errorf("coreschools: reading an assessment score: %w", err)
		}
		if _, ok := out[school]; !ok {
			out[school] = []schooldirectory.SSAScore{}
		}
		if intervention != nil {
			out[school] = append(out[school], schooldirectory.SSAScore{Intervention: *intervention, Score: score})
		}
	}
	return out, rows.Err()
}

// assessmentCells is core_assessment_cells: the year's records' best state's
// word per school, or the word for none.
func assessmentCells(ctx context.Context, db schooldirectory.Querier, pks []string, fy string) (map[string]string, error) {
	rows, err := db.Query(ctx, `SELECT school_id, verification_status FROM ssa_record
WHERE school_id = ANY($1) AND fy = $2 AND deleted_at IS NULL AND verification_status = ANY($3)`, pks, fy, rules.AssessmentRank)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the assessments: %w", err)
	}
	defer rows.Close()
	best := map[string]int{}
	for rows.Next() {
		var school, status string
		if err := rows.Scan(&school, &status); err != nil {
			return nil, fmt.Errorf("coreschools: reading an assessment: %w", err)
		}
		rank := slices.Index(rules.AssessmentRank, status)
		if held, ok := best[school]; !ok || rank < held {
			best[school] = rank
		}
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("coreschools: reading the assessments: %w", err)
	}
	out := map[string]string{}
	for _, pk := range pks {
		out[pk] = rules.AssessmentMissing
		if rank, ok := best[pk]; ok {
			out[pk] = rules.AssessmentWords[rules.AssessmentRank[rank]]
		}
	}
	return out, nil
}

// extraGroupTrainings are the group trainings each school is invited to this
// year that fill no slot of its package.
func extraGroupTrainings(ctx context.Context, db schooldirectory.Querier, list []school, plans map[string]*plan, fy string) (map[string]int, error) {
	pks, _ := ids(list)
	rows, err := db.Query(ctx, `
SELECT DISTINCT caa.school_id, caa.activity_id FROM cluster_activity_attendance caa JOIN activity a ON a.id = caa.activity_id
WHERE caa.school_id = ANY($1) AND caa.invited AND a.fy = $2 AND a.deleted_at IS NULL
  AND a.activity_type = ANY($3) AND a.status = ANY($4)`, pks, fy, rules.ClusterTrainingTypes, rules.SessionLiveStatuses)
	if err != nil {
		return nil, fmt.Errorf("coreschools: reading the group trainings: %w", err)
	}
	defer rows.Close()
	code := map[string]string{}
	for _, sc := range list {
		code[sc.id] = sc.code
	}
	out := map[string]int{}
	for rows.Next() {
		var school, activity string
		if err := rows.Scan(&school, &activity); err != nil {
			return nil, fmt.Errorf("coreschools: reading a group training: %w", err)
		}
		held := false
		if p := plans[code[school]]; p != nil {
			for _, s := range p.slots {
				held = held || (s.activity != "" && s.activity == activity)
			}
		}
		if !held {
			out[school]++
		}
	}
	return out, rows.Err()
}

// record is the row as the feed reads partials/core_schools/school_row.html.
func (pg *page) record(r row) *screensv1.PageBlock {
	d := pg.door
	actions := []*screensv1.PageAction{{Key: "menu", Label: "Schedule", Enabled: true, Drawer: true,
		Href: "/core-schools/schedule-activity?school_id=" + r.code}}
	split := r.gate.Split
	caps := schoolprofile.GateRules().Core.Caps
	if r.available && split.StaffTrainings < caps.StaffTrainings {
		actions = append(actions, &screensv1.PageAction{Key: "menu", Label: "Training", Enabled: true, Drawer: true,
			Href: "/core-schools/schedule-training?school_id=" + r.code})
	}
	if r.available && r.gate.CanAssignPartner {
		actions = append(actions, &screensv1.PageAction{Key: "menu", Label: "Assign", Enabled: true, Drawer: true,
			Href: "/core-schools/assign-partner?school_id=" + r.code})
	}
	if d.AssignProject {
		actions = append(actions, &screensv1.PageAction{Key: "menu", Label: "Add to Project", Enabled: true, Drawer: true,
			Href: "/schools/" + r.id + "/assign-to-project"})
	}
	district := &screensv1.PageFact{Label: "District", Value: "—"}
	switch {
	case r.districtID != "":
		district.Value, district.Href = r.districtName, "/districts/"+r.districtID
	}
	owner := &screensv1.PageFact{Label: "Owner", Value: r.staffName}
	if r.ownerID != "" {
		owner.Href = "/staff/" + r.ownerID
	}
	tone := func(good bool) string {
		if good {
			return "good"
		}
		return "caution"
	}
	progress := func(planned, finished int) string {
		switch {
		case planned == 0:
			return "caution"
		case finished >= planned:
			return "good"
		}
		return "info"
	}
	facts := []*screensv1.PageFact{district, owner,
		{Label: "Assessment", Value: r.assessment, Tone: tone(r.assessment == rules.AssessmentWords[rules.AssessmentRank[0]])},
		{Label: "Visits", Tone: progress(r.visits, r.visitsDone),
			Value: fmt.Sprintf("%d/%d (staff %d/%d · partner %d/%d)", r.visits, r.visitsTarget, split.StaffVisits, caps.StaffVisits,
				split.PartnerHeldVisits(), caps.PartnerVisits)},
		{Label: "Trainings", Tone: progress(r.trainings, r.trainingsDone),
			Value: fmt.Sprintf("%d/%d (staff %d/%d · partner %d/%d)", r.trainings, r.trainingsTarget, split.StaffTrainings, caps.StaffTrainings,
				split.PartnerHeldTrainings(), caps.PartnerTrainings)},
	}
	if r.extraGroupTrainings > 0 {
		word := "group trainings"
		if r.extraGroupTrainings == 1 {
			word = "group training"
		}
		facts = append(facts, &screensv1.PageFact{Label: "Beyond the package", Value: fmt.Sprintf("%d %s", r.extraGroupTrainings, word)})
	}
	partner := "None"
	if r.partnerCount > 0 {
		partner = fmt.Sprintf("%d assigned", r.partnerCount)
	}
	pkg := r.nextMissing
	if r.packageComplete {
		pkg = "Complete"
	}
	facts = append(facts, &screensv1.PageFact{Label: "Partner", Value: partner},
		&screensv1.PageFact{Label: "Package", Value: pkg, Tone: tone(r.packageComplete)})

	orDash := func(s string) string {
		if s == "" {
			return "—"
		}
		return s
	}
	cluster := &screensv1.PageFact{Label: "Cluster:", Value: "Not assigned"}
	if r.clusterName != "—" {
		cluster.Value = r.clusterName
		if r.clusterID != "" && d.OpenClusters {
			cluster.Href = "/clusters/" + r.clusterID
		}
	}
	enrolment := "0"
	if r.enrollment != nil {
		enrolment = strconv.Itoa(*r.enrollment)
	}
	ssa := "Not assessed"
	if r.ssaAverage != nil {
		ssa = clusterpage.ScoreText(*r.ssaAverage) + "/10"
	}
	typeLabel := schoolTypeLabel(r.schoolType)
	if typeLabel == "" {
		typeLabel = "Core"
	}
	details := []*screensv1.PageFact{{Label: "Shipping Address:", Value: orDash(r.shipping)}, {Label: "School Type:", Value: typeLabel},
		cluster, {Label: "Enrollment:", Value: enrolment}, {Label: "Phone:", Value: orDash(r.phone)},
		{Label: "Primary Contact:", Value: orDash(r.contact)}, {Label: "SSA:", Value: ssa}}
	items := []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: "Latest confirmed assessment · FY " + pg.fy}}}
	if r.hasScores {
		items = append(items, clusterpage.ScoreGroupItems(r.ssaGroups)...)
	} else {
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: "No confirmed SSA scores are available yet."}})
	}
	rec := &screensv1.PageRecord{Title: r.name, Href: "/schools/" + r.code, Actions: actions, Facts: facts,
		Details: []*screensv1.PageBlock{
			{Kind: &screensv1.PageBlock_Facts{Facts: &screensv1.PageFacts{Facts: details}}},
			{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Intervention scores", Subtitle: "SSA detail", Items: items}}},
		}}
	if pg.tick {
		rec.PickId, rec.PickLabel = r.code, "Select "+r.name
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Record{Record: rec}}
}
