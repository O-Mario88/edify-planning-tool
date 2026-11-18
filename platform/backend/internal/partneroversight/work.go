package partneroversight

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pricing"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
)

// work draws the page for a team-lens reader whose workspace holds partner
// work, or hands it on (served false) where it draws what this piece does
// not build yet: work waiting for IA verification (its reviewer's Verify
// and Return), Core Schools, Special Project work, a decided hand-back,
// group trainings a Partner facilitates, withdrawal requests, a Partner
// needing follow-up, the Clusters tab (two tables), an activity filter, or
// a table longer than one page.
func (s *Service) work(ctx context.Context, p auth.Principal, w workspace, own []string, supervised []string,
	activityType string, now time.Time) (*screensv1.GetPageResponse, bool, error) {
	if activityType != "" {
		return nil, false, nil
	}
	staff := own
	if !w.role.OwnWorkOnly {
		var err error
		if staff, err = bothIDSpaces(ctx, s.db, append(append([]string{}, own...), supervised...)); err != nil {
			return nil, true, err
		}
	}
	return s.draw(ctx, p, w, staff, now)
}

// country draws the page through the country's lens (Country Director,
// Admin, Impact Assessment, the Accountant, the RVP): every Partner's work,
// one Programme Lead's team at a time. country is the reader's scope's
// country, "" for the whole deployment.
func (s *Service) country(ctx context.Context, p auth.Principal, role Role, per period, query url.Values,
	country string, regions []string, now time.Time) (*screensv1.GetPageResponse, bool, error) {
	if strings.TrimSpace(query.Get("activity_type")) != "" || country == schooldirectory.NoCountry {
		return nil, false, nil
	}
	if role.EngagementRegister {
		engaged, err := anyEngagementAtAll(ctx, s.db)
		if err != nil || engaged {
			return nil, !engaged, err
		}
	}
	w := workspace{role: role, period: per, status: query.Get("status"), fyOptions: schooldirectory.FYOptions(now),
		country: country, regions: regions, withTarget: true}
	w.programLead = strings.TrimSpace(query.Get("program_lead"))
	w.work = strings.TrimSpace(query.Get("work"))
	w.partnerAsked = strings.TrimSpace(query.Get("partner"))
	w.memberAsked = strings.TrimSpace(query.Get("member"))
	return s.draw(ctx, p, w, nil, now)
}

