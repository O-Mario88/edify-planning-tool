package oversightportfolio

import (
	"context"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Owner is one entry of portfolio_service._staff_directory: the officer a
// school's account owner is, and the Programme Lead they report to.
type Owner struct{ OfficerID, OfficerName, LeadID, LeadName string }

// StaffDirectory is _staff_directory for the Planning Monitor: each owner
// id, in either id space, to its officer and their Lead.
func StaffDirectory(ctx context.Context, q schooldirectory.Querier, ownerIDs []string) (map[string]Owner, error) {
	found, err := staffDirectory(ctx, q, ownerIDs)
	if err != nil {
		return nil, err
	}
	out := make(map[string]Owner, len(found))
	for id, o := range found {
		out[id] = Owner{OfficerID: o.officerID, OfficerName: o.officerName, LeadID: o.leadID, LeadName: o.leadName}
	}
	return out, nil
}
