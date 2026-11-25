package planningoversight

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// DetailPath is oversight_detail_view's address.
const DetailPath = "/team-planning-oversight/detail"

// ErrDetailHandOn is a detail drawer Go does not draw yet: the existing
// application draws it.
var ErrDetailHandOn = errors.New("planningoversight: the detail drawer is handed on")

// DetailRefusal is require_any_page_permission's answer, naming the first
// page it asks for.
const DetailRefusal = "Access Denied: Your active role does not have permission to view Team Planning Oversight."

// costPageSize is the cost table's page (TABLE_PAGE_SIZE): more lines page,
// which Go does not draw.
const costPageSize = 50

// notAvailable is the drawer for an item outside the reader's lens or gone.
var notAvailable = &screensv1.PageDrawer{Title: "Not available", HasRequired: true, CancelLabel: "Cancel",
	Items: []*screensv1.DrawerItem{drawerText("This record is not in your scope, or no longer exists.")}}

func drawerText(s string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: s}}
}

func drawerHeading(s string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Heading{Heading: s}}
}

func drawerFacts(facts ...[2]string) *screensv1.DrawerItem {
	out := []*screensv1.PageFact{}
	for _, f := range facts {
		out = append(out, &screensv1.PageFact{Label: f[0], Value: f[1]})
	}
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: out}}}
}

// Detail is oversight_detail_view as the feed reads it: one activity's
// ownership, planning, cost lines and workflow state, for a reader whose
// lens holds it. Drawn for a Programme Lead's team lens and the country
// lens, and for the team's own (staff) work: its risks for a country
// reader, none for a Lead (a risk's Send form, Partner work, a hand-over, a
// region's lens and anyone else are handed on, ErrDetailHandOn). refusal is the view's own refusal.
func (s *Service) Detail(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.PageDrawer, string, error) {
	if !pageaccess.CanOpen(p.ActiveRole, false, DetailPath) {
		return nil, DetailRefusal, nil
	}
	reader, ok := rules.TeamPlan.Readers[p.ActiveRole]
	if !ok || p.Acting != nil || p.InActingAppointment || (reader.Scope != "country" && reader.Scope != "pl") ||
		(reader.Scope == "pl" && p.ActiveRole != rules.TeamPlan.LeadRole) {
		return nil, "", ErrDetailHandOn
	}
	activityID := strings.TrimSpace(query.Get("activity_id"))
	if activityID == "" {
		if strings.TrimSpace(query.Get("assignment_id")) != "" {
			return nil, "", ErrDetailHandOn
		}
		return notAvailable, "", nil
	}
	now := s.now()
	var team []string
	if reader.Scope == "pl" {
		scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
		if err != nil {
			return nil, "", err
		}
		own, err := partneroversight.BothIDSpaces(ctx, s.db, []string{p.UserID, p.StaffProfileID})
		if err != nil {
			return nil, "", err
		}
		supervised, err := partneroversight.BothIDSpaces(ctx, s.db, scope.SupervisedStaffIDs)
		if err != nil {
			return nil, "", err
		}
		team = append(append([]string{}, own...), supervised...)
		if len(team) == 0 {
			// The lens's own rule: a Lead with no ids reads nothing.
			team = []string{""}
		}
	}
	a, err := s.readOneAct(ctx, activityID, team)
	if err != nil {
		return nil, "", err
	}
	if a == nil {
		return notAvailable, "", nil
	}
	if a.isPartner() {
		return nil, "", ErrDetailHandOn
	}
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	it, err := s.oneItem(ctx, a)
	if err != nil {
		return nil, "", err
	}
	risks := risksFor(it, today)
	if hasRisk(it, today) != (len(risks) > 0) {
		return nil, "", ErrDetailHandOn
	}
	// The Lead may send each risk to the one answerable for it (a person
	// through the school's assignment, or a role's queue); the country lens
	// sends nothing (can_send).
	canSend := reader.Scope == "pl" && reader.MayDelegate
	var handedOver bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM partner_assignment WHERE scheduled_activity_id = $1)`,
		a.id).Scan(&handedOver); err != nil {
		return nil, "", fmt.Errorf("planningoversight: the activity's hand-over: %w", err)
	}
	if handedOver {
		return nil, "", ErrDetailHandOn
	}
	lines, err := s.costLines(ctx, a.id)
	if err != nil {
		return nil, "", err
	}
	if len(lines) > costPageSize {
		return nil, "", ErrDetailHandOn
	}
	d, err := s.detailDrawer(ctx, it, lines, reader.OpenActivity && p.ActiveRole != "Accountant")
	if err != nil || len(risks) == 0 {
		return d, "", err
	}
	return withRisks(d, risks, canSend, it.schoolPK != ""), "", nil
}

// withRisks puts the record's risks above the drawer, as the feed reads
// them. A risk the reader may send (canSend, and to a person a school is
// needed; a role's queue needs none) carries a Send form. The
// feed reads a drawer whose one form that is as the form alone (its note,
// the risk's action as the help); with several forms it reads the whole
// drawer, each sendable risk followed by its button's words, and offers the
// first form's button. The send itself is the existing application's.
func withRisks(d *screensv1.PageDrawer, risks []risk, canSend, hasSchool bool) *screensv1.PageDrawer {
	sendable := func(r risk) bool { return canSend && (hasSchool || r.role != "") }
	forms := []risk{}
	for _, r := range risks {
		if sendable(r) {
			forms = append(forms, r)
		}
	}
	button := func(r risk) string { return "Send to " + first(r.owner, "the owner") }
	if len(forms) == 1 {
		return &screensv1.PageDrawer{Title: d.Title, Subtitle: d.Subtitle, HasRequired: true, CancelLabel: "Cancel",
			SubmitLabel: button(forms[0]), CanSubmit: true, Items: []*screensv1.DrawerItem{{Kind: &screensv1.DrawerItem_Field{
				Field: &screensv1.DrawerField{Name: "note", Label: "Note for the recipient", Kind: "text", Help: forms[0].action,
					Placeholder: "Add a note (optional)"}}}}}
	}
	attention := []*screensv1.DrawerItem{drawerHeading("Needs attention")}
	for _, r := range risks {
		// Each risk's three lines, read as one.
		line := r.action + " " + r.reason + " Owner: " + first(r.owner, "Unassigned")
		if r.due != nil {
			line += " · Due " + r.due.Format("2 Jan 2006")
		}
		if sendable(r) {
			line += " " + button(r)
		}
		attention = append(attention, drawerText(line))
	}
	d.Items = append(attention, d.Items...)
	if len(forms) > 0 {
		d.SubmitLabel, d.CanSubmit = button(forms[0]), true
	}
	return d
}

// readOneAct is build_item_by_reference's activity, if record_in_scope lets
// the lens read it (team nil for the country).
func (s *Service) readOneAct(ctx context.Context, id string, team []string) (*act, error) {
	rows, err := s.db.Query(ctx, `SELECT `+actColumns+actJoins+`