// draw reads the work of staff (nil for every Partner's work in the
// country) and draws the page, or hands it on.
func (s *Service) draw(ctx context.Context, p auth.Principal, w workspace, staff []string, now time.Time) (*screensv1.GetPageResponse, bool, error) {
	countryLens := staff == nil
	operational, _ := strconv.Atoi(schooldirectory.OperationalFY(now))
	years, err := schoolplanning.Horizon(ctx, s.db, p.Country, w.period.fy, operational, w.fyOptions, now)
	if err != nil {
		return nil, true, err
	}
	if held, err := handedOn(ctx, s.db, staff, w.regions); err != nil || held {
		return nil, !held, err
	}
	today := dateOf(now.In(zone))
	items, err := readItems(ctx, s.db, staff, w.regions, years, today)
	if err != nil {
		return nil, true, err
	}
	items = narrow(items, w.period)
	// The trainings a Partner facilitates are read over the years alone.
	trainings, err := readTrainings(ctx, s.db, staff, w.regions, years)
	if err != nil {
		return nil, true, err
	}
	if err := annotate(ctx, s.db, items, today); err != nil {
		return nil, true, err
	}
	follow, err := followUps(ctx, s.db, w.country, w.period.fy)
	if err != nil {
		return nil, true, err
	}

	v := &workView{w: w, today: today, years: years}
	if countryLens {
		// One Programme Lead's team at a time (_program_lead_tabs over
		// system_program_leads): the first tab opens when none is asked.
		leads, err := systemProgramLeads(ctx, s.db)
		if err != nil {
			return nil, true, err
		}
		if w.regions != nil {
			// A region's tabs are the leads whose teams hold its work.
			visible := map[string]bool{}
			for _, i := range items {
				visible[i.plID] = true
			}
			for _, t := range trainings {
				visible[t.plID] = true
			}
			kept := []programLead{}
			for _, l := range leads {
				if visible[l.id] {
					kept = append(kept, l)
				}
			}
			leads = kept
		}
		var rows []*item
		var held []*training
		v.leads, w.programLead, rows, held = leadTabs(leads, items, trainings, w.programLead)
		items, trainings = rows, held
		v.w.programLead = w.programLead
		if w.members, err = roster(ctx, s.db, w.programLead); err != nil {
			return nil, true, err
		}
		v.w.members = w.members
	}
	counts := map[string]int{}
	names := map[string]string{}
	for _, i := range items {
		if i.partnerID != "" {
			counts[i.partnerID]++
			names[i.partnerID] = i.partnerName
		}
	}
	for _, t := range trainings {
		if t.partnerID != "" {
			counts[t.partnerID]++
			names[t.partnerID] = t.partnerName
		}
	}
	for id, n := range counts {
		v.partners = append(v.partners, partnerTab{key: id, label: names[id], count: n})
	}
	sort.SliceStable(v.partners, func(a, b int) bool {
		if v.partners[a].label != v.partners[b].label {
			return v.partners[a].label < v.partners[b].label
		}
		return v.partners[a].key < v.partners[b].key
	})
	for idx, t := range v.partners {
		v.partners[idx].followUp = follow[t.key]
		if idx > 0 && t.label == v.partners[idx-1].label {
			// Two Partners of one name: Python's set order picks between
			// them.
			return nil, false, nil
		}
	}
	requested := w.partnerAsked
	if requested == "" {
		requested = "all"
	}
	for idx := range v.partners {
		if v.partners[idx].key == requested {
			v.partnerTab = &v.partners[idx]
		}
	}
	if v.partnerTab == nil && len(v.partners) > 0 {
		v.partnerTab = &v.partners[0]
	}
	partnerItems := []*item{}
	partnerTrainings := []*training{}
	if v.partnerTab != nil {
		v.partner = v.partnerTab.key
		for _, i := range items {
			if i.partnerID == v.partner {
				partnerItems = append(partnerItems, i)
			}
		}
		for _, t := range trainings {
			if t.partnerID == v.partner {
				partnerTrainings = append(partnerTrainings, t)
			}
		}
	}
	for _, i := range partnerItems {
		if i.projectID != "" || i.resolution != "" {
			return nil, false, nil
		}
	}

	// The team members: the roster first, then whoever holds the Partner's
	// work, in the order it arrives; "all" when the one asked for is none.
	order := []string{}
	labels := map[string]string{}
	for _, m := range w.members {
		if _, ok := labels[m.key]; !ok {
			order = append(order, m.key)
		}
		labels[m.key] = m.name
	}
	memberKey := func(i *item) string { return orDefault(i.cceoID, "unassigned") }
	for _, i := range partnerItems {
		k := memberKey(i)
		if _, ok := labels[k]; !ok {
			order = append(order, k)
		}
		labels[k] = orDefault(i.cceoName, "Unassigned")
	}
	trainingKey := func(t *training) string { return orDefault(t.cceoID, "unassigned") }
	for _, t := range partnerTrainings {
		k := trainingKey(t)
		if _, ok := labels[k]; !ok {
			order = append(order, k)
		}
		labels[k] = orDefault(t.cceoName, "Unassigned")
	}
	member := w.memberAsked
	if member == "" {
		member = "all"
	}
	if _, ok := labels[member]; !ok {
		member = "all"
	}
	v.w.member = member
	v.members = []memberTab{{key: "all", label: allMembers, count: len(partnerItems) + len(partnerTrainings)}}
	for _, k := range order {
		n := 0
		for _, i := range partnerItems {
			if memberKey(i) == k {
				n++
			}
		}
		for _, t := range partnerTrainings {
			if trainingKey(t) == k {
				n++
			}
		}
		v.members = append(v.members, memberTab{key: k, label: labels[k], count: n})
	}
	for _, i := range partnerItems {
		if member == "all" || memberKey(i) == member {
			v.typed = append(v.typed, i)
		}
	}
	for _, i := range v.typed {
		if w.status == "" || i.deliveryPhase() == w.status {
			v.shown = append(v.shown, i)
		}
	}
	for _, t := range partnerTrainings {
		if (member == "all" || trainingKey(t) == member) && (w.status == "" || t.deliveryPhase() == w.status) {
			if t.awaitsReview() {
				// Its Programme Lead's Confirm and Return depend on who reads.
				return nil, false, nil
			}
			v.trainings = append(v.trainings, t)
		}
	}
	if len(v.trainings) > tablePageSize {
		return nil, false, nil
	}
	own, err := bothIDSpaces(ctx, s.db, []string{p.UserID, p.StaffProfileID})
	if err != nil {
		return nil, true, err
	}
	if err := s.markReviewable(ctx, p, w.role, own, v.shown); err != nil {
		return nil, true, err
	}
	orderForMonitoring(v.shown)
	v.tableItems = v.shown
	core := 0
	for _, i := range v.shown {
		if i.isCoreSchoolWork() {
			core++
		}
	}
	v.tab = workTabOpen(tablesFor(v.shown), w.work, core, len(v.trainings))
	v.w.work = v.tab
	if v.tab == "clusters" {
		// The card is read part by part there: its head names the Partner's
		// contact, which is not drawn yet.
		var contact bool
		if err := s.db.QueryRow(ctx, `SELECT COALESCE(btrim(contact_person), '') <> '' OR COALESCE(btrim(phone), '') <> ''
FROM partner WHERE id = $1`, v.partner).Scan(&contact); err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return nil, true, fmt.Errorf("partneroversight: reading the Partner's contact: %w", err)
		}
		if contact {
			return nil, false, nil
		}
	}
	if v.tab == "core" {
		if drawn, err := s.coreSupport(ctx, v.shown); err != nil || !drawn {
			return nil, !drawn, err
		}
	}
	for _, t := range tablesFor(v.shown) {
		if tableTab[t.title] == v.tab && len(t.items) > tablePageSize {
			return nil, false, nil
		}
	}
	if w.withTarget {
		if s.target == nil {
			return nil, false, nil
		}
		t, c, b, h, ok, err := s.target(ctx, p, strconv.Itoa(operational), now)
		if errors.Is(err, ErrTargetNotDrawn) {
			return nil, false, nil
		}
		if err != nil {
			return nil, true, err
		}
		if ok {
			v.target = &target{target: t, core: c, beyond: b, held: h}
		}
	}
	header := &screensv1.PageHeader{Eyebrow: eyebrow, Title: title, Description: description}
	if w.role.CreatePartner {
		header.Actions = []*screensv1.PageAction{{
			Key: "add_partner_organisation", Label: "Add Partner Organisation", Primary: true,
			Enabled: true, Href: "/partners/create", Drawer: true,
		}}
	}
	out := &screensv1.GetPageResponse{Header: header, Blocks: v.blocks(), WebPath: Path}
	if v.selectable {
		out.Selection = &screensv1.PageSelection{Noun: "selected", Actions: []*screensv1.PageSelectionAction{
			{Label: "Withdraw selected", Href: "/partner-oversight/withdraw/bulk", Param: "assignment_ids"},
		}}
	}
	return out, true, nil
}

