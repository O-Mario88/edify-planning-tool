package routeplan

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"

	routesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/routes/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Save Plan and Start Field Day (owner, 2026-11-16): a person's own record
// of a field day in field_routes.field_day and field_day_stop (migration
// 0004). Saving keeps the visiting order so the planner opens on it on any
// device; starting, arriving, leaving and ending record when. Nothing here
// schedules, moves or completes an activity.

// maxDayStops is the most schools a saved day holds.
const maxDayStops = 30

// stopTimes is when the person reached and left one stop.
type stopTimes struct{ arrived, left *time.Time }

// fieldDay is one person's day as stored.
type fieldDay struct {
	order                 []string
	saved, started, ended *time.Time
	stops                 map[string]stopTimes
}

// dayEvent is what the person asks: save an order, start (on the day
// itself, optionally with the order to run), arrive at or leave a stop, end.
type dayEvent struct {
	kind   string
	school string
	order  []string
	today  bool
}

func checkOrder(order []string) string {
	if len(order) == 0 {
		return "Choose at least one school."
	}
	if len(order) > maxDayStops {
		return fmt.Sprintf("A field day holds at most %d schools.", maxDayStops)
	}
	seen := map[string]bool{}
	for _, id := range order {
		if strings.TrimSpace(id) == "" || seen[id] {
			return "Each school appears once in the day."
		}
		seen[id] = true
	}
	return ""
}

func timeAt(t time.Time) *time.Time { return &t }

// apply is the day after ev at now, or why ev is refused. The day is never
// changed in place.
func (d fieldDay) apply(ev dayEvent, now time.Time) (fieldDay, string) {
	next := d
	next.stops = map[string]stopTimes{}
	for k, v := range d.stops {
		next.stops[k] = v
	}
	if d.ended != nil && slices.Contains([]string{"start", "arrive", "leave", "end"}, ev.kind) {
		return d, "This field day has ended."
	}
	switch ev.kind {
	case "save":
		if d.started != nil {
			return d, "The field day has started; its order is kept."
		}
		if why := checkOrder(ev.order); why != "" {
			return d, why
		}
		next.order, next.saved = slices.Clone(ev.order), timeAt(now)
	case "start":
		if len(ev.order) > 0 && d.started == nil {
			if why := checkOrder(ev.order); why != "" {
				return d, why
			}
			next.order, next.saved = slices.Clone(ev.order), timeAt(now)
		}
		if len(next.order) == 0 {
			return d, "Save the day's schools or choose them first."
		}
		if !ev.today {
			return d, "A field day can only start on its own day."
		}
		if d.started == nil {
			next.started = timeAt(now)
		}
	case "arrive", "leave":
		if d.started == nil {
			return d, "Start the field day first."
		}
		if !slices.Contains(d.order, ev.school) {
			return d, "That school is not on this field day."
		}
		st, ok := d.stops[ev.school]
		if ev.kind == "arrive" {
			if !ok {
				next.stops[ev.school] = stopTimes{arrived: timeAt(now)}
			}
			break
		}
		if !ok {
			return d, "Arrive at this school first."
		}
		if st.left == nil {
			next.stops[ev.school] = stopTimes{arrived: st.arrived, left: timeAt(now)}
		}
	case "end":
		if d.started == nil {
			return d, "Start the field day first."
		}
		next.ended = timeAt(now)
		for id, st := range next.stops {
			if st.left == nil {
				next.stops[id] = stopTimes{arrived: st.arrived, left: timeAt(now)}
			}
		}
	default:
		return d, "Say start, arrive, leave or end."
	}
	return next, ""
}

// message is the day as the apps read it, stops in the day's order.
func (d fieldDay) message() *routesv1.SavedFieldDay {
	out := &routesv1.SavedFieldDay{SchoolIds: slices.Clone(d.order), SavedAt: stamp(d.saved), StartedAt: stamp(d.started), EndedAt: stamp(d.ended)}
	for _, id := range d.order {
		if st, ok := d.stops[id]; ok {
			out.Stops = append(out.Stops, &routesv1.StopCheckIn{SchoolId: id, ArrivedAt: stamp(st.arrived), LeftAt: stamp(st.left)})
		}
	}
	return out
}

// rowQuerier reads (the read pool or a transaction).
type rowQuerier interface {
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
}

