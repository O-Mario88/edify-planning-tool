package planningmonitor

// The data-quality checks that read the records themselves (checks 5b and
// 7 to 13 of data_quality.checks).

import (
	"context"
	"fmt"
	"slices"
	"strconv"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// cpoOpenHandover is one open Core-school hand-over, as package_credit reads it.
type cpoOpenHandover struct {
	id, school, schoolCode, schoolName, partner, partnerName string
	support, visit, training, purpose, expected, project     string
	course                                                   string
	universal                                                bool
}

func (h cpoOpenHandover) namesItsSlot() bool {
	return strings.TrimSpace(h.support) != "" || h.visit != "" || h.training != ""
}

// kind is assignment_kind: "visit", "training" or "" for none.
func (h cpoOpenHandover) kind(outside []string) string {
	dq := rules.CountryOversight.Page.DataQuality
	if h.project != "" && slices.Contains(outside, h.project) || h.universal {
		return ""
	}
	switch support := strings.ToLower(strings.TrimSpace(h.support)); {
	case support == "visit" || support == "training":
		return support
	case h.visit != "":
		return "visit"
	case h.training != "":
		return "training"
	case slices.Contains(dq.NonPackageVisitPurposes, h.purpose):
		return ""
	}
	expected := h.expected
	if expected == "" && h.purpose != "" {
		expected = dq.PurposeActivityTypes[h.purpose]
	}
	switch {
	case slices.Contains(dq.PackageTrainingTypes, expected) || expected == "in_school_training":
		return "training"
	case slices.Contains(dq.PackageVisitTypes, expected):
		return "visit"
	}
	return ""
}

// cpoUnreservedHandovers is unreserved_core_handovers over the reader's
// schools: open hand-overs at Core Schools that name no slot and hold none.
func cpoUnreservedHandovers(ctx context.Context, db schooldirectory.Querier, ids []string) ([]cpoSample, error) {
	outside, err := visitgate.ProjectsOutsideSSA(ctx, db, schoolprofile.GateRules())
	if err != nil {
		return nil, err
	}
	rows, err := db.Query(ctx, `SELECT pa.id, pa.school_id, COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(pa.partner_id, ''),
  COALESCE(p.name, ''), COALESCE(pa.support_type, ''), COALESCE(pa.visit_number, ''), COALESCE(pa.training_number, ''),
  COALESCE(pa.purpose_of_visit, ''), COALESCE(pa.expected_activity_type, ''), COALESCE(pa.project_id, ''),
  COALESCE(pa.training_course_id, ''), COALESCE(c.universal_training, false)
FROM partner_assignment pa JOIN school s ON s.id = pa.school_id LEFT JOIN partner p ON p.id = pa.partner_id
LEFT JOIN activity_catalogue_item c ON c.id = pa.training_course_id
WHERE pa.status = ANY($1) AND s.school_type = 'core' AND s.deleted_at IS NULL AND pa.school_id = ANY($2)
ORDER BY pa.id`, rules.CountryOversight.UnscheduledHandoverStatuses, ids)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the open Core hand-overs: %w", err)
	}
	all := []cpoOpenHandover{}
	for rows.Next() {
		var h cpoOpenHandover
		if err := rows.Scan(&h.id, &h.school, &h.schoolCode, &h.schoolName, &h.partner, &h.partnerName, &h.support, &h.visit,
			&h.training, &h.purpose, &h.expected, &h.project, &h.course, &h.universal); err != nil {
			rows.Close()
			return nil, fmt.Errorf("planningmonitor: an open Core hand-over: %w", err)
		}
		all = append(all, h)
	}
	rows.Close()
	out := []cpoSample{}
	for _, h := range all {
		kind := h.kind(outside)
		if h.namesItsSlot() || kind == "" {
			continue
		}
		holds, err := cpoUnnamedSlotHeld(ctx, db, h, kind, all, outside)
		if err != nil {
			return nil, err
		}
		if !holds {
			out = append(out, cpoSample{label: orElse(h.schoolName, h.id), detail: h.partnerName})
		}
	}
	return out, nil
}

