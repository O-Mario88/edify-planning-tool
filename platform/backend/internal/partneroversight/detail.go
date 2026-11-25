package partneroversight

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// DetailPath is partner_oversight_detail_view's address.
const DetailPath = "/partner-oversight/detail"

// DetailRefusal is require_page_permission("partner_oversight")'s answer.
const DetailRefusal = "Access Denied: Your active role does not have permission to view Partner Oversight."

// ErrDetailHandOn is a hand-over drawer Go does not draw yet.
var ErrDetailHandOn = errors.New("partneroversight: the hand-over drawer is handed on")

// detailCostPage is the cost table's page (TABLE_PAGE_SIZE).
const detailCostPage = 50

const notInScope = "This assignment is not in your scope, or no longer exists."

func dText(s string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: s}}
}

func dHeading(s string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Heading{Heading: s}}
}

func dFacts(facts ...[2]string) *screensv1.DrawerItem {
	out := []*screensv1.PageFact{}
	for _, f := range facts {
		out = append(out, &screensv1.PageFact{Label: f[0], Value: f[1]})
	}
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: out}}}
}

// Escalation is who a reader's Escalate reaches, in words ("" for none).
type Escalation func(ctx context.Context, userID, activeRole string) (string, error)

// Detail is partner_oversight_detail_view as the feed reads it: one
// hand-over's next action, its risks, the hand-over itself, its schedule,
// cost and verification, and, for a team reader, the Send and Escalate
// forms (whose saves stay the existing application's). An acting reader and
// a country whose roles come from the registry are handed on; refusal is
// the view's own.
func (s *Service) Detail(ctx context.Context, p auth.Principal, assignmentID string, escalation Escalation) (*screensv1.PageDrawer, string, error) {
	if !pageaccess.CanOpen(p.ActiveRole, false, DetailPath) {
		return nil, DetailRefusal, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || p.Acting != nil || p.InActingAppointment || (p.Country != nil && p.Country.FromRegistry()) {
		return nil, "", ErrDetailHandOn
	}
	notAvailable := &screensv1.PageDrawer{Title: "Not available", Subtitle: notInScope, HasRequired: true, CancelLabel: "Cancel",
		Items: []*screensv1.DrawerItem{dText(notInScope)}}
	if assignmentID == "" {
		return notAvailable, "", nil
	}
	now := s.now()
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	it, owners, err := singleItem(ctx, s.db, assignmentID)
	if err != nil || it == nil {
		return notAvailable, "", err
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, "", err
	}
	inScope := true
	switch role.Lens {
	case "region":
		inScope = len(scope.RegionIDs) > 0 && inRegions(ctx, s.db, assignmentID, scope.RegionIDs)
	case "team":
		team, err := bothIDSpaces(ctx, s.db, append([]string{p.UserID, p.StaffProfileID}, scope.SupervisedStaffIDs...))
		if err != nil {
			return nil, "", err
		}
		inScope = false
		for _, id := range owners {
			if id != "" && contains(team, id) {
				inScope = true
			}
		}
	case "country":
	default:
		return nil, "", ErrDetailHandOn
	}
	if !inScope {
		return notAvailable, "", nil
	}
	lines, version, err := detailCostLines(ctx, s.db, it.activityID)
	if err != nil {
		return nil, "", err
	}
	if len(lines) > detailCostPage {
		return nil, "", ErrDetailHandOn
	}
	canAct := role.Lens == "team"
	escalateTo := ""
	if canAct && escalation != nil {
		if escalateTo, err = escalation(ctx, p.UserID, p.ActiveRole); err != nil {
			return nil, "", err
		}
	}
	openRecord := it.activityID != "" && p.ActiveRole != "Accountant" && pageaccess.CanOpen(p.ActiveRole, false, "/activities/0")
	return detailDrawer(it, risksWithWords(it, today), lines, version, canAct, escalateTo, openRecord), "", nil
}

// inRegions is _assignment_team_q for a region: the hand-over's school or
// cluster in one of the regions.
func inRegions(ctx context.Context, db schooldirectory.Querier, id string, regions []string) bool {
	var ok bool
	_ = db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM partner_assignment pa LEFT JOIN school s ON s.id = pa.school_id
LEFT JOIN cluster c ON c.id = pa.cluster_id WHERE pa.id = $1 AND (s.region_id = ANY($2) OR c.region_id = ANY($2)))`, id, regions).Scan(&ok)
	return ok
}

// singleItem is build_item_by_assignment's item, unscoped, and the four ids
// the team lens reads it through (monitor, assigner, school owner, cluster
// owner).
func singleItem(ctx context.Context, db schooldirectory.Querier, id string) (*item, []string, error) {
	it := &item{assignmentID: id}
	var mon, assigner, owner, clusterOwner, activityID string
	var created time.Time
	err := db.QueryRow(ctx, `SELECT pa.status, COALESCE(pa.partner_id, ''), COALESCE(p.name, ''), COALESCE(pa.school_id, ''), COALESCE(s.name, ''),
  COALESCE(d.name, ''), COALESCE(s.account_owner_id, ''), COALESCE(pa.cluster_id, ''), COALESCE(c.name, ''), COALESCE(c.responsible_staff_id, ''),
  COALESCE(pa.monitoring_staff_id, ''), COALESCE(pa.assigning_staff_id, ''), COALESCE(pa.support_type, ''), COALESCE(pa.focus_intervention, ''),
  COALESCE(pa.project_id, ''), COALESCE(pa.return_reason_category, ''), COALESCE(pa.return_reason, ''), pa.created_at,
  COALESCE(pa.scheduled_activity_id, '')
FROM partner_assignment pa
LEFT JOIN partner p ON p.id = pa.partner_id
LEFT JOIN school s ON s.id = pa.school_id
LEFT JOIN district d ON d.id = s.district_id
LEFT JOIN cluster c ON c.id = pa.cluster_id
WHERE pa.id = $1`, id).Scan(&it.assignmentStatus, &it.partnerID, &it.partnerName, &it.schoolID, &it.schoolName, &it.district, &owner,
		&it.clusterID, &it.clusterName, &clusterOwner, &mon, &assigner, &it.supportType, &it.targetIntervention, &it.projectID,
		&it.returnReasonCategory, &it.returnReason, &created, &activityID)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil, nil
	}
	if err != nil {
		return nil, nil, fmt.Errorf("partneroversight: the hand-over: %w", err)
	}
	if it.targetIntervention == "" && it.projectID != "" {
		// intervention_or_general: General for a project outside the SSA,
		// which Go reads only with the project work it hands on.
		return nil, nil, ErrDetailHandOn
	}
	var a *activity
	if activityID != "" {
		acts, err := readActivities(ctx, db, `a.id = ANY($1)`, []string{activityID})
		if err != nil {
			return nil, nil, err
		}
		if len(acts) > 0 {
			a = acts[0]
		}
	}
	switch {
	case it.assignmentStatus == rules.ReturnedToStaff:
		it.stage = stageReturned
	case a != nil:
		it.stage = stageScheduled
	default:
		it.stage = stageAwaiting
	}
	dir, err := readDirectory(ctx, db, nonEmpty([]string{mon, assigner, owner, clusterOwner}))
	if err != nil {
		return nil, nil, err
	}
	cceo := first(mon, assigner, owner, clusterOwner)
	it.cceoID = cceo
	if c, ok := dir.canonical[cceo]; ok {
		it.cceoID = c
	}
	it.cceoName = dir.names[cceo]
	if sup, ok := dir.supervisor[it.cceoID]; ok {
		it.plID, it.plName = sup[0], sup[1]
	}
	day := dateOf(created.In(zone))
	it.assignmentDate = &day
	if a != nil {
		costs, err := readCosts(ctx, db, []string{a.id})
		if err != nil {
			return nil, nil, err
		}
		fill(it, a, costs)
		it.activityID = a.id
	}
	return it, []string{mon, assigner, owner, clusterOwner}, nil
}

// detailLine is one cost line of the drawer.
type detailLine struct {
	label                  string
	unit, quantity, amount int64
}

// detailCostLines are _partner_lineage's cost lines, in the order they were
// written, and the rate card version the activity was priced against
// (_cost_by_activity's first line's).
func detailCostLines(ctx context.Context, db schooldirectory.Querier, activityID string) ([]detailLine, string, error) {
	if activityID == "" {
		return nil, "", nil
	}
	rows, err := db.Query(ctx, `SELECT COALESCE(label, ''), COALESCE(unit_cost, 0)::bigint, COALESCE(quantity, 0)::bigint,
  COALESCE(amount, 0)::bigint, COALESCE(catalogue_version::text, '')
FROM activity_schedule_cost_line WHERE activity_id = $1 ORDER BY created_at, id`, activityID)
	if err != nil {
		return nil, "", fmt.Errorf("partneroversight: the cost lines: %w", err)
	}
	defer rows.Close()
	out := []detailLine{}
	version := ""
	for rows.Next() {
		var l detailLine
		var v string
		if err := rows.Scan(&l.label, &l.unit, &l.quantity, &l.amount, &v); err != nil {
			return nil, "", err
		}
		if len(out) == 0 {
			version = v
		}
		out = append(out, l)
	}
	return out, version, rows.Err()
}

// nextAction is _set_next_action: who the work waits on and what they do.
func nextAction(i *item) (string, string) {
	w := rules.Work
	partner := first(i.partnerName, "Partner")
	switch {
	case i.stage == stageReturned:
		return first(i.cceoName, "CCEO"), "Review the return and decide what happens next"
	case i.stage == stageAwaiting:
		return partner, "Schedule the assignment"
	case in(w.Complete, i.activityStatus):
		if i.paymentStatus == "" || i.paymentStatus == "none" || i.paymentStatus == "pending" {
			return "Accountant", "Pay the partner"
		}
		return "System", "Close the activity"
	case in(w.AwaitingIA, i.activityStatus):
		if !i.salesforceRecorded {
			return first(i.cceoName, "CCEO"), "Enter the Salesforce Activity ID"
		}
		return "Impact Assessment", "Verify the submission"
	case in(w.EvidenceReview, i.activityStatus):
		return partner, "Submit the evidence to IA"
	case i.evidenceStatus == "" || i.evidenceStatus == "none":
		return partner, "Execute and upload evidence"
	}
	return partner, "Continue delivery"
}

// sendLabel is the view's choice of send for a risk, from who it names as
// responsible: a role's queue first, then the Partner, then the CCEO; "" for
// none.
func sendLabel(i *item, r partnerRisk) string {
	s := rules.Work.Sends
	switch {
	case s.RoleQueues[r.role] != "":
		return "Ask " + s.RoleQueues[r.role]
	case in(s.PartnerAddressed, r.key):
		return "Remind " + first(i.partnerName, "the partner")
	case in(s.CCEOAddressed, r.key):
		return "Send to " + first(i.cceoName, "the CCEO")
	}
	return ""
}

// titleWords is |replace_underscore|title|default:"—".
func titleWords(s string) string { return first(djangoTitle(strings.ReplaceAll(s, "_", " ")), "—") }

// detailDrawer is partner_detail_drawer.html as the feed reads it: a drawer
// whose one form (the body's first line its help) is read as that form; with
// several, the whole drawer with each button's words, the first offered.
func detailDrawer(it *item, risks []partnerRisk, lines []detailLine, version string, canAct bool, escalateTo string,
	openRecord bool) *screensv1.PageDrawer {
	owner, action := nextAction(it)
	title := first(it.schoolName, it.clusterName, "Partner assignment")
	subtitle := first(it.partnerName, "Partner")
	if it.district != "" {
		subtitle += " · " + it.district
	}
	d := &screensv1.PageDrawer{Title: title, Subtitle: subtitle, HasRequired: true, CancelLabel: "Cancel"}
	forms := []string{}
	items := []*screensv1.DrawerItem{dHeading("Next action"), dText(action), dText("Waiting on " + owner)}
	if len(risks) > 0 {
		items = append(items, dHeading("Needs attention"))
		for _, r := range risks {
			line := r.action + " " + r.reason + " Responsible: " + first(r.responsible, "—")
			if r.due != nil {
				line += " · Due " + r.due.Format("2 Jan 2006")
			}
			if label := sendLabel(it, r); canAct && label != "" {
				line += " " + label
				forms = append(forms, label)
			}
			items = append(items, dText(line))
		}
	}
	assigned := "—"
	if it.assignmentDate != nil {
		assigned = it.assignmentDate.Format("2 Jan 2006")
	}
	items = append(items, dHeading("The handover"),
		dFacts([2]string{"Partner", first(it.partnerName, "—")}, [2]string{"Managing CCEO", first(it.cceoName, "—")},
			[2]string{"Supervising PL", first(it.plName, "Unassigned")}, [2]string{"Support type", titleWords(it.supportType)},
			[2]string{"Focus intervention", titleWords(it.targetIntervention)}, [2]string{"Assigned on", assigned}))
	if it.isReturned() {
		line := "Returned by the partner"
		if it.returnReasonCategory != "" {
			line += " — " + djangoTitle(strings.ReplaceAll(it.returnReasonCategory, "_", " "))
		}
		line += "."
		if it.returnReason != "" {
			line += " " + it.returnReason
		}
		items = append(items, dText(line))
	}
	items = append(items, dHeading("Scheduling"))
	if it.isScheduled() {
		scheduled := "—"
		if it.scheduledDate != nil {
			scheduled = it.scheduledDate.Format("2 Jan 2006")
		}
		fy := "FY " + first(it.act.fy, "—")
		if it.quarter != "" {
			fy += " · " + it.quarter
		}
		items = append(items, dFacts([2]string{"Scheduled for", scheduled}, [2]string{"Financial year", fy}))
	} else {
		items = append(items, dText(first(it.partnerName, "The partner")+
			" has not set a date yet. Until they do this assignment has no activity, and therefore no cost."))
	}
	items = append(items, dHeading("Cost"))
	switch {
	case !it.isScheduled():
		items = append(items, dText("No cost exists for this assignment. A cost is created when the partner schedules, priced from the Country Director's Cost Catalogue."))
	case len(lines) > 0:
		table := &screensv1.PageTable{}
		for _, l := range []string{"Line", "Unit", "Qty", "Amount"} {
			table.Columns = append(table.Columns, &screensv1.PageColumn{Label: l})
		}
		for _, l := range lines {
			row := &screensv1.PageRow{}
			for _, t := range []string{l.label, "UGX " + intcomma(l.unit), strconv.FormatInt(l.quantity, 10), "UGX " + intcomma(l.amount)} {
				row.Cells = append(row.Cells, &screensv1.PageCell{Text: t})
			}
			table.Rows = append(table.Rows, row)
		}
		// The table's footer (the total) is not read by the feed.
		items = append(items, &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Block{Block: &screensv1.PageBlock{
			Kind: &screensv1.PageBlock_Table{Table: table}}}})
		if version != "" && version != "0" {
			items = append(items, dText("Priced against Cost Catalogue version "+version+"."))
		}
	default:
		items = append(items, dText("Scheduled, but no partner rate was found in the cost catalogue, so this work cannot enter a fund request. The Country Director owns the rates."))
	}
	salesforce := "—"
	if it.isScheduled() {
		salesforce = "Missing"
		if it.salesforceRecorded {
			salesforce = "Recorded"
		}
	}
	activity := "Not scheduled"
	if it.activityStatus != "" {
		activity = djangoTitle(strings.ReplaceAll(it.activityStatus, "_", " "))
	}
	items = append(items, dHeading("Delivery & verification"),
		dFacts([2]string{"Activity", activity}, [2]string{"Salesforce", salesforce},
			[2]string{"Impact Assessment", titleWords(it.iaStatus)}, [2]string{"Payment", titleWords(it.paymentStatus)}))
	if canAct && escalateTo != "" {
		forms = append(forms, "Escalate")
		items = append(items, dHeading("Escalate"),
			dText("Goes to "+escalateTo+", decided on Escalations. Only the Country Director can replace a partner or reprice the work."),
			&screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{}}})
	}
	if openRecord {
		items = append(items, dText("Open the full activity record"))
	}
	if len(forms) == 1 {
		field := &screensv1.DrawerField{Name: "note", Label: "Note for the recipient", Kind: "text", Help: action,
			Placeholder: "Add a note (optional)"}
		if forms[0] == "Escalate" {
			field.Label, field.Required, field.Placeholder = "What has already been tried", true, "What have you already tried?"
		}
		d.SubmitLabel, d.CanSubmit = forms[0], true
		d.Items = []*screensv1.DrawerItem{{Kind: &screensv1.DrawerItem_Field{Field: field}}}
		return d
	}
	if len(forms) > 1 {
		d.SubmitLabel, d.CanSubmit = forms[0], true
	}
	d.Items = items
	return d
}

// djangoTitle is Django's |title: str.title(), then a letter after an
// apostrophe and one after a digit kept lower case.
func djangoTitle(s string) string {
	out := []rune{}
	prevLetter := false
	for _, r := range s {
		isLetter := (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z')
		switch {
		case isLetter && !prevLetter:
			out = append(out, []rune(strings.ToUpper(string(r)))...)
		case isLetter:
			out = append(out, []rune(strings.ToLower(string(r)))...)
		default:
			out = append(out, r)
		}
		prevLetter = isLetter
	}
	t := titleApostrophe.ReplaceAllStringFunc(string(out), strings.ToLower)
	return titleDigit.ReplaceAllStringFunc(t, strings.ToLower)
}

var (
	titleApostrophe = regexp.MustCompile(`[a-z]'[A-Z]`)
	titleDigit      = regexp.MustCompile(`\d[A-Z]`)
)
