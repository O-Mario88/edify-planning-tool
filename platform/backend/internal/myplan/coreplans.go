package myplan

import (
	"context"
	"net/url"
	"slices"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// CoreSchool is one school Core School Oversight shows: its primary key
// and its School ID ("" for none, as the performance record carries it).
type CoreSchool struct {
	PK, Code string
}

// Sheet is one of table_export's sheets as the page shows it: its title,
// its headings and each row's cells written as the page writes them.
type Sheet struct {
	Title   string
	Headers []string
	Rows    [][]string
	// Unported is a sheet holding a partner's completed work, which its
	// uploaded form decides and the gateway may not read (evidence_record
	// is refused to it): its rows are not drawn as the existing code
	// draws them, and the caller leaves the page to the existing code.
	Unported bool
}

// coreActivityIDs is table_export.core_school_activity_ids: every live
// activity of fy at these schools, the group sessions they are invited to
// or attended, and the cluster trainings of their clusters planned before
// invitations were recorded by name.
func coreActivityIDs(ctx context.Context, db schooldirectory.Querier, pks []string, fy string) ([]string, error) {
	aside := []string{}
	for _, s := range rules.Plan.ExcludedStatuses {
		if s != "closed" {
			aside = append(aside, s)
		}
	}
	return idsWhere(ctx, db, `WITH live AS (
  SELECT a.id, a.school_id, a.cluster_id, a.activity_type FROM activity a
  WHERE a.fy = $2 AND a.deleted_at IS NULL AND NOT COALESCE(a.status = ANY($3), false))
SELECT id FROM live WHERE school_id = ANY($1)
UNION SELECT id FROM live WHERE id IN (
  SELECT activity_id FROM cluster_activity_attendance WHERE school_id = ANY($1) AND (invited OR attended))
UNION SELECT id FROM live WHERE school_id IS NULL AND activity_type = ANY($4)
  AND cluster_id IN (SELECT cluster_id FROM school WHERE id = ANY($1) AND cluster_id IS NOT NULL AND deleted_at IS NULL)
  AND NOT (id IN (SELECT activity_id FROM cluster_activity_attendance))`, pks, fy, aside, rules.Rows.TrainingTypes)
}

// CoreSchoolPlans is table_export.core_school_plans: the Core School Visits
// and Core School Trainings sheets of these schools' year, My Plan's own
// rows of them. ErrUnported names a plan whose rows need a part Go does not
// draw yet.
func CoreSchoolPlans(ctx context.Context, db schooldirectory.Querier, schools []CoreSchool, fy string, now time.Time) (visits, trainings Sheet, err error) {
	pks := make([]string, 0, len(schools))
	codes := map[string]bool{}
	for _, s := range schools {
		pks = append(pks, s.PK)
		codes[s.Code] = true
	}
	visits = Sheet{Title: rules.Rows.CoreVisits.Title, Headers: rules.Rows.CoreVisits.Headers}
	trainings = Sheet{Title: rules.Rows.CoreTrainings.Title, Headers: rules.Rows.CoreTrainings.Headers}
	ids, err := coreActivityIDs(ctx, db, pks, fy)
	if err != nil {
		return visits, trainings, err
	}
	visitRows, trainingRows, err := coreRows(ctx, db, ids, now)
	if err != nil {
		return visits, trainings, err
	}
	mine := func(r *row) bool { return !r.schoolID.null && codes[r.schoolID.value] }
	for _, r := range visitRows {
		if mine(r) {
			visits.Rows = append(visits.Rows, visitCells(r))
			visits.Unported = visits.Unported || r.needsEvidence
		}
	}
	for _, r := range trainingRows {
		if mine(r) {
			trainings.Rows = append(trainings.Rows, trainingCells(r))
			trainings.Unported = trainings.Unported || r.needsEvidence
		}
	}
	return visits, trainings, nil
}

// page is what get_frontend_context reads once for all the rows.
type page struct {
	names    names
	leads    map[string]bool
	awaiting map[string]bool
	lines    costLines
	requests map[string]*string
	amounts  map[string]*int64
	notes    map[string]string
	slots    coreSlots
	today    time.Time
}

func readPage(ctx context.Context, db schooldirectory.Querier, acts []*activity, now time.Time) (*page, error) {
	p := &page{}
	y, m, d := now.In(kampala).Date()
	p.today = time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
	ids := make([]string, 0, len(acts))
	var codes []string
	for _, a := range acts {
		ids = append(ids, a.id)
		if str(a.schoolType) == "core" && isSet(a.schoolCode) && !in(codes, *a.schoolCode) {
			codes = append(codes, *a.schoolCode)
		}
	}
	var err error
	if p.lines, err = readCostLines(ctx, db, ids); err != nil {
		return nil, err
	}
	if p.requests, err = firstRequests(ctx, db, p.lines); err != nil {
		return nil, err
	}
	if p.amounts, err = minimumAmounts(ctx, db, ids); err != nil {
		return nil, err
	}
	if p.notes, err = pairNotes(ctx, db, acts, p.lines); err != nil {
		return nil, err
	}
	if p.slots, err = readCoreSlots(ctx, db, codes); err != nil {
		return nil, err
	}
	if p.leads, err = leadVerifiedIDs(ctx, db); err != nil {
		return nil, err
	}
	if p.awaiting, err = awaitingSSA(ctx, db, acts); err != nil {
		return nil, err
	}
	if p.names, err = readNames(ctx, db); err != nil {
		return nil, err
	}
	return p, nil
}

// newRow is the loop's activity_data for one activity, with the Core
// details read.
func (p *page) newRow(a *activity, isCore bool) *row {
	r := &row{a: a}
	switch {
	case !a.hasSchool:
		r.schoolID = schoolID{}
	case a.schoolCode == nil:
		r.schoolID = schoolID{null: true}
	default:
		r.schoolID = schoolID{value: *a.schoolCode}
	}
	switch {
	case a.hasSchool:
		r.schoolName = str(a.schoolName)
		r.schoolDistrict = "—"
		if isSet(a.schoolDistrictID) {
			r.schoolDistrict = str(a.schoolDistrictName)
		}
	case str(a.planningSource) == "manual_work_plan" || in(rules.Rows.ProgrammeEventTypes, a.activityType):
		r.schoolName = "Programme activity"
	case a.hasCluster:
		r.schoolName = str(a.clusterName)
	default:
		r.schoolName = "Unknown School"
	}
	switch {
	case a.hasCluster:
		r.clusterID, r.clusterName = str(a.clusterID), str(a.clusterName)
	case a.hasSchool:
		r.clusterName = str(a.schoolName)
	default:
		r.clusterName = "Unassigned"
	}
	label := typeLabel(a.activityType)
	r.activityTypeLabel = &label
	if isCore {
		if kind, ok := p.slots.kind[a.id]; ok {
			seq := pyIntNone(p.slots.sequence[a.id])
			switch kind {
			case "visit":
				r.visitNumber = "V" + seq
			case "training":
				r.trainingNumber = "T" + seq
			}
		}
		r.coreProgress = p.slots.progress[a.id]
	}
	r.expected = expectedParticipants(a)
	r.purpose = purpose(a)
	r.focus = "General"
	if isSet(a.focus) {
		r.focus = *a.focus
		if l, ok := rules.Rows.FocusInterventionLabels[*a.focus]; ok {
			r.focus = l
		}
	}
	r.owner = p.names.owner(a)
	r.trainingName, r.trainingMode = courseName(a), modeOfDelivery(a)
	r.budgetTotal = p.amounts[a.id]
	r.costNote = p.notes[a.id]
	r.budgetStatus = budgetStatus(a, p.lines, p.requests, p.notes)
	r.verification = verification(a, p.leads)
	r.statusLabel = statusLabel(a, p.today)
	r.awaitingSSA = p.awaiting[a.id]
	if r.awaitingSSA {
		r.statusLabel = rules.Rows.AwaitingSSALabel
	}
	return r
}

// coreRows is get_frontend_context's Core School Visits and Core School
// Trainings lists for exactly these activities (an export's period "fy").
func coreRows(ctx context.Context, db schooldirectory.Querier, ids []string, now time.Time) (visits, trainings []*row, err error) {
	if len(ids) == 0 {
		return nil, nil, nil
	}
	acts, err := readActivities(ctx, db, ids)
	if err != nil || len(acts) == 0 {
		return nil, nil, err
	}
	p, err := readPage(ctx, db, acts, now)
	if err != nil {
		return nil, nil, err
	}
	r := rules.Rows
	var clusterTrainings []*row
	for _, a := range acts {
		isCore := a.hasSchool && str(a.schoolType) == "core"
		slotKind := ""
		if isCore {
			slotKind = p.slots.kind[a.id]
		}
		switch {
		case str(a.planningSource) == "manual_work_plan" || in(r.ProgrammeEventTypes, a.activityType):
		case a.hasSchool && in(r.ProgrammeSchoolTypes, str(a.schoolType)) && (in(r.VisitTypes, a.activityType) || in(r.TrainingTypes, a.activityType)):
		case isCore && (slotKind == "visit" || in(r.VisitTypes, a.activityType)):
			visits = append(visits, p.newRow(a, isCore))
		case isCore && (slotKind == "training" || in(r.TrainingTypes, a.activityType)):
			trainings = append(trainings, p.newRow(a, isCore))
		case in(rules.Plan.VisitTypes, a.activityType):
		case in(rules.Plan.TrainingTypes, a.activityType):
			clusterTrainings = append(clusterTrainings, p.newRow(a, isCore))
		}
	}
	expanded, err := p.expandClusters(ctx, db, acts, clusterTrainings)
	if err != nil {
		return nil, nil, err
	}
	trainings = append(trainings, expanded...)
	if err := p.finish(ctx, db, acts, visits, trainings); err != nil {
		return nil, nil, err
	}
	return visits, trainings, nil
}

// finish is the pass over every table after the loop: the District Type,
// the completion columns, the Status they settle and the order.
func (p *page) finish(ctx context.Context, db schooldirectory.Querier, acts []*activity, tables ...[]*row) error {
	var ids []string
	for _, rows := range tables {
		for _, r := range rows {
			ids = append(ids, r.a.id)
		}
	}
	types, err := readDistrictTypes(ctx, db, ids)
	if err != nil {
		return err
	}
	done := completions(acts, p.today)
	for _, rows := range tables {
		for _, r := range rows {
			r.districtType = types[r.a.id]
			if r.districtType == "" {
				r.districtType = "—"
			}
			c := done[r.a.id]
			officer := officerCompleted(r.a.status)
			// Evidence decides only work its status calls done.
			r.needsEvidence = officer && c.needsEvidence
			r.salesforceID, r.plannedBefore = c.salesforce, c.plannedBefore
			if officer {
				r.completedOn = c.deliveredOn
			}
			r.isComplete = officer && c.salesforce != "" && c.evidenceOK
			early := r.isComplete && c.earlyOn != nil
			if r.awaitingSSA {
				r.isComplete, early = false, false
			}
			if gap := completionGap(officer, c); gap != "" {
				r.statusLabel = gap
			} else if early {
				r.statusLabel = rules.Rows.FinishedEarly
			}
		}
		slices.SortStableFunc(rows, func(x, y *row) int { return completedLast(x).compare(completedLast(y)) })
	}
	return nil
}

func completionGap(officer bool, c completion) string {
	if !officer {
		return ""
	}
	sf, evidence := c.salesforce != "", c.evidenceOK
	switch {
	case sf && evidence:
		return ""
	case !sf && !evidence:
		return rules.Rows.MissingBoth
	case !sf:
		return rules.Rows.MissingSF
	}
	return rules.Rows.MissingEvidence
}

// orderKey is completion_columns.completed_last_key.
type orderKey struct {
	complete, undated bool
	day               time.Time
}

func completedLast(r *row) orderKey {
	k := orderKey{complete: r.isComplete, undated: r.a.plannedDate == nil}
	if d := date(r.a.plannedDate); d != nil {
		k.day = *d
	} else {
		k.day = time.Date(9999, 12, 31, 0, 0, 0, 0, time.UTC)
	}
	return k
}

func (k orderKey) compare(o orderKey) int {
	b := func(v bool) int {
		if v {
			return 1
		}
		return 0
	}
	if c := b(k.complete) - b(o.complete); c != 0 {
		return c
	}
	if c := b(k.undated) - b(o.undated); c != 0 {
		return c
	}
	return k.day.Compare(o.day)
}

// FeedRefusesFormat is the feed's REST framework view answering a ?format=
// it has no renderer for as not found, for everyone, before any page is
// asked (25.3).
func FeedRefusesFormat(query url.Values) bool {
	format := query.Get("format")
	return format != "" && !in(rules.APIFormats, format)
}
