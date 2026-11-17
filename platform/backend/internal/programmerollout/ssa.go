package programmerollout

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The four SSA states, in precedence order (SSA_STATES).
const (
	stateConfirmed  = "confirmed"
	stateAwaiting   = "awaiting"
	stateScheduled  = "scheduled"
	stateNotPlanned = "not_planned"
)

// noCluster is NO_CLUSTER: the cluster row of schools in none.
const noCluster = "none"

func (s *scope) schoolIDs() []string {
	out := make([]string, 0, len(s.schools))
	for id := range s.schools {
		out = append(out, id)
	}
	sort.Strings(out)
	return out
}

func (s *scope) clusterIDs() []string {
	seen := map[string]bool{}
	out := []string{}
	for _, sc := range s.schools {
		if sc.cluster != "" && !seen[sc.cluster] {
			seen[sc.cluster] = true
			out = append(out, sc.cluster)
		}
	}
	sort.Strings(out)
	return out
}

// membersOfCluster is each cluster's portfolio schools.
func (s *scope) membersOfCluster() map[string][]string {
	out := map[string][]string{}
	for id, sc := range s.schools {
		if sc.cluster != "" {
			out[sc.cluster] = append(out[sc.cluster], id)
		}
	}
	return out
}

// ssaStates is ssa_states: each portfolio school's state for the year. A
// school takes the first state it qualifies for: a confirmed record; a record
// Impact Assessment has not confirmed, or a collection already held; a
// collection planned or scheduled, or an unscheduled partner hand-over;
// otherwise nothing is planned. Cluster collections count for the schools
// invited or recorded at them, or every portfolio school in the cluster when
// none is recorded. Only the state is read: the fact behind it is the
// drawer's.
func (s *Service) ssaStates(ctx context.Context, sc *scope, fy string) (map[string]string, error) {
	states := map[string]string{}
	if len(sc.schools) == 0 {
		return states, nil
	}
	portfolio := sc.schoolIDs()
	confirmed, awaiting, scheduled := map[string]bool{}, map[string]bool{}, map[string]bool{}

	rows, err := s.db.Query(ctx, `SELECT school_id, COALESCE(verification_status, '') FROM ssa_record
WHERE school_id = ANY($1) AND fy = $2 AND deleted_at IS NULL`, portfolio, fy)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the year's SSA records: %w", err)
	}
	for rows.Next() {
		var school, status string
		if err := rows.Scan(&school, &status); err != nil {
			rows.Close()
			return nil, fmt.Errorf("programmerollout: reading an SSA record: %w", err)
		}
		switch {
		case status == rules.SSA.ConfirmedStatus:
			confirmed[school] = true
		case slices.Contains(rules.SSA.AwaitingRecordStatuses, status):
			awaiting[school] = true
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("programmerollout: reading the year's SSA records: %w", err)
	}

	clusters := sc.clusterIDs()
	members := sc.membersOfCluster()
	where, args := sc.activityFilter([]any{fy, rules.SSA.CollectionTypes, rules.NotPlannedStatuses, clusters})
	type collection struct {
		id, school, cluster, status string
		attended                    []string
	}
	collections := []collection{}
	rows, err = s.db.Query(ctx, `SELECT a.id, COALESCE(a.school_id, ''), COALESCE(a.cluster_id, ''), COALESCE(a.status, ''),
  COALESCE(a.attended_school_ids, '{}') FROM activity a
WHERE (`+where+` OR (a.school_id IS NULL AND a.cluster_id = ANY($4))) AND a.fy = $1 AND a.deleted_at IS NULL
  AND a.activity_type = ANY($2) AND NOT COALESCE(a.status = ANY($3), FALSE)`, args...)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the SSA collections: %w", err)
	}
	sessions := []string{}
	for rows.Next() {
		var c collection
		if err := rows.Scan(&c.id, &c.school, &c.cluster, &c.status, &c.attended); err != nil {
			rows.Close()
			return nil, fmt.Errorf("programmerollout: reading an SSA collection: %w", err)
		}
		collections = append(collections, c)
		if c.school == "" {
			sessions = append(sessions, c.id)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("programmerollout: reading the SSA collections: %w", err)
	}
	invited := map[string][]string{}
	if len(sessions) > 0 {
		rows, err = s.db.Query(ctx, `SELECT activity_id, school_id FROM cluster_activity_attendance WHERE activity_id = ANY($1)`, sessions)
		if err != nil {
			return nil, fmt.Errorf("programmerollout: reading the collections' schools: %w", err)
		}
		for rows.Next() {
			var id, school string
			if err := rows.Scan(&id, &school); err != nil {
				rows.Close()
				return nil, fmt.Errorf("programmerollout: reading a collection's school: %w", err)
			}
			invited[id] = append(invited[id], school)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return nil, fmt.Errorf("programmerollout: reading the collections' schools: %w", err)
		}
	}
	for _, c := range collections {
		schools := []string{c.school}
		if c.school == "" {
			schools = append(append([]string{}, invited[c.id]...), c.attended...)
			if len(schools) == 0 {
				schools = members[c.cluster]
			}
		}
		for _, id := range schools {
			if _, ok := sc.schools[id]; !ok {
				continue
			}
			if slices.Contains(rules.LiveStatuses, c.status) {
				scheduled[id] = true
			} else {
				awaiting[id] = true
			}
		}
	}

	start, _ := strconv.Atoi(fy)
	from := time.Date(start-1, time.October, 1, 0, 0, 0, 0, time.UTC)
	rows, err = s.db.Query(ctx, `SELECT COALESCE(pa.school_id, ''), COALESCE(pa.cluster_id, '') FROM partner_assignment pa
LEFT JOIN activity_catalogue_item ci ON ci.id = pa.catalogue_item_id
WHERE (pa.school_id = ANY($1) OR (pa.school_id IS NULL AND pa.cluster_id = ANY($2))) AND pa.status = ANY($3)
  AND pa.created_at >= $4 AND pa.created_at < $5 AND (pa.expected_activity_type = ANY($6) OR ci.workflow_kind = ANY($6))`,
		portfolio, clusters, rules.SSA.UnscheduledAssignmentStatuses, from, from.AddDate(1, 0, 0), rules.SSA.CollectionTypes)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the partner hand-overs: %w", err)
	}
	for rows.Next() {
		var school, cluster string
		if err := rows.Scan(&school, &cluster); err != nil {
			rows.Close()
			return nil, fmt.Errorf("programmerollout: reading a partner hand-over: %w", err)
		}
		schools := []string{school}
		if school == "" {
			schools = members[cluster]
		}
		for _, id := range schools {
			if _, ok := sc.schools[id]; ok {
				scheduled[id] = true
			}
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("programmerollout: reading the partner hand-overs: %w", err)
	}

	for _, id := range portfolio {
		switch {
		case confirmed[id]:
			states[id] = stateConfirmed
		case awaiting[id]:
			states[id] = stateAwaiting
		case scheduled[id]:
			states[id] = stateScheduled
		default:
			states[id] = stateNotPlanned
		}
	}
	return states, nil
}

