package myplan

import (
	"context"
	"fmt"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ActivityAccess is what one reader may do with one activity, for the
// drawers that open on it (internal/activities' facilitator drawer).
type ActivityAccess struct {
	// Decided is false for a reader Go does not decide for: a partner's
	// team, a login acting as a partner, the Country Director and the
	// Regional Vice President.
	Decided bool
	// Found is whether the activity exists and is not deleted.
	Found bool
	// Visible is RolePermissionService.can_view_record.
	Visible bool
	// Runnable is services._get_for_execution with _assert_may_schedule:
	// the scope, scheduling and execution checks a change runs.
	Runnable bool
}

// ReadActivityAccess answers ActivityAccess for p and the activity id.
func ReadActivityAccess(ctx context.Context, db schooldirectory.Querier, p auth.Principal, id string, now time.Time) (ActivityAccess, error) {
	if rules.PartnerRoleBridge || in(detailReaderHandedOn, p.ActiveRole) {
		return ActivityAccess{}, nil
	}
	var partner bool
	if err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM partner WHERE user_id = $1 AND active_status)`, p.UserID).Scan(&partner); err != nil {
		return ActivityAccess{}, fmt.Errorf("myplan: reading the reader's organisation: %w", err)
	}
	if partner {
		return ActivityAccess{}, nil
	}
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return ActivityAccess{}, err
	}
	a, err := readDetailActivity(ctx, db, id, scope)
	if err != nil || a == nil {
		return ActivityAccess{Decided: true}, err
	}
	access := ActivityAccess{Decided: true, Found: true}
	if access.Visible, err = mayView(ctx, db, p, scope, a, now); err != nil {
		return ActivityAccess{}, err
	}
	if access.Runnable, err = mayRun(ctx, db, p, scope, a); err != nil {
		return ActivityAccess{}, err
	}
	return access, nil
}

// TakesFacilitator is facilitation.takes_facilitator.
func TakesFacilitator(kind string) bool { return in(rules.Detail.FacilitatorTypes, kind) }

// FacilitatorEditable is whether a training's facilitator may still change
// (facilitation.FACILITATOR_EDITABLE_STATUSES).
func FacilitatorEditable(status string) bool {
	return in(rules.Tables.FacilitatorEditableStatuses, status)
}

// SessionNoun is facilitation.session_noun: "meeting" for a cluster
// meeting, "training" otherwise.
func SessionNoun(kind string) string {
	if in(rules.Detail.MeetingTypes, kind) {
		return "meeting"
	}
	return "training"
}
