package clusterpage

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// cluster is one row of the page's clusters, with what its card names.
type cluster struct {
	ID, Name                string
	District                *string // nil when the cluster has no district
	SubCounty               *string // the cluster's own sub-county, nil when none
	SubCountyName           string
	LeaderName, LeaderPhone string
	FacilitatingPartnerID   string
	Covered                 []string // covered_sub_counties' names
}

// planning is cluster_planning's row for one cluster, as far as the card,
// the risk and the strip read it.
type planning struct {
	Schools, WithSSA, Ready, Baseline, Cleanup int
	MeetingsDone, MeetingsOpen                 int
	NotVisited, NotTrained                     int
	// missing is a cluster cluster_planning does not read (outside the
	// reader's own active clusters): its row is {} on the page, every figure
	// reads 0 and it has no gap.
	missing bool
}

// coverage is ssaCoveragePct: round(done / total * 100, 1), 0.0 with no
// schools.
func (p planning) coverage() float64 {
	if p.Schools == 0 {
		return 0
	}
	return schooldirectory.PyRound1(float64(p.WithSSA) / float64(p.Schools) * 100)
}

func (p planning) metThisQuarter() bool { return p.MeetingsDone > 0 || p.MeetingsOpen > 0 }

// gap is gapCategory.
func (p planning) gap() string {
	switch {
	case p.missing:
		return ""
	case p.MeetingsDone == 0:
		return "no_meetings_this_fy"
	case !p.metThisQuarter():
		return "not_met_this_quarter"
	case p.NotVisited > 0:
		return "schools_not_visited"
	case p.NotTrained > 0:
		return "schools_not_trained"
	}
	return "on_track"
}

// stat is one intervention's average and count below 5.5 over a cluster's
// latest confirmed assessments.
type stat struct {
	avg   float64
	below int
}

// card is ClusterDashboardService.build_cluster_cards' card.
type card struct {
	cluster
	schools, staff int
	avgSSA         *float64
	lastMeeting    *time.Time
	lastTraining   *time.Time
	meetingsFY     int
	stats          map[string]stat
	facilitator    string
	plan           planning
}

// risk is cluster_views.get_cluster_risk.
func (c card) risk() string {
	if c.avgSSA != nil && *c.avgSSA < 5.0 {
		return "critical"
	}
	if c.plan.Schools > 0 && float64(c.plan.WithSSA)/float64(c.plan.Schools) < 0.5 {
		return "critical"
	}
	gap := c.plan.gap()
	if gap == "no_meetings_this_fy" {
		return "critical"
	}
	if c.avgSSA != nil && *c.avgSSA < 6.0 {
		return "needs_attention"
	}
	if gap == "not_met_this_quarter" {
		return "needs_attention"
	}
	if c.plan.NotVisited > 0 || c.plan.NotTrained > 0 {
		return "needs_attention"
	}
	return "healthy"
}

// weak is one of _weakest_from_stats' interventions.
type weak struct {
	intervention, label string
	avg                 float64
}

// weakest is _weakest_from_stats: the scored interventions, lowest average
// first (ties by the intervention's value), at most four.
func (c card) weakest() []weak {
	out := []weak{}
	for _, iv := range rules.SSAInterventions {
		if s, ok := c.stats[iv[0]]; ok {
			out = append(out, weak{intervention: iv[0], label: iv[1], avg: schooldirectory.PyRound1(s.avg)})
		}
	}
	slices.SortStableFunc(out, func(a, b weak) int {
		switch {
		case a.avg < b.avg:
			return -1
		case a.avg > b.avg:
			return 1
		}
		return strings.Compare(a.intervention, b.intervention)
	})
	if len(out) > 4 {
		out = out[:4]
	}
	return out
}

// summary is _intervention_summary_from_stats as build_ssa_score_summary
// reads it: every intervention, its average rounded or none.
func (c card) summary() []schooldirectory.SSAScore {
	out := []schooldirectory.SSAScore{}
	for _, iv := range rules.SSAInterventions {
		var avg *float64
		if s, ok := c.stats[iv[0]]; ok {
			v := schooldirectory.PyRound1(s.avg)
			avg = &v
		}
		out = append(out, schooldirectory.SSAScore{Intervention: iv[0], Score: avg})
	}
	return out
}

