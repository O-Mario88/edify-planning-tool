package schooldirectory

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// What a school's profile (internal/schoolprofile) reads from the directory:
// the same scope, the same reach, the same status words.

// ResolveScope is the existing UserScope for p, read at now.
func ResolveScope(ctx context.Context, q Querier, p auth.Principal, now time.Time) (Scope, error) {
	return resolveScope(ctx, q, p, now)
}

// OperationalFY is core.fy.get_operational_fy, read in UTC as the existing
// code reads it.
func OperationalFY(now time.Time) string { return strconv.Itoa(operationalFY(now)) }

// reach is school_queryset(scope) without its operating filter: the whole
// scope, a lead's team included (the directory narrows to its own).
func (b *sqlb) reach(s Scope) string {
	switch {
	case s.Role == roleCountryDirector && !rules.AllowCDOperational:
		return "false"
	case s.CountryScope:
		if s.Country != "" {
			return b.inCountry(s.Country)
		}
		return "true"
	case s.RegionScope:
		if len(s.RegionIDs) == 0 {
			return "false"
		}
		return "s.region_id = ANY(" + b.arg(s.RegionIDs) + ")"
	case s.SummaryOnly || len(s.SchoolIDs) == 0:
		return "false"
	default:
		return "s.id = ANY(" + b.arg(s.SchoolIDs) + ")"
	}
}

// closedReach is schools.services._scoped_ids: the schools a closed record
// is read from, so a closure never widens or narrows who may read it.
func (b *sqlb) closedReach(s Scope) string {
	switch {
	case s.CountryScope:
		if s.Country != "" {
			return b.inCountry(s.Country)
		}
		return "true"
	case s.SummaryOnly || len(s.SchoolIDs) == 0:
		return "false"
	default:
		return "s.id = ANY(" + b.arg(s.SchoolIDs) + ")"
	}
}

// find is the first school of base named by key: its School ID first, then
// its record id (schools.services.get_one: "Ordered, not OR'd").
func find(ctx context.Context, q Querier, base *sqlb, key string) (string, error) {
	for _, column := range []string{"s.school_id", "s.id"} {
		b := base.clone()
		b.and(column + " = " + b.arg(key))
		var id string
		err := q.QueryRow(ctx, "SELECT s.id FROM school s WHERE "+b.where()+" LIMIT 1", b.args...).Scan(&id)
		if err == nil {
			return id, nil
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return "", fmt.Errorf("schooldirectory: finding the school: %w", err)
		}
	}
	return "", nil
}

// Openable is schools.services.get_one: the record id of the school key
// names (its School ID or record id) when p may open its profile, and ""
// when it may not. The scope's operating schools and its closed ones come
// first; a field officer (mayTake, data_gaps.may_take's role half) with a
// staff profile may also open a school nobody holds in their country.
func Openable(ctx context.Context, q Querier, p auth.Principal, s Scope, key string, closedStatuses []string, mayTake bool) (string, error) {
	b := &sqlb{}
	b.and("s.deleted_at IS NULL")
	operatingReach := b.reach(s)
	closed := "s.operational_status = ANY(" + b.arg(closedStatuses) + ")"
	closedReach := b.closedReach(s)
	b.and(fmt.Sprintf(`(s.operational_status IN ('active', 'reopened') AND (%s)) OR (%s AND (%s))`,
		operatingReach, closed, closedReach))
	id, err := find(ctx, q, b, key)
	if err != nil || id != "" || !mayTake || p.StaffProfileID == "" {
		return id, err
	}
	var country *string
	err = q.QueryRow(ctx, `SELECT country FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL LIMIT 1`, p.UserID).Scan(&country)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("schooldirectory: reading the officer's country: %w", err)
	}
	c := ""
	if country != nil {
		c = *country
	}
	return find(ctx, q, unheldBase(c), key)
}

// InReach is whether school_queryset(scope) holds the school: an operating
// school of the whole scope (ssa.creation.school_in_scope). A school opened
// only because nobody holds it is not in reach.
func InReach(ctx context.Context, q Querier, s Scope, schoolID string) (bool, error) {
	b := &sqlb{}
	b.and(operating)
	b.and(b.reach(s))
	b.and("s.id = " + b.arg(schoolID))
	var found bool
	if err := q.QueryRow(ctx, "SELECT EXISTS (SELECT 1 FROM school s WHERE "+b.where()+")", b.args...).Scan(&found); err != nil {
		return false, fmt.Errorf("schooldirectory: reading the scope: %w", err)
	}
	return found, nil
}

// VisitStatus is a school's visit status for the year, in the directory's
// words.
type VisitStatus struct {
	Label, Tone string
	Next        *time.Time
}

// VisitStatusOf is school_status.visit_statuses for one school.
func VisitStatusOf(ctx context.Context, q Querier, schoolID, fy string) (VisitStatus, error) {
	statuses, err := visitStatuses(ctx, q, []string{schoolID}, fy)
	if err != nil {
		return VisitStatus{}, err
	}
	status := statuses[schoolID]
	return VisitStatus{Label: rules.VisitLabels[status.key], Tone: rules.VisitTones[status.key], Next: status.next}, nil
}

// Coverage is a school's cluster training coverage for the year.
type Coverage struct {
	Planned                bool
	Label, Reason          string
	ClusterID, ClusterName string
	Day                    *time.Time
}

// CoverageOf is school_status.cluster_training_coverage for one school.
func CoverageOf(ctx context.Context, q Querier, schoolID, schoolType, clusterID, fy string) (Coverage, error) {
	covered, err := trainingCoverage(ctx, q, []school{{ID: schoolID, SchoolType: schoolType, ClusterID: clusterID}}, fy)
	if err != nil {
		return Coverage{}, err
	}
	c := covered[schoolID]
	return Coverage{Planned: c.planned, Label: c.label, Reason: c.reason, ClusterID: c.clusterID, ClusterName: c.clusterName, Day: c.day}, nil
}

// SSABand is core.enums.ssa_score_band: (label, tone).
func SSABand(score float64) (string, string) { return ssaBand(&score) }
