package planningpage

import (
	"context"

	"github.com/jackc/pgx/v5"
)

// responsibility is support_responsibility.SupportResponsibility as the
// CSV's Responsible and Partner Workflow columns read it.
type responsibility struct {
	multiple, partner, returned bool
	name, stageLabel            string
}

// display is SupportResponsibility.display.
func (r responsibility) display() string {
	if r.multiple {
		return rules.CSVExport.MultipleLabel
	}
	kind := "Staff"
	if r.partner {
		kind = "Partner"
	}
	name := r.name
	if name == "" {
		name = "Unassigned"
	}
	return kind + " · " + name
}

// workflow is SupportResponsibility.workflow_label.
func (r responsibility) workflow() string {
	switch {
	case r.returned:
		return rules.CSVExport.ReturnedLabel
	case r.multiple:
		return rules.CSVExport.MultipleLabel
	case r.partner && r.stageLabel != "":
		return r.stageLabel
	}
	return "—"
}

// activityStage is support_responsibility.activity_stage.
func activityStage(status, ia string) string {
	x := rules.CSVExport
	switch {
	case in(x.ReturnedByReview, status):
		return "returned_by_ia"
	case ia == "confirmed" || status == "ia_verified" || status == "accountant_confirmed":
		return "ia_verified"
	case in(x.Submitted, status) || status == "completed" || status == "closed":
		return "evidence_submitted"
	case in(x.InProgress, status):
		return "in_progress"
	}
	return "scheduled"
}

// responsibilities is SchoolSupportResponsibilityService.resolve for the
// listed schools in the year fy.
func (s *Service) responsibilities(ctx context.Context, list []school, fy string) (map[string]responsibility, error) {
	ids := make([]string, 0, len(list))
	for _, sc := range list {
		ids = append(ids, sc.ID)
	}
	// The first ownership link stands in for an owner column never filled.
	firstLink := map[string]string{}
	if err := each(ctx, s.db, "the schools' ownership links", `SELECT school_id, staff_id FROM staff_school_assignment WHERE school_id = ANY($1)`,
		func(rows pgx.Rows) error {
			var school, staff string
			if err := rows.Scan(&school, &staff); err != nil {
				return err
			}
			if _, ok := firstLink[school]; !ok {
				firstLink[school] = staff
			}
			return nil
		}, ids); err != nil {
		return nil, err
	}
	ownerOf := map[string]string{}
	wanted := []string{}
	for _, sc := range list {
		owner := sc.OwnerID
		if owner == "" {
			owner = firstLink[sc.ID]
		}
		ownerOf[sc.ID] = owner
		if owner != "" {
			wanted = append(wanted, owner)
		}
	}
	names := map[string]string{}
	if err := each(ctx, s.db, "the owners' names", `SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(NULLIF(u.name, ''), u.email, '')
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id WHERE sp.id = ANY($1) OR sp.user_id = ANY($1)`,
		func(rows pgx.Rows) error {
			var id, user, label string
			if err := rows.Scan(&id, &user, &label); err != nil {
				return err
			}
			names[id] = label
			if user != "" {
				names[user] = label
			}
			return nil
		}, wanted); err != nil {
		return nil, err
	}
	type live struct {
		partner, partnerName, status, activityStatus, ia string
		hasActivity                                      bool
	}
	lives := map[string][]live{}
	returned := map[string]bool{}
	if err := each(ctx, s.db, "the schools' partner support", `SELECT pa.school_id, COALESCE(pa.partner_id, ''), COALESCE(p.name, ''),
  COALESCE(pa.status, ''), a.id IS NOT NULL, COALESCE(a.status, ''), COALESCE(a.ia_verification_status, '')
FROM partner_assignment pa LEFT JOIN partner p ON p.id = pa.partner_id LEFT JOIN activity a ON a.id = pa.scheduled_activity_id
WHERE pa.school_id = ANY($1) AND (
  (pa.status IS DISTINCT FROM 'returned_to_staff' AND (pa.scheduled_activity_id IS NULL
     OR (a.deleted_at IS NULL AND NOT COALESCE(a.status = ANY($2), false) AND a.fy >= $3)))
  OR (pa.status = 'returned_to_staff' AND pa.resolved_at IS NULL))
ORDER BY pa.created_at, pa.id`, func(rows pgx.Rows) error {
		var school string
		var l live
		if err := rows.Scan(&school, &l.partner, &l.partnerName, &l.status, &l.hasActivity, &l.activityStatus, &l.ia); err != nil {
			return err
		}
		if l.status == "returned_to_staff" {
			returned[school] = true
			return nil
		}
		lives[school] = append(lives[school], l)
		return nil
	}, ids, rules.CSVExport.ClosedActivityStatuses, fy); err != nil {
		return nil, err
	}
	out := map[string]responsibility{}
	for _, sc := range list {
		owner := ownerOf[sc.ID]
		r := responsibility{name: names[owner], returned: returned[sc.ID]}
		if r.name == "" {
			r.name = sc.OwnerRaw
		}
		if held := lives[sc.ID]; len(held) > 0 {
			partners := []string{}
			for _, l := range held {
				if !in(partners, l.partner) {
					partners = append(partners, l.partner)
				}
			}
			lead := held[len(held)-1]
			if len(partners) > 1 {
				r.multiple = true
			} else {
				stage := "awaiting_schedule"
				if lead.hasActivity {
					stage = activityStage(lead.activityStatus, lead.ia)
				}
				r.partner, r.name, r.stageLabel = true, lead.partnerName, rules.CSVExport.StageLabels[stage]
			}
		}
		out[sc.ID] = r
	}
	return out, nil
}
