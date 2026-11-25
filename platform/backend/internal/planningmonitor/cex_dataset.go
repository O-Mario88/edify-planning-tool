package planningmonitor

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// The Execution & Completion stage's dataset (apps.planning.country_execution
// .dataset.build): the window's activities, classified once and summed into
// cells for every filter.

// cexBucket is dataset.Bucket: one of the trend's sub-periods.
type cexBucket struct {
	label, caption string
	start, end     time.Time // end exclusive
}

// cexBuckets is buckets_for.
func cexBuckets(w cpoWindow) []cexBucket {
	out := []cexBucket{}
	switch w.period {
	case "week":
		for d := w.start; d.Before(w.end); d = d.AddDate(0, 0, 1) {
			out = append(out, cexBucket{d.Format("Mon"), fmt.Sprintf("%d %s", d.Day(), d.Format("Jan")), d, d.AddDate(0, 0, 1)})
		}
	case "month":
		days := int(w.end.Sub(w.start).Hours() / 24)
		edges := []int{0, 7, 14, 21, days}
		for n := 0; n < 4; n++ {
			start, end := w.start.AddDate(0, 0, edges[n]), w.start.AddDate(0, 0, edges[n+1])
			out = append(out, cexBucket{fmt.Sprintf("W%d", n+1),
				fmt.Sprintf("%d–%d %s", start.Day(), end.AddDate(0, 0, -1).Day(), start.Format("Jan")), start, end})
		}
	case "quarter":
		for c := w.start; c.Before(w.end); {
			next := date(c.Year(), c.Month(), 1).AddDate(0, 1, 0)
			out = append(out, cexBucket{c.Format("Jan"), c.Format("2006"), c, minTime(next, w.end)})
			c = next
		}
	default:
		c := w.start
		for n := 0; n < 4; n++ {
			next := date(c.Year(), c.Month(), 1).AddDate(0, 3, 0)
			out = append(out, cexBucket{fmt.Sprintf("Q%d", n+1),
				c.Format("Jan") + "–" + next.AddDate(0, 0, -1).Format("Jan"), c, minTime(next, w.end)})
			c = next
		}
	}
	return out
}

func minTime(a, b time.Time) time.Time {
	if a.Before(b) {
		return a
	}
	return b
}

// cexBucketOf is _bucket_of: -1 before the first, len after.
func cexBucketOf(day *time.Time, buckets []cexBucket) int {
	if day == nil {
		return len(buckets)
	}
	if day.Before(buckets[0].start) {
		return -1
	}
	for i, b := range buckets {
		if day.Before(b.end) {
			return i
		}
	}
	return len(buckets)
}

// cexRecord is dataset.ActivityRecord.
type cexRecord struct {
	id, activityType, status, stage, ownerKey, partnerKey, channel string
	schoolID, clusterID, regionID, districtID                      string
	due                                                            *time.Time
	overdue, owner, timing                                         string
	age                                                            int
	started, executed, plApplicable, plReviewed, verified, closed  bool
	returned, cancelled, financeOpen, fundsPending, paid           bool
	executedDay, verifiedDay, closedDay, lastAction                *time.Time
	schoolType, kind                                               string
	outreach                                                       bool
	deliveredDay                                                   *time.Time
	complete                                                       bool
}

func (r cexRecord) counted() bool { return r.kind != "" && r.channel == "staff" }

// cexCellKey is a cell's (owner, partner, channel, region, district, type).
type cexCellKey struct{ owner, partner, channel, region, district, activityType string }

// cexDataset is dataset.ExecutionDataset.
type cexDataset struct {
	window      cpoWindow
	today       time.Time
	buckets     []cexBucket
	records     []cexRecord
	cells       map[cexCellKey][]int
	owners      map[string]*cpoOwner
	integrity   cexIntegrity
	width       int
	partnerName map[string]string
	regionName  map[string]string
}

var cexIdx = func() map[string]int {
	m := map[string]int{}
	for i, f := range rules.CountryExecution.BaseFields {
		m[f] = i
	}
	return m
}()

// cexRow is one activity as build reads it (_COLUMNS and due_day).
type cexRow struct {
	id, activityType, status, delivery, schoolID, clusterID, responsible, monitor, partner, purpose string
	started, pl, ia, updated, created, closedAt                                                     *time.Time
	actualDelivery, due                                                                             *time.Time
	payment, owner, schoolRegion, schoolDistrict, schoolStatus, schoolType                          string
	clusterResponsible, clusterRegion, clusterDistrict, salesforce                                  string
}