// cpoUnnamedSlotHeld is slot_held_by_assignment for a hand-over that names
// no slot: an "Assigned" slot its Partner holds at the school that no named
// hand-over of theirs accounts for.
func cpoUnnamedSlotHeld(ctx context.Context, db schooldirectory.Querier, h cpoOpenHandover, kind string, all []cpoOpenHandover,
	outside []string) (bool, error) {
	named := map[int]bool{}
	for _, o := range all {
		if o.id == h.id || o.school != h.school || o.partner != h.partner || !o.namesItsSlot() || o.kind(outside) != kind {
			continue
		}
		number := o.visit
		if kind == "training" {
			number = o.training
		}
		if n, err := strconv.Atoi(strings.TrimSpace(orElse(number, "0"))); err == nil {
			named[n] = true
		}
	}
	rows, err := db.Query(ctx, `SELECT sl.sequence_number FROM core_activity_slot sl LEFT JOIN core_plan cp ON cp.id = sl.core_plan_id
WHERE sl.school_id = $1 AND sl.activity_type = $2 AND sl.assigned_partner_id = $3 AND sl.activity_id IS NULL
  AND lower(trim(COALESCE(sl.status, ''))) = 'assigned'
ORDER BY cp.fy DESC NULLS FIRST, sl.sequence_number`, h.schoolCode, kind, h.partner)
	if err != nil {
		return false, fmt.Errorf("planningmonitor: the hand-over's slot: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var seq int
		if err := rows.Scan(&seq); err != nil {
			return false, fmt.Errorf("planningmonitor: the hand-over's slot: %w", err)
		}
		if !named[seq] {
			return true, nil
		}
	}
	return false, rows.Err()
}

// cpoRecordChecks are checks 7 to 13.
func cpoRecordChecks(ctx context.Context, db schooldirectory.Querier, snap *cpoSnapshot, ids []string, sample int) ([]cpoCheck, error) {
	c := rules.CountryOversight
	d := snap.data
	fy := d.window.fy
	limit := func(n int) int { return min(n, sample) }
	out := []cpoCheck{}

	// 7. Partner work with no hand-over behind it.
	rows, err := db.Query(ctx, `SELECT COALESCE(s.name, a.id), COALESCE(a.activity_type, ''), a.planned_date FROM activity a
LEFT JOIN school s ON s.id = a.school_id
WHERE a.fy = $1 AND a.deleted_at IS NULL AND a.delivery_type = 'partner' AND a.status = ANY($2) AND a.school_id = ANY($3)
  AND NOT EXISTS (SELECT 1 FROM partner_assignment pa WHERE pa.scheduled_activity_id = a.id)
ORDER BY a.planned_date`, fy, c.PlannedStates, ids)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: Partner work with no hand-over: %w", err)
	}
	orphans, err := collectActivityLines(rows, "")
	if err != nil {
		return nil, err
	}
	out = append(out, cpoCheck{label: "Partner schedule without assignment", count: len(orphans), severity: "info",
		meaning:   "Partner-delivered visits with no handover recorded behind them. They count as Partner-scheduled; the handover history is missing.",
		correctAt: "Partner Monitoring", samples: orphans[:limit(len(orphans))]})

	// 8. Cluster sessions with no planned roster, and walk-ins.
	rows, err = db.Query(ctx, `SELECT COALESCE(NULLIF(cl.name, ''), a.id), COALESCE(a.activity_type, ''), a.planned_date FROM activity a
JOIN cluster cl ON cl.id = a.cluster_id
WHERE a.fy = $1 AND a.deleted_at IS NULL AND a.status = ANY($2) AND a.activity_type = ANY($3)
  AND NOT EXISTS (SELECT 1 FROM cluster_activity_attendance x WHERE x.activity_id = a.id AND x.invited)
ORDER BY a.planned_date`, fy, c.PlannedStates, c.Page.DataQuality.SessionTypes)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: sessions with no roster: %w", err)
	}
	sessions, err := collectActivityLines(rows, "")
	if err != nil {
		return nil, err
	}
	out = append(out, cpoCheck{label: "Training or cluster meeting with no planned school roster", count: len(sessions), severity: "warning",
		meaning:   "A cluster session covers only the schools on its planned roster, never the whole cluster — so these cover no school at all.",
		correctAt: "Cluster Oversight (the session's invitations)", samples: sessions[:limit(len(sessions))]})
	var walkIns int
	if err := db.QueryRow(ctx, `SELECT count(*) FROM cluster_activity_attendance x JOIN activity a ON a.id = x.activity_id
WHERE a.fy = $1 AND a.deleted_at IS NULL AND NOT x.invited AND x.attended AND x.school_id = ANY($2)`, fy, ids).Scan(&walkIns); err != nil {
		return nil, fmt.Errorf("planningmonitor: walk-ins: %w", err)
	}
	out = append(out, cpoCheck{label: "Cluster meeting counting schools not on the roster", count: walkIns, severity: "info",
		meaning:   "Schools recorded as attending a session they were not invited to. They are not counted as planned coverage.",
		correctAt: "Cluster Oversight"})

	// 9. Closed schools with planned work.
	rows, err = db.Query(ctx, `SELECT COALESCE(s.name, ''), COALESCE(s.school_id, ''), count(*) FROM activity a JOIN school s ON s.id = a.school_id
WHERE a.fy = $1 AND a.deleted_at IS NULL AND a.status = ANY($2) AND s.operational_status = ANY($3)
GROUP BY a.school_id, s.name, s.school_id ORDER BY count(*) DESC LIMIT 50`, fy, c.PlannedStates, c.ClosedStatuses)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: closed schools with plans: %w", err)
	}
	closed := []cpoSample{}
	for rows.Next() {
		var name, code string
		var n int
		if err := rows.Scan(&name, &code, &n); err != nil {
			rows.Close()
			return nil, fmt.Errorf("planningmonitor: a closed school with plans: %w", err)
		}
		closed = append(closed, cpoSample{label: name, detail: fmt.Sprintf("%s · %d planned", code, n)})
	}
	rows.Close()
	out = append(out, cpoCheck{label: "Closed school in the portfolio", count: len(closed), severity: severityIf(len(closed) > 0, "warning"),
		meaning:   "Closed schools are never in the denominator; these still carry planned work for the year, which is counted nowhere.",
		correctAt: "Closed Schools", samples: closed[:limit(len(closed))]})

	// 10. Several clusters, or a cluster that is not active.
	rows, err = db.Query(ctx, `SELECT school_id, cluster_id FROM school_cluster_assignment WHERE school_id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the schools' clusters: %w", err)
	}
	projection := map[string]map[string]bool{}
	for rows.Next() {
		var school, cluster string
		if err := rows.Scan(&school, &cluster); err != nil {
			rows.Close()
			return nil, fmt.Errorf("planningmonitor: a school's cluster: %w", err)
		}
		if projection[school] == nil {
			projection[school] = map[string]bool{}
		}
		projection[school][cluster] = true
	}
	rows.Close()
	clusters := cpoCheck{label: "School with several active clusters",
		meaning: "Counted once, by its canonical cluster, and only when that cluster is active.", correctAt: "Clusters"}
	for _, s := range d.schools {
		linked := projection[s.id]
		why := ""
		switch {
		case len(linked) > 1 || (s.rawClusterID != "" && len(linked) > 0 && !linked[s.rawClusterID]):
			why = "several cluster records"
		case s.rawClusterID != "" && s.clusterID == "":
			why = "its cluster is not active"
		case s.clusterStatus == "clustered" && s.rawClusterID == "":
			why = "marked clustered with no cluster"
		}
		if why != "" {
			clusters.count++
			if len(clusters.samples) < sample {
				clusters.samples = append(clusters.samples, cpoSample{label: s.name, detail: s.code + " · " + why})
			}
		}
	}
	clusters.severity = severityIf(clusters.count > 0, "warning")
	out = append(out, clusters)

	// 11. Capacity the requirement exceeds, plans past the ceiling, Core
	// schools taking all of it.
	ownerLabel := func(o *cpoOwnerRow) string {
		if o.kind == "pl_personal" {
			return o.name + " (personal)"
		}
		return o.name
	}
	var deficits, overCap, coreOnly []*cpoOwnerRow
	for _, lead := range snap.tree.leads {
		for _, o := range lead.owners {
			t := cpoTally(o.tally)
			if t.n("deficit") > 0 {
				deficits = append(deficits, o)
			}
			if t.n("over_cap") > 0 {
				overCap = append(overCap, o)
			}
			if t.n("core_only_people") > 0 {
				coreOnly = append(coreOnly, o)
			}
		}
	}
	owners := func(check cpoCheck, list []*cpoOwnerRow, detail func(t cpoTally, ceiling int) string) cpoCheck {
		check.count = len(list)
		check.severity = severityIf(len(list) > 0, "warning")
		for _, o := range list[:limit(len(list))] {
			check.samples = append(check.samples, cpoSample{label: ownerLabel(o), detail: detail(cpoTally(o.tally), o.ceiling)})
		}
		return check
	}
	out = append(out,
		owners(cpoCheck{label: "Visit requirement exceeding capacity", correctAt: "Staffing decision (Country Director)",
			meaning: "Core staff slots beyond the holder's annual staff ceiling. They stay staff slots and show as a deficit until reassigned or resolved."},
			deficits, func(t cpoTally, ceiling int) string {
				return commas(t.n("deficit")) + " slots over a " + commas(ceiling) + " ceiling"
			}),
		owners(cpoCheck{label: "Plans past the staff visit ceiling", correctAt: "Programme Lead (hand the schools past the ceiling to a Partner)",
			meaning: "More counted visits planned than the role plans in a year (280 a Programme Lead, 560 a CCEO). Nothing was refused: the visits past the ceiling are the Partner's share."},
			overCap, func(t cpoTally, ceiling int) string {
				return commas(t.n("p_visits")) + " planned, " + commas(t.n("over_cap")) + " past " + commas(ceiling)
			}),
		owners(cpoCheck{label: "Core schools taking the whole ceiling", correctAt: "Staffing decision (Country Director)",
			meaning: "At two staff visits each, the Core schools held take every visit the role plans in a year (OVER_CAPACITY_CORE_ONLY), so every other school held is the Partner's."},
			coreOnly, func(t cpoTally, ceiling int) string {
				return commas(t.n("core_schools")) + " Core schools · " + commas(t.n("core_staff_slots")) + " staff visits against " + commas(ceiling)
			}))

	// 12. Totals that must reconcile.
	mismatches := cpoReconciliation(snap.tree)
	recon := cpoCheck{label: "Totals that do not reconcile", count: len(mismatches), severity: severityIf(len(mismatches) > 0, "critical"),
		meaning:   "The country total must equal the sum of its Programme Leads, and each Lead the sum of their CCEOs and personal delivery.",
		correctAt: "Engineering"}
	for _, m := range mismatches[:limit(len(mismatches))] {
		recon.samples = append(recon.samples, cpoSample{label: m})
	}
	out = append(out, recon)

	// 13. Possible duplicate records, still counted.
	rows, err = db.Query(ctx, `SELECT COALESCE(name, ''), COALESCE(school_id, '') FROM school WHERE id = ANY($1) AND duplicate_status = 'potential'`, ids)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: possible duplicates: %w", err)
	}
	dups := cpoCheck{label: "Possible duplicate school records", severity: "info", correctAt: "School Directory duplicate review",
		meaning: "Flagged as possible duplicates and still counted; confirmed and merged duplicates are already excluded."}
	for rows.Next() {
		var name, code string
		if err := rows.Scan(&name, &code); err != nil {
			rows.Close()
			return nil, fmt.Errorf("planningmonitor: a possible duplicate: %w", err)
		}
		dups.count++
		if len(dups.samples) < sample {
			dups.samples = append(dups.samples, cpoSample{label: name, detail: code})
		}
	}
	rows.Close()
	return append(out, dups), nil
}

// cpoReconciliation is _reconciliation: a Lead row that is not the sum of
// its people, and a country total that is not the sum of its Leads.
func cpoReconciliation(tree *cpoTree) []string {
	problems := []string{}
	total := make([]int, len(tree.country))
	for _, lead := range tree.leads {
		addInto(total, lead.tally)
		members := make([]int, len(tree.country))
		for _, o := range lead.owners {
			addInto(members, o.tally)
		}
		if !slices.Equal(members, lead.tally) {
			problems = append(problems, lead.name+": the Lead row is not the sum of its people")
		}
	}
	country := slices.Clone(tree.country)
	if i, ok := cpoIdx["unmapped_schools"]; ok {
		country[i] = total[i]
	}
	if !slices.Equal(total, country) {
		problems = append(problems, "Country: the total is not the sum of its Programme Leads")
	}
	return problems
}
