package programmerollout

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// Path is the page.
const Path = "/programme-rollout"

// schoolsURL is the read-only school lists' drawer.
const schoolsURL = Path + "/schools"

// tabs are the view rail's labels.
var tabs = [][2]string{{"trainings", "Trainings"}, {"ssa", "Self-Assessments"}, {"spiritual", "Spiritual Formation"}}

// nairobi is the platform's time zone (TIME_ZONE): today.
var nairobi = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		return time.FixedZone("EAT", 3*60*60)
	}
	return z
}()

// Service answers /programme-rollout.
type Service struct {
	db  *pgxpool.Pool
	now func() time.Time
}

// NewService is the page over pool.
func NewService(pool *pgxpool.Pool, now func() time.Time) *Service {
	return &Service{db: pool, now: now}
}

// Build draws every view for a Programme Lead in their own seat, and for the
// Admin or Impact Assessment reading the lead they choose. A lead with no
// officers (warned on the page), no Programme Lead to choose, an acting
// seat, a query key the page does not read, a table running past what it
// shows (but the weak schools'), and a pager carrying more than one key
// hand on; the path with a trailing slash is not a page.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path == Path+"/" {
		return nil, true, pagegate.ErrNotAvailable
	}
	if path != Path {
		return nil, false, nil
	}
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if p.InActingAppointment {
		return nil, false, nil
	}
	chooser := slices.Contains(rules.LeadChoosers, p.ActiveRole)
	for key := range query {
		if key != "view" && key != "fy" && key != weakPageParam && (key != "lead" || !chooser) {
			return nil, false, nil
		}
	}
	lead := leadChoice{staffID: p.StaffProfileID, userID: p.UserID}
	var options [][2]string
	switch {
	case chooser:
		var found bool
		var err error
		if lead, options, found, err = s.chooseLead(ctx, strings.TrimSpace(query.Get("lead"))); err != nil || !found {
			return nil, err != nil, err
		}
	case p.ActiveRole != rules.ProgramLead || p.StaffProfileID == "":
		return nil, false, nil
	}
	view := strings.ToLower(strings.TrimSpace(query.Get("view")))
	if !slices.Contains(rules.Views, view) {
		view = rules.DefaultView
	}
	now := s.now()
	years := schooldirectory.FYOptions(now)
	fy := strings.TrimSpace(query.Get("fy"))
	if !slices.Contains(years, fy) {
		fy = schooldirectory.OperationalFY(now)
	}
	sc, err := readScope(ctx, s.db, lead.staffID, lead.userID, now)
	if err != nil {
		return nil, true, err
	}
	carried := url.Values{"fy": {fy}}
	if chooser {
		sc.support = true
		if sc.lead != nil {
			sc.lead.support = true
		}
		carried.Set("lead", lead.staffID)
	}
	sc.carry = carried.Encode()
	var blocks []*screensv1.PageBlock
	served := true
	switch view {
	case "ssa":
		blocks, served, err = s.selfAssessments(ctx, sc, fy)
	case "spiritual":
		blocks, served, err = s.spiritual(ctx, sc, fy, query)
	default:
		t := now.In(nairobi)
		today := time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
		blocks, served, err = s.trainings(ctx, sc, fy, today)
	}
	if err != nil || !served {
		return nil, served, err
	}
	segments := &screensv1.PageSegments{}
	for _, tab := range tabs {
		segments.Segments = append(segments.Segments, &screensv1.PageSegment{Label: tab[1], Active: tab[0] == view, Blocks: blocks})
	}
	year := &screensv1.PageFilter{Name: "fy", Label: "Fiscal year", Value: fy}
	for _, y := range years {
		year.Options = append(year.Options, &screensv1.PageFilterOption{Value: y, Label: "FY " + y})
	}
	header := &screensv1.PageHeader{
		Eyebrow: "Programme implementation", Title: "Programme Rollout",
		Description: "Coordinate the rollout of training programmes, school self-assessments and spiritual transformation interventions across your team.",
		Badges: []*screensv1.PageBadge{
			{Text: reachText(sc), Tone: "plain"},
			{Tone: "plain"},
		},
		Actions: []*screensv1.PageAction{{Key: "open_planning_oversight", Label: "Open Planning Oversight", Enabled: true,
			Href: "/team-planning-oversight/?fy=" + fy}},
	}
	filters := []*screensv1.PageFilter{year}
	page := []*screensv1.PageBlock{}
	if chooser {
		choose := &screensv1.PageFilter{Name: "lead", Label: "Programme Lead", Value: lead.staffID}
		for _, o := range options {
			choose.Options = append(choose.Options, &screensv1.PageFilterOption{Value: o[0], Label: o[1]})
		}
		filters = []*screensv1.PageFilter{choose, year}
	}
	if notice := noticeText(sc); notice != "" {
		page = append(page, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
			panelText(notice, "")}}}})
	}
	page = append([]*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: filters, Hidden: map[string]string{"view": view}}}}},
		append(page, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Segments{Segments: segments}})...)
	return &screensv1.GetPageResponse{Header: header, WebPath: Path, Blocks: page}, true, nil
}