// subCountyLine is the card's sub-county: every covered sub-county, else
// the cluster's own, else the name it was given, else "District-level
// cluster".
func (c cluster) subCountyLine() string {
	switch {
	case len(c.Covered) > 0:
		return strings.Join(c.Covered, ", ")
	case c.SubCounty != nil:
		return *c.SubCounty
	case c.SubCountyName != "":
		return c.SubCountyName
	}
	return "District-level cluster"
}

func (c cluster) districtLine() string {
	if c.District == nil {
		return "Unknown"
	}
	return *c.District
}

// ── Reads ────────────────────────────────────────────────────────────────

func each(ctx context.Context, q schooldirectory.Querier, what, sql string, scan func(pgx.Rows) error, args ...any) error {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return fmt.Errorf("clusterpage: reading %s: %w", what, err)
	}
	defer rows.Close()
	for rows.Next() {
		if err := scan(rows); err != nil {
			return fmt.Errorf("clusterpage: reading %s: %w", what, err)
		}
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("clusterpage: reading %s: %w", what, err)
	}
	return nil
}

// covered is each cluster's covered sub-counties, as the page's prefetch
// reads them: the links in the order they come back (they have no order of
// their own), then their sub-counties' names.
func covered(ctx context.Context, q schooldirectory.Querier, clusters []cluster) error {
	ids := make([]string, len(clusters))
	at := map[string]int{}
	for i, c := range clusters {
		ids[i], at[c.ID] = c.ID, i
	}
	if len(ids) == 0 {
		return nil
	}
	type link struct{ cluster, subCounty string }
	links := []link{}
	if err := each(ctx, q, "covered sub-counties", `
SELECT cluster_id, sub_county_id FROM cluster_sub_county WHERE cluster_id = ANY($1)`, func(rows pgx.Rows) error {
		var l link
		if err := rows.Scan(&l.cluster, &l.subCounty); err != nil {
			return err
		}
		links = append(links, l)
		return nil
	}, ids); err != nil {
		return err
	}
	if len(links) == 0 {
		return nil
	}
	subIDs := make([]string, len(links))
	for i, l := range links {
		subIDs[i] = l.subCounty
	}
	names := map[string]string{}
	if err := each(ctx, q, "covered sub-county names", `
SELECT id, COALESCE(name, '') FROM sub_county WHERE id = ANY($1)`, func(rows pgx.Rows) error {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return err
		}
		names[id] = name
		return nil
	}, subIDs); err != nil {
		return err
	}
	for _, l := range links {
		// A link whose sub-county is gone is left out (`if link.sub_county`).
		if name, ok := names[l.subCounty]; ok {
			clusters[at[l.cluster]].Covered = append(clusters[at[l.cluster]].Covered, name)
		}
	}
	return nil
}

