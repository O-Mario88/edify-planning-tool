package planningmonitor

// Country Planning Oversight's drawers (country_oversight_views.drawer_view)
// as the feed reads them: a planning card opened (drawer_kpi.html), a
// Programme Lead (drawer_lead.html), a person or one Partner's share of
// their schools (drawer_owner.html), and the year's follow-ups when none is
// open (drawer_followups.html). A drawer listing open follow-ups, a list
// longer than one page, and Impact Assessment's data-quality queue are
// handed on.

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// CPODrawerPath is the drawers' path.
const CPODrawerPath = cpoPath + "drawer"

// ErrCPODrawerNotFound is the view's 404: a card, Lead or person the
// snapshot does not hold.
var ErrCPODrawerNotFound = errors.New("planningmonitor: no such Country Planning Oversight drawer")

// cpoDrawerPage is DRAWER_PAGE_SIZE: a drawer's list a page at a time.
const cpoDrawerPage = 50

// CountryOversightDrawer is drawer_view for the kinds Go draws; served is
// false for one it hands on.
func CountryOversightDrawer(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string,
	now time.Time) (*screensv1.PageDrawer, bool, error) {
	switch strings.TrimSpace(q["kind"]) {
	case "kpi":
		d, err := cpoKPIDrawer(ctx, db, p, q, now)
		if errors.Is(err, errCPOHandOn) {
			return nil, false, nil
		}
		return d, true, err
	case "followups":
		return cpoFollowUpsDrawer(ctx, db, q, now)
	case "lead", "owner", "partner":
		d, err := cpoPersonDrawer(ctx, db, p, q, now)
		if errors.Is(err, errCPOHandOn) {
			return nil, false, nil
		}
		return d, true, err
	}
	return nil, false, nil
}

func dText(s string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: s}}
}

func dHeading(s string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Heading{Heading: s}}
}

// cpoKPIDrawer is drawer_kpi.html: the card's figures and lines, each
// Programme Lead's share, and the schools behind its gap (loaded by the
// browser, so the feed reads its placeholder).
func cpoKPIDrawer(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string,
	now time.Time) (*screensv1.PageDrawer, error) {
	page := rules.CountryOversight.Page
	metric := strings.TrimSpace(q["metric"])
	gap, ok := page.KPIGaps[metric]
	if !ok {
		return nil, ErrCPODrawerNotFound
	}
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	f := cpoReadFilters(q, today)
	snap, err := buildCPOSnapshot(ctx, db, scope, f, today)
	if err != nil {
		return nil, err
	}
	if len(snap.tree.leads) > cpoDrawerPage {
		return nil, errCPOHandOn
	}
	country, err := cpoCountry(ctx, db, scope)
	if err != nil {
		return nil, err
	}
	var card cpoCard
	for _, c := range cpoCardList(snap) {
		if c.key == metric {
			card = c
		}
	}
	w := snap.tree.window
	subtitle := country + " · " + cpoFYLabel(w.fy)
	if !w.isAnnual() {
		subtitle += " · " + w.label()
	}
	items := []*screensv1.DrawerItem{
		dText(cpoFmt(card.part) + " / " + cpoFmt(card.whole) + " " + pct(card.part, card.whole)),
		dText(page.KPIDefinitions[metric]),
	}
	if len(card.extras) > 0 {
		items = append(items, dText(strings.Join(card.extras, " · ")))
	}
	for _, line := range card.more {
		items = append(items, dText(line))
	}
	if card.note != "" {
		items = append(items, dText(card.note))
	}
	items = append(items, dHeading("By Programme Lead"), cpoLeadShares(snap))
	if !scope.SummaryOnly {
		items = append(items, dHeading("Schools: "+strings.ToLower(page.GapFigures[gap])), dText("Reading the schools…"))
	}
	return &screensv1.PageDrawer{Title: page.KPILabels[metric], Subtitle: subtitle, HasRequired: true, CancelLabel: "Cancel",
		Items: items}, nil
}

// errCPOHandOn is a drawer Go reads but does not draw (a list longer than
// one page).
var errCPOHandOn = errors.New("planningmonitor: the drawer is handed on")