WHERE a.id = $1 AND a.deleted_at IS NULL
  AND ($2::text[] IS NULL OR a.responsible_staff_id = ANY($2) OR a.monitored_by_staff_id = ANY($2)
       OR s.account_owner_id = ANY($2) OR c.responsible_staff_id = ANY($2))`, id, team)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the activity: %w", err)
	}
	acts, err := scanActs(rows)
	if err != nil || len(acts) == 0 {
		return nil, err
	}
	return acts[0], nil
}

// oneItem is _activity_item for one activity, through the same build the
// lens's rows use.
func (s *Service) oneItem(ctx context.Context, a *act) (*item, error) {
	names, err := s.staffNames(ctx, []string{a.responsible, a.monitored})
	if err != nil {
		return nil, err
	}
	costs, err := s.costs(ctx, []string{a.id})
	if err != nil {
		return nil, err
	}
	live, err := s.liveCompanions(ctx, []*act{a})
	if err != nil {
		return nil, err
	}
	fixed, err := s.fixedInterventions(ctx)
	if err != nil {
		return nil, err
	}
	outside, err := visitgate.ProjectsOutsideSSA(ctx, s.db, schoolprofile.GateRules())
	if err != nil {
		return nil, err
	}
	it := buildItem(a, names, costs, live, fixed, outside)
	if err := s.stampLeads(ctx, []*item{it}); err != nil {
		return nil, err
	}
	return it, nil
}

// costLine is one ActivityScheduleCostLine.
type costLine struct {
	label                  string
	version                int64
	unit, quantity, amount int64
}

// costLines are the activity's cost lines in the order they were written.
func (s *Service) costLines(ctx context.Context, activityID string) ([]costLine, error) {
	rows, err := s.db.Query(ctx, `SELECT COALESCE(label, ''), COALESCE(cost_setting_version, 0)::bigint, COALESCE(unit_cost, 0)::bigint,
  COALESCE(quantity, 0)::bigint, COALESCE(amount, 0)::bigint
