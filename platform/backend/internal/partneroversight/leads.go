package partneroversight

import (
	"context"
	"fmt"
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// programLead is one of oversight_service.system_program_leads: a staff member
// holding the Programme Lead role, in both id spaces.
type programLead struct {
	id, name string
	ids      []string
}

// leadTab is one Programme Lead's tab and the work under it.
type leadTab struct {
	key, label string
	items      []*item
}

// systemProgramLeads is system_program_leads: every staff member who holds
// the Country Programme Lead role (in use or not), by name.
func systemProgramLeads(ctx context.Context, db schooldirectory.Querier) ([]programLead, error) {
	rows, err := db.Query(ctx, `
SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(NULLIF(u.name, ''), u.email, '')
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (u.active_role = $1 OR $1 = ANY(COALESCE(u.roles, '{}')))
ORDER BY u.name, sp.id`, rules.RosterLeadRole)
	if err != nil {
		return nil, fmt.Errorf("partneroversight: reading the Programme Leads: %w", err)
	}
	defer rows.Close()
	out := []programLead{}
	for rows.Next() {
		var l programLead
		var user string
		if err := rows.Scan(&l.id, &user, &l.name); err != nil {
			return nil, fmt.Errorf("partneroversight: reading the Programme Leads: %w", err)
		}
		l.ids = []string{l.id}
		if user != "" {
			l.ids = append(l.ids, user)
		}
		out = append(out, l)
	}
	return out, rows.Err()
}

// leadTabs is _program_lead_tabs with the system's leads: a tab for each
// lead with the work their teams hold, then Unassigned for work no lead
// supervises; the tab asked for opens, else the first. It answers the tabs,
// the open tab's key and its work.
func leadTabs(leads []programLead, items []*item, asked string) ([]leadTab, string, []*item) {
	tabs := []leadTab{}
	of := map[string]int{}
	for _, l := range leads {
		tabs = append(tabs, leadTab{key: l.id, label: l.name, items: []*item{}})
		for _, id := range l.ids {
			of[id] = len(tabs) - 1
		}
	}
	unassigned := []*item{}
	for _, i := range items {
		if at, ok := of[i.plID]; ok && i.plID != "" {
			tabs[at].items = append(tabs[at].items, i)
		} else {
			unassigned = append(unassigned, i)
		}
	}
	if len(unassigned) > 0 {
		tabs = append(tabs, leadTab{key: "unassigned", label: "Unassigned", items: unassigned})
	}
	if len(tabs) == 0 {
		return nil, "", nil
	}
	open := 0
	for at, t := range tabs {
		if t.key == asked {
			open = at
			break
		}
	}
	return tabs, tabs[open].key, tabs[open].items
}

// leadPanel is the Programme Lead strip as the feed reads it.
func (v *workView) leadPanel() *screensv1.PageBlock {
	links := []*screensv1.PageLink{}
	for _, t := range v.leads {
		links = append(links, &screensv1.PageLink{Text: t.label,
			Href:    "?program_lead=" + t.key + "&partner=all" + v.query(),
			Caption: strconv.Itoa(len(t.items))})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Badges: []*screensv1.PageBadge{},
		Items: []*screensv1.PagePanelItem{
			{Kind: &screensv1.PagePanelItem_Text{Text: "Programme Lead"}},
			{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}},
		},
	}}}
}
