package myplan

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

type sessionState struct {
	nextDate      *time.Time
	planned       int
	delivered     int
	lastDelivered *time.Time
}

func (s sessionState) isPlanned() bool { return s.planned > 0 || s.delivered > 0 }

func (s sessionState) tone() string {
	if s.planned > 0 {
		return "info"
	}
	if s.delivered > 0 {
		return "success"
	}
	return "danger"
}

func (s sessionState) label() string {
	if s.nextDate != nil {
		return "Planned · " + s.nextDate.Format("2 Jan 2006")
	}
	if s.planned > 0 {
		return "Planned · not dated"
	}
	if s.delivered > 0 {
		if s.lastDelivered != nil {
			return "Delivered · " + s.lastDelivered.Format("2 Jan 2006")
		}
		return "Delivered"
	}
	return "Not planned"
}

type clusterPlanRow struct {
	id       string
	name     string
	district string
	schools  int
	training sessionState
	meeting  sessionState
}

var (
	clusterTrainingSessionTypes = []string{"cluster_training", "cluster_training_ssa_collection"}
	clusterOperatingStatuses    = []string{"active", "open"}
	clusterPlannedStatuses      = []string{"scheduled", "in_progress", "pending_evidence", "assigned_to_partner", "planned"}
	clusterDeliveredStatuses    = []string{"completed", "submitted", "pl_approved", "verified", "ia_verified", "confirmed", "closed", "pending_pl_review", "pending_ia_review"}
)

func planningHorizon(fy string) []string {
	n, err := strconv.Atoi(strings.TrimSpace(fy))
	if err != nil {
		return []string{fy}
	}
	return []string{strconv.Itoa(n), strconv.Itoa(n + 1)}
}

// readClusterPlanningStatus ports apps/clusters/planning_status.py.
func readClusterPlanningStatus(ctx context.Context, db schooldirectory.Querier, owners []string, fy string) ([]clusterPlanRow, error) {
	if len(owners) == 0 {
		return nil, nil
	}
	cRows, err := db.Query(ctx, `SELECT c.id, COALESCE(c.name, ''), COALESCE(d.name, '')
FROM cluster c LEFT JOIN district d ON d.id = c.district_id
WHERE c.responsible_staff_id = ANY($1) AND c.deleted_at IS NULL
ORDER BY c.name ASC`, owners)
	if err != nil {
		return nil, fmt.Errorf("myplan: reading clusters: %w", err)
	}
	var clusters []clusterPlanRow
	ids := []string{}
	for cRows.Next() {
		var r clusterPlanRow
		if err := cRows.Scan(&r.id, &r.name, &r.district); err != nil {
			cRows.Close()
			return nil, fmt.Errorf("myplan: scanning cluster: %w", err)
		}
		clusters = append(clusters, r)
		ids = append(ids, r.id)
	}
	cRows.Close()
	if err := cRows.Err(); err != nil || len(clusters) == 0 {
		return nil, err
	}

	members := map[string]int{}
	mRows, err := db.Query(ctx, `SELECT cluster_id, count(*) FROM school
WHERE cluster_id = ANY($1) AND cluster_status = 'clustered'
  AND deleted_at IS NULL AND operational_status = ANY($2)
GROUP BY cluster_id`, ids, clusterOperatingStatuses)
	if err != nil {
		return nil, fmt.Errorf("myplan: counting cluster schools: %w", err)
	}
	for mRows.Next() {
		var cid string
		var n int
		if err := mRows.Scan(&cid, &n); err != nil {
			mRows.Close()
			return nil, err
		}
		members[cid] = n
	}
	mRows.Close()
	if err := mRows.Err(); err != nil {
		return nil, err
	}

	allStatuses := append(append([]string{}, clusterPlannedStatuses...), clusterDeliveredStatuses...)
	allTypes := append(append([]string{}, clusterTrainingSessionTypes...), rules.Plan.MeetingTypes...)
	aRows, err := db.Query(ctx, `SELECT cluster_id, activity_type, status, planned_date
FROM activity
WHERE cluster_id = ANY($1) AND fy = ANY($2) AND deleted_at IS NULL
  AND status = ANY($3) AND activity_type = ANY($4)`,
		ids, planningHorizon(fy), allStatuses, allTypes)
	if err != nil {
		return nil, fmt.Errorf("myplan: reading cluster sessions: %w", err)
	}
	type stateKey struct{ cid, kind string }
	states := map[stateKey]*sessionState{}
	for aRows.Next() {
		var cid, atype, status string
		var planned *time.Time
		if err := aRows.Scan(&cid, &atype, &status, &planned); err != nil {
			aRows.Close()
			return nil, err
		}
		kind := "training"
		if in(rules.Plan.MeetingTypes, atype) {
			kind = "meeting"
		}
		st := states[stateKey{cid, kind}]
		if st == nil {
			st = &sessionState{}
			states[stateKey{cid, kind}] = st
		}
		if in(clusterDeliveredStatuses, status) {
			st.delivered++
			if planned != nil && (st.lastDelivered == nil || planned.After(*st.lastDelivered)) {
				d := *planned
				st.lastDelivered = &d
			}
		} else {
			st.planned++
			if planned != nil && (st.nextDate == nil || planned.Before(*st.nextDate)) {
				d := *planned
				st.nextDate = &d
			}
		}
	}
	aRows.Close()
	if err := aRows.Err(); err != nil {
		return nil, err
	}

	for i := range clusters {
		clusters[i].schools = members[clusters[i].id]
		if st := states[stateKey{clusters[i].id, "training"}]; st != nil {
			clusters[i].training = *st
		}
		if st := states[stateKey{clusters[i].id, "meeting"}]; st != nil {
			clusters[i].meeting = *st
		}
	}
	sort.Slice(clusters, func(i, j int) bool {
		scoreI := boolToInt(clusters[i].training.isPlanned()) + boolToInt(clusters[i].meeting.isPlanned())
		scoreJ := boolToInt(clusters[j].training.isPlanned()) + boolToInt(clusters[j].meeting.isPlanned())
		if scoreI != scoreJ {
			return scoreI < scoreJ
		}
		if clusters[i].training.isPlanned() != clusters[j].training.isPlanned() {
			return !clusters[i].training.isPlanned()
		}
		return strings.ToLower(clusters[i].name) < strings.ToLower(clusters[j].name)
	})
	return clusters, nil
}

