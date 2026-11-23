package routeplan

import (
	"context"
	"errors"
	"fmt"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"

	routesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/routes/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// What the device keeps for working without a connection, the feed of
// accepted changes clients refresh from, and a school's location history.

const (
	// offlineSchoolsMax is the most schools one offline pack carries.
	offlineSchoolsMax = 2000
	// offlineDaysDefault and offlineDaysMax bound the planned visits sent.
	offlineDaysDefault = 14
	offlineDaysMax     = 31
	// changesMax is the most changes one feed answer carries.
	changesMax = 500
)

// locationFacts is a school's location record beyond its pin.
type locationFacts struct {
	verifiedAt, verifiedByName, accessNote, lastConfirmedAt string
	hasPending                                              bool
	// The stored reading's accuracy in metres (nil when none was recorded),
	// how its capture got the point, and whether an approved report placed it.
	accuracy      *float64
	captureSource string
	reviewed      bool
}

// locationSource names where the location on record came from: the capture
// that set it, else an approved report, else the School Directory's point.
func locationSource(capture string, reviewed, placed bool) string {
	switch {
	case capture == "device":
		return "Device GPS (Field)"
	case capture == "typed":
		return "Entered by hand"
	case reviewed:
		return "Approved location report"
	case placed:
		return "School Directory"
	}
	return ""
}

func stamp(t *time.Time) string {
	if t == nil {
		return ""
	}
	return t.UTC().Format(time.RFC3339)
}

// factsCols reads, beside a school (s), its location record's facts.
const factsCols = `COALESCE(sl.verified_at, vl.verified_at), COALESCE(slu.name, vlu.name, ''),
  COALESCE(NULLIF(sl.access_note, ''), vl.access_note, ''),
  (SELECT max(k.received_at) FROM field_routes.location_capture k WHERE k.school_id = s.id AND k.kind = 'confirm'),
  EXISTS (SELECT 1 FROM field_routes.location_capture k WHERE k.school_id = s.id AND k.status = 'pending'),
  sl.accuracy_m,
  COALESCE((SELECT k.point_source FROM field_routes.location_capture k WHERE k.id = sl.capture_id), ''),
  vl.school_id IS NOT NULL`

const factsFrom = ` LEFT JOIN "user" slu ON slu.id = sl.verified_by LEFT JOIN "user" vlu ON vlu.id = vl.verified_by`

func factsScan(f *locationFacts, verifiedAt, confirmedAt **time.Time) []any {
	return []any{verifiedAt, &f.verifiedByName, &f.accessNote, confirmedAt, &f.hasPending, &f.accuracy, &f.captureSource, &f.reviewed}
}

// facts is one school's location facts (field_routes must be ready).
func (s *Service) facts(ctx context.Context, schoolID string) (locationFacts, error) {
	var (
		f                       locationFacts
		verifiedAt, confirmedAt *time.Time
	)
	err := s.db.QueryRow(ctx, `SELECT `+factsCols+` FROM `+schoolFrom()+factsFrom+` WHERE s.id = $1`, schoolID).
		Scan(factsScan(&f, &verifiedAt, &confirmedAt)...)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return f, fmt.Errorf("routeplan: reading the location record: %w", err)
	}
	f.verifiedAt, f.lastConfirmedAt = stamp(verifiedAt), stamp(confirmedAt)
	return f, nil
}

// pendingFor is the oldest capture on the school waiting for review, if any.
func (s *Service) pendingFor(ctx context.Context, p auth.Principal, schoolID string) (*routesv1.LocationReport, error) {
	list, err := s.captures(ctx, p, `lc.school_id = ? AND lc.status = 'pending' ORDER BY lc.received_at LIMIT 1`, schoolID)
	if err != nil || len(list) == 0 {
		return nil, err
	}
	return list[0], nil
}

