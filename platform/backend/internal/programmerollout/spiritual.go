package programmerollout

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// spiritualFacts is what spiritual_rollout reads for the view.
type spiritualFacts struct {
	latest, prev string
	scores       []teamScore
	perSchool    map[[3]string][]float64
	weak         []weakRow
	gaps         int
	programmes   []programmeRow
	deliverers   []*deliverer
	delivered    int
	toDeliver    int
	// The Regional Lead's shared observations, and what naming them needs.
	observations []observation
	catalogue    map[string]programme
	courses      map[string]course
	names        names
}

// programmeRow is one programme of "Spiritual programmes".
type programmeRow struct {
	fold
	name, family string
}

// deliverer is one row of "Delivered by officers and partners".
type deliverer struct {
	name, kind           string
	families             map[string]int
	delivered, toDeliver int
}

// spiritual is the Spiritual Formation view's blocks (spiritual_rollout, the
// view's tiles and partials/programme_rollout/spiritual.html), each long
// table a page at a time. A pager carrying more than one other query key
// hands on.
func (s *Service) spiritual(ctx context.Context, sc *scope, fy string, query url.Values) ([]*screensv1.PageBlock, bool, error) {
	f, served, err := s.spiritualFacts(ctx, sc, fy)
	if err != nil || !served {
		return nil, served, err
	}
	people := sc.rows(nil)
	weakStart, weakEnd, weakPager, ok := paged(query, weakPageParam, len(f.weak))
	if !ok {
		return nil, false, nil
	}
	programmeStart, programmeEnd, programmePager, ok := paged(query, "rollout_programmes_page", len(f.programmes))
	if !ok {
		return nil, false, nil
	}
	delivererStart, delivererEnd, delivererPager, ok := paged(query, "rollout_deliverers_page", len(f.deliverers))
	if !ok {
		return nil, false, nil
	}
	biblicalStart, biblicalEnd, biblicalPager, ok := paged(query, "biblical_page", len(f.observations))
	if !ok {
		return nil, false, nil
	}
	blocks := []*screensv1.PageBlock{strip("Rollout at a glance", spiritualTiles(f)),
		titled("Christlike Behaviour and the Word of God"), pairFigures(f), table(officerPairTable(f, firstOfficers(people), fy)),
		titled("Schools weakest in " + pairText(" or "))}
	blocks = append(blocks, withPager(weakTable(f.weak[weakStart:weakEnd], len(f.weak) == 0), weakPager)...)
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
		panelText("A response is any activity this year at the school, or at its cluster, whose focus or secondary interventions include the weak area. Plan is offered on your own schools only; an officer plans their own.", "")}}}},
		titled("Spiritual programmes"))
	blocks = append(blocks, withPager(programmeTable(f.programmes[programmeStart:programmeEnd]), programmePager)...)
	blocks = append(blocks, titled("Delivered by officers and partners"))
	blocks = append(blocks, withPager(delivererTable(f.deliverers[delivererStart:delivererEnd]), delivererPager)...)
	blocks = append(blocks, titled("Biblical integration ratings"))
	return append(blocks, withPager(biblicalTable(f, sc, f.observations[biblicalStart:biblicalEnd]), biblicalPager)...), true, nil
}

// pairText is the pair's abbreviations joined: "CB or WOG".
func pairText(joint string) string {
	return abbr(rules.Spiritual.Interventions[0]) + joint + abbr(rules.Spiritual.Interventions[1])
}

// spiritualFacts reads the cycle, the team's and officers' scores, the weak
// schools and the programmes.
func (s *Service) spiritualFacts(ctx context.Context, sc *scope, fy string) (*spiritualFacts, bool, error) {
	f := &spiritualFacts{}
	portfolio := sc.schoolIDs()
	var err error
	if len(portfolio) > 0 {
		if f.latest, f.prev, err = s.cycleFYs(ctx, portfolio, fy); err != nil {
			return nil, true, err
		}
		if f.scores, err = s.teamScores(ctx, portfolio, f.latest, f.prev); err != nil {
			return nil, true, err
		}
	} else {
		for _, code := range rules.Spiritual.Interventions {
			f.scores = append(f.scores, teamScore{code: code, band: "No SSA", tone: "neutral"})
		}
	}
	cycles := []string{}
	for _, c := range []string{f.latest, f.prev} {
		if c != "" {
			cycles = append(cycles, c)
		}
	}
	if f.perSchool, err = s.officerScores(ctx, portfolio, cycles); err != nil {
		return nil, true, err
	}
	weak, served, err := s.weakRows(ctx, sc, fy, portfolio)
	if err != nil || !served {
		return nil, served, err
	}
	f.weak = weak
	for _, r := range weak {
		if r.hasGap {
			f.gaps++
		}
	}
	if err := s.readProgrammes(ctx, sc, fy, f); err != nil {
		return nil, true, err
	}
	if f.observations, err = s.observations(ctx, sc, fy); err != nil {
		return nil, true, err
	}
	referenced := []string{}
	for _, o := range f.observations {
		if o.courseID != "" {
			referenced = append(referenced, o.courseID)
		}
	}
	if _, f.courses, err = courses(ctx, s.db, referenced); err != nil {
		return nil, true, err
	}
	if f.names, err = s.names(ctx, sc, observationTrainings(f.observations)); err != nil {
		return nil, true, err
	}
	return f, true, nil
}