// loadDay is the person's stored day; empty when there is none. lock holds
// the row for the transaction that will write it.
func loadDay(ctx context.Context, db rowQuerier, user string, day time.Time, lock bool) (fieldDay, error) {
	d := fieldDay{stops: map[string]stopTimes{}}
	sql := `SELECT school_ids, saved_at, started_at, ended_at FROM field_routes.field_day WHERE user_id = $1 AND day = $2`
	if lock {
		sql += ` FOR UPDATE`
	}
	err := db.QueryRow(ctx, sql, user, day.Format(time.DateOnly)).Scan(&d.order, &d.saved, &d.started, &d.ended)
	if errors.Is(err, pgx.ErrNoRows) {
		return d, nil
	}
	if err != nil {
		return d, fmt.Errorf("routeplan: reading the field day: %w", err)
	}
	rows, err := db.Query(ctx, `SELECT school_id, arrived_at, left_at FROM field_routes.field_day_stop WHERE user_id = $1 AND day = $2`,
		user, day.Format(time.DateOnly))
	if err != nil {
		return d, fmt.Errorf("routeplan: reading the field day's stops: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var st stopTimes
		if err := rows.Scan(&id, &st.arrived, &st.left); err != nil {
			return d, fmt.Errorf("routeplan: reading the field day's stops: %w", err)
		}
		d.stops[id] = st
	}
	return d, rows.Err()
}

// storeDay writes the whole day back inside tx.
func storeDay(ctx context.Context, tx pgx.Tx, user string, day time.Time, d fieldDay) error {
	date := day.Format(time.DateOnly)
	order := d.order
	if order == nil {
		order = []string{}
	}
	if _, err := tx.Exec(ctx, `INSERT INTO field_routes.field_day (user_id, day, school_ids, saved_at, started_at, ended_at)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (user_id, day) DO UPDATE SET school_ids = EXCLUDED.school_ids, saved_at = EXCLUDED.saved_at,
  started_at = EXCLUDED.started_at, ended_at = EXCLUDED.ended_at`, user, date, order, d.saved, d.started, d.ended); err != nil {
		return fmt.Errorf("routeplan: saving the field day: %w", err)
	}
	for id, st := range d.stops {
		if _, err := tx.Exec(ctx, `INSERT INTO field_routes.field_day_stop (user_id, day, school_id, arrived_at, left_at)
VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (user_id, day, school_id) DO UPDATE SET left_at = EXCLUDED.left_at`, user, date, id, st.arrived, st.left); err != nil {
			return fmt.Errorf("routeplan: saving a stop: %w", err)
		}
	}
	return nil
}

func (s *Service) needFieldDays(ctx context.Context) error {
	if s.verifyReady(ctx) {
		return nil
	}
	return apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable,
		"Saving field days is not set up on this server yet.")
}

// savedDay is the reader's stored day for GetFieldDay; empty when field
// days are not set up here.
func (s *Service) savedDay(ctx context.Context, p auth.Principal, day time.Time) (fieldDay, error) {
	if !s.verifyReady(ctx) || p.UserID == "" {
		return fieldDay{}, nil
	}
	return loadDay(ctx, s.db, p.UserID, day, false)
}

// mayVisit refuses an order holding a school the reader may not see.
func mayVisit(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time, order []string) (bool, error) {
	if len(order) == 0 {
		return true, nil
	}
	found, err := schoolsByID(ctx, db, p, now, order)
	if err != nil {
		return false, err
	}
	for _, id := range order {
		if _, ok := found[id]; !ok {
			return false, nil
		}
	}
	return true, nil
}

// change applies ev to the reader's day and stores it.
func (s *Service) change(ctx context.Context, raw string, ev dayEvent) (*routesv1.SavedFieldDay, error) {
	p, err := s.reader(ctx)
	if err != nil {
		return nil, err
	}
	if err := s.needFieldDays(ctx); err != nil {
		return nil, err
	}
	day, err := s.day(ctx, raw)
	if err != nil {
		return nil, err
	}
	now := s.now()
	today, _ := s.day(ctx, "")
	ev.today = day.Equal(today)
	ok, err := mayVisit(ctx, s.db, p, now, ev.order)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	if !ok {
		return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonSchoolNotFound, "school not found")
	}
	tx, err := s.verify.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	d, err := loadDay(ctx, tx, p.UserID, day, true)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	next, refused := d.apply(ev, now)
	if refused != "" {
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument, refused)
	}
	if err := storeDay(ctx, tx, p.UserID, day, next); err != nil {
		return nil, s.fail(ctx, err)
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, s.fail(ctx, err)
	}
	return next.message(), nil
}

// SaveFieldDay is Save Plan.
func (s *Service) SaveFieldDay(ctx context.Context, req *connect.Request[routesv1.SaveFieldDayRequest]) (*connect.Response[routesv1.SaveFieldDayResponse], error) {
	saved, err := s.change(ctx, req.Msg.GetDate(), dayEvent{kind: "save", order: req.Msg.GetSchoolIds()})
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&routesv1.SaveFieldDayResponse{Saved: saved}), nil
}

// RecordFieldDay is Start Field Day and what follows it.
func (s *Service) RecordFieldDay(ctx context.Context, req *connect.Request[routesv1.RecordFieldDayRequest]) (*connect.Response[routesv1.RecordFieldDayResponse], error) {
	m := req.Msg
	if m.GetEvent() == "save" {
		return nil, bad(ctx, "Say start, arrive, leave or end.")
	}
	saved, err := s.change(ctx, m.GetDate(), dayEvent{kind: m.GetEvent(), school: m.GetSchoolId(), order: m.GetSchoolIds()})
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&routesv1.RecordFieldDayResponse{Saved: saved}), nil
}

// savedTrip is the day in the order the reader saved: their saved schools
// they may still see (one they added from the suggestions is marked so),
// then any planned since, in the planner's order. Kept as given.
func (s *Service) savedTrip(ctx context.Context, p auth.Principal, now time.Time, planned []school, order []string) (trip, error) {
	t := trip{kinds: map[string]string{}, mode: ModeAsGiven}
	found, err := schoolsByID(ctx, s.db, p, now, order)
	if err != nil {
		return t, err
	}
	onPlan := map[string]school{}
	for _, sc := range planned {
		onPlan[sc.pin.SchoolId] = sc
	}
	kept := map[string]bool{}
	for _, id := range order {
		sc, ok := onPlan[id]
		if !ok {
			if sc, ok = found[id]; !ok {
				continue
			}
			sc.pin.CanOpenProfile = MayOpenProfile(p.ActiveRole)
			t.kinds[id] = "recommended"
		}
		t.schools = append(t.schools, sc)
		kept[id] = true
	}
	for _, sc := range planned {
		if !kept[sc.pin.SchoolId] {
			t.schools = append(t.schools, sc)
		}
	}
	return t, nil
}
