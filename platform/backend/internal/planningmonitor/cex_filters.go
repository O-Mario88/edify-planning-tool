package planningmonitor

import (
	"context"
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// cexFilters is service.ExecFilters: the Execution & Completion tab's
// selection.
type cexFilters struct {
	fy, period, quarter, week                              string
	month                                                  int
	region, programLead, cceo, channel, partner, activType string
}

// window is ExecFilters.window.
func (f cexFilters) window() cpoWindow {
	return cpoWindowOf(cpoFilters{fy: f.fy, period: f.period, quarter: f.quarter, month: f.month, week: f.week})
}

// cexReadFilters is service.read_filters: it opens on this month.
func cexReadFilters(q map[string]string, today time.Time) cexFilters {
	get := func(name string) string { return strings.TrimSpace(q[name]) }
	digits := func(s string) bool {
		return s != "" && strings.IndexFunc(s, func(r rune) bool { return r < '0' || r > '9' }) < 0
	}
	operational := strconv.Itoa(cpoOperationalFY(today))
	fy := get("fy")
	if !digits(fy) {
		fy = operational
	}
	period := strings.ToLower(get("period"))
	month := 0
	if m, err := strconv.Atoi(get("month")); err == nil && digits(get("month")) && m >= 1 && m <= 12 {
		month = m
	}
	quarter := strings.ToUpper(get("quarter"))
	if !slices.Contains([]string{"Q1", "Q2", "Q3", "Q4"}, quarter) {
		quarter = ""
	}
	week := get("week")
	if !slices.Contains([]string{"week", "month", "quarter", "fy"}, period) {
		period = "fy"
		if fy == operational {
			period = "month"
		}
	}
	if period == "quarter" && quarter == "" {
		quarter = "Q1"
		if fy == operational {
			quarter = "Q" + strconv.Itoa((int(today.Month())+2)%12/3+1)
		}
	}
	if period == "month" && month == 0 {
		month = 10
		if fy == operational {
			month = int(today.Month())
		}
	}
	if period == "week" && week == "" {
		y, w := today.ISOWeek()
		week = fmt.Sprintf("%04d-W%02d", y, w)
	}
	pick := func(name string) string {
		v := get(name)
		if v == "all" || v == "All" {
			return ""
		}
		return v
	}
	f := cexFilters{fy: fy, period: period, region: pick("region"), programLead: pick("program_lead"), cceo: pick("cceo"),
		partner: pick("partner"), activType: pick("activity_type")}
	if c := get("channel"); c == "staff" || c == "partner" {
		f.channel = c
	}
	switch period {
	case "quarter":
		f.quarter = quarter
	case "month":
		f.month = month
	case "week":
		f.week = week
	}
	return f
}

// CEXRecord and CEXDataset are the execution dataset as a comparison reads
// it (local proofs against Django's own dataset).
type CEXRecord map[string]any

// CountryExecutionDataset is dataset.build for the reader and the tab's
// query: each record's fields, each cell's vector by its joined key, and
// the plan's integrity.
func CountryExecutionDataset(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string,
	now time.Time) (map[string]CEXRecord, map[string][]int, map[string]any, error) {
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, nil, nil, err
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	f := cexReadFilters(q, today)
	d, err := buildCEXDataset(ctx, db, scope, f.window(), today)
	if err != nil {
		return nil, nil, nil, err
	}
	day := func(t *time.Time) any {
		if t == nil {
			return nil
		}
		return t.Format("2006-01-02")
	}
	opt := func(s string) any {
		if s == "" {
			return nil
		}
		return s
	}
	recs := map[string]CEXRecord{}
	for _, r := range d.records {
		recs[r.id] = CEXRecord{"stage": r.stage, "owner_key": r.ownerKey, "partner_key": r.partnerKey, "channel": r.channel,
			"school_id": opt(r.schoolID), "cluster_id": opt(r.clusterID), "region_id": opt(r.regionID), "district_id": opt(r.districtID),
			"due": day(r.due), "overdue": r.overdue, "owner": r.owner, "timing": r.timing, "age": r.age, "started": r.started,
			"executed": r.executed, "pl_applicable": r.plApplicable, "pl_reviewed": r.plReviewed, "verified": r.verified,
			"closed": r.closed, "returned": r.returned, "cancelled": r.cancelled, "finance_open": r.financeOpen,
			"funds_pending": r.fundsPending, "paid": r.paid, "executed_day": day(r.executedDay), "verified_day": day(r.verifiedDay),
			"closed_day": day(r.closedDay), "last_action": day(r.lastAction), "school_type": r.schoolType, "kind": r.kind,
			"outreach": r.outreach, "delivered_day": day(r.deliveredDay), "complete": r.complete, "status": r.status,
			"activity_type": r.activityType}
	}
	cells := map[string][]int{}
	for k, v := range d.cells {
		cells[strings.Join([]string{k.owner, k.partner, k.channel, k.region, k.district, k.activityType}, "|")] = v
	}
	in := d.integrity
	integrity := map[string]any{"tracked": in.tracked, "original": in.original, "added": in.added, "moved_in": in.movedIn,
		"moved_out": in.movedOut, "cancelled": in.cancelled, "current": in.live}
	return recs, cells, integrity, nil
}
