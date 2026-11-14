package adminops

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// openIncident is a system incident as Planning lists it.
type openIncident struct {
	ID, Reference, Title string
	Seen                 int
}

// triageTicket is a support ticket waiting for triage.
type triageTicket struct {
	ID, Reference, Title, Category, ReporterRole string
}

// planning is admin_planning_view (AdminPlanningService.context): the
// backlog by severity then oldest first, and the newest open incidents and
// untriaged tickets.
func (s *Service) planning(ctx context.Context, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	rows, err := s.db.Query(ctx, `SELECT `+workItemColumns+` FROM admin_ops_work_item WHERE status = $1`, rules.BacklogStatus)
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the backlog: %w", err)
	}
	backlog, err := pgx.CollectRows(rows, scanWorkItem)
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the backlog: %w", err)
	}
	slices.SortStableFunc(backlog, func(a, b workItem) int {
		if ra, rb := severityRank(a.Severity), severityRank(b.Severity); ra != rb {
			return ra - rb
		}
		return a.CreatedAt.Compare(b.CreatedAt)
	})
	rows, err = s.db.Query(ctx, `SELECT id, reference, title, occurrence_count FROM admin_system_incident
WHERE NOT status = ANY($1) ORDER BY last_detected_at DESC LIMIT $2`, rules.ClosedIncidentStatuses, rules.PlanningLimit)
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the open incidents: %w", err)
	}
	incidents, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (openIncident, error) {
		var i openIncident
		err := r.Scan(&i.ID, &i.Reference, &i.Title, &i.Seen)
		return i, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the open incidents: %w", err)
	}
	rows, err = s.db.Query(ctx, `SELECT id, reference, title, category, reporter_role FROM admin_support_ticket
WHERE status = $1 ORDER BY created_at DESC LIMIT $2`, rules.UntriagedTicketStatus, rules.PlanningLimit)
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the untriaged tickets: %w", err)
	}
	tickets, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (triageTicket, error) {
		var t triageTicket
		err := r.Scan(&t.ID, &t.Reference, &t.Title, &t.Category, &t.ReporterRole)
		return t, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("adminops: reading the untriaged tickets: %w", err)
	}
	return planningPage(backlog, incidents, tickets, query), true, nil
}

func cells(texts ...string) []*screensv1.PageCell {
	out := make([]*screensv1.PageCell, 0, len(texts))
	for _, t := range texts {
		out = append(out, &screensv1.PageCell{Text: collapse(t)})
	}
	return out
}

func columns(labels ...string) []*screensv1.PageColumn {
	out := make([]*screensv1.PageColumn, 0, len(labels))
	for _, l := range labels {
		out = append(out, &screensv1.PageColumn{Label: l})
	}
	return out
}

func planningPage(backlog []workItem, incidents []openIncident, tickets []triageTicket, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Platform Operations", Title: "Admin Planning",
		Description: "Platform work that is not yet scheduled: maintenance, incidents, support, security, performance, data repair, features and releases. Scheduling an item moves it into Admin My Plan."}
	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Planning attention", Metrics: []*screensv1.PageMetric{
			{Label: "Open incidents", Value: strconv.Itoa(len(incidents)), Note: "Needs platform response"},
			{Label: "Tickets awaiting triage", Value: strconv.Itoa(len(tickets)), Note: "Needs an owner"},
		}}}},
	}
	size := rules.TablePageSize
	if len(backlog) == 0 {
		blocks = append(blocks, panel("Unscheduled Platform Work", []string{"Nothing is waiting to be scheduled. New tickets, incidents and maintenance appear here automatically."}))
	} else {
		number, pages := closedschools.PageOf(query.Get("backlog_page"), len(backlog), size)
		t := &screensv1.PageTable{Title: "Unscheduled Platform Work", Columns: columns("Work item", "Reference", "Severity", "Category", "Schedule for", "Action")}
		for _, w := range backlog[(number-1)*size : min(number*size, len(backlog))] {
			// The title and route are two spans in one cell, read with no space.
			t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells(w.Title+w.Route, w.Reference,
				label(rules.Severities, w.Severity), label(rules.WorkItemCategories, w.Category), "", "Schedule")})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
		if pages > 1 {
			blocks = append(blocks, closedschools.PagerPanel("backlog_page", number, pages, len(backlog), size, query, nil))
		}
	}
	if len(incidents) == 0 {
		blocks = append(blocks, panel("Open Incidents", []string{"No open incidents."}))
	} else {
		links := &screensv1.PageLinks{}
		for _, i := range incidents {
			links.Links = append(links.Links, &screensv1.PageLink{Text: collapse(i.Reference + " seen " + strconv.Itoa(i.Seen) + "×"),
				Href: "/admin-ops/incidents/" + i.ID, Caption: collapse(i.Title)})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Open Incidents",
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: links}}}}}})
	}
	if len(tickets) == 0 {
		blocks = append(blocks, panel("Tickets Awaiting Triage", []string{"No tickets are waiting for triage."}))
	} else {
		// The severity select reads as all of its options.
		severities := ""
		for _, c := range rules.SeverityChoices {
			severities += c[1]
		}
		number, pages := closedschools.PageOf(query.Get("triage_page"), len(tickets), size)
		t := &screensv1.PageTable{Title: "Tickets Awaiting Triage", Columns: columns("Ticket", "Category", "Severity", "Action")}
		for _, k := range tickets[(number-1)*size : min(number*size, len(tickets))] {
			t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells(k.Reference+k.Title,
				label(rules.TicketCategories, k.Category)+" · "+orDefault(k.ReporterRole, "user"), severities, "Triage")})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
		if pages > 1 {
			blocks = append(blocks, closedschools.PagerPanel("triage_page", number, pages, len(tickets), size, query, nil))
		}
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: PlanningPath}
}