// cexNoDelivery stands for a delivery type left NULL, which visit_kind and
// is_uncounted_visit read as nobody's staff (an empty one is staff's).
const cexNoDelivery = "<null>"

const cexColumns = `a.id, COALESCE(a.activity_type, ''), a.status, COALESCE(a.delivery_type, '<null>'), COALESCE(a.school_id, ''),
  COALESCE(a.cluster_id, ''), COALESCE(a.responsible_staff_id, ''), COALESCE(a.monitored_by_staff_id, ''),
  COALESCE(a.assigned_partner_id, ''), COALESCE(a.purpose_type, ''), a.execution_started_at, a.pl_reviewed_at,
  a.ia_confirmed_at, a.updated_at, a.created_at, ac.closed_at, a.actual_delivery_date, ` + "COALESCE(a.planned_date, (a.scheduled_date AT TIME ZONE '" + cpoZone + "')::date)" + `,
  COALESCE(a.payment_status, ''), COALESCE(s.account_owner_id, ''), COALESCE(s.region_id, ''), COALESCE(s.district_id, ''),
  COALESCE(s.operational_status, ''), COALESCE(s.school_type, ''), COALESCE(cl.responsible_staff_id, ''),
  COALESCE(cd.region_id, ''), COALESCE(cl.district_id, ''), COALESCE(a.salesforce_activity_id, '')`

const cexJoins = ` FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
  LEFT JOIN district cd ON cd.id = cl.district_id LEFT JOIN activity_closure ac ON ac.activity_id = a.id`