// spiritualObservations is the observations of a spiritual programme.
func (f *spiritualFacts) spiritualObservations() []observation {
	out := []observation{}
	for _, o := range f.observations {
		if _, ok := f.catalogue[o.courseID]; ok && o.courseID != "" {
			out = append(out, o)
		}
	}
	return out
}

// biblicalTable is "Biblical integration ratings": every shared observation
// of the year, latest first, with its Biblical integration rating.
func biblicalTable(f *spiritualFacts, sc *scope, rows []observation) *screensv1.PageTable {
	t := &screensv1.PageTable{Columns: columns("Training", "Delivered by", "Observed", "Biblical integration", "Recommendation", "State")}
	for _, o := range rows {
		activity := training{}
		if o.activity != nil {
			activity = *o.activity
		}
		rating := "Not rated"
		if o.biblical != nil && *o.biblical != 0 {
			rating = rules.Observations.RatingLabels[strconv.Itoa(*o.biblical)]
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{cell(observedTraining(o, f.courses)),
			cell(deliveredBy(sc, f.names, activity)), cell(day(o.heldOn, " Jan 2006")), cell(rating),
			cell(orDash(rules.Observations.RecommendationLabels[o.recommendation])), cell(feedbackState(o, sc))}})
	}
	if len(f.observations) == 0 {
		empty(t, "No observation has been shared with you this year.", "Biblical integration is the first criterion the Regional Lead rates on every training observed.")
	}
	return t
}

// weakRows is the weak schools as the table lists them: without a planned
// response first, the lowest score first, by name, then by school. The
// lead's own weak school with a gap would carry a plan control, and hands
// on.
func (s *Service) weakRows(ctx context.Context, sc *scope, fy string, portfolio []string) ([]weakRow, bool, error) {
	weak, err := s.weakest(ctx, portfolio)
	if err != nil {
		return nil, true, err
	}
	answered, err := s.responses(ctx, sc, fy, weak)
	if err != nil {
		return nil, true, err
	}
	clusterNames, err := s.clusterNames(ctx, sc.clusterIDs())
	if err != nil {
		return nil, true, err
	}
	own := map[string]bool{}
	if sc.lead != nil && !sc.support {
		own = sc.lead.schools
	}
	rows := []weakRow{}
	for id, items := range weak {
		row := weakSchool(sc, id, items, answered, clusterNames)
		if row.hasGap && own[id] {
			// The lead plans their own portfolio only; a supervised school is
			// the officer's to plan.
			row.planURL = "/planning/schedule-modal?school_id=" + id + "&focus_intervention=" + row.firstMissing
		}
		rows = append(rows, row)
	}
	sort.Slice(rows, func(i, j int) bool {
		a, b := rows[i], rows[j]
		if a.hasGap != b.hasGap {
			return a.hasGap
		}
		if a.lowest != b.lowest {
			return a.lowest < b.lowest
		}
		if a.name != b.name {
			return a.name < b.name
		}
		return a.id < b.id
	})
	return rows, true, nil
}

// weakSchool is one weak school's row: its weak areas, the first response
// to each, and whether any is still unanswered.
func weakSchool(sc *scope, id string, items []weakItem, answered map[[2]string][]response, clusterNames map[string]string) weakRow {
	school := sc.schools[id]
	row := weakRow{id: id, code: school.code, name: school.name, cluster: clusterNames[school.cluster], lowest: items[0].score}
	said, parts := []string{}, []string{}
	missing := 0
	for _, w := range items {
		row.lowest = min(row.lowest, w.score)
		parts = append(parts, abbr(w.code)+" "+strconv.FormatFloat(schooldirectory.PyRound1(w.score), 'f', 1, 64))
		found := answered[[2]string{id, w.code}]
		if len(found) == 0 {
			if missing == 0 {
				row.firstMissing = w.code
			}
			missing++
			continue
		}
		text := abbr(w.code) + ": " + found[0].name
		if found[0].planned != nil {
			text += " · " + day(*found[0].planned, " Jan 2006")
		}
		said = append(said, text)
	}
	row.weak, row.responses = strings.Join(parts, " · "), strings.Join(said, " · ")
	if row.responses == "" {
		row.responses = "Nothing planned this FY"
	}
	switch {
	case missing == 0:
		row.state = "Planned"
	case len(said) > 0:
		row.state = "Partly planned"
	default:
		row.state = "No plan"
	}
	row.hasGap = missing > 0
	names := []string{}
	for _, owner := range sc.ownersBySchool[id] {
		if m := sc.member(owner); m != nil {
			names = append(names, memberName(m))
		}
	}
	row.officer = strings.Join(names, ", ")
	return row
}

