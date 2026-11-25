package planningmonitor

// Planning Oversight Data Quality (country_oversight.data_quality and
// drawer_quality.html, kind=dq): every check behind the figures, what it
// means, how many records it found, the first of them and where they are
// corrected, read over the reader's dataset and tree as the feed reads the
// drawer: each check's whole line, then each sample on its own.

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// cpoSample is one record a check shows.
type cpoSample struct{ label, detail string }

// cpoCheck is data_quality.Check.
type cpoCheck struct {
	label, meaning, severity, correctAt string
	count                               int
	samples                             []cpoSample
}

func severityIf(found bool, level string) string {
	if found {
		return level
	}
	return "info"
}

// commas is f"{n:,}".
func commas(n int) string { return cpoFmt(n) }

// cpoQualityDrawer is drawer_view's kind=dq for a reader who may read it.
func cpoQualityDrawer(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string,
	now time.Time) (*screensv1.PageDrawer, error) {
	r, err := cpoReadDrawer(ctx, db, p, q, now)
	if err != nil {
		return nil, err
	}
	checks, err := cpoQualityChecks(ctx, db, r.snap)
	if err != nil {
		return nil, err
	}
	open := 0
	items := []*screensv1.DrawerItem{}
	for _, c := range checks {
		if c.count > 0 && c.severity != "info" {
			open++
		}
		parts := []string{c.label, strconv.Itoa(c.count), c.meaning}
		for _, s := range c.samples {
			parts = append(parts, strings.TrimSpace(s.label+" "+s.detail))
		}
		if c.correctAt != "" {
			parts = append(parts, "Corrected in: "+c.correctAt)
		}
		items = append(items, dText(strings.Join(parts, " ")))
		for _, s := range c.samples {
			items = append(items, dText(strings.TrimSpace(s.label+" "+s.detail)))
		}
	}
	built := now.In(cpoLocation)
	subtitle := fmt.Sprintf("%d %s · read %s · portfolio as of %s", open, pluralize(open, "check needs", "checks need")+" attention",
		built.Format("2 Jan 2006, ")+pyClock(built), r.portfolioAsOf)
	return &screensv1.PageDrawer{Title: "Planning Oversight Data Quality", Subtitle: subtitle, HasRequired: true, CancelLabel: "Cancel",
		Items: items}, nil
}

// pyClock is Django's "g:i A": the hour without a leading zero.
func pyClock(t time.Time) string {
	h := t.Hour() % 12
	if h == 0 {
		h = 12
	}
	return fmt.Sprintf("%d:%02d %s", h, t.Minute(), map[bool]string{true: "PM", false: "AM"}[t.Hour() >= 12])
}

func schoolSample(s *cpoSchool) cpoSample { return cpoSample{label: s.name, detail: s.code} }

// cpoOwnerOrder is the dataset's owners in their first school's order, the
// school-less No Owner last, as service.dataset_for files them.
func cpoOwnerOrder(d *cpoDataset) []*cpoOwner {
	seen := map[string]bool{}
	out := []*cpoOwner{}
	noOwner := rules.CountryOversight.NoOwner[0]
	for _, s := range d.schools {
		if s.ownerKey == noOwner || seen[s.ownerKey] {
			continue
		}
		seen[s.ownerKey] = true
		if o := d.owners[s.ownerKey]; o != nil {
			out = append(out, o)
		}
	}
	return out
}

