package planningoversight

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// handover is one PartnerAssignment a Partner has not scheduled, as
// _assignment_item reads it.
type handover struct {
	id, activityType, partnerName                    string
	schoolPK, schoolName, clusterName                string
	monitoring, assigning, focus, projectID, purpose string
	created                                          *time.Time
}

// handoverDetail is oversight_detail_view for an assignment_id: the
// hand-over, if it still waits on the Partner (open, not left the Partner)
// and the lens reads it (record_in_scope's _assignment_scope_q).
func (s *Service) handoverDetail(ctx context.Context, id string, team, regions []string, now time.Time, canSend bool) (*screensv1.PageDrawer, string, error) {
	c := rules.TeamPlan.Coverage
	var h handover
	err := s.db.QueryRow(ctx, `
SELECT pa.id, COALESCE(pa.expected_activity_type, ''), COALESCE(pt.name, ''), COALESCE(pa.school_id, ''), COALESCE(s.name, ''),
  COALESCE(c.name, ''), COALESCE(pa.monitoring_staff_id, ''), COALESCE(pa.assigning_staff_id, ''),
  COALESCE(pa.focus_intervention, ''), COALESCE(pa.project_id, ''),
  COALESCE(NULLIF(pa.purpose_of_visit, ''), NULLIF(pa.purpose, ''), pa.notes, ''), pa.created_at
FROM partner_assignment pa
LEFT JOIN school s ON s.id = pa.school_id
LEFT JOIN cluster c ON c.id = pa.cluster_id
LEFT JOIN district cd ON cd.id = c.district_id
LEFT JOIN partner pt ON pt.id = pa.partner_id
WHERE pa.id = $1 AND pa.status = ANY($2) AND NOT (pa.status = ANY($3) OR (pa.status = 'returned_to_staff' AND pa.resolved_at IS NOT NULL))
  AND ($4::text[] IS NULL OR pa.monitoring_staff_id = ANY($4) OR pa.assigning_staff_id = ANY($4))
  AND ($5::text[] IS NULL OR s.region_id = ANY($5) OR cd.region_id = ANY($5))`,
		id, c.AssignmentStatuses, c.LeftPartnerStatuses, team, regions).Scan(&h.id, &h.activityType, &h.partnerName, &h.schoolPK,
		&h.schoolName, &h.clusterName, &h.monitoring, &h.assigning, &h.focus, &h.projectID, &h.purpose, &h.created)
	if errors.Is(err, pgx.ErrNoRows) {
		return notAvailable, "", nil
	}
	if err != nil {
		return nil, "", fmt.Errorf("planningoversight: reading the hand-over: %w", err)
	}
	owner := first(h.monitoring, h.assigning)
	people, err := s.staffNames(ctx, []string{owner, h.assigning})
	if err != nil {
		return nil, "", err
	}
	lead := &item{a: &act{}, owner: owner}
	if err := s.stampLeads(ctx, []*item{lead}); err != nil {
		return nil, "", err
	}
	leadName := "Unassigned"
	if lead.lead != "" {
		names, err := s.staffNames(ctx, []string{lead.lead})
		if err != nil {
			return nil, "", err
		}
		leadName = first(names[lead.lead].name, "Unassigned")
	}
	role, err := s.activeRole(ctx, h.assigning)
	if err != nil {
		return nil, "", err
	}
	intervention := h.focus
	if intervention == "" && h.projectID != "" {
		outside, err := visitgate.ProjectsOutsideSSA(ctx, s.db, schoolprofile.GateRules())
		if err != nil {
			return nil, "", err
		}
		if slices.Contains(outside, h.projectID) {
			intervention = rules.TeamPlan.Items.GeneralIntervention
		}
	}
	plannedBy := first(people[h.assigning].name, "—")
	if role != "" {
		plannedBy += " (" + role + ")"
	}
	ownerName := people[owner].name
	assigned := "—"
	var assignedDay *time.Time
	if h.created != nil {
		// created_at.date(): the stored moment's (UTC) day.
		assignedDay = utcDay(h.created)
		assigned = assignedDay.Format("2 Jan 2006")
	}
	title := capFirst(strings.ReplaceAll(h.activityType, "_", " "))
	if title == "" {
		title = "Partner assignment"
	}
	d := &screensv1.PageDrawer{Title: title, Subtitle: first(h.schoolName, h.clusterName, "No context"), HasRequired: true,
		CancelLabel: "Cancel", Items: []*screensv1.DrawerItem{
			drawerHeading("Ownership"),
			drawerFacts([2]string{"Planned by", plannedBy}, [2]string{"Operational owner", first(ownerName, "—")},
				[2]string{"Executor", first(h.partnerName, "—") + " (partner)"}, [2]string{"Managing staff", first(ownerName, "—")},
				[2]string{"Supervising PL", leadName}, [2]string{"Partner", first(h.partnerName, "—")}),
			drawerHeading("Planning"),
			drawerFacts([2]string{"Planned date", "Not scheduled"}, [2]string{"Financial year", "FY —"}, [2]string{"Assigned", assigned},
				[2]string{"Intervention", first(djangoTitle(strings.ReplaceAll(intervention, "_", " ")), "—")},
				[2]string{"Rationale", first(h.purpose, "—")}),
			drawerHeading("Cost lineage"),
			drawerText("Nothing is scheduled yet, so this handover carries no cost line and contributes UGX 0 to the plan. A cost appears when the partner schedules."),
			drawerHeading("Workflow state"),
			drawerFacts([2]string{"Activity", "—"}, [2]string{"Salesforce", ""}, [2]string{"Impact Assessment", "—"},
				[2]string{"Finance", "—"}, [2]string{"Reschedules", "0"}),
		}}
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	if r, ok := partnerNotScheduled(h.partnerName, ownerName, assignedDay, today); ok {
		return withRisks(d, []risk{r}, canSend, h.schoolPK != ""), "", nil
	}
	return d, "", nil
}

// partnerNotScheduled is risk_service._partner_not_scheduled for a hand-over
// with no schedule-by date: due a week after it was assigned (today when it
// carries no day), late from the day after.
func partnerNotScheduled(partner, manager string, assigned *time.Time, today time.Time) (risk, bool) {
	grace := rules.TeamPlan.Items.Risk.PartnerScheduleGraceDays
	from := today
	if assigned != nil {
		from = *assigned
	}
	deadline := from.AddDate(0, 0, grace)
	if !today.After(deadline) {
		return risk{}, false
	}
	days := int(today.Sub(deadline).Hours() / 24)
	severity, plural := "warning", "s"
	if days > grace {
		severity = "high"
	}
	if days == 1 {
		plural = ""
	}
	return risk{key: "partner_not_scheduled", severity: severity,
		reason: fmt.Sprintf("%s has not scheduled this handover; it was due to be scheduled %d day%s ago.",
			first(partner, "The partner"), days, plural),
		action: "Chase the partner or take the work back", owner: manager, due: &deadline}, true
}
