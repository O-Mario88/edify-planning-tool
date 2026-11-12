// Package schoolplanning is what every list where people plan shows per
// school, owned by Go (owner brief, 2026-11-11: "District and Cluster
// management", "Activity planning and scheduling"): the Visit and Training
// planning badges (apps.planning.school_planning_badges), the Next Activity
// (apps.planning.planning_support.next_activities), whether a partner holds
// the school's support (apps.partners.support_responsibility) and the
// planning horizon (apps.planning.fy_policy.planning_horizon).
//
// The vocabularies are the existing ones, exported to rules.json by
// `manage.py export_school_planning_rules`;
// apps/planning/test_school_planning_rules_export.py fails when the two
// differ.
package schoolplanning

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
)

//go:embed rules.json
var rulesJSON []byte

// Rules are the vocabularies the badges are built from.
type Rules struct {
	PlannedStatuses                []string          `json:"planned_statuses"`
	AwaitingVerificationStatuses   []string          `json:"awaiting_verification_statuses"`
	VerifiedStatuses               []string          `json:"verified_statuses"`
	NeedsReplanningStatuses        []string          `json:"needs_replanning_statuses"`
	VisitTypes                     []string          `json:"visit_types"`
	TrainingTypes                  []string          `json:"training_types"`
	ClusterMeetingTypes            []string          `json:"cluster_meeting_types"`
	ClusterSessionTypes            []string          `json:"cluster_session_types"`
	NextNouns                      map[string]string `json:"next_nouns"`
	KindNouns                      map[string]string `json:"kind_nouns"`
	ClosedHandoverActivityStatuses []string          `json:"closed_handover_activity_statuses"`
	FirstFY                        int               `json:"first_fy"`
	DefaultCountry                 string            `json:"default_country"`
}

var rules = mustLoad(rulesJSON)

func mustLoad(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil || len(r.PlannedStatuses) == 0 || len(r.KindNouns) != 3 {
		panic(fmt.Sprintf("schoolplanning: the embedded rules are unreadable: %v", err))
	}
	return r
}

// Querier is the read the package needs; *pgxpool.Pool satisfies it.
type Querier interface {
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// The badges' kinds and buckets (school_planning_badges VISITS …,
// _bucket).
const (
	KindVisits          = "visits"
	KindTrainings       = "trainings"
	KindClusterMeetings = "cluster_meetings"

	bucketPlanned  = "planned"
	bucketAwaiting = "awaiting_verification"
	bucketVerified = "verified"
	bucketReplan   = "needs_replanning"
)

func bucketOf(status string) string {
	switch {
	case slices.Contains(rules.PlannedStatuses, status):
		return bucketPlanned
	case slices.Contains(rules.AwaitingVerificationStatuses, status):
		return bucketAwaiting
	case slices.Contains(rules.VerifiedStatuses, status):
		return bucketVerified
	case slices.Contains(rules.NeedsReplanningStatuses, status):
		return bucketReplan
	}
	return ""
}

// kindOf is _classify: the activity's own type first; a type that is
// neither a visit nor a training counts as training where its catalogue
// item says so.
func kindOf(activityType string, countsAsTraining bool) string {
	switch {
	case slices.Contains(rules.TrainingTypes, activityType):
		return KindTrainings
	case slices.Contains(rules.VisitTypes, activityType):
		return KindVisits
	case countsAsTraining:
		return KindTrainings
	case slices.Contains(rules.ClusterMeetingTypes, activityType):
		return KindClusterMeetings
	}
	return ""
}

// Chip is one labelled count of a badge.
type Chip struct{ Label, Tone string }

// Counts is BadgeCounts.
type Counts struct {
	Planned, Awaiting, Verified, Replan int
}

func (c *Counts) add(bucket string) {
	switch bucket {
	case bucketPlanned:
		c.Planned++
	case bucketAwaiting:
		c.Awaiting++
	case bucketVerified:
		c.Verified++
	case bucketReplan:
		c.Replan++
	}
}

// Chips is BadgeCounts.chips: the counts in reading order, each named by
// noun where the kind of session must be said.
func (c Counts) Chips(noun string) []Chip {
	prefix := ""
	if noun != "" {
		prefix = noun + " "
	}
	out := []Chip{}
	for _, part := range []struct {
		n           int
		label, tone string
	}{
		{c.Planned, "Planned", "planned"},
		{c.Awaiting, "Awaiting Verification", "awaiting"},
		{c.Verified, "Complete", "verified"},
		{c.Replan, "Needs Replanning", "replan"},
	} {
		if part.n > 0 {
			out = append(out, Chip{Label: strconv.Itoa(part.n) + " " + prefix + part.label, Tone: part.tone})
		}
	}
	return out
}

// Badges is SchoolPlanningBadges.
type Badges struct {
	Visits, Trainings, ClusterMeetings Counts
}

var notPlanned = []Chip{{Label: "Not Planned", Tone: "none"}}

// VisitChips is visit_chips: the counts, or "Not Planned".
func (b Badges) VisitChips() []Chip {
	if chips := b.Visits.Chips(""); len(chips) > 0 {
		return chips
	}
	return notPlanned
}

// TrainingChips is training_chips: a cluster meeting the school is invited
// to is training planned for it, so "Not Planned" only when neither is.
func (b Badges) TrainingChips() []Chip {
	if len(b.Trainings.Chips("")) > 0 || len(b.ClusterMeetings.Chips("")) > 0 {
		return b.Trainings.Chips("")
	}
	return notPlanned
}

// ClusterMeetingChips is cluster_meeting_chips, named as meetings.
func (b Badges) ClusterMeetingChips() []Chip { return b.ClusterMeetings.Chips("Cluster Meeting") }

// Counted is one activity a school's badges counted (get_for_schools'
// details), what Next Activity is read from.
type Counted struct {
	SchoolID, ActivityID, ActivityType, Kind, Bucket string
	Day                                              *time.Time
}

// Nairobi is the project's clock (settings.TIME_ZONE): the day a scheduled
// instant falls on (core.clock.local_day) and Python's date.today().
var Nairobi = func() *time.Location {
	l, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		return time.FixedZone("EAT", 3*60*60)
	}
	return l
}()

