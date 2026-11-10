// Package clusterlead serves edify.clusters.v1.ClusterLeadershipService: the
// Cluster Leader Portal's scoped access, Home and member schools, and the
// management of leadership assignments.
//
// Clusters, schools, accounts and activities are the existing records, read
// through the gateway's read-only role. Assignments and their history are
// the portal's own records in the Go-owned schema cluster_leadership, written
// only inside explicit read-write transactions.
package clusterlead

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

var (
	// ErrNotFound: no such cluster, assignment or usable account.
	ErrNotFound = errors.New("clusterlead: not found")
	// ErrAlreadyAssigned: the account already leads the cluster.
	ErrAlreadyAssigned = errors.New("clusterlead: already assigned")
	// ErrNotLive: the assignment has already ended.
	ErrNotLive = errors.New("clusterlead: assignment already ended")
)

// plannedStatuses is a live plan not yet delivered
// (apps/planning/school_planning_badges.py PLANNED_STATUSES).
var plannedStatuses = []string{
	"planned", "scheduled", "rescheduled", "assigned_to_partner",
	"partner_scheduled", "in_progress", "completion_started",
}

// Cluster is an existing cluster with the names the portal shows.
type Cluster struct {
	ID                 string
	Name               string
	Status             string
	Type               string
	District           string
	SubCounty          string
	ResponsibleStaffID string
	ResponsibleStaff   string
}

// Assignment is one leadership assignment and its history.
type Assignment struct {
	ID          string
	ClusterID   string
	UserID      string
	LeaderName  string
	LeaderEmail string
	StartsOn    time.Time
	EndsOn      *time.Time
	Status      string
	AssignedBy  string
	Reason      string
	EndedReason string
	ReplacesID  string
	History     []Event
}

// Event is one change to an assignment.
type Event struct {
	Event  string
	Actor  string
	Reason string
	At     time.Time
}

// Account is an existing account as the portal needs it.
type Account struct {
	UserID   string
	Name     string
	Email    string
	IsLeader bool
}

// School is a member school.
type School struct {
	ID, SchoolID, Name, Type, District, SubCounty, OperationalStatus, SSAStatus string
}

// Activity is an existing cluster activity.
type Activity struct {
	ID       string
	Name     string
	Kind     string
	Status   string
	Date     *time.Time
	Venue    string
	Invited  int32
	Attended int32
}

// Querier is the read access the store needs; *pgxpool.Pool satisfies it.
type Querier interface {
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
	BeginTx(ctx context.Context, options pgx.TxOptions) (pgx.Tx, error)
}

// Store reads the existing records and keeps the portal's own.
type Store struct {
	db Querier
}

// NewStore returns a Store on pool.
func NewStore(pool *pgxpool.Pool) *Store {
	return &Store{db: pool}
}

const selectAssignment = `
SELECT a.id::text, a.cluster_id, a.user_id, COALESCE(u.name, ''), COALESCE(u.email, ''),
       a.starts_on, a.ends_on, a.status, COALESCE(by_user.name, ''), a.assigned_reason,
       COALESCE(a.ended_reason, ''), COALESCE(a.replaces_assignment_id::text, '')
FROM cluster_leadership.leader_assignment a
LEFT JOIN "user" u ON u.id = a.user_id
LEFT JOIN "user" by_user ON by_user.id = a.assigned_by`

func scanAssignment(row pgx.CollectableRow) (Assignment, error) {
	var a Assignment
	err := row.Scan(&a.ID, &a.ClusterID, &a.UserID, &a.LeaderName, &a.LeaderEmail,
		&a.StartsOn, &a.EndsOn, &a.Status, &a.AssignedBy, &a.Reason, &a.EndedReason, &a.ReplacesID)
	return a, err
}