// cpoLeadShares is the card drawer's table: each Programme Lead's figures.
func cpoLeadShares(snap *cpoSnapshot) *screensv1.DrawerItem {
	columns := []*screensv1.PageColumn{}
	for _, c := range []string{"Programme Lead", "Visits planned", "Assigned to Partners", "Partner planned", "Portfolio",
		"Schools planned", "Training", "Clustered", "Meetings"} {
		columns = append(columns, &screensv1.PageColumn{Label: c})
	}
	of := func(t cpoTally, a, b string) string { return cpoFmt(t.n(a)) + " / " + cpoFmt(t.n(b)) }
	rows := []*screensv1.PageRow{}
	for _, lead := range snap.tree.leads {
		t := cpoTally(lead.tally)
		cells := []string{lead.name, of(t, "p_visits", "target"), cpoFmt(t.n("pa_work")), cpoFmt(t.n("pp_work")), cpoFmt(t.n("schools")),
			of(t, "any_visit", "visit_schools"), of(t, "training", "training_slots"),
			strconv.Itoa(t.n("clustered")) + " / " + strconv.Itoa(t.n("schools")), of(t, "meeting_covered_clustered", "clustered")}
		row := &screensv1.PageRow{}
		for _, c := range cells {
			row.Cells = append(row.Cells, &screensv1.PageCell{Text: c})
		}
		rows = append(rows, row)
	}
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Block{Block: &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{
		Table: &screensv1.PageTable{Columns: columns, Rows: rows}}}}}
}

