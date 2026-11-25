package planningoversight

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
)

// The four tables of one panel, as _partition_owner_groups_by_stream files
// them: each item on the table oversight_service.page_table names, a
// cluster meeting carrying the people its schools were invited with, a
// cluster training spread over the schools it invited, and every row with
// its completion columns, open work first.

const (
	clientVisits = iota
	coreVisits
	clusterMeetings
	plannedTrainings
)

// errHandOn is a panel this slice does not draw (the page is handed on).
var errHandOn = errors.New("planningoversight: a panel Go does not draw yet")

// pageTable is oversight_service.page_table.
func pageTable(it *item) int {
	r := rules.TeamPlan.Items
	atype := strings.ToLower(it.activityType)
	isVisit := slices.Contains(r.VisitTypes, atype) && !it.inSchool
	meeting := slices.Contains(r.ClusterMeetingTypes, atype)
	if !isVisit && (it.inSchool || slices.Contains(r.TrainingTypes, atype) ||
		(!meeting && strings.Contains(atype, "training")) || (it.training != "" && it.training != "—")) {
		return plannedTrainings
	}
	if !isVisit && (meeting || strings.Contains(atype, "meeting")) {
		return clusterMeetings
	}
	if strings.ToLower(it.schoolType) == "core" || strings.HasPrefix(atype, "core_") {
		return coreVisits
	}
	return clientVisits
}

// unknownSchool is the names the partition reads as no school.
func unknownSchool(name string) bool {
	return name == "" || name == "Unknown School" || name == "Unknown"
}

// streams files one panel's items into the four tables.
func (s *Service) streams(ctx context.Context, place *registry.Work, items []*item, today time.Time) ([4][]*item, error) {
	var out [4][]*item
	for _, it := range items {
		t := pageTable(it)
		out[t] = append(out[t], it)
	}
	if err := s.meetingHeadCounts(ctx, out[clusterMeetings]); err != nil {
		return out, err
	}
	expanded, err := s.expandTrainings(ctx, place, out[plannedTrainings])
	if err != nil {
		return out, err
	}
	out[plannedTrainings] = expanded
	for t := range out {
		for _, it := range out[t] {
			annotateCompletion(it, today)
		}
		slices.SortStableFunc(out[t], func(x, y *item) int {
			if x.isComplete != y.isComplete {
				if x.isComplete {
					return 1
				}
				return -1
			}
			return compareDay(x.plannedDate, y.plannedDate)
		})
	}
	return out, nil
}

// meetingHeadCounts is cluster_attendance.invited_head_counts over the
// meetings: the people each session's invited schools bring.
func (s *Service) meetingHeadCounts(ctx context.Context, meetings []*item) error {
	if len(meetings) == 0 {
		return nil
	}
	ids, clusters := []string{}, []string{}
	for _, it := range meetings {
		ids = append(ids, it.a.id)
		if it.clusterID != "" {
			clusters = append(clusters, it.clusterID)
		}
	}
	members := map[string]int64{}
	if len(clusters) > 0 {
		rows, err := s.db.Query(ctx, `SELECT cluster_id, COUNT(*) FROM school WHERE cluster_id = ANY($1) AND deleted_at IS NULL GROUP BY cluster_id`, clusters)
		if err != nil {
			return fmt.Errorf("planningoversight: reading the clusters' schools: %w", err)
		}
		for rows.Next() {
			var id string
			var n int64
			if err := rows.Scan(&id, &n); err != nil {
				rows.Close()
				return fmt.Errorf("planningoversight: reading the clusters' schools: %w", err)
			}
			members[id] = n
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return err
		}
	}
	invites, err := s.invitations(ctx, ids)
	if err != nil {
		return err
	}
	for _, it := range meetings {
		a := it.a
		perSchool := a.perSchool
		if perSchool == 0 {
			perSchool = a.teachersPerSchool
		}
		var n int64
		switch list := invites[a.id]; {
		case len(list) > 0:
			allBlank := true
			for _, inv := range list {
				if inv.composed() {
					allBlank = false
				}
			}
			if perSchool == 0 && allBlank {
				n = a.expected
				break
			}
			for _, inv := range list {
				if inv.composed() {
					n += inv.heads()
				} else {
					n += perSchool
				}
			}
		case it.clusterID != "":
			n = a.expected
			if n == 0 {
				n = perSchool * members[it.clusterID]
			}
		default:
			continue
		}
		it.participants = &n
	}
	return nil
}