// readProgrammes reads the team's spiritual programmes of the year and folds
// them by programme and by who delivered them.
func (s *Service) readProgrammes(ctx context.Context, sc *scope, fy string, f *spiritualFacts) error {
	catalogue, ids, err := s.programmes(ctx)
	if err != nil {
		return err
	}
	rows := []training{}
	if len(catalogue) > 0 && len(sc.ownerByID) > 0 {
		where, args := sc.activityFilter([]any{fy, ids, rules.NotPlannedStatuses})
		if rows, err = readTrainings(ctx, s.db, "SELECT "+trainingColumns+` WHERE `+where+` AND a.fy = $1 AND a.deleted_at IS NULL
  AND (a.training_course_id = ANY($2) OR a.catalogue_item_id = ANY($2)) AND NOT COALESCE(a.status = ANY($3), FALSE)
ORDER BY a.planned_date ASC NULLS LAST, a.id`, args); err != nil {
			return err
		}
	}
	reached, err := reach(ctx, s.db, rows)
	if err != nil {
		return err
	}
	byProgramme := map[string][]training{}
	for _, r := range rows {
		id := programmeOf(r, catalogue)
		byProgramme[id] = append(byProgramme[id], r)
	}
	for _, id := range ids {
		if len(byProgramme[id]) == 0 {
			continue
		}
		folds := folded(byProgramme[id], reached)
		f.programmes = append(f.programmes, programmeRow{fold: folds, name: catalogue[id].name, family: familyLabel(catalogue[id].family)})
		f.delivered += folds.delivered
		f.toDeliver += folds.toDeliver
	}
	sort.SliceStable(f.programmes, func(i, j int) bool {
		a, b := f.programmes[i], f.programmes[j]
		if a.family != b.family {
			return a.family < b.family
		}
		if a.delivered != b.delivered {
			return a.delivered > b.delivered
		}
		return a.name < b.name
	})
	partners := names{}
	if withPartners := rowsWithPartners(rows); len(withPartners) > 0 {
		if partners, err = s.names(ctx, sc, withPartners); err != nil {
			return err
		}
	}
	f.deliverers = deliverersOf(sc, rows, catalogue, partners.partners)
	f.catalogue = catalogue
	return nil
}

// deliverersOf folds the programmes' sessions by who delivered them:
// officers and the lead first, then partners, most delivered first, by name.
func deliverersOf(sc *scope, rows []training, catalogue map[string]programme, partners map[string]string) []*deliverer {
	out := []*deliverer{}
	byKey := map[[2]string]*deliverer{}
	for _, r := range rows {
		key, name, kind := [2]string{"partner", r.partner}, "Training partner", "Training partner"
		if r.delivery == "partner" {
			if n, ok := partners[r.partner]; ok {
				name = n
			}
		} else {
			owner := sc.attribute(r.responsible, r.monitor, r.schoolID)
			key, name, kind = [2]string{"member", owner}, "Edify staff", "Officer"
			if m := sc.member(owner); m != nil {
				name = memberName(m)
				if m.isLead {
					kind = "Programme Lead"
				}
			}
		}
		d, ok := byKey[key]
		if !ok {
			d = &deliverer{name: name, kind: kind, families: map[string]int{}}
			byKey[key] = d
			out = append(out, d)
		}
		switch {
		case slices.Contains(rules.CompletedStatuses, r.status):
			d.families[catalogue[programmeOf(r, catalogue)].family]++
			d.delivered++
		case slices.Contains(rules.LiveStatuses, r.status):
			d.toDeliver++
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		a, b := out[i], out[j]
		if (a.kind == "Training partner") != (b.kind == "Training partner") {
			return b.kind == "Training partner"
		}
		if a.delivered != b.delivered {
			return a.delivered > b.delivered
		}
		return a.name < b.name
	})
	return out
}