func boolToInt(b bool) int {
	if b {
		return 1
	}
	return 0
}

func clusterPlanningBlock(rows []clusterPlanRow) *screensv1.PageBlock {
	if len(rows) == 0 {
		return nil
	}
	trainingsMissing, meetingsMissing := 0, 0
	for _, r := range rows {
		if !r.training.isPlanned() {
			trainingsMissing++
		}
		if !r.meeting.isPlanned() {
			meetingsMissing++
		}
	}
	limit := min(len(rows), planTablePageSize)
	pageRows := make([]*screensv1.PageRow, 0, limit)
	for _, r := range rows[:limit] {
		pageRows = append(pageRows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: r.name, Href: "/clusters/" + r.id, Strong: true},
			{Text: orDefault(r.district, dash)},
			{Text: strconv.Itoa(r.schools)},
			{Text: r.training.label(), Tone: r.training.tone()},
			{Text: r.meeting.label(), Tone: r.meeting.tone()},
			{Actions: []*screensv1.PageAction{
				{Key: "training", Label: "Schedule Group Training", Enabled: true, Drawer: true,
					Href: "/planning/schedule-modal?cluster_id=" + r.id + "&action=training"},
				{Key: "meeting", Label: "Schedule Cluster Meeting", Enabled: true, Drawer: true,
					Href: "/planning/schedule-modal?cluster_id=" + r.id + "&action=meeting"},
			}},
		}})
	}
	cols := columns("Cluster Name", "District", "Schools", "Group Training", "Cluster Meeting", "Actions")
	cols[2].Numeric = true
	cols[5].Numeric = true
	subtitle := fmt.Sprintf("%d cluster%s · %d without a group training · %d without a meeting",
		len(rows), pluralS(len(rows)), trainingsMissing, meetingsMissing)
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title:    "Cluster Planning Status",
		Subtitle: subtitle,
		Columns:  cols,
		Rows:     pageRows,
		Count:    strconv.Itoa(len(rows)),
	}}}
}
