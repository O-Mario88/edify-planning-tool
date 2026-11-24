// Package clustermembership is a school joining a cluster in Go with Django
// absent: apps.clusters.services.set_school_cluster_membership, the one
// membership service, and the cluster's Add Schools drawer and save
// (cluster_views.cluster_bulk_assign_drawer_view) that goes through it.
package clustermembership

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// ErrHandOn says the existing application keeps this request.
var ErrHandOn = errors.New("clustermembership: handed on")

// The service's refusals, in its words.
const (
	inactiveCluster = "A school can only be assigned to an active cluster."
	otherCountry    = "A school can only join a cluster in its own country."
	otherOwner      = "That cluster belongs to another staff member. A school joins a cluster owned by the person responsible for the school; moving it across portfolios needs a transfer."
	// oversightOnly is apps.core.scoping.OVERSIGHT_ONLY_MESSAGE.
	oversightOnly = "You have read-only supervisory oversight of this record. Operational planning must be completed by the responsible CCEO."
	// notInScope is assign_school's NotFoundError.
	notInScope = "School not found or outside your scope."
)

// ClusterAccess is who may read a cluster and act on it (clusterpage).
type ClusterAccess interface {
	ProfileAccess(ctx context.Context, p auth.Principal, clusterID string) (schoolprofile.ClusterAccess, error)
}

// Service draws and saves cluster membership.
type Service struct {
	db      *pgxpool.Pool
	access  ClusterAccess
	push    activities.NoticePush
	live    activities.NoticePublisher
	logger  *slog.Logger
	now     func() time.Time
	kampala *time.Location
}

// New makes the service.
func New(db *pgxpool.Pool, access ClusterAccess, push activities.NoticePush, live activities.NoticePublisher, logger *slog.Logger, now func() time.Time) *Service {
	kampala, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		kampala = time.FixedZone("EAT", 3*60*60)
	}
	return &Service{db: db, access: access, push: push, live: live, logger: logger, now: now, kampala: kampala}
}

// Joined is what the membership function answered for one school.
type Joined struct {
	Answer                          string
	OldCluster                      *string
	NewCluster                      string
	Relationship                    *string
	SchoolDistrict, ClusterDistrict *string
}

func refusalOf(answer string) string {
	switch answer {
	case "inactive":
		return inactiveCluster
	case "country":
		return otherCountry
	case "other_owner":
		return otherOwner
	}
	return ""
}

// auditPayload is the cluster.membership_changed entry's payload.
func auditPayload(j Joined) map[string]any {
	var rel any
	if j.Relationship != nil {
		rel = *j.Relationship
	}
	return map[string]any{
		"oldClusterId": optional(j.OldCluster),
		"newClusterId": j.NewCluster,
		"previous":     map[string]any{"clusterId": optional(j.OldCluster)},
		"new": map[string]any{
			"clusterId":         j.NewCluster,
			"relationship":      rel,
			"crossDistrict":     j.Relationship != nil && *j.Relationship == "neighbouring",
			"schoolDistrictId":  optional(j.SchoolDistrict),
			"clusterDistrictId": optional(j.ClusterDistrict),
		},
	}
}

func optional(v *string) any {
	if v == nil {
		return nil
	}
	return *v
}

// School is the school joining.
type School struct{ ID, Name, AccountOwner string }

