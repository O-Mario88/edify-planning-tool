package activities

// A cluster session's SSA reading (docs/migration/38): the invited schools'
// verified need (apps.ssa.plan_alignment.cluster_need), the verdict on it
// (assess and reason_for for a cluster), and the governed recommendation a
// course is scheduled under (activity_catalogue.services
// .recommend_cluster_activities, which merges each member's need as the
// school engine ranks it). Read-only.

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// clusterRow is one row of ClusterNeed.rows.
type clusterRow struct {
	Intervention, Label, Band   string
	Average                     float64
	SchoolsAssessed, SchoolsLow int
}

type clusterNeed struct {
	Members, Assessed, StaleSchools int
	Rows                            []clusterRow
	Priorities, SourceSSAIDs        []string
}

func (n clusterNeed) assessed() bool { return len(n.Rows) > 0 }
func (n clusterNeed) stale() bool    { return len(n.Rows) == 0 && n.StaleSchools > 0 }

// memberRecord is a member's latest confirmed SSA.
type memberRecord struct {
	SchoolID string
	Record   *ssaRecord
}

// clusterNeedOf is plan_alignment.cluster_need(cluster, invited): the
// invited members' latest confirmed records, the out-of-date ones set aside.
func clusterNeedOf(ctx context.Context, q Querier, clusterID string, invited []string, now time.Time) (clusterNeed, error) {
	rows, err := q.Query(ctx, `SELECT id FROM school WHERE cluster_id = $1 AND deleted_at IS NULL
  AND operational_status = ANY($2) AND id = ANY($3) ORDER BY id`, clusterID, rules.GroupTraining.OperatingStatuses, invited)
	if err != nil {
		return clusterNeed{}, fmt.Errorf("activities: reading the invited members: %w", err)
	}
	members, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return clusterNeed{}, fmt.Errorf("activities: reading the invited members: %w", err)
	}
	var records []memberRecord
	for _, id := range members {
		history, err := pgNeed{q}.confirmedHistory(ctx, id)
		if err != nil {
			return clusterNeed{}, err
		}
		if len(history) > 0 {
			records = append(records, memberRecord{id, latestApplicable(history)})
		}
	}
	return clusterNeedFrom(len(members), records, now), nil
}

// clusterNeedFrom is cluster_need's arithmetic: each intervention's mean
// over the current records (Python's sum, round half-even to one place),
// weakest first, with how many schools sit below 5.5.
func clusterNeedFrom(members int, records []memberRecord, now time.Time) clusterNeed {
	need := clusterNeed{Members: members}
	scores := map[string][]float64{}
	ids := []string{}
	for _, m := range records {
		if !isCurrent(m.Record, now) {
			need.StaleSchools++
			continue
		}
		need.Assessed++
		ids = append(ids, m.Record.ID)
		for _, s := range m.Record.Scores {
			if s.Score != nil && rules.labels[s.Intervention] != "" {
				scores[s.Intervention] = append(scores[s.Intervention], *s.Score)
			}
		}
	}
	for code, values := range scores {
		average := schooldirectory.PyRound1(schooldirectory.PySum(values) / float64(len(values)))
		band, _ := schooldirectory.SSABand(average)
		low := 0
		for _, v := range values {
			if v < weakLine {
				low++
			}
		}
		need.Rows = append(need.Rows, clusterRow{Intervention: code, Label: rules.labels[code], Band: band,
			Average: average, SchoolsAssessed: len(values), SchoolsLow: low})
	}
	sort.Slice(need.Rows, func(i, j int) bool {
		if need.Rows[i].Average != need.Rows[j].Average {
			return need.Rows[i].Average < need.Rows[j].Average
		}
		return need.Rows[i].Intervention < need.Rows[j].Intervention
	})
	pairs := make([]scored, len(need.Rows))
	for i, row := range need.Rows {
		pairs[i] = scored{row.Intervention, row.Average}
	}
	need.Priorities = priorityCodes(pairs)
	sort.Strings(ids)
	need.SourceSSAIDs = ids[:min(len(ids), 50)]
	return need
}

