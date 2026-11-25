package partnerassigned

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/stafflogs"
)

// MyPlanPath is My Plan, which a partner login reads as its own page:
// my_plan_view's partner branch (partner_views.partner_plan_context,
// pages/partner/my_plan.html), the accepted implementation schedule in five
// sections with one Actions menu per row and the Send Invoice button.
//
// Handed on (served=false) while Go does not draw them: the organisation's
// invoices (the payment tracker), the clusters it facilitates and the
// trainings it is paid to facilitate, and a section past its first page.
const MyPlanPath = "/my-plan"

const (
	planEyebrow     = "My Work"
	planTitle       = "My Plan"
	invoiceLabel    = "Send Invoice"
	invoiceDrawer   = "/partner/invoices/new"
	nothingHere     = "Nothing here — all clear."
	nothingPlanned  = "Nothing on your plan yet — schedule assigned work from Assigned Schools or Assigned Activities."
	nobodyNamed     = "Nobody named yet"
	noEvidenceYet   = "No evidence yet"
	fieldWork       = "Field work"
	sectionAttend   = 0
	sectionProgress = 1
	sectionToday    = 2
	sectionWeek     = 3
	sectionLater    = 4
)

// planSections are partner_plan_context's sections: title, blurb, tone.
var planSections = [5][3]string{
	{"Needs Attention", "Returned evidence and overdue work — fix these first.", "danger"},
	{"In Progress", "Started — finish the evidence and submit to IA.", "info"},
	{"Due Today", "On today's schedule.", "warning"},
	{"Planned This Week", "Coming up this week.", "neutral"},
	{"Planned Later", "Scheduled beyond this week.", "neutral"},
}

// planRow is one activity on the plan with what its row shows.
type planRow struct {
	id, activityType, status, contact, note, profile string
	schoolPK, code, school, district, cluster        string
	planned                                          *time.Time
	kinds                                            map[string]bool
	actions                                          []string
}