// reachText is the header's reach badge: the lead an administrator reads,
// the officers and the schools.
func reachText(sc *scope) string {
	text := fmt.Sprintf("%d %s · %s %s", len(sc.officers), plural(len(sc.officers), "officer"), intcomma(len(sc.schools)), plural(len(sc.schools), "school"))
	if sc.support {
		return sc.leadName + " · " + text
	}
	return text
}

func plural(n int, word string) string {
	if n == 1 {
		return word
	}
	return word + "s"
}

// intcomma is Django's intcomma.
func intcomma(n int) string {
	s := strconv.Itoa(n)
	if n < 0 {
		return "-" + intcomma(-n)
	}
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	return s
}

func cell(text string) *screensv1.PageCell { return &screensv1.PageCell{Text: text} }

func num(n int) *screensv1.PageCell { return cell(intcomma(n)) }

func columns(labels ...string) []*screensv1.PageColumn {
	out := []*screensv1.PageColumn{}
	for _, l := range labels {
		out = append(out, &screensv1.PageColumn{Label: l})
	}
	return out
}

func titled(title string) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title}}}
}

func table(t *screensv1.PageTable) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

func empty(t *screensv1.PageTable, message, hint string) *screensv1.PageTable {
	t.EmptyMessage = message
	text := message
	if hint != "" {
		text += " " + hint
	}
	t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{cell(text)}}}
	return t
}

// tile is a registry tile as the feed reads it.
type tile struct{ label, value, helper, tone, href string }

func strip(title string, tiles []tile) *screensv1.PageBlock {
	figures := make([]schoolprofile.StripFigure, len(tiles))
	for i, t := range tiles {
		figures[i] = schoolprofile.StripFigure{Label: t.label, Value: t.value, Link: t.href, Helper: t.helper}
	}
	block := schoolprofile.Strip(title, figures)
	for i, m := range block.GetStrip().GetMetrics() {
		if m.Helper != "" {
			m.Tone = tiles[i].tone
		}
	}
	return block
}

func day(t time.Time, layout string) string {
	return strconv.Itoa(t.Day()) + t.Format(layout)
}

