package planningmonitor

import (
	"context"
	"fmt"
	"net/url"
	"sort"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// The page as a workbook (country_oversight_views.coverage_export_view):
// the schools, one row each (not for a reader who sees the country's
// figures only), the hierarchy one row a level, and the year's follow-ups.

// coverageFigures are _figures' tally fields, in its order; three are the
// tally's properties (coverageDerived).
var coverageFigures = []string{"target", "p_visits", "p_follow_up", "p_in_school", "p_outreach", "p_trainings",
	"p_cluster_trainings", "p_meetings", "pa_schools", "pa_work", "pp_work", "schools", "core_schools", "client_schools",
	"core_trained_schools", "core_graduate_schools", "champion_schools", "reach", "shortfall", "over_cap", "p_core_visits",
	"core_staff_slots", "p_client_visits", "client_staff_expected", "partner_expected", "client_partner_expected",
	"partner_assigned", "visit_slots", "staff", "partner_scheduled", "any_visit", "unplanned", "partner_to_plan",
	"with_partner", "duplicates", "training_slots", "training", "training_staff_slots", "training_staff",
	"training_partner_slots", "training_partner", "no_training", "clustered", "unclustered", "meeting_covered",
	"staff_verified", "partner_verified"}

// followUpHeaders are _followup_sheet's headings.
var followUpHeaders = []string{"Sent", "Programme Lead", "CCEO", "School ID", "School Name", "Issue", "Period", "Required",
	"Planned", "Remaining when sent", "Remaining now", "Priority", "Due", "Status", "Reminders", "Instruction"}

// ownerLevels are _hierarchy_sheet's words for an owner row's kind.
var ownerLevels = map[string]string{"cceo": "CCEO", "pl_personal": "Programme Lead (own plan)", "unassigned": "Nobody"}

// planningStateWords are the school sheet's Planning status.
var planningStateWords = map[string]string{"full": "Fully planned", "partial": "Partially planned", "none": "Not planned",
	"outside": "Outreach only"}

// CoverageExport is the workbook export at /country-planning-oversight/coverage-export.
func CoverageExport(db schooldirectory.Querier, now func() time.Time) func(context.Context, auth.Principal, url.Values) (string, []workbook.Sheet, bool, error) {
	return func(ctx context.Context, p auth.Principal, query url.Values) (string, []workbook.Sheet, bool, error) {
		return coverageExport(ctx, db, p, query, now())
	}
}

func coverageExport(ctx context.Context, db schooldirectory.Querier, p auth.Principal, query url.Values, now time.Time) (string, []workbook.Sheet, bool, error) {
	if !pageaccess.CanOpen(p.ActiveRole, false, cpoPath+"coverage-export") {
		return "", nil, true, pagegate.ErrNotAvailable
	}
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return "", nil, true, err
	}
	q := map[string]string{}
	for k, v := range query {
		if len(v) > 0 {
			q[k] = v[len(v)-1]
		}
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	f := cpoReadFilters(q, today)
	snap, err := buildCPOSnapshot(ctx, db, scope, f, today)
	if err != nil {
		return "", nil, true, err
	}
	country := strings.TrimSpace(scope.Country)
	if country == "" || country == schooldirectory.NoCountry {
		country = "Country"
	}
	var sheets []workbook.Sheet
	if !scope.SummaryOnly {
		sheet, err := coverageSchoolSheet(ctx, db, snap, f, country)
		if err != nil {
			return "", nil, true, err
		}
		sheets = append(sheets, sheet)
	}
	counts, err := cpoOpenCounts(ctx, db, f.fy, "planning")
	if err != nil {
		return "", nil, true, err
	}
	hierarchy, err := coverageHierarchySheet(ctx, db, snap, counts, country)
	if err != nil {
		return "", nil, true, err
	}
	followUps, err := coverageFollowUpSheet(ctx, db, f.fy)
	if err != nil {
		return "", nil, true, err
	}
	sheets = append(sheets, hierarchy, followUps)
	return "country-planning-oversight-" + f.fy + "-" + today.Format(time.DateOnly), sheets, true, nil
}

// cpoOpenCounts is followups.open_counts: the open follow-ups of one stage
// per Lead, per officer and for the country.
func cpoOpenCounts(ctx context.Context, db schooldirectory.Querier, fy, module string) (map[[2]string]int, error) {
	out := map[[2]string]int{}
	rows, err := db.Query(ctx, `SELECT COALESCE(program_lead_staff_id, ''), COALESCE(cceo_staff_id, '') FROM planning_oversight_follow_up
		WHERE fy = $1 AND status = ANY($2) AND module = $3`, fy, rules.CountryOversight.Page.FollowUpOpenStates, module)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the open follow-ups: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var lead, cceo string
		if err := rows.Scan(&lead, &cceo); err != nil {
			return nil, err
		}
		out[[2]string{"lead", lead}]++
		out[[2]string{"country", ""}]++
		if cceo == "" {
			cceo = lead
		}
		out[[2]string{"owner", cceo}]++
	}
	return out, rows.Err()
}