// handedOn is whether the reader's page holds what this piece hands on
// before any row is read: a withdrawal request their team must decide, or a
// group training or meeting a Partner facilitates for the team in the
// years read.
func handedOn(ctx context.Context, db schooldirectory.Querier, staff, regions []string) (bool, error) {
	var held bool
	err := db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM partner_assignment_withdrawal w
      LEFT JOIN school ws ON ws.id = w.school_id
      LEFT JOIN partner_assignment wa ON wa.id = w.assignment_id LEFT JOIN cluster wc ON wc.id = wa.cluster_id
      WHERE w.state = $1 AND ($2::text[] IS NULL OR w.supervising_pl_id = ANY($2))
        AND ($3::text[] IS NULL OR ws.region_id = ANY($3) OR wc.region_id = ANY($3)))`,
		rules.WithdrawalRequested, staff, regions).Scan(&held)
	if err != nil {
		return false, fmt.Errorf("partneroversight: reading what the page hands on: %w", err)
	}
	return held, nil
}

// narrow is build_items' period narrowing: a month by the work's day (else
// the day it was handed over), a quarter by the work's quarter (else that
// day's), a week by that day.
func narrow(items []*item, p period) []*item {
	day := func(i *item) *time.Time {
		if i.scheduledDate != nil {
			return i.scheduledDate
		}
		return i.assignmentDate
	}
	out := []*item{}
	for _, i := range items {
		d := day(i)
		switch p.kind {
		case "month":
			if d == nil || int(d.Month()) != p.month {
				continue
			}
		case "quarter":
			q := i.quarter
			if q == "" && d != nil {
				q = quarterOf(*d)
			}
			if q != p.quarter {
				continue
			}
		case "week":
			start := isoWeekStart(p.week)
			if d == nil || d.Before(start) || !d.Before(start.AddDate(0, 0, 7)) {
				continue
			}
		}
		out = append(out, i)
	}
	return out
}

// isoWeekStart is the Monday of an ISO week "YYYY-Www".
func isoWeekStart(week string) time.Time {
	year, _ := strconv.Atoi(week[:4])
	n, _ := strconv.Atoi(week[6:])
	jan4 := time.Date(year, time.January, 4, 0, 0, 0, 0, time.UTC)
	monday := jan4.AddDate(0, 0, -((int(jan4.Weekday()) + 6) % 7))
	return monday.AddDate(0, 0, (n-1)*7)
}

// coreSupport is annotate_core_support over the Core schools the table
// shows: each one's package slot (the slot its activity fills) and the
// Partner's rate (the Core Partner Visit rate, a training's the Partner
// school visit rate). It is false where the table holds what this piece
// does not draw yet: a Core school the Partner has not dated (the slot its
// hand-over holds), or work whose form is in but is not complete (Confirm
// completed work, offered by who may confirm it).
func (s *Service) coreSupport(ctx context.Context, shown []*item) (bool, error) {
	core := []*item{}
	activities := []string{}
	for _, i := range shown {
		if !i.isCoreSchoolWork() {
			continue
		}
		if i.stage == stageAwaiting || (i.evidenceOK && !i.showsComplete()) {
			return false, nil
		}
		core = append(core, i)
		if i.activityID != "" {
			activities = append(activities, i.activityID)
		}
	}
	visit, err := pricing.OperationalRate(ctx, s.db, "core_partner_visit")
	if err != nil {
		return false, err
	}
	training, err := pricing.OperationalRate(ctx, s.db, "client_partner_visit")
	if err != nil {
		return false, err
	}
	slots := map[string]string{}
	if len(activities) > 0 {
		rows, err := s.db.Query(ctx, `SELECT activity_id, activity_type, sequence_number FROM core_activity_slot