// invitation is one invited school's row of a cluster session.
type invitation struct {
	school                   string
	teachers, leaders, other *int64
}

func (i invitation) composed() bool { return i.teachers != nil || i.leaders != nil || i.other != nil }

func (i invitation) heads() int64 {
	var n int64
	for _, v := range []*int64{i.teachers, i.leaders, i.other} {
		if v != nil {
			n += *v
		}
	}
	return n
}

// invitations are each session's invited schools, in the model's order (by
// the school's name).
func (s *Service) invitations(ctx context.Context, ids []string) (map[string][]invitation, error) {
	out := map[string][]invitation{}
	rows, err := s.db.Query(ctx, `SELECT a.activity_id, a.school_id, a.teachers::bigint, a.leaders::bigint, a.other::bigint
FROM cluster_activity_attendance a JOIN school s ON s.id = a.school_id
WHERE a.activity_id = ANY($1) AND a.invited ORDER BY s.name, a.id`, ids)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the invitations: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var activity string
		var inv invitation
		if err := rows.Scan(&activity, &inv.school, &inv.teachers, &inv.leaders, &inv.other); err != nil {
			return nil, fmt.Errorf("planningoversight: reading the invitations: %w", err)
		}
		out[activity] = append(out[activity], inv)
	}
	return out, rows.Err()
}

// member is a school a cluster training is spread over.
type member struct {
	pk, code, name, schoolType, cluster, districtID, district string
	confirmed                                                 bool
}

// expandTrainings is the partition's cluster-training expansion: a session
// with no school of its own becomes one row per school it invited (else per
// confirmed member school, else per member school), each with that school's
// people and their meals; one with no school at all stays one row.
func (s *Service) expandTrainings(ctx context.Context, place *registry.Work, trainings []*item) ([]*item, error) {
	sessions := []*item{}
	for _, it := range trainings {
		if it.clusterID != "" && (it.schoolPK == "" || unknownSchool(it.schoolName)) {
			sessions = append(sessions, it)
		}
	}
	if len(sessions) == 0 {
		return trainings, nil
	}
	ids, clusters := []string{}, []string{}
	for _, it := range sessions {
		ids = append(ids, it.a.id)
		clusters = append(clusters, it.clusterID)
	}
	invites, err := s.invitations(ctx, ids)
	if err != nil {
		return nil, err
	}
	byCluster, confirmed, lookup, err := s.memberSchools(ctx, clusters, invites)
	if err != nil {
		return nil, err
	}
	rates, err := s.sessionMealRates(ctx, place, sessions)
	if err != nil {
		return nil, err
	}
	out := []*item{}
	for _, it := range trainings {
		if !slices.Contains(sessions, it) {
			out = append(out, it)
			continue
		}
		a := it.a
		targets := []member{}
		for _, inv := range invites[a.id] {
			if m, ok := lookup[inv.school]; ok && !slices.ContainsFunc(targets, func(t member) bool { return t.pk == m.pk }) {
				targets = append(targets, m)
			}
		}
		if len(targets) == 0 {
			targets = confirmed[it.clusterID]
			if len(targets) == 0 {
				targets = byCluster[it.clusterID]
			}
		}
		if len(targets) == 0 {
			fb := *it
			fb.schoolName = first(it.clusterName, "Cluster Training")
			out = append(out, &fb)
			continue
		}
		var pps *int64
		if a.perSchool != 0 {
			pps = &a.perSchool
		} else if a.teachersPerSchool != 0 {
			pps = &a.teachersPerSchool
		} else {
			total := int64(0)
			if it.participants != nil {
				total = *it.participants
			}
			if total == 0 {
				total = a.expected
			}
			if total != 0 {
				n := max(1, floorDiv(total, int64(len(targets))))
				pps = &n
			}
		}
		rate := rates[a.id]
		if slices.Contains(rules.TeamPlan.Items.OnlineTrainingTypes, a.activityType) && a.programmeMode == rules.TeamPlan.Items.Online {
			rate = 0
		}
		composition := map[string]int64{}
		for _, inv := range invites[a.id] {
			if inv.composed() {
				composition[inv.school] = inv.heads()
			}
		}
		for _, m := range targets {
			row := *it
			row.schoolPK, row.schoolCode, row.schoolName, row.schoolType = m.pk, first(m.code, m.pk), m.name, m.schoolType
			row.districtID, row.districtName = m.districtID, m.district
			row.plannedFrom = first(it.clusterName, it.plannedFrom, "Cluster Training")
			row.invited = true
			row.participants = pps
			if n, ok := composition[m.pk]; ok {
				row.participants = &n
			}
			row.plannedCost = 0
			if row.participants != nil {
				row.plannedCost = *row.participants * rate
			}
			out = append(out, &row)
		}
	}
	return out, nil
}