// partnerPlan answers My Plan for a partner login, or served=false.
func (s *Service) partnerPlan(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	// my_plan_view's own order: the feed's ?format= refusal and the page's
	// door, then the export drawer's file, before the partner's page.
	if myplan.FeedRefusesFormat(query) || !myplan.Opens(p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if myplan.AsksExport(query) {
		return nil, false, nil
	}
	partners, err := s.partnerIDs(ctx, p)
	if err != nil || len(partners) == 0 {
		return nil, err != nil, err
	}
	member, schools, err := s.teamMember(ctx, p)
	if err != nil {
		return nil, true, err
	}
	if !member {
		var other bool
		err := s.db.QueryRow(ctx, `SELECT
  EXISTS (SELECT 1 FROM partner_invoice WHERE partner_id = ANY($1))
  OR EXISTS (SELECT 1 FROM cluster WHERE deleted_at IS NULL AND facilitating_partner_id = ANY($1))
  OR EXISTS (SELECT 1 FROM activity WHERE deleted_at IS NULL AND facilitating_partner_id = ANY($1)
             AND delivery_type = 'staff' AND (status IS NULL OR NOT status = ANY($2)))`,
			partners, []string{"cancelled", "rejected", "deferred"}).Scan(&other)
		if err != nil {
			return nil, true, fmt.Errorf("partnerassigned: reading the organisation's invoices and facilitation: %w", err)
		}
		if other {
			return nil, false, nil
		}
	}
	rows, err := s.planRows(ctx, partners, member, schools)
	if err != nil {
		return nil, true, err
	}
	leads := p.ActiveRole == roleAdmin || p.ActiveRole == rolePartnerAdmin
	if !leads {
		if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM partner WHERE id = ANY($1) AND user_id = $2)`, partners, p.UserID).Scan(&leads); err != nil {
			return nil, true, fmt.Errorf("partnerassigned: reading who leads the team: %w", err)
		}
	}
	local := time.Now().In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	weekEnd := today.AddDate(0, 0, 6-(int(today.Weekday())+6)%7)
	var filed [5][]planRow
	for _, r := range rows {
		t := bucket(&r, today, weekEnd)
		switch {
		case member:
			r.actions = slices.DeleteFunc(r.actions, func(a string) bool { return a != "reschedule" })
		case leads:
			r.actions = append(r.actions, "team")
		}
		filed[t] = append(filed[t], r)
	}
	for _, rows := range filed {
		if len(rows) > rules.PageSize {
			return nil, false, nil
		}
	}
	return planPage(filed, len(rows), !member), true, nil
}

// planRows are the organisation's activities on the plan (a team member's
// only at their schools), by planned day then age, the first 200.
func (s *Service) planRows(ctx context.Context, partners []string, member bool, schools []string) ([]planRow, error) {
	pl := rules.Plan
	statuses := append(append(append([]string{}, pl.ScheduledStatuses...), pl.InProgressStatuses...), pl.ReturnedStatuses...)
	var narrow []string
	if member {
		narrow = schools
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.activity_type, ''), COALESCE(a.status, ''), COALESCE(a.delivery_contact_name, ''),
  COALESCE(a.pl_review_note, ''), COALESCE(a.evidence_profile_snapshot, ''), a.planned_date,
  COALESCE(a.school_id, ''), COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(d.name, ''),
  COALESCE(c.name, '')
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN district d ON d.id = s.district_id
LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE a.assigned_partner_id = ANY($1) AND a.delivery_type = 'partner' AND a.deleted_at IS NULL
  AND a.status = ANY($2) AND ($3::text[] IS NULL OR a.school_id = ANY($3))
ORDER BY a.planned_date NULLS LAST, a.created_at
LIMIT $4`, partners, statuses, narrow, pl.Limit)
	if err != nil {
		return nil, fmt.Errorf("partnerassigned: reading the plan: %w", err)
	}
	out := []planRow{}
	for rows.Next() {
		var r planRow
		if err := rows.Scan(&r.id, &r.activityType, &r.status, &r.contact, &r.note, &r.profile, &r.planned,
			&r.schoolPK, &r.code, &r.school, &r.district, &r.cluster); err != nil {
			rows.Close()
			return nil, fmt.Errorf("partnerassigned: reading the plan: %w", err)
		}
		r.kinds = map[string]bool{}
		out = append(out, r)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(out) == 0 {
		return out, nil
	}
	ids := make([]string, len(out))
	for i, r := range out {
		ids[i] = r.id
	}
	kinds, err := s.db.Query(ctx, `SELECT activity_id, kind FROM gateway_read.activity_evidence_kind WHERE activity_id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("partnerassigned: reading the evidence uploaded: %w", err)
	}
	defer kinds.Close()
	at := map[string]int{}
	for i, r := range out {
		at[r.id] = i
	}
	for kinds.Next() {
		var id, kind string
		if err := kinds.Scan(&id, &kind); err != nil {
			return nil, fmt.Errorf("partnerassigned: reading the evidence uploaded: %w", err)
		}
		out[at[id]].kinds[kind] = true
	}
	return out, kinds.Err()
}

// bucket is the row's section and its Actions (partner_plan_context).
func bucket(r *planRow, today, weekEnd time.Time) int {
	pl := rules.Plan
	var t int
	switch {
	case slices.Contains(pl.ReturnedStatuses, r.status):
		t, r.actions = sectionAttend, []string{"correct"}
	case slices.Contains(pl.InProgressStatuses, r.status):
		t, r.actions = sectionProgress, []string{"continue", "complete", "reschedule"}
	case r.planned != nil && r.planned.Equal(today):
		t, r.actions = sectionToday, []string{"start", "complete", "reschedule"}
	case r.planned != nil && r.planned.Before(today):
		t, r.actions = sectionAttend, []string{"start", "complete", "reschedule"}
	case r.planned != nil && !r.planned.After(weekEnd):
		t, r.actions = sectionWeek, []string{"start", "complete", "reschedule"}
	default:
		t, r.actions = sectionLater, []string{"start", "complete", "reschedule"}
	}
	// Every row still to be delivered can be cancelled; only a returned
	// row shows its return reason.
	if !slices.Contains(pl.ReturnedStatuses, r.status) {
		r.actions = append(r.actions, "cancel")
		r.note = ""
	}
	return t
}

// evidenceSummary is the row's Evidence: the required kinds met, else the
// files uploaded.
func (r planRow) evidenceSummary() string {
	needed, ok := rules.Plan.ProfileRequiredKinds[r.profile]
	if !ok {
		needed = rules.Plan.RequiredKinds[r.activityType]
	}
	if len(needed) > 0 {
		met := 0
		for _, k := range needed {
			if r.kinds[k] {
				met++
			}
		}
		return strconv.Itoa(met) + "/" + strconv.Itoa(len(needed)) + " evidence items"
	}
	if len(r.kinds) > 0 {
		return strconv.Itoa(len(r.kinds)) + " file(s)"
	}
	return noEvidenceYet
}

func (r planRow) where() string {
	switch {
	case r.schoolPK != "":
		return r.school
	case r.cluster != "":
		return r.cluster
	}
	return fieldWork
}

// cells are the row as the feed reads my_plan.html's table.
func (r planRow) cells(workroom bool) []*screensv1.PageCell { // workroom: not a team member
	code := "—"
	if r.schoolPK != "" {
		code = r.code
	}
	title := &screensv1.PageCell{Text: r.where()}
	if r.note != "" {
		title.Text += " " + r.note
	}
	if workroom {
		title.Href = "/partner/activities/" + r.id + "/evidence"
	}
	planned := "—"
	if r.planned != nil {
		planned = fmt.Sprintf("%02d %s %d", r.planned.Day(), r.planned.Month().String()[:3], r.planned.Year())
	}
	tone := "info"
	switch {
	case r.note != "":
		tone = "danger"
	case r.status == "partner_scheduled" || r.status == "scheduled":
		tone = "neutral"
	}
	kind := rules.ActivityTypes[r.activityType]
	if kind == "" {
		kind = r.activityType
	}
	return []*screensv1.PageCell{
		{Text: code}, title, {Text: kind}, {Text: or(r.district, "—")}, {Text: planned},
		{Text: or(r.contact, nobodyNamed)}, {Text: stafflogs.StatusLabel(r.status), Tone: tone},
		{Text: r.evidenceSummary()}, {Actions: r.menu()},
	}
}

// menu is the row's Actions as the feed reads them: the posted forms (Start
// Activity, and Complete on work not started) are not drawn.
func (r planRow) menu() []*screensv1.PageAction {
	item := func(label, href string, drawer bool) *screensv1.PageAction {
		return &screensv1.PageAction{Key: "menu", Label: label, Enabled: true, Href: href, Drawer: drawer}
	}
	out := []*screensv1.PageAction{}
	has := func(a string) bool { return slices.Contains(r.actions, a) }
	if has("continue") {
		out = append(out, item("Continue Evidence", "/activities/"+r.id+"/evidence", true))
	}
	if has("complete") && !has("start") {
		out = append(out, item("Complete", "/partner/activities/"+r.id+"/evidence", false))
	}
	if has("correct") {
		out = append(out, item("Correct Returned Evidence", "/partner/activities/"+r.id+"/evidence", false))
	}
	if has("reschedule") {
		out = append(out, item("Reschedule", "/my-plan/"+r.id+"/reschedule-drawer", true))
	}
	if has("team") {
		label := "Name team member"
		if r.contact != "" {
			label = "Change team member"
		}
		out = append(out, item(label, "/partner/activities/"+r.id+"/delivered-by", true))
	}
	if has("cancel") {
		cancel := item("Cancel", "/my-plan/"+r.id+"/cancel-drawer", true)
		cancel.Key = "danger"
		out = append(out, cancel)
	}
	return out
}

// planPage is pages/partner/my_plan.html as the feed reads it.
func planPage(filed [5][]planRow, total int, money bool) *screensv1.GetPageResponse {
	noun := "activities"
	if total == 1 {
		noun = "activity"
	}
	header := portalHeader(planEyebrow, planTitle, "Your accepted implementation schedule — "+strconv.Itoa(total)+" "+noun+" on the plan.")
	if money {
		header.Actions = []*screensv1.PageAction{{Key: "send_invoice", Label: invoiceLabel, Primary: true, Enabled: true, Href: invoiceDrawer, Drawer: true}}
	}
	columns := []string{"School ID", "School / Activity", "Type", "Location", "Planned", "Delivered by", "Status", "Evidence", "Actions"}
	blocks := []*screensv1.PageBlock{}
	for i, s := range planSections {
		rows := filed[i]
		if len(rows) == 0 && s[2] != "danger" {
			continue
		}
		if len(rows) == 0 {
			blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
				Title: s[0], Subtitle: s[1], Items: []*screensv1.PagePanelItem{text(nothingHere)},
			}}})
			continue
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Title: s[0] + " (" + strconv.Itoa(len(rows)) + ")", Subtitle: s[1],
		}}})
		out := []*screensv1.PageRow{}
		for _, r := range rows {
			out = append(out, &screensv1.PageRow{Cells: r.cells(money)})
		}
		blocks = append(blocks, table(columns, len(columns)-1, out))
	}
	if total == 0 {
		blocks = append(blocks, plainPanel("", text(nothingPlanned)))
	}
	return portalPage(header, MyPlanPath, blocks...)
}