// spiritualTiles is _spiritual_metrics.
func spiritualTiles(f *spiritualFacts) []tile {
	tiles := []tile{}
	for _, t := range f.scores {
		helper := "no confirmed SSA yet"
		switch {
		case t.delta != nil:
			helper = fmt.Sprintf("%+.1f vs FY %s", *t.delta, f.prev)
		case t.score != nil:
			helper = "no earlier cycle to compare"
		}
		value, tone := "—", "info"
		if t.score != nil {
			value, tone = strconv.FormatFloat(*t.score, 'f', 1, 64), t.tone
		}
		tiles = append(tiles, tile{"Team " + abbr(t.code) + " Average", value, helper, tone, ""})
	}
	gapTone := "success"
	if f.gaps > 0 {
		gapTone = "danger"
	}
	return append(tiles,
		tile{"Schools Weak in " + pairText(" or ") + " Without a Plan", strconv.Itoa(f.gaps),
			fmt.Sprintf("of %d with %s among the three weakest", len(f.weak), pairText(" or ")), gapTone, ""},
		tile{"Spiritual Programmes Delivered", strconv.Itoa(f.delivered),
			fmt.Sprintf("Christian Transformation, CC-SEL and camps · %d still to deliver", f.toDeliver), "info", ""},
		biblicalTile(f),
	)
}

// pairFigures is the pair's figures beside the weak schools and Biblical
// integration, as the feed reads them: a figure with a score is a row and
// its line, one without three lines of text.
func pairFigures(f *spiritualFacts) *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{}
	for _, t := range f.scores {
		label := abbr(t.code) + " · " + rules.InterventionLabels[t.code]
		if t.score == nil {
			items = append(items, panelText(label, ""), panelText("No data", ""), panelText("No confirmed assessment", ""))
			continue
		}
		meta, tone := t.band+" · no earlier cycle", ""
		if t.delta != nil {
			meta = signed(*t.delta) + " vs FY " + f.prev + " · " + t.band
			switch {
			case *t.delta > 0:
				tone = "success"
			case *t.delta < 0:
				tone = "danger"
			default:
				tone = "neutral"
			}
		}
		items = append(items,
			&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{
				{Label: label, Value: strconv.FormatFloat(*t.score, 'f', 1, 64) + " / 10"}}}}},
			panelText(meta, tone))
	}
	items = append(items,
		panelText("Weak schools without a plan", ""), panelText(intcomma(f.gaps)+" of "+intcomma(len(f.weak)), ""),
		panelText("Spiritual pair among the three weakest", ""),
	)
	spiritual := f.spiritualObservations()
	if b := foldObservations(spiritual).biblical; b != nil {
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{
			{Label: "Biblical integration", Value: pyFloat(*b) + " / 4"}}}}})
	} else {
		items = append(items, panelText("Biblical integration", ""), panelText("No data", ""))
	}
	items = append(items,
		panelText(fmt.Sprintf("Regional Lead, on %d spiritual %s", len(spiritual), plural(len(spiritual), "programme")), ""))
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: items}}}
}

// officerPairTable is each officer's average of the pair on the latest
// cycle, the change from the one before, and their weak schools.
func officerPairTable(f *spiritualFacts, people []*member, fy string) *screensv1.PageTable {
	labels := []string{"Officer", "Schools"}
	for _, code := range rules.Spiritual.Interventions {
		labels = append(labels, abbr(code), abbr(code)+" change")
	}
	t := &screensv1.PageTable{Columns: columns(append(labels, "Weak schools", "Without a plan", "")...)}
	for _, m := range people {
		name := &screensv1.PageCell{Text: memberName(m)}
		owner := m.staffID
		if m.isLead {
			owner = "mine"
		} else {
			name.Href = "/staff/" + m.userID + "?from=" + Path
		}
		cells := []*screensv1.PageCell{name, num(len(m.schools))}
		for _, code := range rules.Spiritual.Interventions {
			current, previous := memberScore(f, m, code, f.latest), memberScore(f, m, code, f.prev)
			scoreText, change := "No SSA", "—"
			if current != nil {
				scoreText = strconv.FormatFloat(*current, 'f', 1, 64)
			}
			if d := roundDelta(current, previous); d != nil {
				change = signed(*d)
			}
			cells = append(cells, cell(scoreText), cell(change))
		}
		weakHere, gapsHere := 0, 0
		for _, r := range f.weak {
			if m.schools[r.id] {
				weakHere++
				if r.hasGap {
					gapsHere++
				}
			}
		}
		cells = append(cells, num(weakHere), num(gapsHere), &screensv1.PageCell{Actions: []*screensv1.PageAction{
			{Key: "button", Label: "Oversight", Primary: true, Enabled: true, Href: "/team-planning-oversight/?owner=" + owner + "&fy=" + fy}}})
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells})
	}
	if len(people) == 0 {
		empty(t, "No officers or portfolio schools on this team yet.", "")
	}
	return t
}