// LiveAssignments is every assignment of userID live on day.
func (s *Store) LiveAssignments(ctx context.Context, userID string, day time.Time) ([]Assignment, error) {
	rows, err := s.db.Query(ctx, selectAssignment+`
WHERE a.user_id = $1 AND a.status = 'active'
  AND a.starts_on <= $2 AND (a.ends_on IS NULL OR a.ends_on >= $2)
ORDER BY a.starts_on, a.id`, userID, day)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading live assignments: %w", err)
	}
	return pgx.CollectRows(rows, scanAssignment)
}

// Cluster is one existing, not deleted cluster.
func (s *Store) Cluster(ctx context.Context, clusterID string) (Cluster, error) {
	var c Cluster
	err := s.db.QueryRow(ctx, `
SELECT c.id, c.name, c.status, c.cluster_type, COALESCE(d.name, ''),
       COALESCE(sc.name, c.sub_county_name, ''), COALESCE(c.responsible_staff_id, ''), COALESCE(u.name, '')
FROM cluster c
LEFT JOIN district d ON d.id = c.district_id
LEFT JOIN sub_county sc ON sc.id = c.sub_county_id
LEFT JOIN staff_profile sp ON sp.id = c.responsible_staff_id AND sp.deleted_at IS NULL
LEFT JOIN "user" u ON u.id = sp.user_id
WHERE c.id = $1 AND c.deleted_at IS NULL`, clusterID).Scan(
		&c.ID, &c.Name, &c.Status, &c.Type, &c.District, &c.SubCounty, &c.ResponsibleStaffID, &c.ResponsibleStaff)
	if errors.Is(err, pgx.ErrNoRows) {
		return Cluster{}, ErrNotFound
	}
	if err != nil {
		return Cluster{}, fmt.Errorf("clusterlead: reading a cluster: %w", err)
	}
	return c, nil
}

// memberPredicate is the cluster's member schools: operating, not deleted,
// in the cluster — whatever district they are in (brief A5: "Cross-district
// member schools must remain eligible").
const memberPredicate = `
  s.deleted_at IS NULL
  AND s.operational_status IN ('active', 'reopened')
  AND s.cluster_id = $1`

// MemberSchools is one page of the cluster's member schools and their total.
func (s *Store) MemberSchools(ctx context.Context, clusterID, search string, limit, offset int) ([]School, int64, error) {
	pattern := likePattern(search)
	var total int64
	if err := s.db.QueryRow(ctx, `SELECT count(*) FROM school s WHERE`+memberPredicate+searchPredicate,
		clusterID, pattern).Scan(&total); err != nil {
		return nil, 0, fmt.Errorf("clusterlead: counting member schools: %w", err)
	}
	rows, err := s.db.Query(ctx, `
SELECT s.id, s.school_id, s.name, s.school_type, COALESCE(d.name, ''), COALESCE(sc.name, ''),
       s.operational_status, s.current_fy_ssa_status
FROM school s
LEFT JOIN district d ON d.id = s.district_id
LEFT JOIN sub_county sc ON sc.id = s.sub_county_id
WHERE`+memberPredicate+searchPredicate+`
ORDER BY s.name, s.id
LIMIT $3 OFFSET $4`, clusterID, pattern, limit, offset)
	if err != nil {
		return nil, 0, fmt.Errorf("clusterlead: listing member schools: %w", err)
	}
	schools, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (School, error) {
		var school School
		return school, row.Scan(&school.ID, &school.SchoolID, &school.Name, &school.Type,
			&school.District, &school.SubCounty, &school.OperationalStatus, &school.SSAStatus)
	})
	if err != nil {
		return nil, 0, fmt.Errorf("clusterlead: reading member schools: %w", err)
	}
	return schools, total, nil
}

const searchPredicate = `
  AND ($2 = '' OR s.name ILIKE $2 ESCAPE '\' OR s.school_id ILIKE $2 ESCAPE '\')`

// UpcomingActivities is the cluster's live, undelivered activities from day
// on, soonest first.
func (s *Store) UpcomingActivities(ctx context.Context, clusterID string, day time.Time, limit int) ([]Activity, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.activity_name_snapshot, ''), COALESCE(a.meeting_kind, ''), a.status,
       COALESCE((a.scheduled_date AT TIME ZONE $4)::date, a.planned_date) AS day,
       COALESCE(a.venue, ''), COALESCE(a.schools_invited, 0),
       COALESCE(cardinality(a.attended_school_ids), 0)
