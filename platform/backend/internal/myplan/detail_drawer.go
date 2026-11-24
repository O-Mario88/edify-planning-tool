package myplan

import (
	"context"
	"fmt"
	"regexp"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// An activity's detail drawer (/my-plan/<id>, my_plan_views.
// activity_detail_view and partials/my_plan/activity_detail_drawer.html),
// as the feed reads it: the facts, then the Overview, Finance and
// Salesforce ID tabs. The footer's Edit, Reschedule and Complete buttons
// are not in the feed's drawer; the Cancel row in the Overview is.

var detailPath = regexp.MustCompile(`^/my-plan/([A-Za-z0-9]{1,30})/?$`)

// DetailID is the activity a drawer path opens, ok false for any other
// path.
func DetailID(path string) (string, bool) {
	m := detailPath.FindStringSubmatch(path)
	if m == nil {
		return "", false
	}
	return m[1], true
}

// DetailDrawer draws the activity's drawer for p, or ErrDetailHandOn.
func (s *Service) DetailDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	door, ok := rules.Doors[p.ActiveRole]
	if !ok || !door.Page || rules.PartnerRoleBridge || in(detailReaderHandedOn, p.ActiveRole) {
		return nil, handOn("a reader Go does not decide")
	}
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, err
	}
	// resolve_partner_ids: a login an organisation holds reads as that
	// partner (partner roles and the demo bridge are handed on above).
	var partner bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM partner WHERE user_id = $1 AND active_status)`, p.UserID).Scan(&partner); err != nil {
		return nil, fmt.Errorf("myplan: reading the reader's organisation: %w", err)
	}
	if partner {
		return nil, handOn("a reader who acts as a partner")
	}
	a, err := readDetailActivity(ctx, s.db, id, scope)
	if err != nil {
		return nil, err
	}
	if a == nil || !detailDrawn(a) {
		return nil, handOn("an activity Go does not draw")
	}
	visible, err := mayView(ctx, s.db, p, scope, a, now)
	if err != nil {
		return nil, err
	}
	if !visible {
		return nil, handOn("a reader the existing application refuses")
	}
	if p.ActiveRole == "Accountant" {
		reaches, err := accountantReaches(ctx, s.db, a.id)
		if err != nil {
			return nil, err
		}
		if !reaches {
			return nil, handOn("work the Accountant's evidence reach refuses")
		}
	}
	if evidence, err := hasEvidence(ctx, s.db, a.id); err != nil || evidence {
		return nil, handOnOr(err)
	}
	staff, single, err := staffName(ctx, s.db, a.staffID)
	if err != nil || !single {
		return nil, handOnOr(err)
	}
	overview, err := s.overview(ctx, p, scope, a)
	if err != nil {
		return nil, err
	}
	finance, subtitle, err := s.finance(ctx, a, staff)
	if err != nil {
		return nil, err
	}
	purpose := caption(a)
	return &screensv1.PageDrawer{
		Title:       detailTitle(a.kind),
		HasRequired: true,
		CancelLabel: "Close",
		Items: []*screensv1.DrawerItem{
			{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: detailFacts(a)}}},
			{Kind: &screensv1.DrawerItem_Block{Block: &screensv1.PageBlock{Kind: &screensv1.PageBlock_Segments{Segments: &screensv1.PageSegments{
				Title:    "Budget breakdown",
				Subtitle: subtitle,
				Caption:  purpose,
				Segments: []*screensv1.PageSegment{
					{Label: "Overview", Blocks: overview},
					{Label: "Finance", Blocks: finance},
					{Label: "Salesforce ID", Blocks: []*screensv1.PageBlock{panel("", heading("Activity SF ID"), text(orText(a.salesforce, "No Salesforce ID entered yet.")))}},
				},
			}}}}},
		},
	}, nil
}

// caption is what the feed reads as the tabs' caption: the drawer's first
// paragraph, the SSA verdict's reason or the planner's when the plan has a
// verdict, else the purpose.
func caption(a *detailActivity) string {
	if a.ssaAlignment != "" {
		if a.verdictReason != "" {
			return a.verdictReason
		}
		if a.deviationReason != "" {
			return "Planner's reason: " + a.deviationReason
		}
	}
	return orText(a.purpose, "No purpose description text entered.")
}

func handOnOr(err error) error {
	if err != nil {
		return err
	}
	return handOn("legacy evidence or two accounts for the officer")
}

// detailDrawn is whether Go draws this activity's drawer: not a returned
// activity (its return note), a training or meeting (its training, its
// facilitator to change) or an SSA-informed plan (its verdict).
func detailDrawn(a *detailActivity) bool {
	d := rules.Detail
	switch {
	case in(d.ReturnedStatuses, a.status):
		return false
	}
	return true
}

func orText(v, fallback string) string {
	if v == "" {
		return fallback
	}
	return v
}

// detailFacts are the drawer's four facts.
func detailFacts(a *detailActivity) []*screensv1.PageFact {
	place := "—"
	switch {
	case a.schoolID != "" && a.hasSchool:
		place = a.schoolName + " (ID: " + pyNone(a.schoolCode) + ")"
	case a.clusterID != "" && a.hasCluster:
		place = a.clusterName
	}
	facts := []*screensv1.PageFact{
		{Label: "School or cluster", Value: place},
		{Label: "Planned date", Value: plannedWords(date(a.planned))},
		// {{ act.responsible_staff_name|default:"CCEO User" }}: the activity
		// has no such attribute (the view's name is in the context, not on
		// act), so the drawer always reads the default.
		{Label: "Responsible", Value: responsible(a)},
	}
	if training := a.trainingFact(); training != "" {
		facts = append(facts, &screensv1.PageFact{Label: "Training", Value: training})
	}
	return append(facts, &screensv1.PageFact{Label: "Intervention focus", Value: strings.ReplaceAll(orText(a.focus, "General"), "_", " ")})
}

// responsible is the Responsible fact; a partner's work says the officer
// monitors it.
func responsible(a *detailActivity) string {
	if a.delivery == "partner" {
		return "CCEO User (partner monitored)"
	}
	return "CCEO User"
}

// overview is the Overview tab: purpose, expected outcome, the workflow
// and, for live work the reader may run, Cancel.
func (s *Service) overview(ctx context.Context, p auth.Principal, scope schooldirectory.Scope, a *detailActivity) ([]*screensv1.PageBlock, error) {
	by, err := facilitatedBy(ctx, s.db, a)
	if err != nil {
		return nil, err
	}
	label := detailStatus(a, s.now())
	ia := "None"
	if a.ia != nil {
		ia = *a.ia
	}
	blocks := []*screensv1.PageBlock{
		panel("", heading("Purpose"), text(orText(a.purpose, "No purpose description text entered."))),
		panel("", heading("Expected outcome"), text(orText(a.outcome, "No expected outcome text entered."))),
		panel("", heading("Workflow"), text("Status"), text(label), text("IA status"), text(ia),
			text("Rescheduled"), text(fmt.Sprintf("%d times", a.reschedules)), text("Facilitated by"), facilitatorItem(a, by)),
	}
	cancel, err := mayCancel(ctx, s.db, p, scope, a)
	if err != nil {
		return nil, err
	}
	if cancel {
		blocks = append(blocks, panel("",
			text("Not going ahead? It stays on the record as Cancelled and its cost is withdrawn."),
			&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
				{Text: "Cancel activity", Href: "/my-plan/" + a.id + "/cancel-drawer", Drawer: true},
			}}}}))
	}
	return blocks, nil
}

// finance is the Finance tab and the segments' subtitle (the table's
// total, when there is a table).
func (s *Service) finance(ctx context.Context, a *detailActivity, staff string) ([]*screensv1.PageBlock, string, error) {
	snap, err := readCostSnapshot(ctx, s.db, a.id)
	if err != nil {
		return nil, "", err
	}
	cost, err := s.activityCost(ctx, a, snap)
	if err != nil {
		return nil, "", err
	}
	lines, err := readCostLines(ctx, s.db, []string{a.id})
	if err != nil {
		return nil, "", err
	}
	acts, err := readActivities(ctx, s.db, []string{a.id})
	if err != nil {
		return nil, "", err
	}
	notes, err := pairNotes(ctx, s.db, acts, lines)
	if err != nil {
		return nil, "", err
	}
	if staff == "Unknown Staff" {
		staff = ""
	}
	b, err := budgetOf(ctx, s.db, a, snap, staff, notes[a.id])
	if err != nil {
		return nil, "", err
	}
	value := "Not configured"
	if cost.amount != nil {
		value = money(*cost.amount)
	}
	strip := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
		Title:   "Performance overview",
		Metrics: []*screensv1.PageMetric{{Label: cost.label, Value: value, Note: cost.note}},
	}}}
	if len(b.rows) == 0 {
		return []*screensv1.PageBlock{strip, panel("Budget breakdown"), panel("", text(b.emptyNote))}, "", nil
	}
	total := "Total " + money(b.total)
	return []*screensv1.PageBlock{strip, {Kind: &screensv1.PageBlock_Table{Table: b.table(total)}}}, total, nil
}

// table is the budget table.
func (b budgetBreakdown) table(total string) *screensv1.PageTable {
	columns := []*screensv1.PageColumn{{Label: "Cost item"}, {Label: "Amount", Numeric: true}}
	if b.showMinimum {
		columns = append(columns, &screensv1.PageColumn{Label: "Minimum viable", Numeric: true})
	}
	columns = append(columns, &screensv1.PageColumn{Label: "How it is worked out"}, &screensv1.PageColumn{Label: "Funding status"})
	var rows []*screensv1.PageRow
	for _, r := range b.rows {
		cells := []*screensv1.PageCell{{Text: r.label}, {Text: money(r.amount)}}
		if b.showMinimum {
			cells = append(cells, &screensv1.PageCell{Text: money(r.minimum)})
		}
		cells = append(cells, &screensv1.PageCell{Text: r.basis}, &screensv1.PageCell{Text: r.status})
		rows = append(rows, &screensv1.PageRow{Cells: cells})
	}
	last := []*screensv1.PageCell{{Text: "Total", Strong: true}, {Text: money(b.total), Strong: true}}
	if b.showMinimum {
		last = append(last, &screensv1.PageCell{Text: money(b.minimumTotal), Strong: true})
	}
	last = append(last, &screensv1.PageCell{})
	rows = append(rows, &screensv1.PageRow{Cells: last})
	return &screensv1.PageTable{Title: "Budget breakdown", Subtitle: total, Columns: columns, Rows: rows, Footnote: b.footnote()}
}

// detailStatus is the Status pill's words, read on the local day
// (date.today() in the view) as My Plan's rows read them.
func detailStatus(a *detailActivity, now time.Time) string {
	y, m, d := now.In(kampala).Date()
	sf := a.salesforce
	return statusLabel(&activity{status: a.status, salesforce: &sf, plannedDate: a.planned, rescheduleCount: a.reschedules}, time.Date(y, m, d, 0, 0, 0, 0, time.UTC))
}

// facilitatorItem is who facilitates it and, where the officer may change
// that, the Change button beside the name.
func facilitatorItem(a *detailActivity, by string) *screensv1.PagePanelItem {
	if !a.mayChangeFacilitator() {
		return text(by)
	}
	item := text(by + " Change")
	item.TextLinks = []*screensv1.PageLink{{Text: "Change", Href: "/activities/" + a.id + "/facilitator", Drawer: true}}
	return item
}

func panel(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
}

func heading(s string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: s}}
}

func text(s string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: s}}
}
