package recentchanges

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// unscheduledStatuses are PartnerAssignment.UNSCHEDULED_STATUSES.
var unscheduledStatuses = []string{"assigned", "pending_scheduling"}

type partnerRow struct {
	id                                                string
	at                                                time.Time
	school, cluster, partner, item, expected, project string
	status                                            string
	scheduled, replaces, withdrawal                   bool
}

func (a partnerRow) target() string {
	switch {
	case a.school != "":
		return a.school
	case a.cluster != "":
		return a.cluster + " cluster"
	}
	return "A school"
}

func (a partnerRow) summary() string {
	partner := a.partner
	if partner == "" {
		partner = "a partner"
	}
	work := ""
	switch {
	case a.item != "":
		work = " — " + a.item
	case a.expected != "":
		work = " — " + strings.ReplaceAll(a.expected, "_", " ")
	}
	project := ""
	if a.project != "" {
		project = " (project: " + a.project + ")"
	}
	return a.target() + " assigned to " + partner + work + project
}

// blocked is _partner_blocked within the window.
func (a partnerRow) blocked() string {
	partner := a.partner
	if partner == "" {
		partner = "The partner"
	}
	switch {
	case a.status == "returned_to_staff":
		return partner + " no longer holds it — it was handed back or withdrawn."
	case a.scheduled || !slices.Contains(unscheduledStatuses, a.status):
		return partner + " has already scheduled it. Withdraw it from Partner Monitoring instead, so the activity and its cost are unwound."
	case a.withdrawal:
		return "A withdrawal is already open on it."
	case a.replaces:
		return "It replaced another partner's work. Withdraw it instead, so the school is not left without support."
	}
	return ""
}

func (s *Service) partnerChanges(ctx context.Context, ids []string, since time.Time) ([]Change, error) {
	rows, err := s.db.Query(ctx, `SELECT pa.id, pa.created_at, COALESCE(sc.name, ''), COALESCE(c.name, ''), COALESCE(pt.name, ''),
  COALESCE(ci.display_name, ''), COALESCE(pa.expected_activity_type, ''), COALESCE(pr.name, ''), COALESCE(pa.status, ''),
  COALESCE(pa.scheduled_activity_id, '') <> '', COALESCE(pa.replaces_assignment_id, '') <> '',
  EXISTS (SELECT 1 FROM partner_assignment_withdrawal w WHERE w.assignment_id = pa.id)
FROM partner_assignment pa
LEFT JOIN school sc ON sc.id = pa.school_id LEFT JOIN cluster c ON c.id = pa.cluster_id
LEFT JOIN partner pt ON pt.id = pa.partner_id LEFT JOIN project pr ON pr.id = pa.project_id
LEFT JOIN activity_catalogue_item ci ON ci.id = pa.catalogue_item_id
WHERE pa.assigning_staff_id = ANY($1) AND pa.created_at >= $2 ORDER BY pa.created_at DESC`, ids, since)
	if err != nil {
		return nil, fmt.Errorf("recentchanges: reading the hand-overs: %w", err)
	}
	found, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (partnerRow, error) {
		var a partnerRow
		err := r.Scan(&a.id, &a.at, &a.school, &a.cluster, &a.partner, &a.item, &a.expected, &a.project, &a.status,
			&a.scheduled, &a.replaces, &a.withdrawal)
		return a, err
	})
	if err != nil {
		return nil, err
	}
	out := make([]Change, 0, len(found))
	for _, a := range found {
		partner := a.partner
		if partner == "" {
			partner = "the partner"
		}
		out = append(out, Change{Kind: "Partner", MadeAt: a.at, Summary: a.summary(),
			Effect: "Takes it back from " + partner + " as if it was never assigned.", Blocked: a.blocked()})
	}
	return out, nil
}