FROM activity a
WHERE a.cluster_id = $1 AND a.deleted_at IS NULL AND a.status = ANY($2)
  AND COALESCE((a.scheduled_date AT TIME ZONE $4)::date, a.planned_date) >= $3
ORDER BY day, a.id
LIMIT $5`, clusterID, plannedStatuses, day, zoneName, limit)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading upcoming activities: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (Activity, error) {
		var a Activity
		return a, row.Scan(&a.ID, &a.Name, &a.Kind, &a.Status, &a.Date, &a.Venue, &a.Invited, &a.Attended)
	})
}

// ClusterAssignments is every assignment of the cluster with its history,
// live ones first, then the newest.
func (s *Store) ClusterAssignments(ctx context.Context, clusterID string) ([]Assignment, error) {
	rows, err := s.db.Query(ctx, selectAssignment+`
WHERE a.cluster_id = $1
ORDER BY (a.status = 'ended'), a.created_at DESC, a.id`, clusterID)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading assignments: %w", err)
	}
	assignments, err := pgx.CollectRows(rows, scanAssignment)
	if err != nil {
		return nil, err
	}
	return assignments, s.attachHistory(ctx, assignments)
}

// Assignment is one assignment with its history.
func (s *Store) Assignment(ctx context.Context, id string) (Assignment, error) {
	rows, err := s.db.Query(ctx, selectAssignment+` WHERE a.id::text = $1`, id)
	if err != nil {
		return Assignment{}, fmt.Errorf("clusterlead: reading an assignment: %w", err)
	}
	assignment, err := pgx.CollectOneRow(rows, scanAssignment)
	if errors.Is(err, pgx.ErrNoRows) {
		return Assignment{}, ErrNotFound
	}
	if err != nil {
		return Assignment{}, err
	}
	list := []Assignment{assignment}
	if err := s.attachHistory(ctx, list); err != nil {
		return Assignment{}, err
	}
	return list[0], nil
}

func (s *Store) attachHistory(ctx context.Context, assignments []Assignment) error {
	if len(assignments) == 0 {
		return nil
	}
	ids := make([]string, len(assignments))
	at := make(map[string]int, len(assignments))
	for i, a := range assignments {
		ids[i], at[a.ID] = a.ID, i
	}
	rows, err := s.db.Query(ctx, `
SELECT e.assignment_id::text, e.event, COALESCE(u.name, ''), e.reason, e.at
FROM cluster_leadership.assignment_event e
LEFT JOIN "user" u ON u.id = e.actor_id
WHERE e.assignment_id::text = ANY($1)
ORDER BY e.at, e.id`, ids)
	if err != nil {
		return fmt.Errorf("clusterlead: reading assignment history: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var event Event
		if err := rows.Scan(&id, &event.Event, &event.Actor, &event.Reason, &event.At); err != nil {
			return err
		}
		assignments[at[id]].History = append(assignments[at[id]].History, event)
	}
	return rows.Err()
}

// ManagedCluster is a cluster with its member count and live leaders.
type ManagedCluster struct {
	Cluster
	Members int64
	Leaders []string
}

// ManagedClusters is one page of not deleted clusters (only those staff
// profile staffID is responsible for, unless staffID is ""), with each one's
// operating member schools and live leaders on day.
func (s *Store) ManagedClusters(
	ctx context.Context, staffID, search string, day time.Time, limit, offset int,
) ([]ManagedCluster, int64, error) {
	pattern := likePattern(search)
	const where = `
