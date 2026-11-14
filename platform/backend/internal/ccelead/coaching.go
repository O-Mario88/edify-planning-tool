package ccelead

import (
	"context"
	"fmt"
	"net/url"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// MyCoachingPath is My Coaching.
const MyCoachingPath = "/my-coaching"

const cceo = "CCEO"

// coachingVisible is coaching.coaching_visible_to as a WHERE clause on
// cce_cceo_coaching `c`, for the readers My Coaching opens to: Admin every
// record; of those shared, a CCEO's own (by their account or their People
// record), a Country Director's of their country, a Regional Lead's of the
// countries in reach; nothing for anyone else (Impact Assessment, and a
// Programme Lead, whose own register is Team Coaching).
func coachingVisible(ctx context.Context, db schooldirectory.Querier, p auth.Principal) (string, []any, error) {
	switch p.ActiveRole {
	case adminRole:
		return "TRUE", nil, nil
	case cceo:
		staff := p.StaffProfileID
		if staff == "" {
			err := db.QueryRow(ctx, `SELECT id FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL ORDER BY id LIMIT 1`, p.UserID).Scan(&staff)
			if err != nil && err != pgx.ErrNoRows {
				return "", nil, fmt.Errorf("ccelead: reading the officer's staff record: %w", err)
			}
		}
		if staff == "" {
			return "c.shared_at IS NOT NULL AND c.cceo_user_id = $1", []any{p.UserID}, nil
		}
		return "c.shared_at IS NOT NULL AND (c.cceo_user_id = $1 OR c.cceo_staff_id = $2)", []any{p.UserID, staff}, nil
	case countryDirector:
		var country *string
		err := db.QueryRow(ctx, `SELECT country FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL ORDER BY id LIMIT 1`, p.UserID).Scan(&country)
		if err != nil && err != pgx.ErrNoRows {
			return "", nil, fmt.Errorf("ccelead: reading the reader's country: %w", err)
		}
		if country == nil || *country == "" {
			return "FALSE", nil, nil
		}
		return "c.shared_at IS NOT NULL AND c.country = $1", []any{*country}, nil
	case regionalLead:
		countries, _, err := schooldirectory.RegionCountries(ctx, db, p.StaffProfileID)
		if err != nil {
			return "", nil, err
		}
		if len(countries) == 0 {
			return "FALSE", nil, nil
		}
		return "c.shared_at IS NOT NULL AND c.country = ANY($1)", []any{countries}, nil
	}
	return "FALSE", nil, nil
}

// myCoaching is my_coaching_view: the coaching the reader may read, narrowed
// by a kind it offers and by "awaiting" or "acknowledged", the latest first.
func myCoaching(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time, query url.Values) (register, error) {
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	officer := p.ActiveRole == cceo
	visible, args, err := coachingVisible(ctx, db, p)
	if err != nil {
		return register{}, err
	}
	visibleN := len(args)
	kind, state := query.Get("kind"), query.Get("state")
	where := visible
	known := false
	for _, k := range rules.CoachingKinds {
		known = known || k[0] == kind
	}
	if kind != "" && known {
		args = append(args, kind)
		where += fmt.Sprintf(" AND c.kind = $%d", len(args))
	} else {
		kind = ""
	}
	switch state {
	case "awaiting":
		where += " AND c.shared_at IS NOT NULL AND c.acknowledged_at IS NULL"
	case "acknowledged":
		where += " AND c.acknowledged_at IS NOT NULL"
	default:
		state = ""
	}
	rows, err := db.Query(ctx, fmt.Sprintf(`
SELECT c.id, c.subject, c.cceo_staff_id, c.kind, c.held_on, c.author_id, c.follow_up_due, c.follow_up_done_at, c.shared_at, c.acknowledged_at,
       (SELECT u.name FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE sp.id = c.cceo_staff_id AND sp.deleted_at IS NULL)
FROM cce_cceo_coaching c WHERE %s ORDER BY c.held_on DESC, c.created_at DESC LIMIT %d`, where, feedbackLimit), args...)
	if err != nil {
		return register{}, fmt.Errorf("ccelead: reading the coaching: %w", err)
	}
	type record struct {
		id, subject, staff, kind, author string
		held                             time.Time
		due                              *time.Time
		done, shared, acknowledged       *time.Time
		officerName                      *string
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (record, error) {
		var x record
		err := r.Scan(&x.id, &x.subject, &x.staff, &x.kind, &x.held, &x.author, &x.due, &x.done, &x.shared, &x.acknowledged, &x.officerName)
		return x, err
	})
	if err != nil {
		return register{}, fmt.Errorf("ccelead: reading the coaching: %w", err)
	}
	ids := []string{}
	for _, x := range list {
		ids = append(ids, x.author)
	}
	who, err := names(ctx, db, ids)
	if err != nil {
		return register{}, err
	}
	kinds := map[string]string{}
	for _, k := range rules.CoachingKinds {
		kinds[k[0]] = k[1]
	}
	reg := register{
		path: MyCoachingPath, title: "My Coaching", eyebrow: "My performance", registerTitle: "Shared coaching",
		description: "What your Programme Lead shared from your one-to-ones, the visits and trainings they observed, and feedback " +
			"passed on from the Regional Lead. Acknowledge each one and say what you will do.",
		emptyTitle: "No coaching shared with you yet",
		emptyBody:  "Coaching appears here when your Programme Lead shares it with you.",
		columns:    []string{"Coaching"},
	}
	if officer {
		reg.registerTitle = "Coaching shared with you"
	} else {
		reg.columns = append(reg.columns, "Officer")
	}
	reg.columns = append(reg.columns, "Kind", "Held", "From", "Follow up by", "State")
	for _, x := range list {
		cells := []string{dash(x.subject)}
		if !officer {
			cells = append(cells, dash(deref(x.officerName)))
		}
		label, ok := kinds[x.kind]
		if !ok {
			label = x.kind
		}
		// coaching.state_of
		st := "Not shared yet"
		switch {
		case x.due != nil && x.done == nil && !x.due.After(today) && !officer:
			st = "Follow-up due"
		case x.acknowledged != nil:
			st = "Acknowledged"
		case x.shared != nil:
			st = "Awaiting the officer"
			if officer {
				st = "Awaiting your acknowledgement"
			}
		}
		due := ""
		if x.due != nil {
			due = x.due.Format("2 Jan 2006")
		}
		cells = append(cells, dash(label), dash(x.held.Format("2 Jan 2006")), dash(who[x.author]), dash(due), dash(st))
		reg.rows = append(reg.rows, cells)
		act := "Open"
		if officer && x.acknowledged == nil {
			act = "Acknowledge"
		}
		reg.rowActions = append(reg.rowActions, []action{{label: act, drawer: MyCoachingPath + "/" + x.id}})
	}
	// coaching.coaching_counts over everything visible, unfiltered.
	var awaiting, acknowledged, open int
	if err := db.QueryRow(ctx, fmt.Sprintf(`
SELECT count(*) FILTER (WHERE c.shared_at IS NOT NULL AND c.acknowledged_at IS NULL),
       count(*) FILTER (WHERE c.acknowledged_at IS NOT NULL),
       count(*) FILTER (WHERE c.follow_up_due IS NOT NULL AND c.follow_up_done_at IS NULL)
FROM cce_cceo_coaching c WHERE %s`, visible), args[:visibleN]...).Scan(&awaiting, &acknowledged, &open); err != nil {
		return register{}, fmt.Errorf("ccelead: counting the coaching: %w", err)
	}
	awaitingTone := "info"
	if awaiting > 0 {
		awaitingTone = "warning"
	}
	reg.metrics = []metric{
		{"Coaching Awaiting My Acknowledgement", strconv.Itoa(awaiting), "shared with you, not yet answered", awaitingTone},
		{"Coaching I Have Acknowledged", strconv.Itoa(acknowledged), "with your response", "success"},
		{"Agreed Coaching Actions Open", strconv.Itoa(open), "your lead will follow these up", "info"},
	}
	reg.filters = []*screensv1.PageFilter{
		filter("kind", "Kind", kind, "Every kind", rules.CoachingKinds),
		filter("state", "State", state, "Every state", [][2]string{{"awaiting", "Awaiting your acknowledgement"}, {"acknowledged", "Acknowledged"}}),
	}
	return reg, nil
}