// cpoFollowUpsDrawer is drawer_followups.html for a year with nothing to
// list; a register with follow-ups in it is handed on.
func cpoFollowUpsDrawer(ctx context.Context, db schooldirectory.Querier, q map[string]string,
	now time.Time) (*screensv1.PageDrawer, bool, error) {
	l := now.In(cpoLocation)
	f := cpoReadFilters(q, date(l.Year(), l.Month(), l.Day()))
	show := strings.TrimSpace(q["show"])
	if show == "" {
		show = "open"
	}
	where := `fy = $1`
	args := []any{f.fy}
	if show == "open" {
		where += ` AND status = ANY($2)`
		args = append(args, rules.CountryOversight.Page.FollowUpOpenStates)
	}
	var any bool
	if err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM planning_oversight_follow_up WHERE `+where+`)`, args...).Scan(&any); err != nil {
		return nil, true, err
	}
	if any {
		return nil, false, nil
	}
	subtitle, empty := cpoFYLabel(f.fy)+" · open", "No follow-up is open for this year."
	if show != "open" {
		subtitle, empty = cpoFYLabel(f.fy)+" · all this year", "No follow-up has been sent this year."
	}
	return &screensv1.PageDrawer{Title: "Follow-ups", Subtitle: subtitle, HasRequired: true, CancelLabel: "Cancel",
		Items: []*screensv1.DrawerItem{dText(empty)}}, true, nil
}

// cpoDrawerRead is what a person's drawer reads: the snapshot, the reader's
// rights, and the subtitle's period.
type cpoDrawerRead struct {
	snap                  *cpoSnapshot
	followUp, seesSchools bool
	period, portfolioAsOf string
}

func cpoReadDrawer(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string,
	now time.Time) (cpoDrawerRead, error) {
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return cpoDrawerRead{}, err
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	snap, err := buildCPOSnapshot(ctx, db, scope, cpoReadFilters(q, today), today)
	if err != nil {
		return cpoDrawerRead{}, err
	}
	w := snap.tree.window
	period := cpoFYLabel(w.fy)
	if !w.isAnnual() {
		period += " · " + w.label()
	}
	return cpoDrawerRead{snap: snap, followUp: cpoReaderFor(p.ActiveRole, false).followUp, seesSchools: !scope.SummaryOnly,
		period: period, portfolioAsOf: snap.data.asOf.Format("2 Jan 2006")}, nil
}

// cpoPersonDrawer is drawer_lead.html and drawer_owner.html.
func cpoPersonDrawer(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string,
	now time.Time) (*screensv1.PageDrawer, error) {
	r, err := cpoReadDrawer(ctx, db, p, q, now)
	if err != nil {
		return nil, err
	}
	kind, key := strings.TrimSpace(q["kind"]), strings.TrimSpace(q["key"])
	if kind == "lead" {
		for _, lead := range r.snap.tree.leads {
			if lead.key == key {
				return cpoLeadDrawer(ctx, db, r, lead)
			}
		}
		return nil, ErrCPODrawerNotFound
	}
	for _, lead := range r.snap.tree.leads {
		for _, owner := range lead.owners {
			if owner.key == key {
				return cpoOwnerDrawer(ctx, db, r, lead, owner, kind, strings.TrimSpace(q["partner_key"]))
			}
		}
	}
	return nil, ErrCPODrawerNotFound
}

// cpoLeadDrawer is drawer_lead.html. For the Director it holds one form,
// the team asks, which the feed reads alone; for every other reader, the
// Lead's figures, gaps, people and follow-ups.
func cpoLeadDrawer(ctx context.Context, db schooldirectory.Querier, r cpoDrawerRead, lead *cpoLeadRow) (*screensv1.PageDrawer, error) {
	d := &screensv1.PageDrawer{Title: lead.name, Subtitle: "Programme Lead · " + r.period + " · portfolio as of " + r.portfolioAsOf,
		HasRequired: true, CancelLabel: "Cancel"}
	t := cpoTally(lead.tally)
	issues := cpoIssueMenu(t)
	if r.followUp && !lead.noLead && len(issues) > 0 {
		d.Items = []*screensv1.DrawerItem{{Kind: &screensv1.DrawerItem_Field{Field: &screensv1.DrawerField{Name: "issue",
			Label: "What to ask for", Kind: "select", Value: "team_execution_risk", Help: issues[0].Label,
			Options: []*screensv1.DrawerOption{{Value: "team_execution_risk", Label: "Recovery plan"},
				{Value: "team_partner_backlog", Label: "Partner backlog"}, {Value: "team_costing_backlog", Label: "Costing backlog"}}}}}}
		d.SubmitLabel, d.CanSubmit = "Send", true
		return d, nil
	}
	if len(lead.owners) == 0 || len(lead.owners) > cpoDrawerPage {
		return nil, errCPOHandOn
	}
	open, err := cpoScopeHasOpenFollowUps(ctx, db, r.snap.filters.fy, lead.key, "")
	if err != nil || open {
		return nil, errOr(err, errCPOHandOn)
	}
	items := []*screensv1.DrawerItem{dHeading("Figures"), cpoFigures(t), dHeading("Gaps")}
	items = append(items, cpoGapLines(t, issues, r.followUp)...)
	items = append(items, dHeading("People"), cpoPeopleTable(lead))
	if r.seesSchools {
		items = append(items, dHeading("Schools"), dText("Reading the schools…"))
	}
	items = append(items, dHeading("Open follow-ups"), dText("No open follow-up."))
	if !lead.noLead {
		items = append(items, dText("Country Plan (activities) Planning Oversight Country Portfolio"))
	}
	d.Items = items
	return d, nil
}

// cpoOwnerDrawer is drawer_owner.html: one person, or (kind "partner") one
// Partner's share of the schools they hold.
func cpoOwnerDrawer(ctx context.Context, db schooldirectory.Querier, r cpoDrawerRead, lead *cpoLeadRow, owner *cpoOwnerRow,
	kind, partner string) (*screensv1.PageDrawer, error) {
	tally := cpoTally(owner.tally)
	title, subtitle := owner.name, ""
	if kind == "partner" {
		held, ok := owner.partners[partner]
		if !ok {
			return nil, ErrCPODrawerNotFound
		}
		tally = cpoTally(held)
		title = "Staff delivery"
		if partner != cpoNoPartnerKey {
			names, err := cpoNames(ctx, db, "partner", []string{partner})
			if err != nil {
				return nil, err
			}
			title = ""
			for _, n := range names {
				if n.value == partner {
					title = n.label
				}
			}
		}
		subtitle = "Partner working " + owner.name + "'s schools"
	} else {
		partner = ""
		switch owner.kind {
		case "pl_personal":
			subtitle = "Programme Lead · own plan and schools"
		case "unassigned":
			subtitle = "Schools no one holds"
		default:
			// The Lead the row sits under, the No Programme Lead row too.
			subtitle = orElse(owner.role, "Holder") + " · reports to " + lead.name
		}
	}
	open, err := cpoScopeHasOpenFollowUps(ctx, db, r.snap.filters.fy, lead.key, map[bool]string{true: "", false: owner.key}[owner.kind == "pl_personal"])
	if err != nil || open {
		return nil, errOr(err, errCPOHandOn)
	}
	d := &screensv1.PageDrawer{Title: title, Subtitle: subtitle + " · " + r.period, HasRequired: true, CancelLabel: "Cancel"}
	items := []*screensv1.DrawerItem{}
	if partner == "" && owner.kind != "unassigned" {
		items = append(items, dHeading("Staff capacity"), cpoCapacity(owner, tally))
	}
	items = append(items, dHeading("Figures"), cpoFigures(tally), dHeading("Gaps"))
	noLead, noOwner := rules.CountryOversight.NoLead[0], rules.CountryOversight.NoOwner[0]
	here := !lead.noLead && lead.key != noLead && owner.key != noOwner
	items = append(items, cpoGapLines(tally, cpoIssueMenu(tally), r.followUp && here)...)
	if !here {
		items = append(items, dText("These schools have no Programme Lead to follow up with. Place their holder under a Programme Lead, "+
			"or give the schools an owner, first."))
	}
	if kind == "owner" && len(owner.assigned) > 0 {
		table, err := cpoPartnerShares(ctx, db, owner)
		if err != nil {
			return nil, err
		}
		items = append(items, dHeading("Partners this person assigned work to"), table,
			dText("Partner planning counts only what a Partner has dated. A school assigned and not yet dated is in the Partner's "+
				"hands, not planned."))
	}
	if r.seesSchools {
		items = append(items, dHeading("Schools"), dText("Reading the schools…"))
	}
	d.Items = append(items, dHeading("Open follow-ups"), dText("No open follow-up."))
	return d, nil
}

// cpoNoPartnerKey is NO_PARTNER_KEY: staff delivery's place among the
// Partners a person's schools are worked by.
const cpoNoPartnerKey = "__staff__"

func errOr(err, otherwise error) error {
	if err != nil {
		return err
	}
	return otherwise
}

// cpoScopeHasOpenFollowUps is whether _scoped_followups finds any open follow-up
// for the scope (the drawers draw only an empty list).
func cpoScopeHasOpenFollowUps(ctx context.Context, db schooldirectory.Querier, fy, lead, cceo string) (bool, error) {
	var any bool
	err := db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM planning_oversight_follow_up WHERE fy = $1 AND status = ANY($2)
  AND ($3 = '' OR program_lead_staff_id = $3) AND ($4 = '' OR cceo_staff_id = $4))`,
		fy, rules.CountryOversight.Page.FollowUpOpenStates, lead, cceo).Scan(&any)
	return any, err
}