// stateCounts is _state_counts over some schools.
type stateCounts struct {
	portfolio, confirmed, awaiting, scheduled, notPlanned int
	coverage                                              *int
}

func countStates(schools map[string]bool, states map[string]string) stateCounts {
	c := stateCounts{portfolio: len(schools)}
	for id := range schools {
		switch states[id] {
		case stateConfirmed:
			c.confirmed++
		case stateAwaiting:
			c.awaiting++
		case stateScheduled:
			c.scheduled++
		case stateNotPlanned:
			c.notPlanned++
		}
	}
	c.coverage = percentage(c.confirmed, c.portfolio)
	return c
}

// confirmedText is the Confirmed SSA cell: "n · p%".
func (c stateCounts) confirmedText() string {
	text := intcomma(c.confirmed)
	if c.coverage != nil {
		text += fmt.Sprintf(" · %d%%", *c.coverage)
	}
	return text
}

// matrixRow is one cluster of the SSA intervention heatmap.
type matrixRow struct {
	name    string
	cells   []*float64
	overall *float64
}

// ssaScore is _ssa_score: round(round(x, 6), 1).
func ssaScore(x *float64) *float64 {
	if x == nil {
		return nil
	}
	v := pyRound(pyRound(*x, 6), 1)
	return &v
}

func pyRound(x float64, digits int) float64 {
	v, _ := strconv.ParseFloat(strconv.FormatFloat(x, 'f', digits, 64), 64)
	return v
}

