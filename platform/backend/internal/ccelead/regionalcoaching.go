package ccelead

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// RegionalCoachingPath is Regional Lead Coaching (cce_leadership_views.
// regional_coaching_view): the coaching conversations the Regional Lead
// shared with Programme Leads, and each lead's answer.
const RegionalCoachingPath = "/cce-leadership/coaching"

// regionalCoachingLimit is how many conversations the register reads.
const regionalCoachingLimit = 500

// regionalCoachingNotice is what the Country Director is told: none of the
// conversations reach them.
const regionalCoachingNotice = "Coaching the Regional Lead shares stays between the Regional Lead and each Programme Lead. " +
	"Training feedback on your country's trainings is on Training Feedback."

// coachingConversations is regional_coaching_visible_to as a WHERE clause on
// cce_regional_engagement `e` (a Programme Lead coaching): Admin every one;
// the Regional Lead their own; a Programme Lead those shared with them;
// nothing for anyone else.
func coachingConversations(ctx context.Context, db schooldirectory.Querier, p auth.Principal) (string, []any, error) {
	switch p.ActiveRole {
	case adminRole:
		return "TRUE", nil, nil
	case regionalLead:
		return "e.author_id = $1", []any{p.UserID}, nil
	case programLead:
		staff := p.StaffProfileID
		if staff == "" {
			err := db.QueryRow(ctx, `SELECT id FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL ORDER BY id LIMIT 1`, p.UserID).Scan(&staff)
			if err != nil && err != pgx.ErrNoRows {
				return "", nil, fmt.Errorf("ccelead: reading the lead's staff record: %w", err)
			}
		}
		if staff == "" {
			return "FALSE", nil, nil
		}
		return "e.feedback_shared_at IS NOT NULL AND e.program_lead_ids @> ARRAY[$1]::varchar[]", []any{staff}, nil
	}
	return "FALSE", nil, nil
}

type coachingConversation struct {
	id, author, subject, actions string
	held                         time.Time
	followUp                     *time.Time
	shared, acknowledged         *time.Time
	leads                        []string
}

// leadNames is each Programme Lead's staff id to their name.
func leadNames(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]string, error) {
	out := map[string]string{}
	rows, err := db.Query(ctx, `SELECT sp.id, COALESCE(u.name, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE sp.id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("ccelead: reading the Programme Leads' names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("ccelead: reading the Programme Leads' names: %w", err)
		}
		out[id] = name
	}
	return out, rows.Err()
}

// regionalCoaching is regional_coaching_view's register.
func regionalCoaching(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) (register, error) {
	where, args, err := coachingConversations(ctx, db, p)
	if err != nil {
		return register{}, err
	}
	rows, err := db.Query(ctx, fmt.Sprintf(`
SELECT e.id, e.author_id, e.subject, COALESCE(e.agreed_actions, ''), e.held_on, e.follow_up_due, e.feedback_shared_at,
       e.acknowledged_at, COALESCE(e.program_lead_ids, '{}')
FROM cce_regional_engagement e
WHERE e.kind = 'pl_coaching' AND %s ORDER BY e.held_on DESC, e.created_at DESC LIMIT %d`, where, regionalCoachingLimit), args...)
	if err != nil {
		return register{}, fmt.Errorf("ccelead: reading the coaching conversations: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (coachingConversation, error) {
		var c coachingConversation
		err := r.Scan(&c.id, &c.author, &c.subject, &c.actions, &c.held, &c.followUp, &c.shared, &c.acknowledged, &c.leads)
		return c, err
	})
	if err != nil {
		return register{}, fmt.Errorf("ccelead: reading the coaching conversations: %w", err)
	}
	pl := p.ActiveRole == programLead
	authors, leads := []string{}, []string{}
	for _, c := range list {
		authors = append(authors, c.author)
		leads = append(leads, c.leads...)
	}
	who, err := names(ctx, db, authors)
	if err != nil {
		return register{}, err
	}
	leadName := map[string]string{}
	if !pl {
		if leadName, err = leadNames(ctx, db, leads); err != nil {
			return register{}, err
		}
	}
	reg := register{
		path: RegionalCoachingPath, title: "Regional Lead Coaching", eyebrow: "Collaboration",
		registerTitle: "Coaching conversations", emptyTitle: "No coaching shared yet",
		description: "Coaching conversations the Regional Lead shared with Programme Leads, and each lead's response.",
		emptyBody:   "Coaching appears here once it is shared with a Programme Lead.",
		columns:     []string{"Conversation", "Held", "Programme Leads", "Actions agreed", "Follow up by", "State"},
	}
	if pl {
		reg.description = "Coaching conversations your Regional Lead shared with you: what was discussed and the actions " +
			"agreed. Acknowledge each one and say what you will do."
		reg.emptyBody = "Coaching appears here when your Regional Lead shares the notes of a coaching conversation with you."
		reg.columns[2] = "Regional Lead"
	}
	if p.ActiveRole == countryDirector {
		reg.notice = regionalCoachingNotice
	}
	// timezone.localdate(): the day in the platform's zone.
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	awaiting, acknowledged := 0, 0
	for _, c := range list {
		state := "Not shared yet"
		switch {
		case c.acknowledged != nil:
			state = "Acknowledged"
		case c.shared != nil:
			state = "Awaiting the Programme Lead"
			if pl {
				state = "Awaiting your acknowledgement"
			}
		}
		if c.shared != nil {
			if c.acknowledged != nil {
				acknowledged++
			} else {
				awaiting++
			}
		}
		followUp := ""
		if c.followUp != nil {
			followUp = c.followUp.Format("2 Jan 2006")
			if c.followUp.Before(today) && c.acknowledged == nil {
				followUp += " · passed"
			}
		}
		third := who[c.author]
		if !pl {
			parts := make([]string, len(c.leads))
			for i, id := range c.leads {
				name, ok := leadName[id]
				if !ok {
					name = "Programme Lead"
				}
				parts[i] = name
			}
			third = strings.Join(parts, ", ")
		}
		reg.rows = append(reg.rows, []string{dash(c.subject), dash(c.held.Format("2 Jan 2006")), dash(third),
			dash(c.actions), dash(followUp), dash(state)})
		label := "Open"
		if pl && c.acknowledged == nil {
			label = "Acknowledge"
		}
		reg.rowActions = append(reg.rowActions, []action{{label: label, drawer: RegionalCoachingPath + "/" + c.id}})
	}
	awaitingTone := "info"
	if awaiting > 0 {
		awaitingTone = "warning"
	}
	reg.metrics = []metric{
		{"Regional Lead Coaching Awaiting Acknowledgement", strconv.Itoa(awaiting), "shared, not yet acknowledged", awaitingTone},
		{"Regional Lead Coaching Acknowledged", strconv.Itoa(acknowledged), "with the Programme Lead's response", "success"},
	}
	return reg, nil
}