// floorDiv is Python's //.
func floorDiv(a, b int64) int64 {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}

// memberSchools are the clusters' operating schools (newest first), those
// confirmed in them, and every school an invitation names.
func (s *Service) memberSchools(ctx context.Context, clusters []string, invites map[string][]invitation) (map[string][]member, map[string][]member, map[string]member, error) {
	byCluster, confirmed, lookup := map[string][]member{}, map[string][]member{}, map[string]member{}
	r := rules.TeamPlan.Items
	read := func(where string, arg []string) ([]member, error) {
		rows, err := s.db.Query(ctx, `SELECT s.id, COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(s.school_type, ''),
  COALESCE(s.cluster_id, ''), COALESCE(s.district_id, ''), COALESCE(d.name, ''),
  COALESCE(s.cluster_status = 'clustered' AND (COALESCE(s.operational_status, '') = '' OR s.operational_status = ANY($2)), false)
FROM school s LEFT JOIN district d ON d.id = s.district_id WHERE `+where+` ORDER BY s.created_at DESC, s.id`, arg, r.OperatingStatuses)
		if err != nil {
			return nil, fmt.Errorf("planningoversight: reading the schools invited: %w", err)
		}
		defer rows.Close()
		out := []member{}
		for rows.Next() {
			var m member
			if err := rows.Scan(&m.pk, &m.code, &m.name, &m.schoolType, &m.cluster, &m.districtID, &m.district, &m.confirmed); err != nil {
				return nil, fmt.Errorf("planningoversight: reading the schools invited: %w", err)
			}
			out = append(out, m)
		}
		return out, rows.Err()
	}
	active, err := read(`s.cluster_id = ANY($1) AND s.deleted_at IS NULL AND s.operational_status = ANY($2)`, clusters)
	if err != nil {
		return nil, nil, nil, err
	}
	for _, m := range active {
		byCluster[m.cluster] = append(byCluster[m.cluster], m)
		if m.confirmed {
			confirmed[m.cluster] = append(confirmed[m.cluster], m)
		}
		lookup[m.pk] = m
	}
	missing := []string{}
	for _, list := range invites {
		for _, inv := range list {
			if _, ok := lookup[inv.school]; !ok && !slices.Contains(missing, inv.school) {
				missing = append(missing, inv.school)
			}
		}
	}
	if len(missing) > 0 {
		more, err := read(`s.id = ANY($1) AND $2::text[] IS NOT NULL`, missing)
		if err != nil {
			return nil, nil, nil, err
		}
		for _, m := range more {
			lookup[m.pk] = m
		}
	}
	return byCluster, confirmed, lookup, nil
}