// trainings is the Trainings view's blocks (trainings_rollout and
// partials/programme_rollout/trainings.html).
func (s *Service) trainings(ctx context.Context, sc *scope, fy string, today time.Time) ([]*screensv1.PageBlock, bool, error) {
	rows, err := sc.trainingRows(ctx, s.db, fy)
	if err != nil {
		return nil, true, err
	}
	soon, err := sc.upcoming(ctx, s.db, today)
	if err != nil {
		return nil, true, err
	}
	reached, err := reach(ctx, s.db, rows)
	if err != nil {
		return nil, true, err
	}
	obs, err := s.observations(ctx, sc, fy)
	if err != nil {
		return nil, true, err
	}
	referenced := []string{}
	for _, r := range append(append([]training{}, rows...), soon...) {
		if id := r.courseID(); id != "" {
			referenced = append(referenced, id)
		}
	}
	for _, o := range obs {
		if o.courseID != "" {
			referenced = append(referenced, o.courseID)
		}
	}
	list, byID, err := courses(ctx, s.db, referenced)
	if err != nil {
		return nil, true, err
	}
	trained, err := sc.trainedSchools(ctx, s.db, fy)
	if err != nil {
		return nil, true, err
	}
	names, err := s.names(ctx, sc, append(append([]training{}, soon...), observationTrainings(obs)...))
	if err != nil {
		return nil, true, err
	}
	summary := folded(rows, reached)
	observed := foldObservations(obs)
	observedByCourse := map[string][]observation{}
	for _, o := range obs {
		observedByCourse[o.courseID] = append(observedByCourse[o.courseID], o)
	}
	portfolio := len(sc.schools)
	untrained := portfolio - len(trained)
	carry := sc.carry
	trainedValue, trainedHelper, trainedTone, trainedHref := "—", "No schools in the portfolio", "success", ""
	if portfolio > 0 {
		trainedValue, trainedHelper = strconv.Itoa(len(trained)), fmt.Sprintf("of %d · %d not yet trained", portfolio, untrained)
	}
	if untrained > 0 {
		trainedTone, trainedHref = "warning", schoolsURL+"?kind=not_trained&"+carry
	}
	deliveredTone := "info"
	if summary.delivered > 0 {
		deliveredTone = "success"
	}
	blocks := []*screensv1.PageBlock{strip("Rollout at a glance", []tile{
		{"Trainings Delivered", strconv.Itoa(summary.delivered), fmt.Sprintf("of %d planned · %d held, in review", summary.planned, summary.inReview), deliveredTone, ""},
		{"Portfolio Schools Trained", trainedValue, trainedHelper, trainedTone, trainedHref},
		{"Teachers and Leaders Trained", strconv.Itoa(summary.teachers + summary.leaders), fmt.Sprintf("%d teachers · %d leaders", summary.teachers, summary.leaders), "info", ""},
		{"Trainings Due in 30 Days", strconv.Itoa(len(soon)), "scheduled across the team", "info", ""},
		{"Open Training Recommendations", strconv.Itoa(observed.open), "strengthen or replace, not yet answered", openTone(observed.open), ""},
	})}

	// By intervention: all eight, the spiritual pair first.
	byFocus := map[string][]training{}
	for _, r := range rows {
		byFocus[r.focus] = append(byFocus[r.focus], r)
	}
	it := &screensv1.PageTable{Columns: columns("Intervention", "Planned", "Delivered", "Held, in review", "Schools reached", "Teachers", "Leaders", "By staff", "By partners")}
	interventionRow := func(label string, f fold) {
		it.Rows = append(it.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{cell(label), num(f.planned), num(f.delivered), num(f.inReview),
			num(f.schoolsReached), num(f.teachers), num(f.leaders), num(f.byStaff), num(f.byPartner)}})
	}
	for _, code := range rules.InterventionOrder {
		interventionRow(abbr(code)+" · "+rules.InterventionLabels[code], folded(byFocus[code], reached))
	}
	if len(byFocus[""]) > 0 {
		interventionRow("— · No intervention named", folded(byFocus[""], reached))
	}
	blocks = append(blocks, titled("Trainings by SSA intervention"), table(it))

	// By course.
	byCourse := map[string][]training{}
	for _, r := range rows {
		byCourse[r.courseID()] = append(byCourse[r.courseID()], r)
	}
	courseRows := []courseRow{}
	for _, c := range list {
		if !c.isCourse && len(byCourse[c.id]) == 0 {
			continue
		}
		category := c.category
		if category == "" {
			category = "Other"
		}
		a := "—"
		if c.intervention != "" {
			a = abbr(c.intervention)
		}
		courseRows = append(courseRows, courseRow{fold: folded(byCourse[c.id], reached), observed: foldObservations(observedByCourse[c.id]),
			name: c.name, category: category, abbr: a})
	}
	sortCourses(courseRows)
	if len(byCourse[""]) > 0 {
		courseRows = append(courseRows, courseRow{fold: folded(byCourse[""], reached), observed: foldObservations(observedByCourse[""]),
			name: "Training with no course named", category: "—", abbr: "—"})
	}
	if len(courseRows) > rules.PageSize {
		return nil, false, nil
	}
	ct := &screensv1.PageTable{Columns: columns("Course", "Category", "Intervention", "Planned", "Delivered", "Schools reached",
		"Teachers and leaders", "Staff · partner", "Regional Lead rating", "Open recommendations")}
	for _, c := range courseRows {
		ct.Rows = append(ct.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{cell(c.name), cell(c.category), cell(c.abbr),
			num(c.planned), num(c.delivered), num(c.schoolsReached), num(c.teachers + c.leaders),
			cell(fmt.Sprintf("%d · %d", c.byStaff, c.byPartner)), cell(courseRating(c.observed)), cell(strconv.Itoa(c.observed.open))}})
	}
	if len(courseRows) == 0 {
		empty(ct, "No training course is active in the catalogue.", "Courses appear here once the Training Catalogue holds them, with zeros until the team plans one.")
	}
	blocks = append(blocks, titled("Trainings by course"), table(ct))

	// By officer.
	byOwner := map[string][]training{}
	for _, r := range rows {
		if owner := sc.attribute(r.responsible, r.monitor, r.schoolID); owner != "" {
			byOwner[owner] = append(byOwner[owner], r)
		}
	}
	attributed := map[string]bool{}
	for k := range byOwner {
		attributed[k] = true
	}
	people := sc.rows(attributed)
	if len(people) > rules.OfficerRows {
		return nil, false, nil
	}
	ot := &screensv1.PageTable{Columns: columns("Officer", "Planned", "Delivered", "Held, in review", "Schools trained",
		"Teachers and leaders", "Staff · partner", "Next training", "")}
	for _, m := range people {
		f := folded(byOwner[m.staffID], reached)
		here := 0
		for id := range m.schools {
			if trained[id] {
				here++
			}
		}
		var next *time.Time
		for _, r := range byOwner[m.staffID] {
			if slices.Contains(rules.LiveStatuses, r.status) && r.planned != nil && !r.planned.Before(today) && (next == nil || r.planned.Before(*next)) {
				next = r.planned
			}
		}
		name := &screensv1.PageCell{Text: m.name}
		owner := m.staffID
		if m.isLead {
			name.Text, owner = memberName(m), "mine"
		} else {
			name.Href = "/staff/" + m.userID + "?from=" + Path
		}
		schoolsTrained := "No schools"
		if len(m.schools) > 0 {
			schoolsTrained = fmt.Sprintf("%d of %d", here, len(m.schools))
		}
		nextText := "None scheduled"
		if next != nil {
			nextText = day(*next, " Jan 2006")
		}
		oversight := "/team-planning-oversight/?owner=" + owner + "&fy=" + fy
		actions := []*screensv1.PageAction{{Key: "button", Label: "Oversight", Primary: true, Enabled: true, Href: oversight}}
		if len(m.schools)-here > 0 {
			actions = []*screensv1.PageAction{
				{Key: "menu", Label: "Not yet trained", Enabled: true, Href: schoolsURL + "?kind=not_trained&member=" + m.staffID + "&" + carry, Drawer: true},
				{Key: "menu", Label: "Oversight", Enabled: true, Href: oversight},
			}
		}
		ot.Rows = append(ot.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{name, num(f.planned), num(f.delivered), num(f.inReview),
			cell(schoolsTrained), num(f.teachers + f.leaders), cell(fmt.Sprintf("%d · %d", f.byStaff, f.byPartner)), cell(nextText), {Actions: actions}}})
	}
	if len(people) == 0 {
		empty(ot, "No officers or portfolio schools on this team yet.", "Officers appear here once HR records you as their supervisor.")
	}
	blocks = append(blocks, titled("Trainings by officer"), table(ot),
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{
			Text: "Schools trained counts a verified training at the school or a confirmed attendance at a verified cluster training, the rule every page uses. Oversight opens the officer's plan in Team Oversight, read-only."}}}}}})

	// The next days.
	if len(soon) > rules.PageSize {
		return nil, false, nil
	}
	ut := &screensv1.PageTable{Columns: columns("Date", "Training", "School ID", "School or cluster", "Delivered by", "Intervention", "State", "")}
	for _, r := range soon {
		when := ""
		if r.planned != nil {
			when = day(*r.planned, " Jan")
		}
		place := r.schoolName
		if place == "" {
			place = r.clusterName
		}
		if place == "" {
			place = "No school or cluster"
		}
		code := "—"
		if r.schoolID != "" {
			code = ""
		}
		by := deliveredBy(sc, names, r)
		if r.delivery == "partner" {
			by += " (partner)"
		}
		a := "—"
		if r.focus != "" {
			a = abbr(r.focus)
		}
		label, ok := rules.StatusLabels[r.status]
		if !ok {
			label = r.status
		}
		ut.Rows = append(ut.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{cell(when), cell(trainingName(r, byID)), cell(code),
			cell(place), cell(by), cell(a), cell(label),
			{Actions: []*screensv1.PageAction{{Key: "button", Label: "Open", Primary: true, Enabled: true, Href: "/activities/" + r.id}}}}})
	}
	if len(soon) == 0 {
		empty(ut, "No team training is scheduled in the next 30 days.", "Officers schedule trainings from Planning; partner trainings appear once the partner sets a date.")
	}
	blocks = append(blocks, titled(fmt.Sprintf("Trainings in the next %d days", rules.UpcomingDays)), table(ut))

	// The Regional Lead's observations.
	byDeliverer, ok := observationsByDeliverer(obs, names, sc)
	recommended, okRecs, err := s.recommendations(ctx, sc, obs, byID, names)
	if err != nil {
		return nil, true, err
	}
	if !ok || !okRecs {
		return nil, false, nil
	}
	blocks = append(blocks, titled("Regional Lead observations"), table(byDeliverer),
		titled("Strengthen or replace recommendations"), table(recommended))
	return blocks, true, nil
}

