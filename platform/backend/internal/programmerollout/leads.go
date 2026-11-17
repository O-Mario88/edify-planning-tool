package programmerollout

import (
	"context"
	"fmt"
)

// leadChoice is the Programme Lead whose team the page reads.
type leadChoice struct{ staffID, userID string }

// chooseLead is _admin_lead: the active Programme Leads by name, and the one
// asked for, else the first who supervises anyone, else the first. No lead
// at all is the page's own notice, and hands on (found false).
func (s *Service) chooseLead(ctx context.Context, asked string) (leadChoice, [][2]string, bool, error) {
	rows, err := s.db.Query(ctx, `SELECT sp.id, u.id, COALESCE(NULLIF(u.name, ''), u.email),
  EXISTS (SELECT 1 FROM staff_supervisor_assignment a WHERE a.supervisor_id = sp.id)
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE u.roles @> ARRAY[$1]::varchar[] AND u.is_active AND u.deleted_at IS NULL AND sp.deleted_at IS NULL
ORDER BY u.name, sp.id`, rules.ProgramLead)
	if err != nil {
		return leadChoice{}, nil, false, fmt.Errorf("programmerollout: reading the Programme Leads: %w", err)
	}
	defer rows.Close()
	options := [][2]string{}
	var chosen, supervising, first *leadChoice
	for rows.Next() {
		var c leadChoice
		var name string
		var supervises bool
		if err := rows.Scan(&c.staffID, &c.userID, &name, &supervises); err != nil {
			return leadChoice{}, nil, false, fmt.Errorf("programmerollout: reading a Programme Lead: %w", err)
		}
		options = append(options, [2]string{c.staffID, name})
		switch {
		case c.staffID == asked && chosen == nil:
			chosen = &c
		case supervises && supervising == nil:
			supervising = &c
		}
		if first == nil {
			first = &c
		}
	}
	if err := rows.Err(); err != nil {
		return leadChoice{}, nil, false, fmt.Errorf("programmerollout: reading the Programme Leads: %w", err)
	}
	for _, c := range []*leadChoice{chosen, supervising, first} {
		if c != nil {
			return *c, options, true, nil
		}
	}
	return leadChoice{}, options, false, nil
}