// cards is build_cluster_cards for clusters, the year fy.
func cards(ctx context.Context, q schooldirectory.Querier, clusters []cluster, fy string) ([]card, error) {
	out := make([]card, len(clusters))
	at := map[string]int{}
	ids := make([]string, len(clusters))
	partners := []string{}
	for i, c := range clusters {
		out[i].cluster = c
		out[i].stats = map[string]stat{}
		ids[i], at[c.ID] = c.ID, i
		if c.FacilitatingPartnerID != "" {
			partners = append(partners, c.FacilitatingPartnerID)
		}
	}
	if len(ids) == 0 {
		return out, nil
	}
	names := map[string]string{}
	if err := each(ctx, q, "facilitating partners", `
SELECT id, COALESCE(name, '') FROM partner WHERE id = ANY($1) AND deleted_at IS NULL AND active_status`,
		func(rows pgx.Rows) error {
			var id, name string
			if err := rows.Scan(&id, &name); err != nil {
				return err
			}
			names[id] = name
			return nil
		}, partners); err != nil {
		return nil, err
	}
	for i := range out {
		out[i].facilitator = names[out[i].FacilitatingPartnerID]
	}

	// The card counts the schools its list shows: operating, and not a
	// school kept on a table of its own (Champion).
	listed := `s.cluster_id = ANY($1) AND s.deleted_at IS NULL AND s.operational_status = ANY($2)
  AND NOT (s.school_type = ANY($3) AND s.school_type IS NOT NULL)`
	staff := map[string]map[string]bool{}
	if err := each(ctx, q, "the cards' schools", `SELECT s.cluster_id, COALESCE(s.account_owner_id, '') FROM school s WHERE `+listed,
		func(rows pgx.Rows) error {
			var clusterID, owner string
			if err := rows.Scan(&clusterID, &owner); err != nil {
				return err
			}
			out[at[clusterID]].schools++
			if owner != "" {
				if staff[clusterID] == nil {
					staff[clusterID] = map[string]bool{}
				}
				staff[clusterID][owner] = true
			}
			return nil
		}, ids, rules.OperatingStatuses, rules.OwnTableSchoolTypes); err != nil {
		return nil, err
	}
	for id, owners := range staff {
		out[at[id]].staff = len(owners)
	}

	// Each school's latest confirmed assessment, found once; the averages
	// are then read as the page reads them, over that list of ids. Postgres
	// adds floats in the order it reads the rows, so the statements keep the
	// page's own shape: another plan can turn 5.1499… into 5.15.
	latest := []string{}
	if err := each(ctx, q, "the cards' latest assessments", `
SELECT DISTINCT ON (ssa_record.school_id) ssa_record.id FROM ssa_record
WHERE ssa_record.school_id IN (SELECT s.id FROM school s WHERE `+listed+`)
  AND ssa_record.deleted_at IS NULL AND ssa_record.verification_status = 'confirmed'
ORDER BY ssa_record.school_id ASC, ssa_record.date_of_ssa DESC, ssa_record.created_at DESC`, func(rows pgx.Rows) error {
		var id string
		if err := rows.Scan(&id); err != nil {
			return err
		}
		latest = append(latest, id)
		return nil
	}, ids, rules.OperatingStatuses, rules.OwnTableSchoolTypes); err != nil {
		return nil, err
	}
	if len(latest) > 0 {
		if err := each(ctx, q, "the cards' SSA averages", `
SELECT "school"."cluster_id", AVG("ssa_record"."average_score") FROM "ssa_record"
INNER JOIN "school" ON ("ssa_record"."school_id" = "school"."id")
WHERE ("ssa_record"."deleted_at" IS NULL AND "ssa_record"."id" IN (SELECT unnest($1::varchar[]))) GROUP BY 1`,
			func(rows pgx.Rows) error {
				var clusterID *string
				var avg *float64
				if err := rows.Scan(&clusterID, &avg); err != nil {
					return err
				}
				if clusterID != nil && avg != nil {
					if i, ok := at[*clusterID]; ok {
						v := schooldirectory.PyRound1(*avg)
						out[i].avgSSA = &v
					}
				}
				return nil
			}, latest); err != nil {
			return nil, err
		}
		if err := each(ctx, q, "the cards' intervention scores", `
SELECT "school"."cluster_id", "ssa_score"."intervention", AVG("ssa_score"."score"),
  COUNT(*) FILTER (WHERE "ssa_score"."score" < 5.5)
FROM "ssa_score" INNER JOIN "ssa_record" ON ("ssa_score"."ssa_record_id" = "ssa_record"."id")
INNER JOIN "school" ON ("ssa_record"."school_id" = "school"."id")
WHERE ("ssa_score"."score" IS NOT NULL AND "ssa_score"."ssa_record_id" IN (SELECT unnest($1::varchar[]))) GROUP BY 1, 2`,
			func(rows pgx.Rows) error {
				var clusterID *string
				var intervention string
				var avg float64
				var below int
				if err := rows.Scan(&clusterID, &intervention, &avg, &below); err != nil {
					return err
				}
				if clusterID != nil {
					if i, ok := at[*clusterID]; ok {
						out[i].stats[intervention] = stat{avg: avg, below: below}
					}
				}
				return nil
			}, latest); err != nil {
			return nil, err
		}
	}

	if err := each(ctx, q, "the cards' meetings and trainings", `
SELECT a.cluster_id,
  MAX(a.planned_date) FILTER (WHERE a.activity_type = 'cluster_meeting'),
  COUNT(*) FILTER (WHERE a.activity_type = 'cluster_meeting' AND a.fy = $3),
  MAX(a.planned_date) FILTER (WHERE a.activity_type = ANY($4))
FROM activity a
WHERE a.cluster_id = ANY($1) AND a.deleted_at IS NULL AND a.status = ANY($2)
GROUP BY a.cluster_id`, func(rows pgx.Rows) error {
		var clusterID string
		var meeting, training *time.Time
		var meetings int
		if err := rows.Scan(&clusterID, &meeting, &meetings, &training); err != nil {
			return err
		}
		c := &out[at[clusterID]]
		c.lastMeeting, c.meetingsFY, c.lastTraining = meeting, meetings, training
		return nil
	}, ids, rules.CompletedWorkStatuses, fy, rules.CardTrainingTypes); err != nil {
		return nil, err
	}
	return out, plannings(ctx, q, out, at, ids)
}

