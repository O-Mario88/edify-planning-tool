package planningpage

import (
	"context"
	"fmt"
	"slices"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// ownWorkload is staff_plan.own_workload: a Programme Lead's or CCEO's own
// year shared out (country_oversight.rules.workload) — the staff visits the
// schools they hold take, two at each Core school and then one at each
// Client, Core Trained and Core Graduate school until the ceiling — and
// what they have planned against it.
type ownWorkload struct {
	fy                string
	ceiling           int
	corePlanned       int
	clientPlanned     int
	coreSchools       int
	clientSchools     int
	coreStaffVisits   int
	corePartnerVisits int
}

func (w ownWorkload) planned() int { return w.corePlanned + w.clientPlanned }

// over is rules.over_ceiling.
func (w ownWorkload) over() int { return max(0, w.planned()-w.ceiling) }

func (w ownWorkload) staffCore() int   { return w.coreStaffVisits * w.coreSchools }
func (w ownWorkload) partnerCore() int { return w.corePartnerVisits * w.coreSchools }

func (w ownWorkload) staffClient() int {
	return min(w.clientSchools, max(0, w.ceiling-w.staffCore()))
}

func (w ownWorkload) partnerSchools() int { return w.clientSchools - w.staffClient() }

func (w ownWorkload) coreOver() int { return max(0, w.staffCore()-w.ceiling) }

func (w ownWorkload) coreOnly() bool {
	return w.ceiling > 0 && w.coreSchools > 0 && w.staffCore() >= w.ceiling
}

// lead is the line's bold opening (partials/planning/_workload_line.html).
func (w ownWorkload) lead() string {
	return fmt.Sprintf("Your FY%s visits: %d of %d planned.", w.fy, w.planned(), w.ceiling)
}

// pick is Django's pluralize:"one,many".
func pick(n int, one, many string) string {
	if n == 1 {
		return one
	}
	return many
}

// text is the whole line as the page writes it, sentence by sentence.
func (w ownWorkload) text() string {
	parts := []string{
		w.lead(),
		fmt.Sprintf("Core %d of %d · Client %d of %d.", w.corePlanned, w.staffCore(), w.clientPlanned, w.staffClient()),
	}
	if n := w.partnerSchools(); n != 0 {
		parts = append(parts, fmt.Sprintf("%d of your Client schools %s beyond your %d and %s the Partner's to visit: assign %s to a Partner.",
			n, pick(n, "is", "are"), w.ceiling, pick(n, "is", "are"), pick(n, "it", "them")))
	}
	if w.partnerCore() != 0 {
		parts = append(parts, "The Partner also takes two visits and two trainings at each of your Core schools.")
	}
	if w.coreOnly() {
		over := ""
		if n := w.coreOver(); n != 0 {
			over = fmt.Sprintf(" (%d over)", n)
		}
		parts = append(parts, fmt.Sprintf("Your Core schools alone take your whole %d%s, so every other school you hold is the Partner's.", w.ceiling, over))
	}
	if n := w.over(); n != 0 {
		parts = append(parts, fmt.Sprintf("You are %d past your %d. Nothing was refused; the visits past it are the Partner's share.", n, w.ceiling))
	}
	return strings.Join(parts, " ")
}

// tone is the note's data-tone: warning past the ceiling or when the Core
// schools alone fill it.
func (w ownWorkload) tone() string {
	if w.over() != 0 || w.coreOnly() {
		return "warning"
	}
	return "info"
}

// readWorkload is own_workload for the person; ok false for a role that
// plans no visits.
func readWorkload(ctx context.Context, q schooldirectory.Querier, p auth.Principal, fy string) (ownWorkload, bool, error) {
	cv := rules.CountedVisits
	held := map[string]bool{p.ActiveRole: p.ActiveRole != ""}
	for _, r := range p.Roles {
		held[r] = true
	}
	role := ""
	switch {
	case held[cv.ProgramLeadRole]:
		role = cv.ProgramLeadRole
	case held[cv.CCEORole]:
		role = cv.CCEORole
	}
	ceiling := cv.VisitTargets[role]
	if ceiling == 0 {
		return ownWorkload{}, false, nil
	}
	ids := []string{}
	for _, id := range []string{p.UserID, p.StaffProfileID} {
		if id != "" {
			ids = append(ids, id)
		}
	}
	w := ownWorkload{fy: fy, ceiling: ceiling, coreStaffVisits: cv.CoreStaffVisits, corePartnerVisits: cv.CorePartnerVisits}
	if err := heldSchools(ctx, q, ids, &w); err != nil {
		return ownWorkload{}, false, err
	}
	if err := countedVisits(ctx, q, ids, fy, &w); err != nil {
		return ownWorkload{}, false, err
	}
	return w, true, nil
}

// heldSchools is the operating schools the person holds, Core and the Client
// rule types (active_schools by account owner, by school type).
func heldSchools(ctx context.Context, q schooldirectory.Querier, ids []string, w *ownWorkload) error {
	cv := rules.CountedVisits
	rows, err := q.Query(ctx, `
SELECT COALESCE(s.school_type, ''), count(*) FROM school s
WHERE s.account_owner_id = ANY($1) AND s.deleted_at IS NULL AND s.operational_status = ANY($2)
GROUP BY 1`, ids, cv.OperatingStatuses)
	if err != nil {
		return fmt.Errorf("planningpage: reading held schools: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var kind string
		var n int
		if err := rows.Scan(&kind, &n); err != nil {
			return fmt.Errorf("planningpage: reading held schools: %w", err)
		}
		switch {
		case kind == cv.CoreType:
			w.coreSchools += n
		case slices.Contains(cv.ClientRuleTypes, kind):
			w.clientSchools += n
		}
	}
	return rows.Err()
}

// countedVisits is staff_plan.visit_tally: the person's counted visits of
// the year, Core or Client by the school's type.
func countedVisits(ctx context.Context, q schooldirectory.Querier, ids []string, fy string, w *ownWorkload) error {
	cv := rules.CountedVisits
	outside, err := visitgate.ProjectsOutsideSSA(ctx, q, schoolprofile.GateRules())
	if err != nil {
		return err
	}
	rows, err := q.Query(ctx, `
SELECT s.school_type, count(*) FROM activity a LEFT JOIN school s ON s.id = a.school_id
WHERE a.responsible_staff_id = ANY($1) AND a.fy = $2 AND a.deleted_at IS NULL
  AND a.status = ANY($3) AND (a.planned_date IS NOT NULL OR a.scheduled_date IS NOT NULL)
  AND a.activity_type = ANY($4) AND a.school_id IS NOT NULL AND a.cluster_id IS NULL
  AND a.purpose_type IS DISTINCT FROM $5 AND NOT COALESCE(a.purpose_type = ANY($6), false)
  AND NOT COALESCE(a.project_id = ANY($7), false)
  AND (NOT (COALESCE(a.purpose_type = ANY($8), false)
        OR (a.activity_type = ANY($9) AND NOT COALESCE(a.purpose_type = ANY($10), false)))
       OR a.delivery_type IS DISTINCT FROM 'partner')
  AND a.delivery_type IS DISTINCT FROM 'partner'
GROUP BY 1`,
		ids, fy, cv.PlannedStates, cv.VisitShapeTypes, cv.CompanionPurpose, cv.OutreachPurposes, nonNil(outside),
		cv.DataCollectionPurposes, cv.DataCollectionTypes, cv.KindPurposes)
	if err != nil {
		return fmt.Errorf("planningpage: counting counted visits: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var kind *string
		var n int
		if err := rows.Scan(&kind, &n); err != nil {
			return fmt.Errorf("planningpage: counting counted visits: %w", err)
		}
		if kind != nil && slices.Contains(cv.CoreTypes, *kind) {
			w.corePlanned += n
		} else {
			w.clientPlanned += n
		}
	}
	return rows.Err()
}

// workload is the page's workload line (partials/planning/_workload_line.html,
// a note read whole: its bold opening, the rest and its tone); nil for a
// role that plans no visits.
func workload(ctx context.Context, q schooldirectory.Querier, p auth.Principal, fy string) (*screensv1.PageBlock, error) {
	w, ok, err := readWorkload(ctx, q, p, fy)
	if err != nil || !ok {
		return nil, err
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: w.text()}, Lead: w.lead(), Tone: w.tone()}},
	}}}, nil
}