// coverageDerived are Tally's properties among the figures: the work still
// for a Partner to date (no_visit less unplanned), the visits the schools
// held allow (2 a Core school, 1 a Client, Core Trained or Core Graduate
// one), and how far that falls short of the target.
var coverageDerived = map[string]func(cpoTally) int{
	"partner_to_plan": cpoTally.partnerToPlan,
	"reach":           reach,
	"shortfall": func(t cpoTally) int {
		if t.n("target") == 0 {
			return 0
		}
		return max(0, t.n("target")-reach(t))
	},
}

func reach(t cpoTally) int {
	return 2*t.n("core_schools") + t.n("client_schools") + t.n("core_trained_schools") + t.n("core_graduate_schools")
}

func figureCells(t []int) []workbook.Cell {
	tally := cpoTally(t)
	out := make([]workbook.Cell, 0, len(coverageFigures))
	for _, name := range coverageFigures {
		n := 0
		if derived, ok := coverageDerived[name]; ok {
			n = derived(tally)
		} else {
			n = tally.n(name)
		}
		out = append(out, workbook.Int(int64(n)))
	}
	return out
}

// coverageHierarchySheet is _hierarchy_sheet: the country, each Lead, each
// owner and the Partners an owner's schools are assigned to.
func coverageHierarchySheet(ctx context.Context, db schooldirectory.Querier, snap *cpoSnapshot, counts map[[2]string]int, country string) (workbook.Sheet, error) {
	txt := workbook.Text
	row := func(level, lead, person, partner string, tally []int, count workbook.Cell) []workbook.Cell {
		cells := []workbook.Cell{txt(level), txt(country), txt(lead), txt(person), txt(partner)}
		return append(append(cells, figureCells(tally)...), count)
	}
	partnerIDs := []string{}
	for _, lead := range snap.tree.leads {
		for _, o := range lead.owners {
			partnerIDs = append(partnerIDs, o.assignedOrder...)
		}
	}
	names, err := partnerNameMap(ctx, db, partnerIDs)
	if err != nil {
		return workbook.Sheet{}, err
	}
	rows := [][]workbook.Cell{row("Country", "", "", "", snap.tree.country, workbook.Int(int64(counts[[2]string{"country", ""}])))}
	for _, lead := range snap.tree.leads {
		rows = append(rows, row("Programme Lead", lead.name, "", "", lead.tally, workbook.Int(int64(counts[[2]string{"lead", lead.key}]))))
		for _, o := range lead.owners {
			level, ok := ownerLevels[o.kind]
			if !ok {
				level = "Other staff"
			}
			rows = append(rows, row(level, lead.name, o.name, "", o.tally, workbook.Int(int64(counts[[2]string{"owner", o.key}]))))
			for _, pid := range o.assignedOrder {
				name, ok := names[pid]
				if !ok {
					name = "Unrecorded Partner"
				}
				rows = append(rows, row("Partner", lead.name, o.name, name, o.assigned[pid], txt("")))
			}
		}
	}
	return workbook.Sheet{Title: "People (one row per level)", Headers: rules.CountryOversight.Page.CoverageExport.HierarchyHeaders, Rows: rows}, nil
}

func partnerNameMap(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]string, error) {
	names, err := cpoNames(ctx, db, "partner", ids)
	if err != nil {
		return nil, err
	}
	out := map[string]string{}
	for _, o := range names {
		out[o.value] = o.label
	}
	return out, nil
}