// plannings fills each card's cluster_planning row: the cluster's operating
// schools (Champion included), its meetings done and open, and the schools
// no completed visit or school training has reached.
func plannings(ctx context.Context, q schooldirectory.Querier, out []card, at map[string]int, ids []string) error {
	if err := each(ctx, q, "the clusters' schools", `
SELECT s.cluster_id, COUNT(*),
  COUNT(*) FILTER (WHERE s.current_fy_ssa_status = 'done'),
  COUNT(*) FILTER (WHERE s.planning_readiness = 'ready_for_support_planning'),
  COUNT(*) FILTER (WHERE s.planning_readiness = 'ready_for_baseline_ssa'),
  COUNT(*) FILTER (WHERE s.data_quality_status IS DISTINCT FROM 'Clean')
FROM school s WHERE s.cluster_id = ANY($1) AND s.deleted_at IS NULL AND s.operational_status = ANY($2)
GROUP BY s.cluster_id`, func(rows pgx.Rows) error {
		var clusterID string
		var p planning
		if err := rows.Scan(&clusterID, &p.Schools, &p.WithSSA, &p.Ready, &p.Baseline, &p.Cleanup); err != nil {
			return err
		}
		out[at[clusterID]].plan = p
		return nil
	}, ids, rules.OperatingStatuses); err != nil {
		return err
	}
	if err := each(ctx, q, "the clusters' meetings", `
SELECT a.cluster_id,
  COUNT(*) FILTER (WHERE a.activity_type = 'cluster_meeting' AND a.status = ANY($2)),
  COUNT(*) FILTER (WHERE a.activity_type = 'cluster_meeting' AND a.status = ANY($3))
FROM activity a WHERE a.cluster_id = ANY($1) AND a.deleted_at IS NULL
GROUP BY a.cluster_id`, func(rows pgx.Rows) error {
		var clusterID string
		var done, open int
		if err := rows.Scan(&clusterID, &done, &open); err != nil {
			return err
		}
		c := &out[at[clusterID]]
		c.plan.MeetingsDone, c.plan.MeetingsOpen = done, open
		return nil
	}, ids, rules.PlanningDoneStatuses, rules.PlanningOpenStatuses); err != nil {
		return err
	}
	reached := func(what string, types []string) (map[string]int, error) {
		counts := map[string]int{}
		err := each(ctx, q, what, `
SELECT s.cluster_id, COUNT(DISTINCT a.school_id) FROM activity a JOIN school s ON s.id = a.school_id
WHERE s.cluster_id = ANY($1) AND a.activity_type = ANY($2) AND a.status = ANY($3) AND a.deleted_at IS NULL
GROUP BY s.cluster_id`, func(rows pgx.Rows) error {
			var clusterID string
			var n int
			if err := rows.Scan(&clusterID, &n); err != nil {
				return err
			}
			counts[clusterID] = n
			return nil
		}, ids, types, rules.PlanningDoneStatuses)
		return counts, err
	}
	visited, err := reached("the visited schools", []string{"school_visit"})
	if err != nil {
		return err
	}
	trained, err := reached("the trained schools", rules.PlanningSchoolTrainingTypes)
	if err != nil {
		return err
	}
	for i := range out {
		p := &out[i].plan
		p.NotVisited = max(0, p.Schools-visited[out[i].ID])
		p.NotTrained = max(0, p.Schools-trained[out[i].ID])
	}
	return nil
}