// assessCluster is plan_alignment.assess for a cluster session.
func assessCluster(activityType, focus, focusSource string, modes []string, need clusterNeed, today time.Time) evidence {
	nature := planNature(activityType, modes, false)
	data := map[string]any{
		"engine":      rules.Alignment.EngineVersion,
		"assessedOn":  today.Format(time.DateOnly),
		"nature":      nature,
		"focus":       optString(focus),
		"focusSource": "",
		"cluster":     clusterEvidence(need, focus),
	}
	if focus != "" {
		data["focusSource"] = focusSource
	}
	var alignment string
	switch {
	case nature == "collection":
		alignment = "ssa_collection"
	case nature == "not_applicable":
		alignment = "not_applicable"
	case need.stale():
		alignment = "stale_ssa"
	case !need.assessed():
		alignment = "no_ssa"
	case focus == "":
		alignment = "no_focus"
	case slices.Contains(need.Priorities, focus):
		alignment = "priority"
	default:
		alignment = "off_priority"
	}
	data["alignment"] = alignment
	return evidence{Alignment: alignment, Focus: focus, Data: data}
}

func clusterRowMap(row clusterRow) map[string]any {
	return map[string]any{
		"intervention": row.Intervention, "label": row.Label, "average": pyFloat(row.Average), "band": row.Band,
		"schoolsAssessed": row.SchoolsAssessed, "schoolsBelow": row.SchoolsLow,
	}
}

// clusterEvidence is plan_alignment._cluster_evidence.
func clusterEvidence(need clusterNeed, focus string) map[string]any {
	out := map[string]any{
		"members": need.Members, "assessedSchools": need.Assessed,
		"priorities": append([]string{}, need.Priorities...), "top": nil,
		"focusAverage": nil, "focusSchoolsBelow": nil, "focusRank": nil,
		"sourceSsaIds": append([]string{}, need.SourceSSAIDs...), "staleSchools": need.StaleSchools,
	}
	if len(need.Rows) > 0 {
		out["top"] = clusterRowMap(need.Rows[0])
	}
	for i, row := range need.Rows {
		if focus != "" && row.Intervention == focus {
			out["focusAverage"], out["focusSchoolsBelow"], out["focusRank"] = pyFloat(row.Average), row.SchoolsLow, i+1
		}
	}
	return out
}

// clusterReason is reason_for's cluster sentence (after the verdicts every
// plan shares).
func clusterReason(e evidence, cluster map[string]any) string {
	detail := "not scored in any member school"
	if rank, ok := cluster["focusRank"].(int); ok && rank > 0 {
		average := "None"
		if a, ok := cluster["focusAverage"].(pyFloat); ok {
			average = pyRepr(float64(a))
		}
		detail = fmt.Sprintf("cluster average %s/10, %v of %v assessed schools below 5.5",
			average, cluster["focusSchoolsBelow"], cluster["assessedSchools"])
	}
	suffix := ""
	if e.Alignment != "priority" {
		suffix = fmt.Sprintf("; the weakest cluster need is %s", topLabel(cluster, "another"))
	}
	return fmt.Sprintf("Targets %s (%s)%s.", rules.labels[e.Focus], detail, suffix)
}

// clusterItem is a catalogue item as recommend_cluster_activities reads it.
type clusterItem struct {
	ID, Code, Name string
	Mappings       []itemMapping
	Conflict       bool
}

type itemMapping struct {
	Mode, Intervention string
	Priority           int
}

// suggestion is one merged row of recommend_cluster_activities.
type suggestion struct {
	Code, Name, ItemID, Target string
	Rank, Matched              int
	Conflict                   bool
	SSAIDs                     []any
}

// clusterRecommendation is what `_create` keeps of it (3071–3100).
type clusterRecommendation struct {
	reason, itemID, verification string
	recommended                  bool
	ssaIDs                       []any
}

func (r clusterRecommendation) source() map[string]any {
	return map[string]any{
		"engine": "apps.ssa.recommendation_engine", "sourceSsaIds": r.ssaIDs,
		"verificationState": r.verification, "catalogueItemId": r.itemID, "recommended": r.recommended,
		"projectId": nil, "executorType": "staff", "context": "cluster",
	}
}

// memberNeed is one member's ranked need, as the school engine ranks it.
type memberNeed struct {
	SchoolID string
	Record   *ssaRecord
	Ranked   []rankedNeed
}

