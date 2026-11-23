package plreview

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	statusSubmittedToPL = "submitted_to_pl"
	statusAwaitingIA    = "awaiting_ia_verification"
	partnerDelivery     = "partner"
	unnamedOfficer      = "Unnamed officer"
	deliveredLayout     = "2 Jan 2006"
)

// leadVerifiedStaff is _lead_verified_profiles over staff_profile sp joined to
// its "user" u: every CCEO and lead, and anyone a Programme Lead supervises.
// $1 is rules.LeadVerifiedRoles and $2 rules.LeadRole.
const leadVerifiedStaff = `sp.deleted_at IS NULL AND (u.roles && $1::varchar[] OR EXISTS (
    SELECT 1 FROM staff_supervisor_assignment l JOIN staff_profile sv ON sv.id = l.supervisor_id JOIN "user" su ON su.id = sv.user_id
    WHERE l.supervisee_id = sp.id AND sv.deleted_at IS NULL AND su.roles @> ARRAY[$2::varchar]))`

// reviewCase is what the review rule reads of a completion.
type reviewCase struct {
	found             bool
	status            string
	deliveryType      string
	owner             string // _owning_staff_id: the responsible staff, else the monitor
	ownerLeadVerified bool
}

// reviewerReach is what the review rule reads of the person deciding.
type reviewerReach struct {
	admin      bool
	clearsOwn  bool     // lead_clears_own_work: the lead role held and in use
	own        []string // both id spaces
	supervised []string // both id spaces
}

// refusalFor is apps.pl_review.services._check_reviewable. Nil means this
// reviewer may decide this completion.
func refusalFor(work reviewCase, by reviewerReach) *ReviewRefusal {
	switch {
	case !work.found:
		return &ReviewRefusal{Message: "Activity not found."}
	case work.status != statusSubmittedToPL && work.status != statusAwaitingIA:
		return &ReviewRefusal{Message: "Activity is not awaiting PL review."}
	case work.status == statusAwaitingIA && (work.deliveryType == partnerDelivery || !work.ownerLeadVerified):
		return &ReviewRefusal{Message: "This work is verified by Impact Assessment."}
	case by.admin:
		return nil
	}
	if work.owner != "" && slices.Contains(by.own, work.owner) {
		if by.clearsOwn && work.deliveryType != partnerDelivery {
			return nil
		}
		return &ReviewRefusal{Message: "You cannot review your own completion.", Forbidden: true}
	}
	if work.owner == "" || !slices.Contains(by.supervised, work.owner) {
		return &ReviewRefusal{Message: "This completion belongs to another Program Lead's team.", Forbidden: true}
	}
	return nil
}

// Review is a completion a reviewer may decide, as the review forms show it.
type Review struct {
	ID, Status, ActivityType, SchoolID, ResponsibleStaffID string
	Officer, Activity, Where, Delivered                    string
	// What a decision on it reads.
	Owner, DeliveryType, ProjectID, CatalogueItemID, Intervention string
	Planned, IAConfirmedAt                                        *time.Time
}