// sessionMealRates is the partition's meal_rates: each session's meals
// rate from its own costing, else the live card's (a meeting at the cluster
// meals rate, a training at the group training one), 0 where neither says.
func (s *Service) sessionMealRates(ctx context.Context, place *registry.Work, sessions []*item) (map[string]int64, error) {
	r := rules.TeamPlan.Items
	ids := []string{}
	for _, it := range sessions {
		ids = append(ids, it.a.id)
	}
	found, err := myplan.MealRates(ctx, s.db, ids)
	if errors.Is(err, myplan.ErrUnported) {
		return nil, errHandOn
	}
	if err != nil {
		return nil, err
	}
	fallbacks := map[string]int64{}
	out := map[string]int64{}
	for _, it := range sessions {
		if rate, ok := found[it.a.id]; ok {
			out[it.a.id] = rate
			continue
		}
		key := r.GroupTrainingMealsRateKey
		if slices.Contains(r.ClusterMeetingTypes, it.activityType) {
			key = r.ClusterMealsRateKey
		}
		rate, seen := fallbacks[key]
		if !seen {
			live, err := myplan.CatalogueRate(ctx, s.db, place, key)
			if err != nil {
				return nil, err
			}
			if live != nil {
				rate = *live
			}
			fallbacks[key] = rate
		}
		out[it.a.id] = rate
	}
	return out, nil
}

// annotateCompletion is completion_columns.annotate for one staff item: the
// Salesforce ID, the day it was done, what a done status still lacks, and
// the row's ink (the item has no scheduled time of its own, so its planned
// date alone decides overdue).
func annotateCompletion(it *item, today time.Time) {
	r := rules.TeamPlan.Items
	a := it.a
	it.salesforceID = strings.TrimSpace(a.salesforce)
	sf := it.salesforceID != ""
	done := slices.Contains(r.OfficerCompletedStatuses, it.status)
	it.plannedBefore = dateOnly(a.plannedBefore)
	delivered := dateOnly(a.actualDelivery)
	if delivered == nil {
		delivered = localDay(a.executionStarted)
	}
	it.completedOn = nil
	if done {
		it.completedOn = delivered
	}
	it.isComplete = done && sf
	it.gap = ""
	if done && !sf {
		it.gap = r.Words.MissingSF
	}
	it.showsComplete = it.isComplete && slices.Contains(r.CompletedWorkStatuses, it.status)
	it.finishedEarly = it.isComplete && earlyDay(a, today) != nil
	it.rowState = ""
	switch {
	case done:
		it.rowState = "done"
	case slices.Contains(r.NeverOverdue, it.status) || it.plannedDate == nil:
	case it.plannedDate.Before(today):
		it.rowState = "overdue"
	}
}

// earlyDay is completion_columns.early_day over the activity's own dates.
func earlyDay(a *act, today time.Time) *time.Time {
	planned, scheduled := dateOnly(a.plannedDate), a.scheduled
	if a.plannedBefore != nil {
		planned, scheduled = dateOnly(a.plannedBefore), nil
	}
	day := planned
	if day == nil {
		day = localDay(scheduled)
	}
	if day == nil {
		return nil
	}
	if actual := dateOnly(a.actualDelivery); actual != nil {
		if actual.Before(*day) {
			return actual
		}
		return nil
	}
	started := localDay(a.executionStarted)
	if started == nil {
		return nil
	}
	finishedBy := today
	for _, d := range []*time.Time{localDay(a.submittedToIA), localDay(a.plReviewed)} {
		if d != nil && d.Before(finishedBy) {
			finishedBy = *d
		}
	}
	if finishedBy.Before(*day) {
		return started
	}
	return nil
}