// recommendForCluster reads what recommend_cluster_activities ranks.
func recommendForCluster(ctx context.Context, q Querier, clusterID, itemID string, now, today time.Time) (clusterRecommendation, error) {
	g := rules.GroupTraining
	rows, err := q.Query(ctx, `SELECT id FROM school WHERE cluster_id = $1 AND deleted_at IS NULL
  AND operational_status = ANY($2) ORDER BY school_id`, clusterID, g.OperatingStatuses)
	if err != nil {
		return clusterRecommendation{}, fmt.Errorf("activities: reading the cluster's members: %w", err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return clusterRecommendation{}, fmt.Errorf("activities: reading the cluster's members: %w", err)
	}
	members := make([]memberNeed, 0, len(ids))
	for _, id := range ids {
		need, err := schoolNeedOf(ctx, pgNeed{q}, id, clusterID, now)
		if err != nil {
			return clusterRecommendation{}, err
		}
		members = append(members, memberNeed{SchoolID: id, Record: need.Record, Ranked: need.Ranked})
	}
	fy := schooldirectory.OperationalFY(time.Date(today.Year(), today.Month(), today.Day(), 0, 0, 0, 0, time.UTC))
	items, err := clusterCatalogue(ctx, q, clusterID, fy, today)
	if err != nil {
		return clusterRecommendation{}, err
	}
	followTarget := ""
	if slices.ContainsFunc(items, func(it clusterItem) bool { return it.hasMode(g.FollowUpMode) }) {
		if followTarget, err = followUpSource(ctx, q, clusterID); err != nil {
			return clusterRecommendation{}, err
		}
	}
	return rankForCluster(members, items, followTarget, itemID), nil
}

func (it clusterItem) hasMode(mode string) bool {
	for _, m := range it.Mappings {
		if m.Mode == mode {
			return true
		}
	}
	return false
}

// clusterCatalogue is the effective catalogue staff may deliver to a
// cluster, administration left out, each item with its active mappings and
// whether it is already planned or delivered at the cluster this year.
func clusterCatalogue(ctx context.Context, q Querier, clusterID, fy string, today time.Time) ([]clusterItem, error) {
	g := rules.GroupTraining
	rows, err := q.Query(ctx, `SELECT i.id, i.stable_code, i.display_name, EXISTS (SELECT 1 FROM activity a
  WHERE a.catalogue_item_id = i.id AND a.cluster_id = $2 AND a.fy = $3 AND a.deleted_at IS NULL AND a.status = ANY($4))
FROM activity_catalogue_item i
WHERE `+effective+` AND i.staff_delivery_allowed AND i.cluster_delivery_allowed AND i.activity_type IS DISTINCT FROM $5`,
		today.Format(time.DateOnly), clusterID, fy, g.ActiveSupportStatuses, g.AdminCatalogueType)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the cluster catalogue: %w", err)
	}
	items, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (clusterItem, error) {
		var it clusterItem
		return it, r.Scan(&it.ID, &it.Code, &it.Name, &it.Conflict)
	})
	if err != nil {
		return nil, fmt.Errorf("activities: reading the cluster catalogue: %w", err)
	}
	ids := make([]string, len(items))
	at := map[string]int{}
	for i, it := range items {
		ids[i], at[it.ID] = it.ID, i
	}
	mrows, err := q.Query(ctx, `SELECT catalogue_item_id, mapping_mode, COALESCE(intervention, ''), priority
FROM activity_intervention_mapping WHERE active AND catalogue_item_id = ANY($1) ORDER BY id`, ids)
	if err != nil {
		return nil, fmt.Errorf("activities: reading the catalogue's mappings: %w", err)
	}
	defer mrows.Close()
	for mrows.Next() {
		var itemID string
		var m itemMapping
		if err := mrows.Scan(&itemID, &m.Mode, &m.Intervention, &m.Priority); err != nil {
			return nil, fmt.Errorf("activities: reading the catalogue's mappings: %w", err)
		}
		items[at[itemID]].Mappings = append(items[at[itemID]].Mappings, m)
	}
	if err := mrows.Err(); err != nil {
		return nil, fmt.Errorf("activities: reading the catalogue's mappings: %w", err)
	}
	return items, nil
}

