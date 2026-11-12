package clusterpage

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
)

// What the Planning page (internal/planningpage) shares with a cluster's
// schools list: the Partner-supported school rule, the score groups, a
// badge cell's text and a fact's colour.

// SupportRuleOn is support_responsibility.visibility_enabled(reader).
func SupportRuleOn(p auth.Principal) bool { return supportRuleOn(p) }

// ScoreGroupItems are partials/ssa/score_group_columns.html's groups.
func ScoreGroupItems(groups []schooldirectory.SSAGroup) []*screensv1.PagePanelItem {
	return groupItems(groups)
}

// JoinedChips is a badge cell's text.
func JoinedChips(chips ...[]schoolplanning.Chip) string { return joinedChips(chips...) }

// FactTone is the feed's colour for a fact whose holder carries words.
func FactTone(classes string) string { return factTone(classes) }

// ScoreText is |floatformat:"-1".
func ScoreText(v float64) string { return scoreText(v) }

// ScopedClusters are the reader's clusters (scoping.cluster_queryset, any
// status, not deleted), as a condition over the clusters aliased c: their
// own (direct) or, for a supervisor, their team's too.
func ScopedClusters(ctx context.Context, q schooldirectory.Querier, s schooldirectory.Scope, direct bool, arg func(any) string) (string, error) {
	if direct || s.CountryScope || s.SummaryOnly {
		owners, err := ownerIDs(ctx, q, s)
		if err != nil {
			return "", err
		}
		b := &sqlb{}
		where := b.inScope(s, owners)
		return renumber(where, b.args, arg), nil
	}
	clusters, districts, err := scopeGeography(ctx, q, s.SchoolIDs)
	if err != nil {
		return "", err
	}
	owners, err := teamOwnerIDs(ctx, q, s)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf(`(c.responsible_staff_id = ANY(%s) OR c.id = ANY(%s)
  OR ((c.responsible_staff_id IS NULL OR c.responsible_staff_id = '') AND c.district_id = ANY(%s)))`,
		arg(nonNil(owners)), arg(nonNil(clusters)), arg(nonNil(districts))), nil
}

// renumber hands a clause's parameters to arg in order.
func renumber(where string, args []any, arg func(any) string) string {
	for i := len(args); i >= 1; i-- {
		where = strings.ReplaceAll(where, fmt.Sprintf("$%d", i), fmt.Sprintf("\x00%d\x00", i))
	}
	for i, v := range args {
		where = strings.ReplaceAll(where, fmt.Sprintf("\x00%d\x00", i+1), arg(v))
	}
	return where
}

// PlanningRecords are the Planning page's Clusters tab cards for the
// clusters ids (in order): the Clusters page's cards, each cluster's
// planning figures read only where cluster_planning reads it (the reader's
// own active clusters) and the doors of the reader's role.
func PlanningRecords(ctx context.Context, q schooldirectory.Querier, p auth.Principal, s schooldirectory.Scope,
	ids []string, fy string) ([]*screensv1.PageRecord, error) {
	if len(ids) == 0 {
		return nil, nil
	}
	list := []cluster{}
	at := map[string]int{}
	err := each(ctx, q, "the tab's clusters", `
SELECT c.id, COALESCE(c.name, ''), d.name, CASE WHEN sc.id IS NULL THEN NULL ELSE COALESCE(sc.name, '') END,
  COALESCE(c.sub_county_name, ''), COALESCE(c.cluster_leader_name, ''), COALESCE(c.cluster_leader_phone, ''),
  COALESCE(c.facilitating_partner_id, '')
FROM cluster c LEFT JOIN district d ON d.id = c.district_id LEFT JOIN sub_county sc ON sc.id = c.sub_county_id
WHERE c.id = ANY($1)`, func(rows pgx.Rows) error {
		var c cluster
		if err := rows.Scan(&c.ID, &c.Name, &c.District, &c.SubCounty, &c.SubCountyName, &c.LeaderName, &c.LeaderPhone, &c.FacilitatingPartnerID); err != nil {
			return err
		}
		at[c.ID] = len(list)
		list = append(list, c)
		return nil
	}, ids)
	if err != nil {
		return nil, err
	}
	ordered := []cluster{}
	for _, id := range ids {
		if i, ok := at[id]; ok {
			ordered = append(ordered, list[i])
		}
	}
	if err := covered(ctx, q, ordered); err != nil {
		return nil, err
	}
	all, err := cards(ctx, q, ordered, fy)
	if err != nil {
		return nil, err
	}
	// cluster_planning reads the reader's own active clusters only.
	owners, err := ownerIDs(ctx, q, s)
	if err != nil {
		return nil, err
	}
	b := &sqlb{}
	planned := map[string]bool{}
	direct, err := strings1(ctx, q, "SELECT c.id FROM cluster c WHERE c.id = ANY("+b.arg(ids)+") AND "+base(b, s, owners), b.args...)
	if err != nil {
		return nil, fmt.Errorf("clusterpage: reading the planned clusters: %w", err)
	}
	for _, id := range direct {
		planned[id] = true
	}
	doors := rules.Doors[p.ActiveRole]
	out := []*screensv1.PageRecord{}
	for _, c := range all {
		if !planned[c.ID] {
			c.plan = planning{missing: true}
		}
		out = append(out, record(c, doors, fy))
	}
	return out, nil
}

func strings1(ctx context.Context, q schooldirectory.Querier, sql string, args ...any) ([]string, error) {
	out := []string{}
	err := each(ctx, q, "ids", sql, func(rows pgx.Rows) error {
		var id string
		if err := rows.Scan(&id); err != nil {
			return err
		}
		out = append(out, id)
		return nil
	}, args...)
	return out, err
}