// cpoIssueMenu is _issue_menu: the gaps a follow-up could be about.
func cpoIssueMenu(t cpoTally) []cpoIssueRule {
	out := []cpoIssueRule{}
	for _, i := range rules.CountryOversight.Page.FollowUpIssues {
		if i.Key != "school_gap" && i.Key != "other" {
			out = append(out, i)
		}
	}
	return out
}

// cpoGapLines is _gaps.html as the feed reads each gap: its name and live
// figure, and, where the reader may ask, the button's words.
func cpoGapLines(t cpoTally, issues []cpoIssueRule, ask bool) []*screensv1.DrawerItem {
	out := []*screensv1.DrawerItem{}
	for _, i := range issues {
		required, planned, remaining := i.metricValues(t)
		line := fmt.Sprintf("%s %d of %d · %d remaining", i.Label, planned, required, remaining)
		if ask && remaining > 0 {
			line += " Follow Up with PL"
		}
		out = append(out, dText(line))
	}
	return out
}

// cpoFact is a figure with its note run on, as the feed reads a dd and its
// small.
func cpoFact(label string, value int, note string) [2]string {
	return [2]string{label, strconv.Itoa(value) + note}
}

func cpoFacts(facts ...[2]string) *screensv1.DrawerItem {
	out := []*screensv1.PageFact{}
	for _, f := range facts {
		out = append(out, &screensv1.PageFact{Label: f[0], Value: f[1]})
	}
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: out}}}
}