// followUpSource is the target of the cluster's latest completed session
// with an intervention, or "" when there is none.
func followUpSource(ctx context.Context, q Querier, clusterID string) (string, error) {
	var focus string
	err := q.QueryRow(ctx, `SELECT focus_intervention FROM activity WHERE cluster_id = $1 AND deleted_at IS NULL
  AND status = ANY($2) AND focus_intervention IS NOT NULL AND focus_intervention <> ''
ORDER BY planned_date DESC, created_at DESC LIMIT 1`, clusterID, rules.GroupTraining.CompletedSupportStatuses).Scan(&focus)
	if err == pgx.ErrNoRows {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("activities: reading the cluster's last completed session: %w", err)
	}
	return focus, nil
}

// rankForCluster is recommend_cluster_activities' merge and order, and the
// row `_create` keeps for itemID: its reason, its schools' SSAs and whether
// it is among the first three.
func rankForCluster(members []memberNeed, items []clusterItem, followTarget, itemID string) clusterRecommendation {
	g := rules.GroupTraining
	merged := map[string]*suggestion{}
	order := []string{}
	merge := func(it clusterItem, target string, rank int, m memberNeed) {
		row, ok := merged[it.Code]
		if !ok {
			row = &suggestion{Code: it.Code, Name: it.Name, ItemID: it.ID, Target: target, Rank: rank, Conflict: it.Conflict}
			merged[it.Code] = row
			order = append(order, it.Code)
		}
		row.SSAIDs = append(row.SSAIDs, m.Record.ID)
		row.Matched++
		row.Rank = min(row.Rank, rank)
		row.Conflict = row.Conflict || it.Conflict
	}
	withSSA := 0
	for _, m := range members {
		if m.Record == nil || len(m.Ranked) == 0 {
			continue
		}
		withSSA++
		rankOf := map[string]int{}
		for i, need := range m.Ranked {
			rankOf[need.Intervention] = i
		}
		for _, it := range items {
			if !it.hasMode(g.RankedModes[0]) && !it.hasMode(g.RankedModes[1]) {
				continue
			}
			var best *itemMapping
			for i := range it.Mappings {
				mp := &it.Mappings[i]
				if _, ranked := rankOf[mp.Intervention]; !ranked || !in(g.RankedModes, mp.Mode) {
					continue
				}
				if best == nil || mappingBefore(*mp, *best, rankOf) {
					best = mp
				}
			}
			if best != nil {
				merge(it, best.Intervention, rankOf[best.Intervention], m)
			}
		}
		for _, it := range items {
			if !it.hasMode(g.FollowUpMode) {
				continue
			}
			target := m.Ranked[0].Intervention
			if followTarget != "" {
				target = followTarget
			}
			rank, ok := rankOf[target]
			if !ok {
				rank = 999
			}
			merge(it, target, rank+20, m)
		}
	}
	rows := make([]*suggestion, 0, len(order))
	for _, code := range order {
		rows = append(rows, merged[code])
	}
	sort.SliceStable(rows, func(i, j int) bool { return suggestionBefore(*rows[i], *rows[j]) })
	out := clusterRecommendation{reason: "Authorized alternative Catalogue Activity.", itemID: itemID,
		verification: "none", ssaIDs: []any{}}
	if withSSA > 0 {
		out.verification = "verified"
	}
	for i, row := range rows {
		if row.ItemID != itemID {
			continue
		}
		out.reason = fmt.Sprintf("%d Cluster member School(s) have verified %s need.",
			row.Matched, pyTitle(strings.ReplaceAll(row.Target, "_", " ")))
		out.ssaIDs = row.SSAIDs
		out.recommended = i < primaryLimit
	}
	return out
}

// mappingBefore is the min key (rank, priority, intervention).
func mappingBefore(a, b itemMapping, rankOf map[string]int) bool {
	if rankOf[a.Intervention] != rankOf[b.Intervention] {
		return rankOf[a.Intervention] < rankOf[b.Intervention]
	}
	if a.Priority != b.Priority {
		return a.Priority < b.Priority
	}
	return a.Intervention < b.Intervention
}

// suggestionBefore is the sort key (rank, -schools matched, conflict,
// display name casefolded, stable code).
func suggestionBefore(a, b suggestion) bool {
	switch {
	case a.Rank != b.Rank:
		return a.Rank < b.Rank
	case a.Matched != b.Matched:
		return a.Matched > b.Matched
	case a.Conflict != b.Conflict:
		return !a.Conflict
	}
	if x, y := strings.ToLower(a.Name), strings.ToLower(b.Name); x != y {
		return x < y
	}
	return a.Code < b.Code
}