// cpoQualityChecks is data_quality.checks: every check, in the order IA works them.
func cpoQualityChecks(ctx context.Context, db schooldirectory.Querier, snap *cpoSnapshot) ([]cpoCheck, error) {
	c := rules.CountryOversight
	dq := c.Page.DataQuality
	sample := dq.Sample
	d := snap.data
	noOwner, noLead := c.NoOwner[0], c.NoLead[0]
	ids := make([]string, 0, len(d.schools))
	for _, s := range d.schools {
		ids = append(ids, s.id)
	}
	limit := func(n int) int { return min(n, sample) }
	out := []cpoCheck{}

	// 1. No governed family.
	unmapped := []*cpoSchool{}
	reasons := map[string]bool{}
	for _, s := range d.schools {
		if !s.governed() {
			unmapped = append(unmapped, s)
			reasons[orElse(s.schoolType, "blank")] = true
		}
	}
	words := []string{}
	for _, t := range sortedKeys(reasons) {
		w, ok := dq.PendingFamilyDecisions[t]
		if !ok {
			w = "'" + t + "' is not a school type the planning rulebook knows."
		}
		words = append(words, w)
	}
	meaning := strings.Join(words, " ")
	if meaning == "" {
		meaning = "Every school's type is one the planning rulebook knows."
	}
	one := cpoCheck{label: "School type with no planning rule", meaning: meaning, count: len(unmapped),
		severity: severityIf(len(unmapped) > 0, "warning"), correctAt: "Product-owner decision, then the school profile"}
	for _, s := range unmapped[:limit(len(unmapped))] {
		one.samples = append(one.samples, schoolSample(s))
	}
	out = append(out, one)

	// 2. Several active owners, or an owner the assignment table disagrees with.
	rows, err := db.Query(ctx, `SELECT a.school_id, a.staff_id, COALESCE(sp.user_id, '') FROM staff_school_assignment a
LEFT JOIN staff_profile sp ON sp.id = a.staff_id WHERE a.school_id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the schools' assignments: %w", err)
	}
	assignments := map[string]int{}
	linked := map[string]map[string]bool{}
	for rows.Next() {
		var school, staff, user string
		if err := rows.Scan(&school, &staff, &user); err != nil {
			rows.Close()
			return nil, fmt.Errorf("planningmonitor: a school's assignment: %w", err)
		}
		assignments[school]++
		if linked[school] == nil {
			linked[school] = map[string]bool{}
		}
		linked[school][staff], linked[school][user] = true, true
	}
	rows.Close()
	several := map[string]bool{}
	for school, n := range assignments {
		if n > 1 {
			several[school] = true
		}
	}
	leadInTeam := []*cpoSchool{}
	for _, s := range d.schools {
		if l := linked[s.id]; s.rawOwner != "" && len(l) > 0 && !l[s.rawOwner] {
			several[s.id] = true
		}
		o := d.owners[s.ownerKey]
		if o != nil && ownerKind(o.key, o.role) == "cceo" && linked[s.id][o.leadKey] {
			leadInTeam = append(leadInTeam, s)
		}
	}
	two := cpoCheck{label: "School with several active owners", count: len(several), severity: severityIf(len(several) > 0, "critical"),
		meaning:   "The account owner and the staff-school assignment disagree, or more than one person holds the school. The account owner is counted.",
		correctAt: "School ownership transfer (Admin or Impact Assessment)"}
	// list(several)[:SAMPLE] is a set's order: the facts' order stands in.
	for _, s := range d.schools {
		if several[s.id] && len(two.samples) < sample {
			two.samples = append(two.samples, schoolSample(s))
		}
	}
	out = append(out, two)
	lead := cpoCheck{label: "PL team school appearing in PL personal scope", count: len(leadInTeam),
		severity:  severityIf(len(leadInTeam) > 0, "warning"),
		meaning:   "A Programme Lead holds an assignment to a school their CCEO owns. The school stays in the CCEO's portfolio; the Lead's personal figures never include it.",
		correctAt: "School ownership transfer"}
	for _, s := range leadInTeam[:limit(len(leadInTeam))] {
		lead.samples = append(lead.samples, schoolSample(s))
	}
	out = append(out, lead)

	// 3. Nobody holds the school, or somebody who cannot hold a portfolio.
	nobody, odd := []*cpoSchool{}, []*cpoSchool{}
	for _, s := range d.schools {
		if !s.governed() {
			continue
		}
		if s.ownerKey == noOwner {
			nobody = append(nobody, s)
			continue
		}
		if o := d.owners[s.ownerKey]; o != nil && (ownerKind(o.key, o.role) == "other" || !o.active) {
			odd = append(odd, s)
		}
	}
	three := cpoCheck{label: "School with no account owner", count: len(nobody), severity: severityIf(len(nobody) > 0, "critical"),
		meaning:   "Its Core staff slots count as a capacity deficit and its one client-rule visit falls to Partners until somebody holds it.",
		correctAt: "Staff Setup Queue"}
	for _, s := range nobody[:limit(len(nobody))] {
		three.samples = append(three.samples, schoolSample(s))
	}
	out = append(out, three)
	oddCheck := cpoCheck{label: "School held by an inactive person or a non-portfolio role", count: len(odd),
		severity:  severityIf(len(odd) > 0, "warning"),
		meaning:   "Only CCEOs and Programme Leads carry staff visit capacity; any other holder's schools show their Core staff slots as a deficit.",
		correctAt: "School ownership transfer"}
	for _, s := range odd[:limit(len(odd))] {
		o := d.owners[s.ownerKey]
		oddCheck.samples = append(oddCheck.samples, cpoSample{label: s.name, detail: s.code + " · " + o.name + " (" + orElse(o.role, "no role") + ")"})
	}
	out = append(out, oddCheck)

	// 4. Officers with no Programme Lead, or with several.
	noLeadOfficers, severalLeads := []*cpoOwner{}, []*cpoOwner{}
	for _, o := range cpoOwnerOrder(d) {
		if ownerKind(o.key, o.role) != "cceo" {
			continue
		}
		if o.leadKey == noLead || o.leadKey == "" {
			noLeadOfficers = append(noLeadOfficers, o)
		}
		if len(o.leadKeys) > 1 {
			severalLeads = append(severalLeads, o)
		}
	}
	four := cpoCheck{label: "CCEO with no Programme Lead, or with several", count: len(noLeadOfficers) + len(severalLeads),
		severity:  severityIf(len(noLeadOfficers)+len(severalLeads) > 0, "warning"),
		meaning:   "A CCEO's schools sit under the Lead they report to directly. With none they sit under 'No Programme Lead'; with several, the first by name is used.",
		correctAt: "Staff supervisor assignment"}
	for _, o := range noLeadOfficers[:limit(len(noLeadOfficers))] {
		four.samples = append(four.samples, cpoSample{label: o.name, detail: "No Programme Lead"})
	}
	for _, o := range severalLeads[:limit(len(severalLeads))] {
		four.samples = append(four.samples, cpoSample{label: o.name, detail: fmt.Sprintf("%d Programme Leads", len(o.leadKeys))})
	}
	out = append(out, four)

	// 5. Package work that fills no slot, and hand-overs holding none.
	unlinked, err := cpoUncreditedWork(ctx, db, ids, d.window.fy)
	if err != nil {
		return nil, err
	}
	five := cpoCheck{label: "Visit activity not linked to an eligible slot", count: len(unlinked), severity: "warning",
		meaning:   "Core-school visits and trainings that fill no package slot (V1–V4, T1–T4). They still count here by type, but the package does not know them.",
		correctAt: "manage.py repair_core_data / package repair"}
	five.samples = unlinked[:limit(len(unlinked))]
	out = append(out, five)
	held, err := cpoUnreservedHandovers(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	handovers := cpoCheck{label: "Partner assignment with no slot", count: len(held), severity: severityIf(len(held) > 0, "warning"),
		meaning: "An open Core-school handover that holds no package slot.", correctAt: "Partner Monitoring"}
	handovers.samples = held[:limit(len(held))]
	out = append(out, handovers)

	// 6. More planned work than slots, and schools planned twice.
	type beyond struct {
		n int
		s *cpoSchool
	}
	over := []beyond{}
	twice := []*cpoSchool{}
	for _, s := range d.schools {
		if !s.governed() {
			continue
		}
		req := c.slots(s.family)
		totals, _ := partnerTotals(s, nil)
		n := 0
		switch s.family {
		case c.CoreFamily:
			n = max(0, totals[pSchedT]-req.Partner) + max(0, s.staff[2]-req.Staff)
		case c.ClientFamily:
			n = max(0, s.staff[2]+totals[pSchedT]-1)
		default:
			n = s.staff[2] + totals[pSchedT]
		}
		if n > 0 {
			over = append(over, beyond{n, s})
		}
		if len(duplicateReasons(s)) > 0 {
			twice = append(twice, s)
		}
	}
	sort.SliceStable(over, func(i, j int) bool { return over[i].n > over[j].n })
	slotLinks, err := cpoDuplicateSlotLinks(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	six := cpoCheck{label: "Two activities claiming the same slot", count: len(over) + slotLinks,
		severity:  severityIf(len(over)+slotLinks > 0, "warning"),
		meaning:   "Schools with more planned visits than visit slots, and package slots linked to the same activity twice. Each slot is counted once; the extra work claims nothing.",
		correctAt: "The school's plan (cancel the duplicate)"}
	for _, b := range over[:limit(len(over))] {
		six.samples = append(six.samples, cpoSample{label: b.s.name, detail: fmt.Sprintf("%s · %d beyond the slots", b.s.code, b.n)})
	}
	out = append(out, six)
	planned := cpoCheck{label: "School planned twice", count: len(twice), severity: severityIf(len(twice) > 0, "warning"),
		meaning:   "A Client, Core Trained or Core Graduate school is visited by staff or by a Partner, never both, and once for each kind of visit; a Core school takes two staff and two Partner visits. These carry more. Each is counted once as coverage, and the Schools Planned Twice table lists every plan at every one of them.",
		correctAt: "The school's plan (cancel the duplicate)"}
	for _, s := range twice[:limit(len(twice))] {
		why := []string{}
		for _, r := range duplicateReasons(s) {
			why = append(why, c.Page.TableWords.Duplicates[r])
		}
		planned.samples = append(planned.samples, cpoSample{label: s.name, detail: s.code + " · " + strings.Join(why, "; ")})
	}
	out = append(out, planned)

	// 7–13 read the records themselves.
	rest, err := cpoRecordChecks(ctx, db, snap, ids, sample)
	if err != nil {
		return nil, err
	}
	return append(out, rest...), nil
}

func sortedKeys(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// activityLine is a session's or a visit's sample detail:
// "<activity_type> · <planned date or ...>".
func activityLine(activityType string, planned *time.Time, undated string) string {
	day := undated
	if planned != nil {
		day = planned.Format("2006-01-02")
	}
	return activityType + " · " + day
}

// cpoUncreditedWork is uncredited_package_work over the reader's schools:
// live package work at Core Schools that fills no slot, oldest first by
// school code.
func cpoUncreditedWork(ctx context.Context, db schooldirectory.Querier, ids []string, fy string) ([]cpoSample, error) {
	dq := rules.CountryOversight.Page.DataQuality
	outside, err := visitgate.ProjectsOutsideSSA(ctx, db, schoolprofile.GateRules())
	if err != nil {
		return nil, err
	}
	visitTypes := append(append([]string{}, dq.PackageVisitTypes...), dq.PackageTrainingTypes...)
	notPurposes := append([]string{dq.CompanionVisitPurpose}, dq.NonPackageVisitPurposes...)
	outreachPurposes := append([]string{dq.CompanionVisitPurpose}, dq.OutreachVisitPurposes...)
	rows, err := db.Query(ctx, `SELECT COALESCE(s.name, a.id), COALESCE(a.activity_type, ''), a.planned_date
FROM activity a JOIN school s ON s.id = a.school_id
WHERE a.deleted_at IS NULL AND s.school_type = 'core' AND a.school_id = ANY($1) AND a.fy = $2
  AND NOT (COALESCE(a.status, '') = ANY($3))
  AND (
    (a.activity_type = ANY($4) AND a.cluster_id IS NULL AND NOT (COALESCE(a.purpose_type, '') = ANY($5) AND a.purpose_type IS NOT NULL))
    OR ((a.activity_type = ANY($6) OR a.purpose_type = ANY($7)) AND COALESCE(a.delivery_type, '') <> 'partner' AND a.cluster_id IS NULL
        AND NOT (a.activity_type = ANY($8)) AND NOT (COALESCE(a.purpose_type, '') = ANY($9) AND a.purpose_type IS NOT NULL))
    OR (a.purpose_type = $10 AND a.cluster_id IS NULL)
  )
  AND NOT (COALESCE(a.project_id, '') = ANY($11) AND a.project_id IS NOT NULL)
  AND NOT EXISTS (SELECT 1 FROM activity_catalogue_item c WHERE c.id = a.training_course_id AND c.universal_training)
  AND NOT EXISTS (SELECT 1 FROM activity_catalogue_item c WHERE c.id = a.catalogue_item_id AND c.universal_training)
  AND NOT EXISTS (SELECT 1 FROM activity t JOIN activity_catalogue_item c ON c.id = t.training_course_id
                  WHERE t.paired_school_visit_id = a.id AND c.universal_training)
  AND NOT EXISTS (SELECT 1 FROM core_activity_slot sl WHERE sl.activity_id = a.id)
ORDER BY s.school_id, a.planned_date, a.created_at, a.id`,
		ids, fy, dq.UncreditedStatuses, visitTypes, notPurposes, dq.DataCollectionVisitTypes, dq.DataCollectionVisitPurposes,
		dq.OutreachVisitTypes, outreachPurposes, dq.CompanionVisitPurpose, nonNilIDs(outside))
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the package work no slot holds: %w", err)
	}
	return collectActivityLines(rows, "undated")
}

func nonNilIDs(ids []string) []string {
	if ids == nil {
		return []string{}
	}
	return ids
}

func collectActivityLines(rows pgx.Rows, undated string) ([]cpoSample, error) {
	defer rows.Close()
	out := []cpoSample{}
	for rows.Next() {
		var label, kind string
		var day *time.Time
		if err := rows.Scan(&label, &kind, &day); err != nil {
			return nil, fmt.Errorf("planningmonitor: a sample: %w", err)
		}
		out = append(out, cpoSample{label: label, detail: activityLine(kind, day, undated)})
	}
	return out, rows.Err()
}

// cpoDuplicateSlotLinks is _duplicate_slot_links: activities two package
// slots of the reader's schools both claim.
func cpoDuplicateSlotLinks(ctx context.Context, db schooldirectory.Querier, ids []string) (int, error) {
	var n int
	err := db.QueryRow(ctx, `SELECT count(*) FROM (SELECT sl.activity_id FROM core_activity_slot sl
WHERE sl.activity_id IS NOT NULL AND sl.school_id IN (SELECT school_id FROM school WHERE id = ANY($1))
GROUP BY sl.activity_id HAVING count(*) > 1) x`, ids).Scan(&n)
	if err != nil {
		return 0, fmt.Errorf("planningmonitor: the slots linked twice: %w", err)
	}
	return n, nil
}