func (s *Service) projectChanges(ctx context.Context, ids []string, since time.Time) ([]Change, error) {
	rows, err := s.db.Query(ctx, `SELECT a.created_at, COALESCE(sc.name, ''), COALESCE(pr.name, ''), pr.deleted_at IS NOT NULL,
  EXISTS (SELECT 1 FROM activity x WHERE x.project_id = a.project_id AND x.school_id = a.school_id AND x.deleted_at IS NULL
           AND x.status IS DISTINCT FROM 'cancelled'),
  EXISTS (SELECT 1 FROM partner_assignment h WHERE h.project_id = a.project_id AND h.school_id = a.school_id
           AND h.status IS DISTINCT FROM 'returned_to_staff')
FROM project_school_assignment a LEFT JOIN school sc ON sc.id = a.school_id LEFT JOIN project pr ON pr.id = a.project_id
WHERE a.assigned_by = ANY($1) AND a.created_at >= $2 ORDER BY a.created_at DESC`, ids, since)
	if err != nil {
		return nil, fmt.Errorf("recentchanges: reading the enrolments: %w", err)
	}
	defer rows.Close()
	out := []Change{}
	for rows.Next() {
		var at time.Time
		var school, project string
		var deleted, planned, handed bool
		if err := rows.Scan(&at, &school, &project, &deleted, &planned, &handed); err != nil {
			return nil, err
		}
		c := Change{Kind: "Project", MadeAt: at, Summary: or(school, "A school") + " added to " + or(project, "a project"),
			Effect: "Takes the school out of " + or(project, "the project") + "."}
		switch {
		case deleted:
			c.Blocked = "The project has been deleted."
		case planned:
			c.Blocked = "Work is already planned for this school under the project. Cancel that work first."
		case handed:
			c.Blocked = "It has been assigned to a partner under this project. Undo or withdraw that assignment first."
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

func or(v, fallback string) string {
	if v == "" {
		return fallback
	}
	return v
}

func clusterSummary(school, cluster, previous string) string {
	if previous != "" {
		return or(school, "A school") + " moved from " + previous + " to " + or(cluster, "a cluster")
	}
	return or(school, "A school") + " added to " + or(cluster, "a cluster")
}

type membershipRow struct {
	at                                time.Time
	schoolID, clusterID, school, name string
	schoolGone                        bool
	schoolCluster                     string
}

type previousCluster struct {
	name, owner string
	usable      bool
}

func (s *Service) clusterChanges(ctx context.Context, p auth.Principal, ids []string, since time.Time) ([]Change, error) {
	rows, err := s.db.Query(ctx, `SELECT m.started_at, m.school_id, m.cluster_id, COALESCE(sc.name, ''), COALESCE(c.name, ''),
  sc.id IS NULL OR sc.deleted_at IS NOT NULL, COALESCE(sc.cluster_id, '')
FROM school_cluster_membership m LEFT JOIN school sc ON sc.id = m.school_id LEFT JOIN cluster c ON c.id = m.cluster_id
WHERE m.started_by = ANY($1) AND m.started_at >= $2 AND m.ended_at IS NULL AND m.start_reason NOT LIKE 'Undo:%'
ORDER BY m.started_at DESC`, ids, since)
	if err != nil {
		return nil, fmt.Errorf("recentchanges: reading the cluster moves: %w", err)
	}
	found, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (membershipRow, error) {
		var m membershipRow
		err := r.Scan(&m.at, &m.schoolID, &m.clusterID, &m.school, &m.name, &m.schoolGone, &m.schoolCluster)
		return m, err
	})
	if err != nil || len(found) == 0 {
		return nil, err
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return nil, err
	}
	out := make([]Change, 0, len(found))
	for _, m := range found {
		before, err := s.previous(ctx, m.schoolID, m.at)
		if err != nil {
			return nil, err
		}
		c := Change{Kind: "Cluster", MadeAt: m.at}
		if before != nil {
			c.Summary = clusterSummary(m.school, m.name, before.name)
		} else {
			c.Summary = clusterSummary(m.school, m.name, "")
		}
		if c.Effect, c.Blocked, err = s.clusterPlan(ctx, scope, m, before); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, nil
}

// previous is _previous_membership: the row closed the instant this one opened.
func (s *Service) previous(ctx context.Context, schoolID string, startedAt time.Time) (*previousCluster, error) {
	var pc previousCluster
	err := s.db.QueryRow(ctx, `SELECT COALESCE(c.name, ''), COALESCE(c.responsible_staff_id, ''),
  c.deleted_at IS NULL AND c.status = 'active'
FROM school_cluster_membership p JOIN cluster c ON c.id = p.cluster_id
WHERE p.school_id = $1 AND p.ended_at = $2 ORDER BY p.id LIMIT 1`, schoolID, startedAt).Scan(&pc.name, &pc.owner, &pc.usable)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("recentchanges: reading the previous membership: %w", err)
	}
	return &pc, nil
}

// clusterPlan is _cluster_plan's effect and refusal within the window.
func (s *Service) clusterPlan(ctx context.Context, scope schooldirectory.Scope, m membershipRow, before *previousCluster) (string, string, error) {
	current := or(m.name, "the cluster")
	switch {
	case m.schoolGone:
		return "", "The school is no longer on the platform.", nil
	case m.schoolCluster != m.clusterID:
		return "", "The school has moved cluster again since.", nil
	}
	var args []any
	arg := func(v any) string { args = append(args, v); return "$" + strconv.Itoa(len(args)) }
	var mine bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM school s WHERE `+schooldirectory.DirectPortfolio(scope, arg)+
		` AND s.id = `+arg(m.schoolID)+`)`, args...).Scan(&mine); err != nil {
		return "", "", fmt.Errorf("recentchanges: reading the reader's portfolio: %w", err)
	}
	switch {
	case !mine:
		return "", "The school is no longer in your portfolio.", nil
	case before == nil:
		return "Takes the school out of " + current + "; it is unclustered again.", "", nil
	case !before.usable:
		return "Takes the school out of " + current + ". Its previous cluster, " + before.name + ", is no longer active, so it is left unclustered.", "", nil
	}
	accepts, err := s.ownerAccepts(ctx, strings.TrimSpace(before.owner), m.schoolID)
	if err != nil {
		return "", "", err
	}
	if !accepts {
		return "", "Its previous cluster, " + before.name + ", belongs to another staff member now. Change the cluster from the school instead.", nil
	}
	return "Moves the school back to " + before.name + ".", "", nil
}

// ownerAccepts is _owner_accepts: an owned cluster takes only its owner's
// schools (owner_id_variants of portfolio_owner_profile_id).
func (s *Service) ownerAccepts(ctx context.Context, owner, schoolID string) (bool, error) {
	if owner == "" {
		return true, nil
	}
	portfolio, err := s.portfolioOwner(ctx, schoolID)
	if err != nil || portfolio == "" {
		return false, err
	}
	variants, err := s.variants(ctx, portfolio)
	return slices.Contains(variants, owner), err
}

// variants is owner_id_variants: an id and its staff profile's other id.
func (s *Service) variants(ctx context.Context, ident string) ([]string, error) {
	ids := []string{ident}
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(user_id, '') FROM staff_profile
WHERE deleted_at IS NULL AND (id = $1 OR user_id = $1)`, ident)
	if err != nil {
		return nil, fmt.Errorf("recentchanges: reading an owner's ids: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var profile, user string
		if err := rows.Scan(&profile, &user); err != nil {
			return nil, err
		}
		for _, id := range []string{profile, user} {
			if id != "" && !slices.Contains(ids, id) {
				ids = append(ids, id)
			}
		}
	}
	return ids, rows.Err()
}

// portfolioOwner is portfolio_owner_profile_id: the school's owner (its
// account owner, else its one staff assignment) as a live staff profile id.
func (s *Service) portfolioOwner(ctx context.Context, schoolID string) (string, error) {
	var owner string
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(account_owner_id, '') FROM school WHERE id = $1`, schoolID).Scan(&owner); err != nil {
		return "", fmt.Errorf("recentchanges: reading the school's owner: %w", err)
	}
	owner = strings.TrimSpace(owner)
	if owner == "" {
		rows, err := s.db.Query(ctx, `SELECT staff_id FROM staff_school_assignment WHERE school_id = $1 LIMIT 2`, schoolID)
		if err != nil {
			return "", fmt.Errorf("recentchanges: reading the school's staff: %w", err)
		}
		assigned, err := pgx.CollectRows(rows, pgx.RowTo[string])
		if err != nil || len(assigned) != 1 {
			return "", err
		}
		owner = assigned[0]
	}
	ids, err := s.variants(ctx, owner)
	if err != nil {
		return "", err
	}
	var profile string
	err = s.db.QueryRow(ctx, `SELECT id FROM staff_profile WHERE deleted_at IS NULL AND (id = ANY($1) OR user_id = ANY($1))
ORDER BY id LIMIT 1`, ids).Scan(&profile)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	return profile, err
}
