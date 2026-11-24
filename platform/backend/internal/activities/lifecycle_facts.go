package activities

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// LifecycleFacts is what the Start, Salesforce ID and Submit drawers
// (my_plan_views start_activity_drawer_view, salesforce_id_drawer_view,
// submit_for_review_drawer_view) read of an officer's own staff school
// visit: the visits whose saves Go makes. Reading them writes nothing.
type LifecycleFacts struct {
	ActivityType, Place, Status, SalesforceID string
	Delivered                                 *time.Time
	// HandsInWithID is _hands_in_with_id: saving the ID hands the visit in,
	// so the drawer asks the day it was done.
	HandsInWithID bool
}

// LifecycleFacts reads the visit for its drawers, or hands it on (ErrHandOn)
// when it is not one Go saves.
func (s *Service) LifecycleFacts(ctx context.Context, p auth.Principal, activityID string) (LifecycleFacts, error) {
	if p.InActingAppointment || p.StaffProfileID == "" || p.ActiveRole != officerRole || slices.Contains(p.Roles, programmeLeadRole) {
		return LifecycleFacts{}, handOn("not an officer opening their own visit")
	}
	a, err := readCompletedVisit(ctx, s.db, strings.TrimSpace(activityID))
	if err != nil {
		return LifecycleFacts{}, err
	}
	switch {
	case a == nil:
		return LifecycleFacts{}, handOn("not a staff school visit with a school and a day")
	case a.other:
		return LifecycleFacts{}, handOn("a visit in a cluster, a project, a pair or a partner's hands")
	case !ownsVisit(p, a.responsible):
		return LifecycleFacts{}, handOn("someone else's visit")
	}
	if err := s.ownVisitSchool(ctx, p, a.schoolID, s.now()); err != nil {
		return LifecycleFacts{}, err
	}
	f := LifecycleFacts{ActivityType: a.activityType, Status: a.status, SalesforceID: a.salesforceID,
		HandsInWithID: slices.Contains(startableStatuses, a.status) || slices.Contains(submittableStatuses, a.status)}
	if err := s.db.QueryRow(ctx, `SELECT s.name, a.actual_delivery_date FROM activity a JOIN school s ON s.id = a.school_id
WHERE a.id = $1`, a.id).Scan(&f.Place, &f.Delivered); err != nil {
		return LifecycleFacts{}, fmt.Errorf("activities: reading the visit's school: %w", err)
	}
	return f, nil
}