// matrix is ProgramLeadDashboardService.ssa_cluster_matrix over the
// portfolio: each cluster's average score per intervention and overall, in
// the latest year at or before fy with a confirmed SSA.
func (s *Service) matrix(ctx context.Context, sc *scope, fy string) ([]matrixRow, error) {
	if len(sc.schools) == 0 {
		return nil, nil
	}
	portfolio := sc.schoolIDs()
	rows, err := s.db.Query(ctx, `SELECT DISTINCT fy FROM ssa_record WHERE school_id = ANY($1) AND verification_status = $2
  AND fy <= $3 AND deleted_at IS NULL AND fy IS NOT NULL`, portfolio, rules.SSA.ConfirmedStatus, fy)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the SSA cycles: %w", err)
	}
	latest := ""
	for rows.Next() {
		var y string
		if err := rows.Scan(&y); err != nil {
			rows.Close()
			return nil, fmt.Errorf("programmerollout: reading an SSA cycle: %w", err)
		}
		if y > latest {
			latest = y
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("programmerollout: reading the SSA cycles: %w", err)
	}
	if latest == "" {
		return nil, nil
	}
	clusters := sc.clusterIDs()
	names, err := s.clusterNames(ctx, clusters)
	if err != nil {
		return nil, err
	}
	const records = `FROM ssa_record r JOIN school s ON s.id = r.school_id
WHERE r.school_id = ANY($1) AND COALESCE(s.cluster_id, '') <> '' AND r.verification_status = $2 AND r.fy = $3 AND r.deleted_at IS NULL`
	scores := map[string]map[string]*float64{}
	rows, err = s.db.Query(ctx, `SELECT s.cluster_id, x.intervention, AVG(x.score) FROM ssa_score x JOIN ssa_record r ON r.id = x.ssa_record_id
JOIN school s ON s.id = r.school_id
WHERE r.school_id = ANY($1) AND COALESCE(s.cluster_id, '') <> '' AND r.verification_status = $2 AND r.fy = $3 AND r.deleted_at IS NULL
GROUP BY 1, 2`, portfolio, rules.SSA.ConfirmedStatus, latest)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the heatmap's scores: %w", err)
	}
	for rows.Next() {
		var cluster, intervention string
		var avg *float64
		if err := rows.Scan(&cluster, &intervention, &avg); err != nil {
			rows.Close()
			return nil, fmt.Errorf("programmerollout: reading a heatmap score: %w", err)
		}
		if scores[cluster] == nil {
			scores[cluster] = map[string]*float64{}
		}
		scores[cluster][intervention] = avg
	}
	rows.Close()
	overall := map[string]*float64{}
	rows, err = s.db.Query(ctx, `SELECT s.cluster_id, AVG(r.average_score) `+records+` GROUP BY 1`, portfolio, rules.SSA.ConfirmedStatus, latest)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the heatmap's averages: %w", err)
	}
	for rows.Next() {
		var cluster string
		var avg *float64
		if err := rows.Scan(&cluster, &avg); err != nil {
			rows.Close()
			return nil, fmt.Errorf("programmerollout: reading a heatmap average: %w", err)
		}
		overall[cluster] = avg
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("programmerollout: reading the heatmap's averages: %w", err)
	}
	out := []matrixRow{}
	for _, id := range clusters {
		name, ok := names[id]
		if !ok {
			name = "Cluster"
		}
		row := matrixRow{name: name, overall: ssaScore(overall[id])}
		for _, col := range rules.SSA.MatrixInterventions {
			row.cells = append(row.cells, ssaScore(scores[id][col[0]]))
		}
		out = append(out, row)
	}
	return out, nil
}

func scoreCell(v *float64) *screensv1.PageCell {
	if v == nil {
		return cell("—")
	}
	return cell(strconv.FormatFloat(*v, 'f', 1, 64))
}

// clusterRow is one row of SSA rollout by cluster.
type clusterRow struct {
	stateCounts
	id, name, officers string
}