// readWork is the completion and whether a lead verifies its owner's work.
func readWork(ctx context.Context, q schooldirectory.Querier, activityID string) (Review, reviewCase, error) {
	review, work, err := readReview(ctx, q, activityID)
	if err != nil {
		return Review{}, reviewCase{}, err
	}
	if work.found && work.status == statusAwaitingIA && work.deliveryType != partnerDelivery && work.owner != "" {
		err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE (sp.id = $3 OR sp.user_id = $3) AND `+leadVerifiedStaff+`)`,
			rules.LeadVerifiedRoles, rules.LeadRole, work.owner).Scan(&work.ownerLeadVerified)
		if err != nil {
			return Review{}, reviewCase{}, fmt.Errorf("plreview: reading who verifies the owner's work: %w", err)
		}
	}
	return review, work, nil
}

// decidable is the decision views' order: the record exists, this reviewer
// holds it (may_review, whatever its state), and only then whether it is
// still waiting (_check_reviewable).
func decidable(ctx context.Context, q schooldirectory.Querier, p auth.Principal, activityID string, now time.Time) (Review, error) {
	review, work, err := readWork(ctx, q, activityID)
	if err != nil {
		return Review{}, err
	}
	if !work.found {
		return Review{}, &ReviewRefusal{Message: "Activity not found.", NotFound: true}
	}
	reach, err := reachOf(ctx, q, p, now)
	if err != nil {
		return Review{}, err
	}
	if !mayDecide(work, reach) {
		return Review{}, &ReviewRefusal{Message: notYourOfficer, Forbidden: true}
	}
	if refusal := refusalFor(work, reach); refusal != nil {
		return Review{}, refusal
	}
	if err := q.QueryRow(ctx, `SELECT ia_confirmed_at FROM activity WHERE id = $1`, activityID).Scan(&review.IAConfirmedAt); err != nil {
		return Review{}, fmt.Errorf("plreview: reading the earlier confirmation: %w", err)
	}
	return review, nil
}

// Reviewable is apps.pl_review.services.reviewable_activity. A completion this
// reviewer may not decide answers a *ReviewRefusal in the existing words.
func Reviewable(ctx context.Context, q schooldirectory.Querier, p auth.Principal, activityID string, now time.Time) (Review, error) {
	review, work, err := readWork(ctx, q, activityID)
	if err != nil {
		return Review{}, err
	}
	// The record's own state refuses first, and needs no reading of the team.
	if refusal := refusalFor(work, reviewerReach{admin: true}); refusal != nil {
		return Review{}, refusal
	}
	reach, err := reachOf(ctx, q, p, now)
	if err != nil {
		return Review{}, err
	}
	if refusal := refusalFor(work, reach); refusal != nil {
		return Review{}, refusal
	}
	names, _, err := readPeople(ctx, q, []string{work.owner})
	if err != nil {
		return Review{}, err
	}
	if review.Officer = names[work.owner]; review.Officer == "" {
		review.Officer = unnamedOfficer
	}
	return review, nil
}

func readReview(ctx context.Context, q schooldirectory.Querier, activityID string) (Review, reviewCase, error) {
	review := Review{ID: activityID}
	work := reviewCase{found: true}
	var name string
	var delivered *time.Time
	err := q.QueryRow(ctx, `
SELECT COALESCE(a.status, ''), COALESCE(a.delivery_type, ''),
  COALESCE(NULLIF(a.responsible_staff_id, ''), NULLIF(a.monitored_by_staff_id, ''), ''),
  COALESCE(a.responsible_staff_id, ''), COALESCE(a.school_id, ''), COALESCE(a.activity_type, ''),
  COALESCE(a.activity_name_snapshot, ''),
  COALESCE(CASE WHEN a.school_id IS NOT NULL THEN s.name WHEN a.cluster_id IS NOT NULL THEN cl.name ELSE a.venue END, ''),
  COALESCE(a.actual_delivery_date, a.planned_date),
  COALESCE(a.project_id, ''), COALESCE(a.catalogue_item_id, ''), COALESCE(a.focus_intervention, ''), a.planned_date
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
WHERE a.id = $1 AND a.deleted_at IS NULL`, activityID).Scan(
		&work.status, &work.deliveryType, &work.owner, &review.ResponsibleStaffID, &review.SchoolID,
		&review.ActivityType, &name, &review.Where, &delivered,
		&review.ProjectID, &review.CatalogueItemID, &review.Intervention, &review.Planned)
	if errors.Is(err, pgx.ErrNoRows) {
		return review, reviewCase{}, nil
	}
	if err != nil {
		return review, work, fmt.Errorf("plreview: reading the completion: %w", err)
	}
	review.Status, review.Owner, review.DeliveryType = work.status, work.owner, work.deliveryType
	review.Activity = name
	if review.Activity == "" {
		review.Activity = activityTypeLabel(review.ActivityType)
	}
	if delivered != nil {
		review.Delivered = delivered.UTC().Format(deliveredLayout)
	}
	return review, work, nil
}

// activityTypeLabel is get_activity_type_display: the stored value when it is
// not one of the choices.
func activityTypeLabel(activityType string) string {
	if label, ok := rules.ActivityTypes[activityType]; ok {
		return label
	}
	return activityType
}

// reachOf is _is_admin, _own_ids, lead_clears_own_work and _reviewer_staff_ids.
func reachOf(ctx context.Context, q schooldirectory.Querier, p auth.Principal, now time.Time) (reviewerReach, error) {
	if p.ActiveRole == rules.AdminRole {
		return reviewerReach{admin: true}, nil
	}
	scope, err := schooldirectory.ResolveScope(ctx, q, p, now)
	if err != nil {
		return reviewerReach{}, fmt.Errorf("plreview: resolving the reviewer's scope: %w", err)
	}
	reach := reviewerReach{
		clearsOwn: p.ActiveRole == rules.LeadRole && slices.Contains(p.Roles, rules.LeadRole),
	}
	for _, id := range []string{p.UserID, p.StaffProfileID, scope.StaffID} {
		if id != "" {
			reach.own = append(reach.own, id)
		}
	}
	if len(scope.SupervisedStaffIDs) == 0 {
		return reach, nil
	}
	rows, err := q.Query(ctx, `SELECT user_id FROM staff_profile WHERE id = ANY($1) AND user_id IS NOT NULL`, scope.SupervisedStaffIDs)
	if err != nil {
		return reviewerReach{}, fmt.Errorf("plreview: reading the team's accounts: %w", err)
	}
	users, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return reviewerReach{}, fmt.Errorf("plreview: reading a team account: %w", err)
	}
	reach.supervised = slices.Concat(scope.SupervisedStaffIDs, users)
	return reach, nil
}