// dayOf is _day: the planned date, else the scheduled instant's local day.
func dayOf(planned, scheduled *time.Time) *time.Time {
	if planned != nil {
		d := time.Date(planned.Year(), planned.Month(), planned.Day(), 0, 0, 0, 0, time.UTC)
		return &d
	}
	if scheduled != nil {
		l := scheduled.In(Nairobi)
		d := time.Date(l.Year(), l.Month(), l.Day(), 0, 0, 0, 0, time.UTC)
		return &d
	}
	return nil
}

// ForSchools is SchoolPlanningBadgeService.get_for_schools over the years
// fys: the activities that name each school, the cluster sessions it is
// named on (invited, or attended once delivered), and the delivered
// sessions that recorded it as attending, each activity counted once per
// school. It also returns what it counted.
func ForSchools(ctx context.Context, q Querier, schoolIDs, fys []string) (map[string]*Badges, []Counted, error) {
	badges := map[string]*Badges{}
	ids := []string{}
	for _, id := range schoolIDs {
		if id != "" && badges[id] == nil {
			badges[id] = &Badges{}
			ids = append(ids, id)
		}
	}
	if len(ids) == 0 {
		return badges, nil, nil
	}
	seen := map[[2]string]bool{}
	counted := []Counted{}
	count := func(schoolID, activityID, activityType string, flag bool, status string, day *time.Time) {
		key := [2]string{schoolID, activityID}
		if seen[key] {
			return
		}
		kind, bucket := kindOf(activityType, flag), bucketOf(status)
		if kind == "" || bucket == "" {
			return
		}
		seen[key] = true
		b := badges[schoolID]
		switch kind {
		case KindVisits:
			b.Visits.add(bucket)
		case KindTrainings:
			b.Trainings.add(bucket)
		case KindClusterMeetings:
			b.ClusterMeetings.add(bucket)
		}
		counted = append(counted, Counted{SchoolID: schoolID, ActivityID: activityID, ActivityType: activityType, Kind: kind, Bucket: bucket, Day: day})
	}
	fyFilter := func(column string, n int) string {
		if len(fys) == 0 {
			return ""
		}
		return fmt.Sprintf(" AND %s = ANY($%d)", column, n)
	}
	args := func(more ...any) []any {
		if len(fys) == 0 {
			return more
		}
		return append(more, fys)
	}
	type row struct {
		schoolID, activityID, activityType, status string
		planned, scheduled                         *time.Time
		flag                                       bool
	}
	read := func(what, sql string, scan func(pgx.Rows) (row, bool, error), a []any) error {
		rows, err := q.Query(ctx, sql, a...)
		if err != nil {
			return fmt.Errorf("schoolplanning: reading %s: %w", what, err)
		}
		defer rows.Close()
		for rows.Next() {
			r, keep, err := scan(rows)
			if err != nil {
				return fmt.Errorf("schoolplanning: reading %s: %w", what, err)
			}
			if keep {
				count(r.schoolID, r.activityID, r.activityType, r.flag, r.status, dayOf(r.planned, r.scheduled))
			}
		}
		return rows.Err()
	}
	direct := slices.Concat(rules.VisitTypes, rules.TrainingTypes, rules.ClusterMeetingTypes)
	if err := read("the activities naming the schools", `
SELECT a.id, a.school_id, a.activity_type, a.status, a.planned_date, a.scheduled_date,
  COALESCE(ci.counts_toward_client_training, false) OR COALESCE(ci.is_training_course, false)
FROM activity a LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
WHERE a.school_id = ANY($1) AND a.deleted_at IS NULL
  AND (a.activity_type = ANY($2) OR ci.counts_toward_client_training OR ci.is_training_course)`+fyFilter("a.fy", 3),
		func(rows pgx.Rows) (row, bool, error) {
			var r row
			err := rows.Scan(&r.activityID, &r.schoolID, &r.activityType, &r.status, &r.planned, &r.scheduled, &r.flag)
			return r, err == nil, err
		}, args(ids, direct)); err != nil {
		return nil, nil, err
	}
	postDelivery := slices.Concat(rules.AwaitingVerificationStatuses, rules.VerifiedStatuses)
	if err := read("the cluster sessions naming the schools", `
SELECT c.activity_id, c.school_id, a.activity_type, a.status, a.planned_date, a.scheduled_date,
  COALESCE(ci.counts_toward_client_training, false) OR COALESCE(ci.is_training_course, false), c.attended
FROM cluster_activity_attendance c JOIN activity a ON a.id = c.activity_id
LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
WHERE c.school_id = ANY($1) AND a.deleted_at IS NULL AND a.activity_type = ANY($2)
  AND (c.invited OR c.attended)`+fyFilter("a.fy", 3),
		func(rows pgx.Rows) (row, bool, error) {
			var r row
			var attended bool
			err := rows.Scan(&r.activityID, &r.schoolID, &r.activityType, &r.status, &r.planned, &r.scheduled, &r.flag, &attended)
			// Once delivered, the register is the record: invited but
			// absent is not credited.
			return r, err == nil && !(slices.Contains(postDelivery, r.status) && !attended), err
		}, args(ids, rules.ClusterSessionTypes)); err != nil {
		return nil, nil, err
	}
	rows, err := q.Query(ctx, `
SELECT a.id, a.activity_type, a.status, a.planned_date, a.scheduled_date, COALESCE(a.attended_school_ids, '{}'),
  COALESCE(ci.counts_toward_client_training, false) OR COALESCE(ci.is_training_course, false)
FROM activity a LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
WHERE a.deleted_at IS NULL AND a.activity_type = ANY($2) AND a.status = ANY($3)
  AND a.attended_school_ids && $1::varchar[]`+fyFilter("a.fy", 4), args(ids, rules.ClusterSessionTypes, postDelivery)...)
	if err != nil {
		return nil, nil, fmt.Errorf("schoolplanning: reading the attended sessions: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var r row
		var attended []string
		if err := rows.Scan(&r.activityID, &r.activityType, &r.status, &r.planned, &r.scheduled, &attended, &r.flag); err != nil {
			return nil, nil, fmt.Errorf("schoolplanning: reading the attended sessions: %w", err)
		}
		for _, schoolID := range attended {
			if badges[schoolID] != nil {
				count(schoolID, r.activityID, r.activityType, r.flag, r.status, dayOf(r.planned, r.scheduled))
			}
		}
	}
	return badges, counted, rows.Err()
}
