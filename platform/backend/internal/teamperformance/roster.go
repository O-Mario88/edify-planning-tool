package teamperformance

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// How far a reader sees (roster.OWN, TEAM, ALL).
const (
	reachOwn  = "own"
	reachTeam = "team"
	reachAll  = "all"
)

// officer is roster.Officer.
type officer struct {
	staffID, name, role, lead, region string
}

// team is roster.Region: a Programme Lead's team, named by the lead.
type team struct {
	key, label, leadName, place string
	officers                    []*officer
}

func (t *team) staffIDs() map[string]bool {
	out := map[string]bool{}
	for _, o := range t.officers {
		out[o.staffID] = true
	}
	return out
}

// roster is roster.Roster.
type roster struct {
	teams []*team
	reach string
	lead  string
}

func (r *roster) own() bool      { return r.reach == reachOwn }
func (r *roster) narrowed() bool { return r.reach != reachAll }

func (r *roster) homeLabel() string {
	switch r.reach {
	case reachOwn:
		return "Your portfolio"
	case reachTeam:
		return "Your team"
	}
	return "National Total"
}

func (r *roster) officers() []*officer {
	out := []*officer{}
	for _, t := range r.teams {
		out = append(out, t.officers...)
	}
	return out
}

func (r *roster) officer(id string) *officer {
	for _, o := range r.officers() {
		if o.staffID == id {
			return o
		}
	}
	return nil
}

func (r *roster) team(key string) *team {
	for _, t := range r.teams {
		if t.key == key {
			return t
		}
	}
	return nil
}

func (r *roster) teamOf(staffID string) *team {
	for _, t := range r.teams {
		if t.staffIDs()[staffID] {
			return t
		}
	}
	return nil
}

func reachOf(role string) string {
	if d, ok := rules.Doors[role]; ok {
		return d.Reach
	}
	return reachOwn
}