// trainingName is _training_name: the course, else the activity's own name,
// else its type, else "Training".
func trainingName(r training, byID map[string]course) string {
	if c, ok := byID[r.courseID()]; ok && r.courseID() != "" {
		return c.name
	}
	if r.snapshot != "" {
		return r.snapshot
	}
	if l := rules.TypeLabels[r.kind]; l != "" {
		return l
	}
	return "Training"
}

// names are the people and partners the upcoming rows name who are not on
// the team (_people_names, _partner_names).
type names struct{ people, partners map[string]string }

func (s *Service) names(ctx context.Context, sc *scope, soon []training) (names, error) {
	out := names{people: map[string]string{}, partners: map[string]string{}}
	unknown, partners := []string{}, []string{}
	for _, r := range soon {
		if _, ok := sc.ownerByID[r.responsible]; r.responsible != "" && !ok {
			unknown = append(unknown, r.responsible)
		}
		if r.partner != "" {
			partners = append(partners, r.partner)
		}
	}
	if len(unknown) > 0 {
		rows, err := s.db.Query(ctx, `SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(u.name, '') FROM staff_profile sp
LEFT JOIN "user" u ON u.id = sp.user_id WHERE sp.id = ANY($1) OR sp.user_id = ANY($1)`, unknown)
		if err != nil {
			return out, fmt.Errorf("programmerollout: reading the deliverers: %w", err)
		}
		for rows.Next() {
			var id, user, name string
			if err := rows.Scan(&id, &user, &name); err != nil {
				rows.Close()
				return out, fmt.Errorf("programmerollout: reading a deliverer: %w", err)
			}
			out.people[id], out.people[user] = name, name
		}
		rows.Close()
	}
	if len(partners) > 0 {
		rows, err := s.db.Query(ctx, `SELECT id, name FROM partner WHERE id = ANY($1)`, partners)
		if err != nil {
			return out, fmt.Errorf("programmerollout: reading the partners: %w", err)
		}
		for rows.Next() {
			var id, name string
			if err := rows.Scan(&id, &name); err != nil {
				rows.Close()
				return out, fmt.Errorf("programmerollout: reading a partner: %w", err)
			}
			out.partners[id] = name
		}
		rows.Close()
	}
	return out, nil
}