WHERE activity_id = ANY($1) ORDER BY activity_id`, activities)
		if err != nil {
			return false, fmt.Errorf("partneroversight: reading the Core slots: %w", err)
		}
		defer rows.Close()
		for rows.Next() {
			var id, kind string
			var sequence int
			if err := rows.Scan(&id, &kind, &sequence); err != nil {
				return false, fmt.Errorf("partneroversight: reading the Core slots: %w", err)
			}
			letter := "T"
			if kind == "visit" {
				letter = "V"
			}
			slots[id] = letter + strconv.Itoa(sequence)
		}
		if err := rows.Err(); err != nil {
			return false, err
		}
	}
	for _, i := range core {
		i.partnerRate = visit
		if i.coreTraining() {
			i.partnerRate = training
		}
		i.coreSlotLabel = slots[i.activityID]
	}
	return true, nil
}

// markReviewable sets can_review on the work shown that waits for IA
// verification (RolePermissionService.can_confirm_partner_activity): Impact
// Assessment, unless it is their own work; the Country Director for work an
// Impact Assessment officer ran; and the activity's monitor among the field
// roles.
func (s *Service) markReviewable(ctx context.Context, p auth.Principal, role Role, own []string, shown []*item) error {
	waiting := []*item{}
	for _, i := range shown {
		if i.activityStatus == "awaiting_ia_verification" && i.act != nil && i.act.delivery == rules.PartnerDelivery {
			waiting = append(waiting, i)
		}
	}
	if len(waiting) == 0 {
		return nil
	}
	officers := map[string]bool{}
	if p.ActiveRole == "CountryDirector" {
		rows, err := s.db.Query(ctx, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND 'ImpactAssessment' = ANY(COALESCE(u.roles, '{}'))`)
		if err != nil {
			return fmt.Errorf("partneroversight: reading the Impact Assessment officers: %w", err)
		}
		defer rows.Close()
		for rows.Next() {
			var id string
			if err := rows.Scan(&id); err != nil {
				return fmt.Errorf("partneroversight: reading the Impact Assessment officers: %w", err)
			}
			officers[id] = true
		}
		if err := rows.Err(); err != nil {
			return err
		}
	}
	field := p.ActiveRole == "CCEO" || p.ActiveRole == "Program Lead" || p.ActiveRole == "ProjectCoordinator"
	for _, i := range waiting {
		a := i.act
		ownWork := a.responsible != "" && contains(own, a.responsible)
		switch {
		case !ownWork && role.VerifiesIA:
			i.canReview = true
		case !ownWork && p.ActiveRole == "CountryDirector" && a.responsible != "" && officers[a.responsible]:
			i.canReview = true
		case field && a.monitor != "" && contains(own, a.monitor):
			i.canReview = true
		}
		i.reviewIsSSA = a.schoolID != "" && (a.ssaExpected || a.purposeType == "ssa_support" || in(rules.Work.SSASupportTypes, a.activityType))
	}
	return nil
}
