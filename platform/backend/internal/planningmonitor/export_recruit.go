package planningmonitor

import (
	"context"
	"fmt"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// RecruitPortfolio is recruit_notice.Portfolio: one Programme Lead or CCEO
// of the deployment, their visit target, and how many visits short of it
// the schools they hold leave them (Workload.short_of_target).
type RecruitPortfolio struct {
	Key, UserID   string
	Target, Short int
}

// RecruitPortfolios is recruit_notice.portfolios: every live Programme Lead
// and CCEO (by the role they hold), with the operating Core and Client, Core
// Trained and Core Graduate schools filed to either of their ids, by key.
func RecruitPortfolios(ctx context.Context, db schooldirectory.Querier) ([]RecruitPortfolio, error) {
	// In the roster's order (each Lead by name with their CCEOs, then the
	// CCEOs with no Lead), as the existing sweep walks it.
	teams, err := (&monitor{db: db}).roster(ctx, countryLens{})
	if err != nil {
		return nil, err
	}
	var people []rosterPerson
	ownerOf := map[string]string{}
	for _, t := range teams {
		for _, p := range t.people {
			people = append(people, p)
			for _, id := range p.ids {
				ownerOf[id] = p.key
			}
		}
	}
	owners := make([]string, 0, len(ownerOf))
	for id := range ownerOf {
		owners = append(owners, id)
	}
	held := map[string][2]int{}
	counts, err := db.Query(ctx, `SELECT account_owner_id, school_type, count(*)::int FROM school
WHERE deleted_at IS NULL AND operational_status = ANY($1) AND account_owner_id = ANY($2)
GROUP BY 1, 2`, rules.OperatingStatuses, owners)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: counting the schools held: %w", err)
	}
	for counts.Next() {
		var owner, kind string
		var n int
		if err := counts.Scan(&owner, &kind, &n); err != nil {
			counts.Close()
			return nil, err
		}
		if !monitored(kind) {
			continue
		}
		h := held[ownerOf[owner]]
		if isCore(kind) {
			h[0] += n
		} else {
			h[1] += n
		}
		held[ownerOf[owner]] = h
	}
	counts.Close()
	if err := counts.Err(); err != nil {
		return nil, err
	}
	out := make([]RecruitPortfolio, 0, len(people))
	for _, p := range people {
		user := ""
		if len(p.ids) > 1 {
			user = p.ids[1]
		}
		target := rules.VisitTargets[p.role]
		w := workload{cap: max(0, target), core: held[p.key][0], client: held[p.key][1]}
		out = append(out, RecruitPortfolio{Key: p.key, UserID: user, Target: target, Short: w.shortOfTarget()})
	}
	return out, nil
}