// deliveredBy is trainings_rollout.delivered_by.
func deliveredBy(sc *scope, n names, r training) string {
	if r.delivery == "partner" {
		if name, ok := n.partners[r.partner]; ok {
			return name
		}
		return "Training partner"
	}
	m := sc.member(sc.attribute(r.responsible, r.monitor, r.schoolID))
	if m != nil && slices.Contains(m.ids(), r.responsible) {
		return memberName(m)
	}
	if name := n.people[r.responsible]; name != "" {
		return name
	}
	if m != nil {
		return memberName(m)
	}
	return "Edify staff"
}

// memberName is _member_name: the lead's own row is "Your own portfolio",
// or "{name} (own portfolio)" to an administrator reading the team.
func memberName(m *member) string {
	switch {
	case m.isLead && m.support:
		return m.name + " (own portfolio)"
	case m.isLead:
		return "Your own portfolio"
	}
	return m.name
}

// noticeText is _notice: an administrator is told whose team they read; a
// lead nobody reports to yet that the page shows their own portfolio only.
func noticeText(sc *scope) string {
	switch {
	case sc.support:
		return "You are reading " + sc.leadName + "'s team as they see it. Choose another Programme Lead in the filters."
	case len(sc.officers) == 0:
		return "No officers are assigned to you yet, so this page shows your own portfolio only. HR records who you supervise on the staff profile."
	}
	return ""
}