// GetOfflinePack is the reader's schools and planned visits, the least the
// device needs to open a school and capture its location with no
// connection.
func (s *Service) GetOfflinePack(ctx context.Context, req *connect.Request[routesv1.GetOfflinePackRequest]) (*connect.Response[routesv1.GetOfflinePackResponse], error) {
	p, err := s.signedIn(ctx)
	if err != nil {
		return nil, err
	}
	if !MayOpenProfile(p.ActiveRole) {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: Your active role does not work with school locations.")
	}
	if err := s.needVerify(ctx); err != nil {
		return nil, err
	}
	now := s.now()
	a := &args{}
	where, err := reach(ctx, s.db, p, now, a)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	rows, err := s.db.Query(ctx, `SELECT `+schoolCols()+`, `+factsCols+` FROM `+schoolFrom()+factsFrom+
		` WHERE `+where+` ORDER BY s.name, s.id LIMIT `+a.add(offlineSchoolsMax+1), *a...)
	if err != nil {
		return nil, s.fail(ctx, fmt.Errorf("routeplan: reading the offline schools: %w", err))
	}
	schools, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (*routesv1.OfflineSchool, error) {
		var (
			f                       locationFacts
			verifiedAt, confirmedAt *time.Time
		)
		sc, err := scanSchool(r, factsScan(&f, &verifiedAt, &confirmedAt)...)
		if err != nil {
			return nil, err
		}
		sc.pin.CanOpenProfile = MayOpenProfile(p.ActiveRole)
		return &routesv1.OfflineSchool{School: sc.pin, VerifiedAt: stamp(verifiedAt), AccessNote: f.accessNote,
			HasPending: f.hasPending, LastConfirmedAt: stamp(confirmedAt)}, nil
	})
	if err != nil {
		return nil, s.fail(ctx, fmt.Errorf("routeplan: reading the offline schools: %w", err))
	}
	out := &routesv1.GetOfflinePackResponse{GeneratedAt: now.UTC().Format(time.RFC3339), Policy: policyOf(DefaultPolicy),
		CanCapture: MayCapture(p.ActiveRole), CanReview: MayReview(p.ActiveRole)}
	if len(schools) > offlineSchoolsMax {
		schools, out.Truncated = schools[:offlineSchoolsMax], true
	}
	out.Schools = schools
	days := int(req.Msg.GetDays())
	if days <= 0 {
		days = offlineDaysDefault
	}
	days = min(days, offlineDaysMax)
	planned, err := s.plannedVisits(ctx, owners(p), now.In(kampala), days)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	out.Planned = planned
	return connect.NewResponse(out), nil
}

// plannedVisits is the reader's live school visits from today for days.
func (s *Service) plannedVisits(ctx context.Context, ids []string, today time.Time, days int) ([]*routesv1.PlannedVisit, error) {
	from := today.Format(time.DateOnly)
	to := today.AddDate(0, 0, days).Format(time.DateOnly)
	rows, err := s.db.Query(ctx, `
SELECT to_char((a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date, 'YYYY-MM-DD'), a.school_id, a.id
FROM activity a
WHERE a.deleted_at IS NULL AND a.school_id IS NOT NULL AND a.responsible_staff_id = ANY($1)
  AND a.activity_type = ANY($2) AND a.status <> ALL($3)
  AND (a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date >= $4::date
  AND (a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date < $5::date
ORDER BY a.scheduled_date, a.id`, ids, Rules.VisitTypes, Rules.NotLiveStatuses, from, to)
	if err != nil {
		return nil, fmt.Errorf("routeplan: reading planned visits: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (*routesv1.PlannedVisit, error) {
		var v routesv1.PlannedVisit
		return &v, r.Scan(&v.Date, &v.SchoolId, &v.ActivityId)
	})
	if err != nil {
		return nil, fmt.Errorf("routeplan: reading planned visits: %w", err)
	}
	return list, nil
}

// ListLocationChanges is the accepted location changes since a time, on
// schools in the reader's reach.
func (s *Service) ListLocationChanges(ctx context.Context, req *connect.Request[routesv1.ListLocationChangesRequest]) (*connect.Response[routesv1.ListLocationChangesResponse], error) {
	p, err := s.signedIn(ctx)
	if err != nil {
		return nil, err
	}
	if !MayOpenProfile(p.ActiveRole) && !MayPlan(p.ActiveRole) {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: Your active role does not work with school locations.")
	}
	if err := s.needVerify(ctx); err != nil {
		return nil, err
	}
	now := s.now()
	since := now.Add(-24 * time.Hour)
	if raw := req.Msg.GetSince(); raw != "" {
		at, err := time.Parse(time.RFC3339, raw)
		if err != nil {
			return nil, bad(ctx, "since is a time like 2026-11-14T10:00:00Z")
		}
		since = at
	}
	a := &args{}
	where, err := reach(ctx, s.db, p, now, a)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	rows, err := s.db.Query(ctx, `
SELECT g.school_id, g.target, g.version, g.lat, g.lng, g.changed_at
FROM field_routes.location_change g JOIN school s ON s.id = g.school_id
WHERE `+where+` AND g.changed_at > `+a.add(since)+`
ORDER BY g.changed_at, g.id LIMIT `+a.add(changesMax), *a...)
	if err != nil {
		return nil, s.fail(ctx, fmt.Errorf("routeplan: reading location changes: %w", err))
	}
	changes, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (*routesv1.LocationChange, error) {
		var (
			c        routesv1.LocationChange
			lat, lng float64
			at       time.Time
		)
		if err := r.Scan(&c.SchoolId, &c.Target, &c.Version, &lat, &lng, &at); err != nil {
			return nil, err
		}
		c.Point, c.ChangedAt = &routesv1.Point{Lat: lat, Lng: lng}, at.UTC().Format(time.RFC3339Nano)
		return &c, nil
	})
	if err != nil {
		return nil, s.fail(ctx, fmt.Errorf("routeplan: reading location changes: %w", err))
	}
	out := &routesv1.ListLocationChangesResponse{Changes: changes, Now: now.UTC().Format(time.RFC3339Nano)}
	if len(changes) == changesMax {
		// More to come: the next ask starts after the last one sent.
		out.Now = changes[len(changes)-1].GetChangedAt()
	}
	return connect.NewResponse(out), nil
}