// visibleStaff is roster.visible_staff: nil (everyone) for the readers of
// the whole country; a Programme Lead and the CCEOs whose direct line is to
// them; anyone else only themselves.
func visibleStaff(ctx context.Context, db schooldirectory.Querier, p auth.Principal) (map[string]bool, error) {
	reach := reachOf(p.ActiveRole)
	if reach == reachAll {
		return nil, nil
	}
	me := p.StaffProfileID
	if me == "" {
		return map[string]bool{"": true}, nil
	}
	if reach == reachOwn {
		return map[string]bool{me: true}, nil
	}
	rows, err := db.Query(ctx, `SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $1`, me)
	if err != nil {
		return nil, fmt.Errorf("teamperformance: supervised: %w", err)
	}
	supervised := []string{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return nil, err
		}
		supervised = append(supervised, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	lines, _, err := directLeads(ctx, db, supervised)
	if err != nil {
		return nil, err
	}
	out := map[string]bool{me: true}
	for staff, lead := range lines {
		if lead == me {
			out[staff] = true
		}
	}
	return out, nil
}

// directLeads is roster.direct_leads: each officer's Programme Lead, the
// first one assigned; with the order the officers were first met.
func directLeads(ctx context.Context, db schooldirectory.Querier, staffIDs []string) (map[string]string, []string, error) {
	lead := rules.Roles.Lead
	rows, err := db.Query(ctx, `SELECT a.supervisee_id, a.supervisor_id FROM staff_supervisor_assignment a
		JOIN staff_profile t3 ON a.supervisor_id = t3.id JOIN "user" u ON t3.user_id = u.id
		WHERE a.supervisee_id = ANY($1::varchar[]) AND (u.active_role = $2 OR u.roles @> ARRAY[$2]::varchar(64)[])
		ORDER BY a.created_at ASC, a.id ASC`, staffIDs, lead)
	if err != nil {
		return nil, nil, fmt.Errorf("teamperformance: leads: %w", err)
	}
	defer rows.Close()
	out, order := map[string]string{}, []string{}
	for rows.Next() {
		var supervisee, supervisor string
		if err := rows.Scan(&supervisee, &supervisor); err != nil {
			return nil, nil, err
		}
		if supervisee == supervisor {
			continue
		}
		if _, ok := out[supervisee]; !ok {
			out[supervisee] = supervisor
			order = append(order, supervisee)
		}
	}
	return out, order, rows.Err()
}

// buildRoster is roster.build.
func buildRoster(ctx context.Context, db schooldirectory.Querier, p auth.Principal, visible map[string]bool, l *ledger) (*roster, error) {
	reach := reachOf(p.ActiveRole)
	cceo, leadRole := rules.Roles.CCEO, rules.Roles.Lead
	rows, err := db.Query(ctx, `SELECT COALESCE(u.name, ''), COALESCE(u.email, ''), COALESCE(u.roles, '{}'), sp.id, COALESCE(sp.primary_district_id, '')
		FROM "user" u LEFT JOIN staff_profile sp ON u.id = sp.user_id
		WHERE u.deleted_at IS NULL AND u.status = 'active' AND u.roles && ARRAY[$1, $2]::varchar(64)[]
		ORDER BY u.name ASC`, cceo, leadRole)
	if err != nil {
		return nil, fmt.Errorf("teamperformance: people: %w", err)
	}
	holders := l.holders()
	officers := map[string]*officer{}
	order := []string{}
	leads := map[string]string{}
	homes := map[string]string{}
	for rows.Next() {
		var name, email, district string
		var roles []string
		var staff *string
		if err := rows.Scan(&name, &email, &roles, &staff, &district); err != nil {
			rows.Close()
			return nil, err
		}
		if staff == nil {
			continue
		}
		id := *staff
		shown := name
		if shown == "" {
			shown = email
		}
		has := func(r string) bool {
			for _, x := range roles {
				if x == r {
					return true
				}
			}
			return false
		}
		if has(leadRole) {
			leads[id] = shown
		}
		if has(cceo) || holders[id] {
			role := leadRole
			if has(cceo) {
				role = cceo
			}
			if _, ok := officers[id]; !ok {
				order = append(order, id)
			}
			officers[id] = &officer{staffID: id, name: shown, role: role}
			if district != "" {
				homes[id] = district
			} else {
				delete(homes, id)
			}
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if err := placeOfficers(ctx, db, officers, l, homes); err != nil {
		return nil, err
	}
	lines, _, err := directLeads(ctx, db, order)
	if err != nil {
		return nil, err
	}
	for id, lead := range lines {
		if officers[id].role == cceo {
			officers[id].lead = lead
		}
	}
	for id, o := range officers {
		if _, ok := leads[id]; ok && o.role == leadRole {
			o.lead = id
		}
	}

	teamOrder := []string{}
	members := map[string][]*officer{}
	for _, id := range order {
		o := officers[id]
		if _, ok := members[o.lead]; !ok {
			teamOrder = append(teamOrder, o.lead)
		}
		members[o.lead] = append(members[o.lead], o)
	}
	teams := []*team{}
	for _, lead := range teamOrder {
		all := members[lead]
		sort.SliceStable(all, func(i, j int) bool {
			a, b := all[i].staffID != lead, all[j].staffID != lead
			if a != b {
				return !a
			}
			return pyLower(all[i].name) < pyLower(all[j].name)
		})
		shown := all
		if visible != nil {
			shown = []*officer{}
			for _, o := range all {
				if visible[o.staffID] {
					shown = append(shown, o)
				}
			}
			if len(shown) == 0 {
				continue
			}
		}
		leadName := leads[lead]
		if leadName == "" && lead != "" {
			if leadName, err = nameOf(ctx, db, lead); err != nil {
				return nil, err
			}
		}
		ids := map[string]bool{}
		for _, o := range all {
			ids[o.staffID] = true
		}
		tallied, _ := l.placesOf(ids, "region")
		place := ""
		if len(tallied) > 0 {
			place = mostOf(tallied)
		}
		key, label := lead, rules.NoLead
		if lead == "" {
			key = "none"
		} else if leadName != "" {
			label = leadName
		}
		teams = append(teams, &team{key: key, label: label, leadName: leadName, officers: shown, place: place})
	}
	sort.SliceStable(teams, func(i, j int) bool { return teamOrderLess(teams[i], teams[j]) })
	distinguish(teams)
	leadKey := ""
	if reach == reachTeam && visible != nil {
		leadKey = p.StaffProfileID
	}
	return &roster{teams: teams, reach: reach, lead: leadKey}, nil
}

func nameOf(ctx context.Context, db schooldirectory.Querier, staffID string) (string, error) {
	var name, email string
	err := db.QueryRow(ctx, `SELECT COALESCE(u.name, ''), COALESCE(u.email, '') FROM staff_profile sp JOIN "user" u ON sp.user_id = u.id
		WHERE sp.deleted_at IS NULL AND sp.id = $1 LIMIT 1`, staffID).Scan(&name, &email)
	if err != nil {
		if strings.Contains(err.Error(), "no rows") {
			return "", nil
		}
		return "", fmt.Errorf("teamperformance: lead name: %w", err)
	}
	if name == "" {
		return email, nil
	}
	return name, nil
}

// placeOfficers is roster._place_officers: where most of an officer's
// schools are (by name on a tie), else their primary district's region.
func placeOfficers(ctx context.Context, db schooldirectory.Querier, officers map[string]*officer, l *ledger, homes map[string]string) error {
	districtRegions := map[string]string{}
	if len(homes) > 0 {
		ids := []string{}
		for _, d := range homes {
			ids = append(ids, d)
		}
		rows, err := db.Query(ctx, `SELECT d.id, COALESCE(r.name, '') FROM district d LEFT JOIN region r ON d.region_id = r.id WHERE d.id = ANY($1::varchar[])`, ids)
		if err != nil {
			return fmt.Errorf("teamperformance: home districts: %w", err)
		}
		for rows.Next() {
			var id, name string
			if err := rows.Scan(&id, &name); err != nil {
				rows.Close()
				return err
			}
			if name != "" {
				districtRegions[id] = strings.TrimSpace(strings.ReplaceAll(name, " Region", ""))
			}
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return err
		}
	}
	for id, o := range officers {
		tallied, _ := l.placesOf(map[string]bool{id: true}, "region")
		if len(tallied) > 0 {
			o.region = mostOf(tallied)
		} else {
			o.region = districtRegions[homes[id]]
		}
	}
	return nil
}

func regionIndex(place string) int {
	for i, r := range rules.RegionOrder {
		if r == place {
			return i
		}
	}
	return -1
}

// teamOrderLess is roster._region_order.
func teamOrderLess(a, b *team) bool {
	rank := func(t *team) (int, int, string) {
		if t.key == "none" {
			return 2, 0, ""
		}
		if i := regionIndex(t.place); i >= 0 {
			return 0, i, pyLower(t.label)
		}
		return 1, 0, pyLower(t.label)
	}
	a1, a2, a3 := rank(a)
	b1, b2, b3 := rank(b)
	if a1 != b1 {
		return a1 < b1
	}
	if a2 != b2 {
		return a2 < b2
	}
	return a3 < b3
}

// distinguish is roster._distinguish: two leads of a name told apart by
// their team's region.
func distinguish(teams []*team) {
	seen := map[string]int{}
	for _, t := range teams {
		seen[t.label]++
	}
	for _, t := range teams {
		if seen[t.label] > 1 && t.place != "" {
			t.label = t.label + " (" + t.place + ")"
		}
	}
}

// pyLower is str.lower.
func pyLower(s string) string { return strings.ToLower(s) }