FROM activity_schedule_cost_line WHERE activity_id = $1 ORDER BY created_at, id`, activityID)
	if err != nil {
		return nil, fmt.Errorf("planningoversight: reading the cost lines: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (costLine, error) {
		var l costLine
		err := r.Scan(&l.label, &l.version, &l.unit, &l.quantity, &l.amount)
		return l, err
	})
}

// detailDrawer is partials/oversight/detail_drawer.html for a staff item
// with no risk, as the feed reads it.
func (s *Service) detailDrawer(ctx context.Context, it *item, lines []costLine, openRecord bool) (*screensv1.PageDrawer, error) {
	a := it.a
	planner := first(a.responsible, a.monitored)
	people, err := s.staffNames(ctx, []string{planner, it.owner, it.lead})
	if err != nil {
		return nil, err
	}
	role, err := s.activeRole(ctx, planner)
	if err != nil {
		return nil, err
	}
	plannedBy := first(people[planner].name, "—")
	if role != "" {
		plannedBy += " (" + role + ")"
	}
	ownerName := people[it.owner].name
	lead := "Unassigned"
	if it.lead != "" {
		lead = first(people[it.lead].name, "Unassigned")
	}
	planned := "Not scheduled"
	if it.plannedDate != nil {
		planned = it.plannedDate.Format("2 Jan 2006")
	}
	fy := "FY " + first(a.fy, "—")
	if q, err := s.quarterOf(ctx, a.id); err != nil {
		return nil, err
	} else if q != "" {
		fy += " · " + q
	}
	title := capFirst(strings.ReplaceAll(it.activityType, "_", " "))
	if title == "" {
		title = "Partner assignment"
	}
	items := []*screensv1.DrawerItem{
		drawerHeading("Ownership"),
		drawerFacts([2]string{"Planned by", plannedBy}, [2]string{"Operational owner", first(ownerName, "—")},
			[2]string{"Executor", first(ownerName, "—") + " (staff)"}, [2]string{"Managing staff", "—"},
			[2]string{"Supervising PL", lead}, [2]string{"Partner", "—"}),
		drawerHeading("Planning"),
		drawerFacts([2]string{"Planned date", planned}, [2]string{"Financial year", fy}, [2]string{"Assigned", "—"},
			[2]string{"Intervention", first(djangoTitle(strings.ReplaceAll(it.intervention, "_", " ")), "—")},
			[2]string{"Rationale", first(it.rationale, "—")}),
		drawerHeading("Cost lineage"),
	}
	if len(lines) == 0 {
		items = append(items, drawerText("No cost lines. This activity cannot enter a fund request until it is priced."))
	} else {
		table := &screensv1.PageTable{}
		for _, l := range []string{"Line", "Unit", "Qty", "Amount"} {
			table.Columns = append(table.Columns, &screensv1.PageColumn{Label: l})
		}
		for _, l := range lines {
			label := l.label
			if l.version != 0 {
				label += " v" + strconv.FormatInt(l.version, 10)
			}
			row := &screensv1.PageRow{}
			for _, t := range []string{label, "UGX " + intcomma(l.unit), strconv.FormatInt(l.quantity, 10), "UGX " + intcomma(l.amount)} {
				row.Cells = append(row.Cells, &screensv1.PageCell{Text: t})
			}
			table.Rows = append(table.Rows, row)
		}
		// The table's footer (the total) is not read by the feed.
		items = append(items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Block{Block: &screensv1.PageBlock{
			Kind: &screensv1.PageBlock_Table{Table: table}}}})
	}
	salesforce := "Missing"
	if a.salesforce != "" {
		salesforce = "Recorded"
	}
	items = append(items, drawerHeading("Workflow state"),
		drawerFacts([2]string{"Activity", first(djangoTitle(strings.ReplaceAll(a.status, "_", " ")), "—")},
			[2]string{"Salesforce", salesforce},
			[2]string{"Impact Assessment", first(djangoTitle(strings.ReplaceAll(a.ia, "_", " ")), "—")},
			[2]string{"Finance", first(djangoTitle(strings.ReplaceAll(a.payment, "_", " ")), "—")},
			[2]string{"Reschedules", strconv.FormatInt(a.reschedules, 10)}))
	if openRecord {
		// The link reads as its words.
		items = append(items, drawerText("Open the full activity record"))
	}
	return &screensv1.PageDrawer{Title: title, Subtitle: it.contextLabel(), HasRequired: true, CancelLabel: "Cancel", Items: items}, nil
}

// activeRole is _StaffDirectory.role: the active role of the account behind
// a staff profile or user id.
func (s *Service) activeRole(ctx context.Context, id string) (string, error) {
	if id == "" {
		return "", nil
	}
	var role string
	err := s.db.QueryRow(ctx, `SELECT COALESCE(u.active_role, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.id = $1 OR sp.user_id = $1 ORDER BY sp.id LIMIT 1`, id).Scan(&role)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("planningoversight: the planner's role: %w", err)
	}
	return role, nil
}

// quarterOf is the activity's stored quarter.
func (s *Service) quarterOf(ctx context.Context, id string) (string, error) {
	var q string
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(quarter, '') FROM activity WHERE id = $1`, id).Scan(&q); err != nil {
		return "", fmt.Errorf("planningoversight: the activity's quarter: %w", err)
	}
	return q, nil
}

// capFirst is Django's |capfirst: the first character upper-cased.
func capFirst(s string) string {
	if s == "" {
		return s
	}
	r := []rune(s)
	return strings.ToUpper(string(r[0])) + string(r[1:])
}

// djangoTitle is Django's |title: str.title(), then a letter after an
// apostrophe and one after a digit kept lower case.
func djangoTitle(s string) string {
	t := titleApostrophe.ReplaceAllStringFunc(pyTitle(s), strings.ToLower)
	return titleDigit.ReplaceAllStringFunc(t, strings.ToLower)
}

var (
	titleApostrophe = regexp.MustCompile(`[a-z]'[A-Z]`)
	titleDigit      = regexp.MustCompile(`\d[A-Z]`)
)