// Join is set_school_cluster_membership(school, cluster, p.UserID,
// actor_role=p.ActiveRole): the writes in one transaction, then the audit
// row and the notices once a membership changed. A refusal comes back in the
// service's words and writes nothing.
func (s *Service) Join(ctx context.Context, p auth.Principal, school School, clusterID, clusterName, reason string, origin activities.Origin) (Joined, string, error) {
	now := s.now()
	j := Joined{NewCluster: clusterID}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return j, "", fmt.Errorf("clustermembership: opening the save: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	err = tx.QueryRow(ctx, `SELECT answer, old_cluster, relationship, school_district, cluster_district
FROM gateway_cluster_membership.join($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)`,
		school.ID, clusterID, p.UserID, p.ActiveRole, reason, now, now.In(s.kampala).Format(time.DateOnly),
		cuid.New(), cuid.New(), cuid.New(), origin.CorrelationID).
		Scan(&j.Answer, &j.OldCluster, &j.Relationship, &j.SchoolDistrict, &j.ClusterDistrict)
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && strings.HasSuffix(pgErr.Message, "clustermembership: other_owner") {
		return j, otherOwner, nil
	}
	if err != nil {
		return j, "", fmt.Errorf("clustermembership: saving the membership: %w", err)
	}
	if refusal := refusalOf(j.Answer); refusal != "" {
		return j, refusal, nil
	}
	if j.Answer != "joined" {
		return j, "", tx.Commit(ctx)
	}
	cover, err := audit.CoverageStamp(ctx, tx, p.UserID, now)
	if err != nil {
		return j, "", err
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "cluster.membership_changed", SubjectKind: audit.Text("school"), SubjectID: audit.Text(school.ID),
		ActorID: audit.Text(p.UserID), ActorRole: textOrNil(p.ActiveRole), Reason: textOrNil(reason), Success: true,
		Payload:   audit.WithStamps(auditPayload(j), cover),
		IPAddress: textOrNil(origin.IP), UserAgent: textOrNil(origin.UserAgent), CorrelationID: textOrNil(origin.CorrelationID),
	}, now); err != nil {
		return j, "", fmt.Errorf("clustermembership: writing the audit row: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return j, "", fmt.Errorf("clustermembership: committing the membership: %w", err)
	}
	s.notify(ctx, p, school, clusterName, j, now, origin)
	return j, "", nil
}

// notify is _notify_membership_change: the school's owner when someone else
// changed it, and their supervisors for a cross-district membership.
// Information only: a failure is logged, never undoes the membership.
func (s *Service) notify(ctx context.Context, p auth.Principal, school School, clusterName string, j Joined, now time.Time, origin activities.Origin) {
	if school.AccountOwner == "" {
		return
	}
	var ownerProfile, ownerUser string
	err := s.db.QueryRow(ctx, `SELECT id, COALESCE(user_id, '') FROM staff_profile
WHERE deleted_at IS NULL AND (id = $1 OR user_id = $1) ORDER BY id LIMIT 1`, school.AccountOwner).Scan(&ownerProfile, &ownerUser)
	if errors.Is(err, pgx.ErrNoRows) {
		return
	}
	if err != nil {
		s.warn("reading the school's owner", school.ID, err)
		return
	}
	route := "/schools/" + school.ID
	if ownerUser != "" && ownerUser != p.UserID {
		s.send(ctx, p, school.ID, origin, now, activities.Notice{
			Title: "School cluster changed", Body: fmt.Sprintf("%s is now in %s.", school.Name, clusterName),
			Event: "school_cluster_membership_changed", Category: "cluster", ContextType: "School", Priority: "normal",
		}, []string{ownerUser}, route)
	}
	if j.Relationship == nil || *j.Relationship != "neighbouring" {
		return
	}
	supervisors, err := s.supervisors(ctx, ownerProfile, p.UserID)
	if err != nil {
		s.warn("reading the owner's supervisors", school.ID, err)
		return
	}
	if len(supervisors) > 0 {
		s.send(ctx, p, school.ID, origin, now, activities.Notice{
			Title: "Cross-district cluster membership",
			Body:  fmt.Sprintf("%s joined %s, which serves its district under an approved neighbouring-district catchment.", school.Name, clusterName),
			Event: "school_cross_district_cluster", Category: "cluster", ContextType: "School", Priority: "normal",
		}, supervisors, route)
	}
}

func (s *Service) supervisors(ctx context.Context, ownerProfile, actor string) ([]string, error) {
	rows, err := s.db.Query(ctx, `SELECT COALESCE(sp.user_id, '') FROM staff_supervisor_assignment a
JOIN staff_profile sp ON sp.id = a.supervisor_id WHERE a.supervisee_id = $1`, ownerProfile)
	if err != nil {
		return nil, err
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, err
	}
	out := []string{}
	for _, id := range ids {
		if id != "" && id != actor {
			out = append(out, id)
		}
	}
	return out, nil
}

func (s *Service) send(ctx context.Context, p auth.Principal, schoolID string, origin activities.Origin, now time.Time, n activities.Notice, users []string, route string) {
	to := make([]activities.NoticeTo, 0, len(users))
	for _, u := range users {
		to = append(to, activities.NoticeTo{UserID: u, Route: route, Label: "View School"})
	}
	if err := activities.SendNotices(ctx, s.db, s.push, s.live, s.logger, now, schoolID, p.UserID, origin, n, to); err != nil {
		s.warn("telling "+n.Event, schoolID, err)
	}
}

func (s *Service) warn(what, schoolID string, err error) {
	if s.logger != nil {
		s.logger.Warn("clustermembership: "+what+" failed", "school", schoolID, "err", err)
	}
}

func textOrNil(v string) *string {
	if v == "" {
		return nil
	}
	return &v
}