// cpoFigures is _figures.html: a row's figures from its tally.
func cpoFigures(t cpoTally) *screensv1.DrawerItem {
	n := t.n
	facts := [][2]string{}
	if n("target") > 0 {
		note := ""
		if s, ok := share(n("p_visits"), n("target")); ok {
			note = strconv.Itoa(s) + "% of the target · "
		}
		facts = append(facts, [2]string{"Visits planned", fmt.Sprintf("%d / %d%s%d still to plan", n("p_visits"), n("target"), note,
			t.planRemaining())})
	}
	kinds := fmt.Sprintf("Follow up %d · In-school Training %d · SSA Support %d", n("p_follow_up"), n("p_in_school"), n("p_ssa"))
	if n("p_outreach") > 0 {
		kinds += fmt.Sprintf(" · %d donor, story and social not counted", n("p_outreach"))
	}
	portfolio := fmt.Sprintf("%d Core · %d Client · %d Core Trained · %d Core Graduate", n("core_schools"), n("client_schools"),
		n("core_trained_schools"), n("core_graduate_schools"))
	if n("champion_schools") > 0 {
		portfolio += fmt.Sprintf(" · %d Champion", n("champion_schools"))
	}
	visited := fmt.Sprintf("%d not yet planned", n("unplanned"))
	if t.partnerToPlan() > 0 {
		visited += fmt.Sprintf(" · %d awaiting a Partner's date", t.partnerToPlan())
	}
	if n("duplicates") > 0 {
		visited += fmt.Sprintf(" · %d planned twice", n("duplicates"))
	}
	facts = append(facts,
		cpoFact("By kind", n("p_visits"), kinds),
		cpoFact("Assigned to Partners", n("pa_work"), fmt.Sprintf("%d schools · %d dated by the Partner · %d awaiting", n("pa_schools"),
			n("pp_work"), t.partnerWaiting())),
		cpoFact("Portfolio", n("schools"), portfolio),
		[2]string{"Schools with a visit planned", fmt.Sprintf("%d / %d%s", n("any_visit"), n("visit_schools"), visited)},
		[2]string{"Visit slots", fmt.Sprintf("%d / %d%d by staff · %d dated by Partners · %d nobody holds", t.planned(), n("visit_slots"),
			n("staff"), n("partner_scheduled"), n("unallocated"))},
		cpoFact("In a Partner's hands", n("with_partner"), "schools held with any live Partner work"),
		[2]string{"Training", fmt.Sprintf("%d / %d%d schools planned · %d not yet · planned by this row: %d at schools, %d cluster",
			n("training"), n("training_slots"), n("any_training"), n("no_training"), n("p_trainings"), n("p_cluster_trainings"))},
		[2]string{"Clusters", fmt.Sprintf("%d / %d%d unclustered", n("clustered"), n("schools"), n("unclustered"))},
		[2]string{"Cluster meetings", fmt.Sprintf("%d / %d%d clustered with none · %d meetings planned by this row", n("meeting_covered"),
			n("schools"), n("clustered_no_meeting"), n("p_meetings"))},
		cpoFact("Verified so far", n("staff_verified")+n("partner_verified"), fmt.Sprintf("%d staff · %d Partner (not planned figures)",
			n("staff_verified"), n("partner_verified"))),
	)
	return cpoFacts(facts...)
}

// cpoReach is Tally.reach: the visits staff could plan at the schools
// held; cpoShortfall how far that falls short of the target.
func cpoReach(t cpoTally) int {
	return 2*t.n("core_schools") + t.n("client_schools") + t.n("core_trained_schools") + t.n("core_graduate_schools")
}

func cpoShortfall(t cpoTally) int {
	if t.n("target") == 0 {
		return 0
	}
	return max(0, t.n("target")-cpoReach(t))
}