// selfAssessments is the Self-Assessments view's blocks (ssa_rollout, the
// view's tiles and partials/programme_rollout/ssa.html). A table running
// past a page hands on.
func (s *Service) selfAssessments(ctx context.Context, sc *scope, fy string) ([]*screensv1.PageBlock, bool, error) {
	states, err := s.ssaStates(ctx, sc, fy)
	if err != nil {
		return nil, true, err
	}
	all := map[string]bool{}
	for id := range sc.schools {
		all[id] = true
	}
	summary := countStates(all, states)
	carry := sc.carry
	drawer := func(state string, n int) string {
		if n == 0 {
			return ""
		}
		return schoolsURL + "?kind=ssa_" + state + "&" + carry
	}
	confirmedValue := "—"
	if summary.portfolio > 0 {
		confirmedValue = strconv.Itoa(summary.confirmed)
	}
	confirmedHelper := fmt.Sprintf("of %d portfolio schools", summary.portfolio)
	if summary.coverage != nil {
		confirmedHelper += fmt.Sprintf(" · %d%%", *summary.coverage)
	}
	confirmedTone := "warning"
	if summary.coverage != nil && *summary.coverage >= 80 {
		confirmedTone = "success"
	}
	notPlannedTone := "success"
	if summary.notPlanned > 0 {
		notPlannedTone = "danger"
	}
	blocks := []*screensv1.PageBlock{strip("Rollout at a glance", []tile{
		{"Schools With a Confirmed SSA", confirmedValue, confirmedHelper, confirmedTone, drawer(stateConfirmed, summary.confirmed)},
		{"SSAs Awaiting IA Verification", strconv.Itoa(summary.awaiting), "collected, not yet confirmed", "info", drawer(stateAwaiting, summary.awaiting)},
		{"SSA Collections Scheduled", strconv.Itoa(summary.scheduled), "planned, or handed to a partner", "info", drawer(stateScheduled, summary.scheduled)},
		{"Schools With No SSA Planned", strconv.Itoa(summary.notPlanned), "no collection planned this year", notPlannedTone, drawer(stateNotPlanned, summary.notPlanned)},
	})}

	// By officer.
	people := sc.rows(nil)
	if len(people) > rules.OfficerRows {
		return nil, false, nil
	}
	ot := &screensv1.PageTable{Columns: columns("Officer", "Portfolio schools", "Confirmed SSA", "Awaiting PL verification",
		"Scheduled or with a partner", "Not yet planned", "")}
	for _, m := range people {
		c := countStates(m.schools, states)
		name := &screensv1.PageCell{Text: memberName(m)}
		owner := m.staffID
		if m.isLead {
			owner = "mine"
		} else {
			name.Href = "/staff/" + m.userID + "?from=" + Path
		}
		confirmedCell := "No schools"
		if c.portfolio > 0 {
			confirmedCell = c.confirmedText()
		}
		oversight := "/team-planning-oversight/?owner=" + owner + "&fy=" + fy
		actions := []*screensv1.PageAction{{Key: "button", Label: "Oversight", Primary: true, Enabled: true, Href: oversight}}
		if c.notPlanned > 0 || c.awaiting > 0 {
			actions = nil
			if c.notPlanned > 0 {
				actions = append(actions, &screensv1.PageAction{Key: "menu", Label: "Not planned", Enabled: true, Drawer: true,
					Href: schoolsURL + "?kind=ssa_not_planned&member=" + m.staffID + "&" + carry})
			}
			if c.awaiting > 0 {
				actions = append(actions, &screensv1.PageAction{Key: "menu", Label: "Awaiting", Enabled: true, Drawer: true,
					Href: schoolsURL + "?kind=ssa_awaiting&member=" + m.staffID + "&" + carry})
			}
			actions = append(actions, &screensv1.PageAction{Key: "menu", Label: "Oversight", Enabled: true, Href: oversight})
		}
		ot.Rows = append(ot.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{name, num(c.portfolio), cell(confirmedCell),
			num(c.awaiting), num(c.scheduled), num(c.notPlanned), {Actions: actions}}})
	}
	if len(people) == 0 {
		empty(ot, "No officers or portfolio schools on this team yet.", "Officers appear here once HR records you as their supervisor.")
	} else {
		total := &screensv1.PageCell{}
		if summary.notPlanned > 0 {
			total = &screensv1.PageCell{Actions: []*screensv1.PageAction{{Key: "button", Label: "Not planned", Primary: true, Enabled: true,
				Drawer: true, Href: schoolsURL + "?kind=ssa_not_planned&" + carry}}}
		}
		ot.Rows = append(ot.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{cell("Whole team"), num(summary.portfolio),
			cell(summary.confirmedText()), num(summary.awaiting), num(summary.scheduled), num(summary.notPlanned), total}})
	}
	blocks = append(blocks, titled("SSA rollout by officer"), table(ot),
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{
			Text: "A school takes the first state it qualifies for. A school two officers share counts in both rows and once in the team total. Awaiting PL verification includes a collection held whose confirmed record has not arrived."}}}}}})

	// By cluster, lowest coverage first.
	byCluster := map[string]map[string]bool{}
	for id, school := range sc.schools {
		key := school.cluster
		if key == "" {
			key = noCluster
		}
		if byCluster[key] == nil {
			byCluster[key] = map[string]bool{}
		}
		byCluster[key][id] = true
	}
	if len(byCluster) > rules.PageSize {
		return nil, false, nil
	}
	names, err := s.clusterNames(ctx, sc.clusterIDs())
	if err != nil {
		return nil, true, err
	}
	clusterRows := []clusterRow{}
	for key, schools := range byCluster {
		row := clusterRow{stateCounts: countStates(schools, states), id: key, name: "Not in a cluster"}
		if key != noCluster {
			row.name = "Cluster"
			if n, ok := names[key]; ok {
				row.name = n
			}
		}
		owners := map[string]bool{}
		for id := range schools {
			for _, owner := range sc.ownersBySchool[id] {
				owners[owner] = true
			}
		}
		officers := []string{}
		for owner := range owners {
			if m := sc.member(owner); m != nil {
				officers = append(officers, memberName(m))
			}
		}
		sort.Strings(officers)
		row.officers = strings.Join(officers, ", ")
		clusterRows = append(clusterRows, row)
	}
	sort.Slice(clusterRows, func(i, j int) bool {
		a, b := clusterRows[i], clusterRows[j]
		if (a.id == noCluster) != (b.id == noCluster) {
			return b.id == noCluster
		}
		ca, cb := 101, 101
		if a.coverage != nil {
			ca = *a.coverage
		}
		if b.coverage != nil {
			cb = *b.coverage
		}
		if ca != cb {
			return ca < cb
		}
		if a.notPlanned != b.notPlanned {
			return a.notPlanned > b.notPlanned
		}
		return a.name < b.name
	})
	ct := &screensv1.PageTable{Columns: columns("Cluster", "Officers", "Schools", "Confirmed SSA", "Awaiting PL verification",
		"Scheduled or with a partner", "Not yet planned", "")}
	for _, r := range clusterRows {
		officers := r.officers
		if officers == "" {
			officers = "—"
		}
		action := &screensv1.PageCell{}
		if r.notPlanned > 0 {
			action = &screensv1.PageCell{Actions: []*screensv1.PageAction{{Key: "button", Label: "Not planned", Primary: true, Enabled: true,
				Drawer: true, Href: schoolsURL + "?kind=ssa_not_planned&cluster=" + r.id + "&" + carry}}}
		}
		ct.Rows = append(ct.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{cell(r.name), cell(officers), num(r.portfolio),
			cell(r.confirmedText()), num(r.awaiting), num(r.scheduled), num(r.notPlanned), action}})
	}
	if len(clusterRows) == 0 {
		empty(ct, "No portfolio school is in a cluster yet.", "")
	}
	blocks = append(blocks, titled("SSA rollout by cluster"), table(ct))

	// The cluster × intervention heatmap.
	heat, err := s.matrix(ctx, sc, fy)
	if err != nil {
		return nil, true, err
	}
	if len(heat) > rules.PageSize {
		return nil, false, nil
	}
	labels := []string{"Cluster"}
	// A team with no schools has no matrix at all, so no intervention heads.
	for _, col := range rules.SSA.MatrixInterventions {
		if len(sc.schools) > 0 {
			labels = append(labels, col[2])
		}
	}
	ht := &screensv1.PageTable{Columns: columns(append(labels, "Overall")...)}
	for _, r := range heat {
		cells := []*screensv1.PageCell{cell(r.name)}
		for _, v := range r.cells {
			cells = append(cells, scoreCell(v))
		}
		ht.Rows = append(ht.Rows, &screensv1.PageRow{Cells: append(cells, scoreCell(r.overall))})
	}
	if len(heat) == 0 {
		empty(ht, "No confirmed SSA in your clusters yet.", "The heatmap fills in as Impact Assessment confirms the team's assessments.")
	}
	blocks = append(blocks, titled("SSA intervention heatmap"), table(ht))
	return blocks, true, nil
}

// clusterNames is the live clusters' names (Cluster.objects).
func (s *Service) clusterNames(ctx context.Context, ids []string) (map[string]string, error) {
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(name, '') FROM cluster WHERE id = ANY($1) AND deleted_at IS NULL`, ids)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the clusters' names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("programmerollout: reading a cluster's name: %w", err)
		}
		out[id] = name
	}
	return out, rows.Err()
}