// coverageSchoolSheet is _school_sheet: each governed school the filters
// keep, by name, with its slots, cluster, planning status, Partners, the
// reasons it is planned twice and whether a follow-up is open on it.
func coverageSchoolSheet(ctx context.Context, db schooldirectory.Querier, snap *cpoSnapshot, f cpoFilters, country string) (workbook.Sheet, error) {
	d := snap.data
	followed := map[string]bool{}
	rs, err := db.Query(ctx, `SELECT school_id FROM planning_oversight_follow_up WHERE fy = $1 AND status = ANY($2) AND school_id IS NOT NULL`,
		f.fy, rules.CountryOversight.Page.FollowUpOpenStates)
	if err != nil {
		return workbook.Sheet{}, fmt.Errorf("planningmonitor: the schools followed up: %w", err)
	}
	for rs.Next() {
		var id string
		if err := rs.Scan(&id); err != nil {
			rs.Close()
			return workbook.Sheet{}, err
		}
		followed[id] = true
	}
	rs.Close()
	partnerIDs := []string{}
	for _, s := range d.schools {
		partnerIDs = append(partnerIDs, s.partnerOrder...)
	}
	names, err := partnerNameMap(ctx, db, partnerIDs)
	if err != nil {
		return workbook.Sheet{}, err
	}
	schools := append([]*cpoSchool{}, d.schools...)
	sort.SliceStable(schools, func(i, j int) bool {
		a, b := strings.ToLower(schools[i].name), strings.ToLower(schools[j].name)
		if a != b {
			return a < b
		}
		return schools[i].id < schools[j].id
	})
	var only *string
	if f.partner != "" {
		only = &f.partner
	}
	txt, num := workbook.Text, func(n int) workbook.Cell { return workbook.Int(int64(n)) }
	yes := func(b bool) workbook.Cell {
		if b {
			return txt("Yes")
		}
		return txt("")
	}
	rows := [][]workbook.Cell{}
	for _, s := range schools {
		if !s.governed() {
			continue
		}
		owner := d.owners[s.ownerKey]
		lead := rules.CountryOversight.NoLead[0]
		if owner != nil {
			lead = owner.leadKey
		}
		if !keepsPlace(f, s, lead) {
			continue
		}
		cl := claimsFor(s, d.allocations[s.id], d.window, f.channel, only)
		if !statusMatches(cl, f) {
			continue
		}
		values := schoolValues(s, cl)
		held := []string{}
		for pid := range s.partners {
			name, ok := names[pid]
			if !ok {
				name = "Unrecorded Partner"
			}
			held = append(held, name)
		}
		sort.Strings(held)
		leadName, holder := "No Programme Lead", "No account owner"
		if owner != nil {
			leadName, holder = owner.leadName, owner.name
		}
		cluster := "Unclustered"
		if s.clustered() {
			cluster = "Clustered"
		}
		meeting := "No meeting planned"
		if cl.cumMeetingCovered {
			meeting = "Meeting planned"
		}
		reasons := []string{}
		for _, r := range duplicateReasons(s) {
			reasons = append(reasons, rules.CountryOversight.Page.TableWords.Duplicates[r])
		}
		rows = append(rows, []workbook.Cell{
			txt(country), txt(leadName), txt(holder), txt(strings.Join(held, ", ")), txt(s.code), txt(s.name),
			txt(typeLabel(s.schoolType)), num(cl.visitSlots), num(cl.staffExpected), num(cl.cumStaff), num(cl.partnerExpected),
			num(cl.cumPartnerAssigned), num(cl.cumPartnerScheduled), num(values[cpoIdx["unallocated"]]), num(cl.trainingSlots),
			num(cl.cumTraining), txt(cluster), txt(meeting), txt(planningStateWords[planningState(cl)]), yes(s.withPartner),
			txt(strings.Join(reasons, "; ")), yes(followed[s.id]),
		})
	}
	return workbook.Sheet{Title: "Schools (one row per school)", Headers: rules.CountryOversight.Page.CoverageExport.SchoolHeaders, Rows: rows}, nil
}

// coverageFollowUpSheet is _followup_sheet: every follow-up of the year,
// newest first, its School ID whichever key it was filed under.
func coverageFollowUpSheet(ctx context.Context, db schooldirectory.Querier, fy string) (workbook.Sheet, error) {
	page := rules.CountryOversight.Page
	rs, err := db.Query(ctx, `SELECT f.assigned_at, COALESCE(f.program_lead_name, ''), COALESCE(f.cceo_name, ''),
  COALESCE((SELECT s.school_id FROM school s WHERE s.id = f.school_id OR s.school_id = f.school_id ORDER BY s.id = f.school_id DESC LIMIT 1), ''),
  COALESCE(f.school_name, ''), COALESCE(f.issue_type, ''), COALESCE(f.period_label, ''), f.required_value, f.planned_value,
  f.remaining_value, f.live_remaining, COALESCE(f.priority, ''), f.due_date, COALESCE(f.status, ''), COALESCE(f.reminder_count, 0),
  COALESCE(f.instruction, '')
FROM planning_oversight_follow_up f WHERE f.fy = $1 ORDER BY f.assigned_at DESC`, fy)
	if err != nil {
		return workbook.Sheet{}, fmt.Errorf("planningmonitor: the year's follow-ups: %w", err)
	}
	defer rs.Close()
	txt := workbook.Text
	value := func(n *int64) workbook.Cell {
		if n == nil {
			return workbook.Empty()
		}
		return workbook.Int(*n)
	}
	rows := [][]workbook.Cell{}
	for rs.Next() {
		var sent time.Time
		var lead, cceo, code, school, issue, period, priority, status, instruction string
		var required, planned, remaining, live *int64
		var due time.Time
		var reminders int64
		if err := rs.Scan(&sent, &lead, &cceo, &code, &school, &issue, &period, &required, &planned, &remaining, &live,
			&priority, &due, &status, &reminders, &instruction); err != nil {
			return workbook.Sheet{}, err
		}
		label, ok := page.FollowUpIssueLabels[issue]
		if !ok {
			label = issue
		}
		liveCell := txt("")
		if live != nil {
			liveCell = workbook.Int(*live)
		}
		rows = append(rows, []workbook.Cell{
			txt(sent.UTC().Format(time.DateOnly)), txt(lead), txt(cceo), txt(code), txt(school), txt(label), txt(period),
			value(required), value(planned), value(remaining), liveCell, txt(orElse(page.FollowUpPriorityLabels[priority], priority)),
			txt(due.Format(time.DateOnly)), txt(orElse(page.FollowUpStatusLabels[status], status)), workbook.Int(reminders), txt(instruction),
		})
	}
	return workbook.Sheet{Title: "Follow-ups (one row each)", Headers: followUpHeaders, Rows: rows}, rs.Err()
}