// cpoCapacity is drawer_owner.html's Staff capacity.
func cpoCapacity(owner *cpoOwnerRow, t cpoTally) *screensv1.DrawerItem {
	role := "No target for this role"
	switch owner.kind {
	case "pl_personal":
		role = "Programme Lead"
	case "cceo":
		role = "CCEO"
	}
	reach := "2 per Core school, 1 per Client, Core Trained and Core Graduate school"
	if short := cpoShortfall(t); short > 0 {
		reach += fmt.Sprintf(" — %d short of the target", short)
	}
	deficit := "none"
	if t.n("deficit") > 0 {
		deficit = "visible until reassigned or resolved"
	}
	return cpoFacts(cpoFact("Visit target", owner.ceiling, role), cpoFact("Visits the schools held allow", cpoReach(t), reach),
		cpoFact("Core staff slots", t.n("core_staff_slots"), "2 per Core school — always required"),
		cpoFact("Client slots for staff", t.n("client_staff_expected"), "from the capacity left after Core"),
		cpoFact("Client slots for Partners", t.n("client_partner_expected"), "the balance of the Client, Core Trained and Core Graduate slots"),
		cpoFact("Internal capacity deficit", t.n("deficit"), deficit))
}

func cpoTableItem(columns []string, rows [][]string) *screensv1.DrawerItem {
	cols := []*screensv1.PageColumn{}
	for _, c := range columns {
		cols = append(cols, &screensv1.PageColumn{Label: c})
	}
	out := []*screensv1.PageRow{}
	for _, r := range rows {
		row := &screensv1.PageRow{}
		for _, c := range r {
			row.Cells = append(row.Cells, &screensv1.PageCell{Text: c})
		}
		out = append(out, row)
	}
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Block{Block: &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{
		Table: &screensv1.PageTable{Columns: cols, Rows: out}}}}}
}

// cpoPeopleTable is drawer_lead.html's People table (owner_rows).
func cpoPeopleTable(lead *cpoLeadRow) *screensv1.DrawerItem {
	rows := [][]string{}
	for _, o := range lead.owners {
		t := cpoTally(o.tally)
		plan := cpoFmt(t.n("p_visits"))
		if t.n("target") > 0 {
			plan += " / " + cpoFmt(t.n("target"))
		}
		rows = append(rows, []string{o.name, plan, cpoFmt(t.n("schools")), cpoFmt(t.n("any_visit")) + " / " + cpoFmt(t.n("visit_schools")),
			cpoFmt(t.n("pa_work")), cpoFmt(t.n("pp_work")), cpoFmt(t.n("training")) + " / " + cpoFmt(t.n("training_slots")),
			strconv.Itoa(cpoShortfall(t)), "View"})
	}
	return cpoTableItem([]string{"Name", "Visits planned", "Portfolio", "Schools planned", "Assigned to Partners", "Partner planned",
		"Training", "Schools short of target", "Action"}, rows)
}

// cpoPartnerShares is drawer_owner.html's Partners table (partner_rows):
// what the person assigned each Partner, by the Partner's name.
func cpoPartnerShares(ctx context.Context, db schooldirectory.Querier, owner *cpoOwnerRow) (*screensv1.DrawerItem, error) {
	if len(owner.assigned) > cpoDrawerPage {
		return nil, errCPOHandOn
	}
	ids := []string{}
	for pid := range owner.assigned {
		ids = append(ids, pid)
	}
	names, err := cpoNames(ctx, db, "partner", ids)
	if err != nil {
		return nil, err
	}
	name := map[string]string{}
	for _, n := range names {
		name[n.value] = n.label
	}
	label := func(pid string) string { return orElse(name[pid], pid) }
	sort.SliceStable(ids, func(i, j int) bool { return pyCasefold(label(ids[i])) < pyCasefold(label(ids[j])) })
	rows := [][]string{}
	for _, pid := range ids {
		t := cpoTally(owner.assigned[pid])
		view := "—"
		if _, ok := owner.partners[pid]; ok {
			view = "View"
		}
		rows = append(rows, []string{orElse(name[pid], "Unrecorded Partner"), cpoFmt(t.n("pa_schools")), cpoFmt(t.n("pa_work")),
			cpoFmt(t.n("pp_work")), strconv.Itoa(t.partnerWaiting()), view})
	}
	return cpoTableItem([]string{"Partner", "Schools assigned", "Work assigned", "Dated by the Partner", "Awaiting the Partner's date",
		"Action"}, rows), nil
}

// pyCasefold is str.casefold for the names it sorts.
func pyCasefold(s string) string { return strings.ToLower(s) }