// GetLocationHistory is every capture and report on one school with its
// decision, newest first: the point, its accuracy, who sent it and who
// decided. Nothing about where anyone was beyond the school is kept.
func (s *Service) GetLocationHistory(ctx context.Context, req *connect.Request[routesv1.GetLocationHistoryRequest]) (*connect.Response[routesv1.GetLocationHistoryResponse], error) {
	p, err := s.signedIn(ctx)
	if err != nil {
		return nil, err
	}
	if !MayOpenProfile(p.ActiveRole) {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: Your active role does not have permission to view school locations.")
	}
	if err := s.needVerify(ctx); err != nil {
		return nil, err
	}
	sc, found, err := schoolByRef(ctx, s, p, req.Msg.GetSchoolId())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	if !found {
		return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonSchoolNotFound, "school not found")
	}
	list, err := s.captures(ctx, p, `lc.school_id = ? ORDER BY lc.received_at DESC, lc.id LIMIT 200`, sc.pin.GetSchoolId())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	older, err := s.firstReports(ctx, p, sc.pin.GetSchoolId())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&routesv1.GetLocationHistoryResponse{School: sc.pin, Entries: append(list, older...)}), nil
}

// firstReports is the school's Verify Location reports of 0001 (before
// captures), oldest last.
func (s *Service) firstReports(ctx context.Context, p auth.Principal, schoolID string) ([]*routesv1.LocationReport, error) {
	rows, err := s.db.Query(ctx, `
SELECT r.id::text, r.kind, r.point_source, r.proposed_lat, r.proposed_lng, COALESCE(r.accuracy_m, 0), r.note,
  r.access_note, r.previous_lat, r.previous_lng, r.status, r.reported_by, COALESCE(ru.name, ''), r.reported_at,
  COALESCE(rv.name, ''), r.reviewed_at, r.review_note
FROM field_routes.location_report r LEFT JOIN "user" ru ON ru.id = r.reported_by LEFT JOIN "user" rv ON rv.id = r.reviewed_by
WHERE r.school_id = $1 ORDER BY r.reported_at DESC`, schoolID)
	if err != nil {
		return nil, fmt.Errorf("routeplan: reading earlier reports: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (*routesv1.LocationReport, error) {
		var (
			out                        routesv1.LocationReport
			lat, lng, prevLat, prevLng *float64
			by                         string
			reportedAt                 time.Time
			reviewedAt                 *time.Time
		)
		if err := r.Scan(&out.Id, &out.Kind, &out.PointSource, &lat, &lng, &out.AccuracyM, &out.Note, &out.AccessNote,
			&prevLat, &prevLng, &out.Status, &by, &out.ReportedByName, &reportedAt, &out.ReviewedByName, &reviewedAt,
			&out.ReviewNote); err != nil {
			return nil, err
		}
		out.Target, out.IsOwn, out.ReportedAt, out.ReviewedAt = "school", by == p.UserID, reportedAt.UTC().Format(time.RFC3339), stamp(reviewedAt)
		if lat != nil && lng != nil {
			out.Proposed = &routesv1.Point{Lat: *lat, Lng: *lng}
		}
		if prevLat != nil && prevLng != nil {
			out.Previous = &routesv1.Point{Lat: *prevLat, Lng: *prevLng}
			if lat != nil && lng != nil {
				out.MovedMeters = StraightMeters(LatLng{*prevLat, *prevLng}, LatLng{*lat, *lng})
			}
		}
		if out.Status == CaptureApproved {
			out.ResultVersion = 1
		}
		return &out, nil
	})
}
