package signin

import (
	"context"
	"fmt"
	"strconv"
	"sync"
	"time"
)

// Figures are the four public figures under the sign-in form, each a share
// of one portfolio (owner, 2026-09-07: "schools reached, schools visited,
// Schools trained, and SSA Completed out of the total portfolio in the
// system and should fetch from the DB"). Counts only: no school or person.
type Figures struct {
	Portfolio, SchoolsReached, SchoolsVisited, SchoolsTrained, SSACompleted string
}

// The existing reckoning's sets (apps/frontend/views/auth_views.py
// _login_stats, with its constants as the existing modules define them).
var (
	operatingStatuses = []string{"active", "reopened"}
	completedStatuses = []string{"completed", "closed", "ia_verified", "accountant_confirmed",
		"salesforce_id_required", "awaiting_ia_verification", "submitted_to_pl", "evidence_accepted"}
	visitTypes = []string{"school_visit", "follow_up_visit", "coaching_visit", "in_school_support",
		"donor_visit", "story_gathering_visit", "school_invitation", "social_visit", "training_follow_up_visit",
		"in_school_coaching_visit", "core_visit", "core_assessment_visit", "baseline_ssa_visit",
		"school_visit_ssa_collection", "partner_ssa_collection"}
	trainingTypes = []string{"training", "in_school_training", "school_improvement_training",
		"cluster_training", "core_training", "cluster_training_ssa_collection"}
)

// A school counts as visited or trained when completed work of the year
// names it, or a cluster session records it attending. Only portfolio
// schools count, so every figure is out of the same denominator.
const figuresSQL = `
WITH portfolio AS (
  SELECT id FROM school WHERE deleted_at IS NULL AND operational_status = ANY($1)
), done AS (
  SELECT activity_type, school_id, attended_school_ids FROM activity
  WHERE deleted_at IS NULL AND fy = $2 AND status = ANY($3)
    AND status NOT IN ('cancelled', 'rejected', 'deferred')
), touched AS (
  SELECT activity_type, school_id AS sid FROM done WHERE school_id IS NOT NULL
  UNION
  SELECT activity_type, unnest(attended_school_ids) FROM done
)
SELECT
  (SELECT count(*) FROM portfolio),
  (SELECT count(DISTINCT t.sid) FROM touched t JOIN portfolio p ON p.id = t.sid WHERE t.activity_type = ANY($4)),
  (SELECT count(DISTINCT t.sid) FROM touched t JOIN portfolio p ON p.id = t.sid WHERE t.activity_type = ANY($5)),
  (SELECT count(DISTINCT r.school_id) FROM ssa_record r JOIN portfolio p ON p.id = r.school_id
     WHERE r.deleted_at IS NULL AND r.fy = $2 AND r.verification_status = 'confirmed')`

// operationalFY is get_operational_fy: the year an October-to-September
// year ends in, by the UTC date.
func operationalFY(now time.Time) string {
	at := now.UTC()
	if at.Month() >= time.October {
		return strconv.Itoa(at.Year() + 1)
	}
	return strconv.Itoa(at.Year())
}

// figuresCache keeps the figures for five minutes, like the existing page;
// the sign-in screen is public, so a burst of openings costs one query.
type figuresCache struct {
	mu      sync.Mutex
	at      time.Time
	fy      string
	figures Figures
}

const figuresTTL = 5 * time.Minute

func (s *Store) figures(ctx context.Context, cache *figuresCache, now time.Time) (Figures, error) {
	fy := operationalFY(now)
	cache.mu.Lock()
	defer cache.mu.Unlock()
	if cache.fy == fy && now.Sub(cache.at) < figuresTTL {
		return cache.figures, nil
	}
	var portfolio, visited, trained, ssa int64
	if err := s.db.QueryRow(ctx, figuresSQL, operatingStatuses, fy, completedStatuses, visitTypes, trainingTypes).
		Scan(&portfolio, &visited, &trained, &ssa); err != nil {
		return Figures{}, fmt.Errorf("signin: counting the sign-in figures: %w", err)
	}
	// "Schools reached" is the portfolio itself (owner, 2026-09-12).
	cache.figures = Figures{
		Portfolio: grouped(portfolio), SchoolsReached: grouped(portfolio),
		SchoolsVisited: grouped(visited), SchoolsTrained: grouped(trained), SSACompleted: grouped(ssa),
	}
	cache.at, cache.fy = now, fy
	return cache.figures, nil
}

// grouped writes n with thousands commas, as Python's f"{n:,}".
func grouped(n int64) string {
	digits := strconv.FormatInt(n, 10)
	if n < 0 {
		return "-" + grouped(-n)
	}
	for i := len(digits) - 3; i > 0; i -= 3 {
		digits = digits[:i] + "," + digits[i:]
	}
	return digits
}