func scanCexRows(ctx context.Context, db schooldirectory.Querier, q string, args ...any) ([]cexRow, error) {
	rows, err := db.Query(ctx, q, args...)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the window's activities: %w", err)
	}
	defer rows.Close()
	out := []cexRow{}
	for rows.Next() {
		var r cexRow
		if err := rows.Scan(&r.id, &r.activityType, &r.status, &r.delivery, &r.schoolID, &r.clusterID, &r.responsible,
			&r.monitor, &r.partner, &r.purpose, &r.started, &r.pl, &r.ia, &r.updated, &r.created, &r.closedAt,
			&r.actualDelivery, &r.due, &r.payment, &r.owner, &r.schoolRegion, &r.schoolDistrict, &r.schoolStatus,
			&r.schoolType, &r.clusterResponsible, &r.clusterRegion, &r.clusterDistrict, &r.salesforce); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// cexScope is activity_scope_q as a condition on activity a (school s,
// cluster cl), or "" for none at all.
func cexScope(b *sql, scope schooldirectory.Scope) string {
	regions := func(ids []string) string {
		if len(ids) == 0 {
			return ""
		}
		arg := b.arg(ids)
		return "(s.region_id = ANY(" + arg + ") OR (a.school_id IS NULL AND cd.region_id = ANY(" + arg + ")))"
	}
	switch {
	case scope.CountryScope:
		if scope.Country == "" {
			return "TRUE"
		}
		b.args = append(b.args, scope.CountryIDs())
		return schoolprofile.ActivityInCountry(len(b.args))
	case scope.RegionScope:
		return regions(scope.RegionIDs)
	case scope.SummaryOnly:
		if len(scope.RegionIDs) > 0 {
			return regions(scope.RegionIDs)
		}
		return "TRUE"
	}
	if len(scope.SchoolIDs) == 0 {
		return ""
	}
	return "a.school_id = ANY(" + b.arg(scope.SchoolIDs) + ")"
}

// buildCEXDataset is dataset.build for this reader and window.
func buildCEXDataset(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope, w cpoWindow,
	today time.Time) (*cexDataset, error) {
	c := rules.CountryExecution
	buckets := cexBuckets(w)
	d := &cexDataset{window: w, today: today, buckets: buckets, cells: map[cexCellKey][]int{}, owners: map[string]*cpoOwner{},
		width: len(c.BaseFields) + len(c.TrendSeries)*len(buckets), partnerName: map[string]string{}, regionName: map[string]string{}}
	b := &sql{}
	scopeQ := cexScope(b, scope)
	var rows []cexRow
	var err error
	day := "COALESCE(a.planned_date, (a.scheduled_date AT TIME ZONE '" + cpoZone + "')::date)"
	if scopeQ != "" {
		where := `a.deleted_at IS NULL AND a.status = ANY(` + b.arg(c.Stages.ReadStates) + `) AND ` + day + ` >= ` + b.arg(w.start) +
			`::date AND ` + day + ` < ` + b.arg(w.end) + `::date AND (` + scopeQ + `)`
		if rows, err = scanCexRows(ctx, db, `SELECT `+cexColumns+cexJoins+` WHERE `+where, b.args...); err != nil {
			return nil, err
		}
	}
	ids := make([]string, 0, len(rows))
	for _, r := range rows {
		ids = append(ids, r.id)
	}
	funds, forms, closure, err := cexMoneyAndForms(ctx, db, ids)
	if err != nil {
		return nil, err
	}
	if d.integrity, err = cexIntegrityOf(ctx, db, scope, w, rows); err != nil {
		return nil, err
	}
	partnerIDs := []string{}
	for _, r := range rows {
		if r.delivery == "partner" {
			partnerIDs = append(partnerIDs, r.id)
		}
	}
	for _, r := range d.integrity.movedRows {
		if r.delivery == "partner" {
			partnerIDs = append(partnerIDs, r.id)
		}
	}
	handed, err := cexHandedBy(ctx, db, partnerIDs)
	if err != nil {
		return nil, err
	}
	candidates := map[string][]string{}
	raw := []string{}
	for _, r := range append(slices.Clone(rows), d.integrity.movedRows...) {
		cs := cexCandidates(r, handed)
		candidates[r.id] = cs
		raw = append(raw, cs...)
	}
	directory, err := cpoOwnerDirectory(ctx, db, raw)
	if err != nil {
		return nil, err
	}
	noOwner := rules.CountryOversight.NoOwner[0]
	ownerOf := func(r cexRow) (string, *cpoOwner) {
		cs := candidates[r.id]
		if r.delivery != "partner" && len(cs) > 1 {
			cs = cs[:1] // staff work is its responsible person's, known or not
		}
		for _, id := range cs {
			if o := directory[id]; o != nil {
				if _, ok := d.owners[o.key]; !ok {
					d.owners[o.key] = o
				}
				return o.key, o
			}
		}
		return noOwner, nil
	}
	notOperating := c.Stages.NotOperating
	for _, r := range rows {
		key, info := ownerOf(r)
		partner := r.delivery == "partner"
		kind := "unassigned"
		if info != nil {
			kind = ownerKind(info.key, info.role)
		}
		start := r.actualDelivery
		if start == nil && r.started != nil {
			s := localDay(*r.started)
			start = &s
		}
		verifiedAt := r.ia
		if verifiedAt == nil && slices.Contains(c.Stages.Verified, r.status) {
			verifiedAt = r.pl
		}
		stage := cexClassify(cexInput{status: r.status, partner: partner, due: r.due, start: start, plReviewed: r.pl != nil,
			plPath: kind == "cceo" || kind == "pl_personal", schoolOperating: !slices.Contains(notOperating, r.schoolStatus),
			fundsPending: funds[r.id], closureOwner: cexClosureOwner(r, closure), today: today})
		partnerKey := c.StaffKey
		if partner {
			partnerKey = r.partner
		}
		region, district := first(r.schoolRegion, r.clusterRegion), first(r.schoolDistrict, r.clusterDistrict)
		rec := cexRecord{id: r.id, activityType: r.activityType, status: r.status, stage: stage.stage, ownerKey: key,
			partnerKey: partnerKey, channel: "staff", schoolID: r.schoolID, clusterID: r.clusterID, regionID: region,
			districtID: district, due: r.due, overdue: stage.overdue, owner: stage.owner, timing: stage.timing, age: stage.age,
			started: stage.started, executed: stage.executed, plApplicable: stage.plApplicable, plReviewed: stage.reviewed,
			verified: stage.verified, closed: stage.closed, returned: stage.returned, cancelled: stage.cancelled,
			financeOpen: stage.financeOpen, fundsPending: funds[r.id], paid: r.payment == "paid" || r.payment == "closed",
			schoolType: r.schoolType, deliveredDay: r.actualDelivery}
		if partner {
			rec.channel = "partner"
		}
		if stage.executed {
			switch {
			case r.actualDelivery != nil:
				rec.executedDay = r.actualDelivery
			case start != nil:
				rec.executedDay = start
			default:
				rec.executedDay = r.due
			}
		}
		if stage.verified && verifiedAt != nil {
			v := localDay(*verifiedAt)
			rec.verifiedDay = &v
		}
		if stage.closed && r.closedAt != nil {
			v := localDay(*r.closedAt)
			rec.closedDay = &v
		}
		if r.updated != nil {
			v := localDay(*r.updated)
			rec.lastAction = &v
		}
		rec.complete = stage.verified && strings.TrimSpace(r.salesforce) != "" && forms[r.id][cexExpectedForm(r.activityType)]
		delivery := r.delivery
		if delivery == cexNoDelivery {
			delivery = "partner" // not staff's
		}
		if r.schoolID != "" && r.clusterID == "" {
			rec.kind = visitKind(r.activityType, r.purpose, "", delivery, nil)
		}
		if r.schoolID != "" {
			rec.outreach = isUncountedVisit(r.activityType, r.purpose, delivery, nil)
		}
		d.records = append(d.records, rec)
		ck := cexCellKey{key, partnerKey, rec.channel, region, district, r.activityType}
		v := d.cells[ck]
		if v == nil {
			v = make([]int, d.width)
			d.cells[ck] = v
		}
		cexAdd(v, rec, stage, buckets)
	}
	for _, r := range d.integrity.movedRows {
		key, _ := ownerOf(r)
		partnerKey, channel := c.StaffKey, "staff"
		if r.delivery == "partner" {
			partnerKey, channel = r.partner, "partner"
		}
		ck := cexCellKey{key, partnerKey, channel, first(r.schoolRegion, r.clusterRegion), first(r.schoolDistrict, r.clusterDistrict), r.activityType}
		v := d.cells[ck]
		if v == nil {
			v = make([]int, d.width)
			d.cells[ck] = v
		}
		v[cexIdx["carried_forward"]]++
	}
	regions, partners := []string{}, []string{}
	for _, r := range d.records {
		regions = append(regions, r.regionID)
		if r.partnerKey != "" && r.partnerKey != c.StaffKey {
			partners = append(partners, r.partnerKey)
		}
	}
	for table, into := range map[string]map[string]string{"region": d.regionName, "partner": d.partnerName} {
		ids := regions
		if table == "partner" {
			ids = partners
		}
		names, err := cpoNames(ctx, db, table, ids)
		if err != nil {
			return nil, err
		}
		for _, o := range names {
			into[o.value] = o.label
		}
	}
	return d, nil
}

// cexExpectedForm is completion_columns.expected_evidence's kind.
func cexExpectedForm(activityType string) string {
	if slices.Contains(rules.CountryExecution.AttendanceFormTypes, activityType) {
		return "attendance_form"
	}
	return "visit_form"
}

// cexCandidates is _owner_candidates.
func cexCandidates(r cexRow, handed map[string][2]string) []string {
	var raw []string
	if r.delivery == "partner" {
		h := handed[r.id]
		raw = []string{h[0], h[1], r.monitor, r.responsible, r.owner, r.clusterResponsible}
	} else {
		raw = []string{r.responsible, r.owner, r.clusterResponsible, r.monitor}
	}
	out := []string{}
	for _, v := range raw {
		if v != "" {
			out = append(out, v)
		}
	}
	return out
}

// cexHandedBy is _handed_by: Partner activity → (monitor, assigner) of the
// hand-over it came from or carries, the latest hand-over winning.
func cexHandedBy(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string][2]string, error) {
	out := map[string][2]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT COALESCE(scheduled_activity_id, ''), COALESCE(source_activity_id, ''),
		COALESCE(monitoring_staff_id, ''), COALESCE(assigning_staff_id, '') FROM partner_assignment
		WHERE scheduled_activity_id = ANY($1) OR source_activity_id = ANY($1) ORDER BY created_at`, ids)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the hand-overs behind Partner work: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var scheduled, source, monitor, assigner string
		if err := rows.Scan(&scheduled, &source, &monitor, &assigner); err != nil {
			return nil, err
		}
		for _, id := range []string{scheduled, source} {
			if id != "" {
				out[id] = [2]string{monitor, assigner}
			}
		}
	}
	return out, rows.Err()
}

// cexMoneyAndForms is _funds_pending, _forms_in and _closure_owners.
func cexMoneyAndForms(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]bool, map[string]map[string]bool,
	map[string]map[string]bool, error) {
	c := rules.CountryExecution
	funds, forms, closure := map[string]bool{}, map[string]map[string]bool{}, map[string]map[string]bool{}
	if len(ids) == 0 {
		return funds, forms, closure, nil
	}
	moved := map[string]bool{}
	rows, err := db.Query(ctx, `SELECT activity_id, status FROM advance_request WHERE activity_id = ANY($1)`, ids)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("planningmonitor: the advances behind the work: %w", err)
	}
	for rows.Next() {
		var id, status string
		if err := rows.Scan(&id, &status); err != nil {
			rows.Close()
			return nil, nil, nil, err
		}
		switch {
		case slices.Contains(c.AwaitingDisbursement, status):
			funds[id] = true
		case slices.Contains(c.MoneyMoved, status):
			moved[id] = true
		}
	}
	rows.Close()
	for id := range moved {
		delete(funds, id)
	}
	rows, err = db.Query(ctx, `SELECT DISTINCT activity_id, kind FROM evidence_record WHERE activity_id = ANY($1)
		AND NOT quarantined AND kind IN ('visit_form', 'attendance_form')`, ids)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("planningmonitor: the work's forms: %w", err)
	}
	for rows.Next() {
		var id, kind string
		if err := rows.Scan(&id, &kind); err != nil {
			rows.Close()
			return nil, nil, nil, err
		}
		if forms[id] == nil {
			forms[id] = map[string]bool{}
		}
		forms[id][kind] = true
	}
	rows.Close()
	open := []string{}
	for _, s := range c.Stages.Verified {
		if !slices.Contains(c.Stages.Closed, s) {
			open = append(open, s)
		}
	}
	rows, err = db.Query(ctx, `SELECT b.activity_id, COALESCE(b.responsible_role, '') FROM closure_blocker b
		JOIN activity a ON a.id = b.activity_id WHERE b.activity_id = ANY($1) AND a.status = ANY($2)`, ids, open)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("planningmonitor: the closure blockers: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, role string
		if err := rows.Scan(&id, &role); err != nil {
			return nil, nil, nil, err
		}
		if closure[id] == nil {
			closure[id] = map[string]bool{}
		}
		closure[id][role] = true
	}
	return funds, forms, closure, rows.Err()
}

// cexClosureOwner is _closure_owner.
func cexClosureOwner(r cexRow, closure map[string]map[string]bool) string {
	st := rules.CountryExecution.Stages
	if !slices.Contains(st.Verified, r.status) || slices.Contains(st.Closed, r.status) {
		return ""
	}
	if r.delivery == "partner" && r.payment != "paid" && r.payment != "closed" {
		return "finance"
	}
	roles := closure[r.id]
	switch {
	case roles["Accountant"]:
		return "finance"
	case roles["ImpactAssessment"] && !roles["CCEO"]:
		return "ia"
	}
	return "staff"
}

// cexAdd is _add_record.
func cexAdd(v []int, r cexRecord, s cexStage, buckets []cexBucket) {
	i := cexIdx
	if r.cancelled {
		v[i["cancelled"]]++
		return
	}
	inc := func(cond bool, name string) {
		if cond {
			v[i[name]]++
		}
	}
	v[i["due"]]++
	inc(s.started, "started")
	inc(s.executed, "executed")
	inc(s.plApplicable, "pl_applicable")
	inc(s.reviewed, "pl_reviewed")
	inc(s.verified, "verified")
	inc(s.closed, "closed")
	inc(s.returned, "returned")
	if s.overdue != "" {
		v[i["overdue"]]++
		v[i["od_"+s.overdue]]++
		if g := cexAgeGroup(s.age); g != "" {
			v[i[g]]++
		}
	}
	inc(s.financeOpen, "finance_open")
	if s.owner != "" {
		v[i["own_"+s.owner]]++
	}
	inc(r.fundsPending && !s.started, "funds_pending")
	if r.complete {
		v[i["complete"]]++
	} else if s.started {
		v[i["in_progress"]]++
	}
	if r.counted() {
		inc(slices.Contains(rules.CountryOversight.PlannedStates, r.status), "v_planned")
		inc(s.executed, "v_delivered")
		inc(s.verified, "v_verified")
	} else if r.outreach && r.channel == "staff" && s.executed {
		v[i["v_outreach"]]++
	}
	switch s.timing {
	case "on_time":
		v[i["on_time"]]++
	case "late":
		v[i["late"]]++
	case "unknown":
		v[i["start_unknown"]]++
	case "not_started":
		v[i["not_started"]]++
	case "upcoming":
		v[i["upcoming"]]++
	}
	base, count := len(rules.CountryExecution.BaseFields), len(buckets)
	for series, day := range []*time.Time{r.due, r.executedDay, r.verifiedDay, r.closedDay} {
		if day == nil {
			continue
		}
		if index := max(0, cexBucketOf(day, buckets)); index < count {
			v[base+series*count+index]++
		}
	}
}