// memberScore is officer_score: the flat mean of a member's schools' scores
// for one intervention in one cycle.
func memberScore(f *spiritualFacts, m *member, code, cycle string) *float64 {
	if cycle == "" {
		return nil
	}
	values := []float64{}
	for id := range m.schools {
		values = append(values, f.perSchool[[3]string{id, cycle, code}]...)
	}
	return mean(values)
}

// weakTable is one page of the weak schools.
func weakTable(rows []weakRow, none bool) *screensv1.PageTable {
	t := &screensv1.PageTable{Columns: columns("School ID", "School", "Officer", "Cluster", "Weak areas", "Planned response", "State", "")}
	for _, r := range rows {
		name := &screensv1.PageCell{Text: r.name}
		if ref := strings.TrimSpace(r.code); ref != "" && r.name != "" {
			name.Href = "/schools/" + url.PathEscape(ref)
		}
		actions := []*screensv1.PageAction{{Key: "button", Label: "School", Primary: true, Enabled: true, Href: "/schools/" + r.id}}
		if r.planURL != "" {
			// School and Plan are one Actions menu (owner, 2026-09-26).
			actions = []*screensv1.PageAction{
				{Key: "menu", Label: "School", Enabled: true, Href: "/schools/" + r.id},
				{Key: "menu", Label: "Plan", Enabled: true, Href: r.planURL, Drawer: true},
			}
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{cell(orDash(r.code)), name, cell(orDash(r.officer)),
			cell(orElse(r.cluster, "Not in a cluster")), cell(r.weak), cell(r.responses), cell(r.state), {Actions: actions}}})
	}
	if none {
		empty(t, "No portfolio school has the spiritual pair among its three weakest interventions.", "Schools appear here from their latest confirmed SSA.")
	}
	return t
}

func orDash(text string) string { return orElse(text, "—") }

func orElse(text, fallback string) string {
	if text == "" {
		return fallback
	}
	return text
}

// programmeTable is "Spiritual programmes".
func programmeTable(rows []programmeRow) *screensv1.PageTable {
	t := &screensv1.PageTable{Columns: columns("Programme", "Family", "Planned", "Delivered", "Still to deliver", "Staff · partner", "Schools reached")}
	for _, r := range rows {
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{cell(r.name), cell(r.family), cell(strconv.Itoa(r.planned)),
			cell(strconv.Itoa(r.delivered)), cell(strconv.Itoa(r.toDeliver)), cell(fmt.Sprintf("%d · %d", r.byStaff, r.byPartner)), num(r.schoolsReached)}})
	}
	if len(rows) == 0 {
		empty(t, "No Christian Transformation, CC-SEL or camp programme is planned by the team this year.", "")
	}
	return t
}

// delivererTable is "Delivered by officers and partners".
func delivererTable(rows []*deliverer) *screensv1.PageTable {
	labels := []string{"Delivered by"}
	for _, f := range rules.Spiritual.Families {
		labels = append(labels, f[1])
	}
	t := &screensv1.PageTable{Columns: columns(append(labels, "Still to deliver")...)}
	for _, d := range rows {
		cells := []*screensv1.PageCell{cell(d.name)}
		for _, f := range rules.Spiritual.Families {
			cells = append(cells, cell(strconv.Itoa(d.families[f[0]])))
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: append(cells, cell(strconv.Itoa(d.toDeliver)))})
	}
	if len(rows) == 0 {
		empty(t, "Nothing delivered or scheduled yet.", "")
	}
	return t
}

// rowsWithPartners is the rows the partner names are read for.
func rowsWithPartners(rows []training) []training {
	out := []training{}
	for _, r := range rows {
		if r.partner != "" {
			out = append(out, training{partner: r.partner})
		}
	}
	return out
}

// biblicalTile is the Biblical Integration Rating tile: the average over
// every shared observation of the year.
func biblicalTile(f *spiritualFacts) tile {
	value, tone := "—", "info"
	b := foldObservations(f.observations).biblical
	if b != nil {
		value = pyFloat(*b) + " / 4"
		if *b >= 3 {
			tone = "success"
		}
	}
	n := len(f.observations)
	return tile{"Biblical Integration Rating", value, fmt.Sprintf("across %d Regional Lead %s", n, plural(n, "observation")), tone, ""}
}