WHERE c.deleted_at IS NULL AND ($1 = '' OR c.responsible_staff_id = $1)
  AND ($2 = '' OR c.name ILIKE $2 ESCAPE '\')`
	var total int64
	if err := s.db.QueryRow(ctx, `SELECT count(*) FROM cluster c`+where, staffID, pattern).Scan(&total); err != nil {
		return nil, 0, fmt.Errorf("clusterlead: counting clusters: %w", err)
	}
	rows, err := s.db.Query(ctx, `
SELECT c.id, c.name, c.status, c.cluster_type, COALESCE(d.name, ''),
       COALESCE(sc.name, c.sub_county_name, ''), COALESCE(c.responsible_staff_id, ''), COALESCE(u.name, ''),
       (SELECT count(*) FROM school s WHERE s.cluster_id = c.id AND s.deleted_at IS NULL
          AND s.operational_status IN ('active', 'reopened')),
       ARRAY(SELECT lu.name FROM cluster_leadership.leader_assignment a
             JOIN "user" lu ON lu.id = a.user_id
             WHERE a.cluster_id = c.id AND a.status = 'active'
               AND a.starts_on <= $3 AND (a.ends_on IS NULL OR a.ends_on >= $3)
             ORDER BY lu.name)
FROM cluster c
LEFT JOIN district d ON d.id = c.district_id
LEFT JOIN sub_county sc ON sc.id = c.sub_county_id
LEFT JOIN staff_profile sp ON sp.id = c.responsible_staff_id AND sp.deleted_at IS NULL
LEFT JOIN "user" u ON u.id = sp.user_id`+where+`
ORDER BY c.name, c.id
LIMIT $4 OFFSET $5`, staffID, pattern, day, limit, offset)
	if err != nil {
		return nil, 0, fmt.Errorf("clusterlead: listing clusters: %w", err)
	}
	clusters, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (ManagedCluster, error) {
		var m ManagedCluster
		return m, row.Scan(&m.ID, &m.Name, &m.Status, &m.Type, &m.District, &m.SubCounty,
			&m.ResponsibleStaffID, &m.ResponsibleStaff, &m.Members, &m.Leaders)
	})
	if err != nil {
		return nil, 0, fmt.Errorf("clusterlead: reading clusters: %w", err)
	}
	return clusters, total, nil
}

// maxCandidates bounds the accounts offered for an assignment.
const maxCandidates = 200

// Candidates is every usable account holding the Cluster Leader role.
func (s *Store) Candidates(ctx context.Context) ([]Account, error) {
	rows, err := s.db.Query(ctx, `
SELECT id, name, email, true FROM "user"
WHERE deleted_at IS NULL AND is_active AND status = 'active' AND $1 = ANY(roles)
ORDER BY name, id
LIMIT $2`, RoleClusterLeader, maxCandidates)
	if err != nil {
		return nil, fmt.Errorf("clusterlead: reading leader accounts: %w", err)
	}
	return pgx.CollectRows(rows, scanAccount)
}

// Account is one usable account, ErrNotFound when it is deleted or inactive.
func (s *Store) Account(ctx context.Context, userID string) (Account, error) {
	rows, err := s.db.Query(ctx, `
SELECT id, name, email, $2 = ANY(roles) FROM "user"
WHERE id = $1 AND deleted_at IS NULL AND is_active AND status = 'active'`, userID, RoleClusterLeader)
	if err != nil {
		return Account{}, fmt.Errorf("clusterlead: reading an account: %w", err)
	}
	account, err := pgx.CollectOneRow(rows, scanAccount)
	if errors.Is(err, pgx.ErrNoRows) {
		return Account{}, ErrNotFound
	}
	return account, err
}

func scanAccount(row pgx.CollectableRow) (Account, error) {
	var a Account
	return a, row.Scan(&a.UserID, &a.Name, &a.Email, &a.IsLeader)
}

// likePattern turns free text into a contains-pattern with the LIKE
// wildcards escaped, so "50%" searches for the text.
func likePattern(search string) string {
	search = strings.TrimSpace(search)
	if search == "" {
		return ""
	}
	return "%" + strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`).Replace(search) + "%"
}

func isUniqueViolation(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "23505"
}
