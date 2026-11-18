package routeplan

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	routesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/routes/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// Offline school GPS capture (owner brief, 2026-11-14): a capture taken on
// the device, often without a connection, and sent when it has one. The
// server checks everything again (who sends it, that the school is still in
// their reach, the point, its accuracy and age, the version it was taken
// against) and either accepts it at once or keeps it for review. A retry
// with the same capture id gets the first answer.

var uuidPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

func policyOf(p Policy) *routesv1.CapturePolicy {
	return &routesv1.CapturePolicy{GoodM: p.GoodM, ConfirmM: p.ConfirmM, FreshSeconds: p.FreshSeconds, LargeMoveM: int32(p.LargeMoveM)}
}

// SubmitLocationCapture files a capture from the field.
func (s *Service) SubmitLocationCapture(ctx context.Context, req *connect.Request[routesv1.SubmitLocationCaptureRequest]) (*connect.Response[routesv1.SubmitLocationCaptureResponse], error) {
	p, err := s.signedIn(ctx)
	if err != nil {
		return nil, err
	}
	m := req.Msg
	id := strings.ToLower(strings.TrimSpace(m.GetCaptureId()))
	if !uuidPattern.MatchString(id) {
		return nil, bad(ctx, "The capture could not be sent. Please try again.")
	}
	in := CaptureInput{Target: m.GetTarget(), Kind: m.GetKind(), Source: m.GetPointSource(), AccuracyM: m.GetAccuracyM(),
		SampleCount: m.GetSampleCount(), SpreadM: m.GetSpreadM(), BaseVersion: m.GetBaseVersion(),
		Reason: m.GetReason(), AccessNote: m.GetAccessNote()}
	if pt := m.GetPoint(); pt != nil {
		in.Point = &LatLng{pt.GetLat(), pt.GetLng()}
	}
	if raw := m.GetCapturedAt(); raw != "" {
		at, err := time.Parse(time.RFC3339, raw)
		if err != nil {
			return nil, bad(ctx, "The capture has no time. Please capture again.")
		}
		in.CapturedAt = at
	}
	answer, err := s.submit(ctx, p, id, m.GetSchoolId(), in)
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(answer), nil
}

// submit checks and files a capture; BaseVersion -1 means "the version on
// record now" (the profile's form, which shows the current point).
func (s *Service) submit(ctx context.Context, p auth.Principal, id, schoolRef string, in CaptureInput) (*routesv1.SubmitLocationCaptureResponse, error) {
	if !MayOpenProfile(p.ActiveRole) {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: Your active role does not have permission to report school locations.")
	}
	if err := s.needVerify(ctx); err != nil {
		return nil, err
	}
	if in.Source == "device" && !MayCapture(p.ActiveRole) {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: Your active role does not capture school locations by GPS.")
	}
	in, msg := CheckCapture(in, DefaultPolicy)
	if msg != "" {
		return nil, bad(ctx, msg)
	}
	// A retry: the first answer stands.
	if done, err := s.priorCapture(ctx, p, id); err != nil || done != nil {
		return done, err
	}
	// The school must still be in the sender's reach today: cached rights
	// on the device are never trusted.
	sc, found, err := schoolByRef(ctx, s, p, schoolRef)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	if !found {
		return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonSchoolNotFound,
			"This school is no longer in your schools, so its location cannot be changed by you.")
	}
	centre, err := s.districtCentre(ctx, sc.pin.GetSchoolId())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	status, err := s.file(ctx, p, id, sc, in, centre)
	if errors.Is(err, errDuplicate) {
		if done, err := s.priorCapture(ctx, p, id); err != nil || done != nil {
			return done, err
		}
	}
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return s.answer(ctx, p, id, status)
}

var errDuplicate = errors.New("routeplan: the capture id is already filed")

// priorCapture is the answer to a capture already filed by this person, nil
// when there is none; another person's id is refused.
func (s *Service) priorCapture(ctx context.Context, p auth.Principal, id string) (*routesv1.SubmitLocationCaptureResponse, error) {
	var by, status string
	err := s.db.QueryRow(ctx, `SELECT captured_by, status FROM field_routes.location_capture WHERE id = $1::uuid`, id).Scan(&by, &status)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, s.fail(ctx, fmt.Errorf("routeplan: reading the capture: %w", err))
	}
	if by != p.UserID {
		return nil, bad(ctx, "The capture could not be sent. Please try again.")
	}
	return s.answer(ctx, p, id, status)
}

func (s *Service) answer(ctx context.Context, p auth.Principal, id, status string) (*routesv1.SubmitLocationCaptureResponse, error) {
	report, err := s.capture(ctx, p, id)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	out := &routesv1.SubmitLocationCaptureResponse{Capture: report, School: report.GetSchool(), Version: report.GetSchool().GetLocationVersion()}
	switch status {
	case CaptureAccepted, CaptureApproved:
		out.Outcome, out.Message = "accepted", "Saved. This is now the school's location."
		if report.GetTarget() == "entrance" {
			out.Message = "Saved. This is now the school's entrance."
		}
	case CaptureNoted:
		out.Outcome, out.Message = "noted", "Thank you. The location is marked as checked."
	case CaptureRejected:
		out.Outcome, out.Message = "rejected", "A reviewer did not accept this location."
	default:
		out.Outcome, out.Message = "pending", "Sent for review. The location changes once a reviewer approves it."
	}
	return out, nil
}

// districtCentre is the middle of the other placed schools in the school's
// district (the School Directory's own points), or nil.
func (s *Service) districtCentre(ctx context.Context, schoolID string) (*LatLng, error) {
	var lat, lng *float64
	err := s.db.QueryRow(ctx, `
SELECT avg(o.latitude), avg(o.longitude) FROM school me JOIN school o ON o.district_id = me.district_id AND o.id <> me.id
WHERE me.id = $1 AND o.deleted_at IS NULL AND o.latitude BETWEEN $2 AND $3 AND o.longitude BETWEEN $4 AND $5
  AND NOT (o.latitude = 0 AND o.longitude = 0)`, schoolID, minLat, maxLat, minLng, maxLng).Scan(&lat, &lng)
	if err != nil {
		return nil, fmt.Errorf("routeplan: reading the district's schools: %w", err)
	}
	if lat == nil || lng == nil {
		return nil, nil
	}
	return &LatLng{*lat, *lng}, nil
}

// lockSchool serializes every change to one school's location target.
func lockSchool(ctx context.Context, tx pgx.Tx, schoolID, target string) error {
	if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtext($1))`, "field_routes:"+schoolID+":"+target); err != nil {
		return fmt.Errorf("routeplan: locking the school's location: %w", err)
	}
	return nil
}

// current is the target's location on record inside the transaction.
func current(ctx context.Context, tx pgx.Tx, schoolID, target string, pin *routesv1.SchoolPin) (SchoolState, error) {
	var (
		st       SchoolState
		lat, lng float64
	)
	err := tx.QueryRow(ctx, `SELECT version, lat, lng FROM field_routes.school_location WHERE school_id = $1 AND target = $2 FOR UPDATE`,
		schoolID, target).Scan(&st.Version, &lat, &lng)
	switch {
	case err == nil:
		st.Placed, st.At = true, LatLng{lat, lng}
	case !errors.Is(err, pgx.ErrNoRows):
		return st, fmt.Errorf("routeplan: reading the school's location: %w", err)
	case target == "school" && pin != nil:
		// The 0001 verified location or the School Directory's own point.
		st.Version = pin.GetLocationVersion()
		if pt := pin.GetPoint(); pt != nil {
			st.Placed, st.At = true, LatLng{pt.GetLat(), pt.GetLng()}
		}
	}
	return st, nil
}

// file decides and records a capture, applying it when it is accepted.
func (s *Service) file(ctx context.Context, p auth.Principal, id string, sc school, in CaptureInput, centre *LatLng) (string, error) {
	tx, err := s.verify.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return "", fmt.Errorf("routeplan: opening the capture: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	schoolID := sc.pin.GetSchoolId()
	if err := lockSchool(ctx, tx, schoolID, in.Target); err != nil {
		return "", err
	}
	st, err := current(ctx, tx, schoolID, in.Target, sc.pin)
	if err != nil {
		return "", err
	}
	if err := tx.QueryRow(ctx, `SELECT count(*) FROM field_routes.location_capture WHERE school_id = $1 AND target = $2 AND status = 'pending'`,
		schoolID, in.Target).Scan(&st.Pending); err != nil {
		return "", fmt.Errorf("routeplan: reading waiting captures: %w", err)
	}
	st.DistrictCentre = centre
	if in.BaseVersion < 0 {
		in.BaseVersion = st.Version
	}
	now := s.now().UTC()
	d := Decide(in, st, p.ActiveRole, now, DefaultPolicy)
	var lat, lng, acc, capturedAt, prevLat, prevLng, spread any
	if in.Point != nil {
		lat, lng = in.Point.Lat, in.Point.Lng
	}
	if in.Source == "device" {
		acc, capturedAt, spread = in.AccuracyM, in.CapturedAt.UTC(), in.SpreadM
	}
	if st.Placed {
		prevLat, prevLng = st.At.Lat, st.At.Lng
	}
	flags := d.Flags
	if flags == nil {
		flags = []string{}
	}
	_, err = tx.Exec(ctx, `
INSERT INTO field_routes.location_capture (id, school_id, school_code, target, kind, point_source, lat, lng, accuracy_m,
  captured_at, sample_count, spread_m, received_at, base_version, previous_lat, previous_lng, previous_status,
  displacement_m, reason, access_note, flags, status, captured_by, captured_role, country_code)
VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24,
  `+registry.SchoolCountryCode("$2")+`)`,
		id, schoolID, sc.pin.GetCode(), in.Target, in.Kind, in.Source, lat, lng, acc, capturedAt, in.SampleCount, spread,
		now, in.BaseVersion, prevLat, prevLng, sc.pin.GetLocationStatus(), d.DisplacementM, in.Reason, in.AccessNote,
		flags, d.Status, p.UserID, p.ActiveRole)
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == "23505" {
		return "", errDuplicate
	}
	if err != nil {
		return "", fmt.Errorf("routeplan: filing the capture: %w", err)
	}
	if d.Status == CaptureAccepted {
		var accuracy *float64
		if in.Source == "device" {
			accuracy = &in.AccuracyM
		}
		version, err := s.apply(ctx, tx, change{schoolID: schoolID, target: in.Target, captureID: id, at: *in.Point,
			accuracy: accuracy, note: in.AccessNote, by: p.UserID, when: now, fallback: sc.pin})
		if err != nil {
			return "", err
		}
		if _, err := tx.Exec(ctx, `UPDATE field_routes.location_capture SET result_version = $2 WHERE id = $1::uuid`, id, version); err != nil {
			return "", fmt.Errorf("routeplan: recording the new version: %w", err)
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return "", fmt.Errorf("routeplan: committing the capture: %w", err)
	}
	return d.Status, nil
}

// change is an accepted location.
type change struct {
	schoolID, target, captureID string
	at                          LatLng
	accuracy                    *float64
	note, by                    string
	when                        time.Time
	// fallback is the school as read before the change, for the version and
	// point when it has no field_routes location yet.
	fallback *routesv1.SchoolPin
}

// apply makes the point the target's location one version up and records
// the change (the history, and the event clients refresh from).
func (s *Service) apply(ctx context.Context, tx pgx.Tx, c change) (int32, error) {
	if err := lockSchool(ctx, tx, c.schoolID, c.target); err != nil {
		return 0, err
	}
	st, err := current(ctx, tx, c.schoolID, c.target, c.fallback)
	if err != nil {
		return 0, err
	}
	version := st.Version + 1
	if _, err := tx.Exec(ctx, `
INSERT INTO field_routes.school_location (school_id, target, lat, lng, accuracy_m, access_note, version, capture_id, verified_by, verified_at,
  country_code)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8::uuid, $9, $10, `+registry.SchoolCountryCode("$1")+`)
ON CONFLICT (school_id, target) DO UPDATE SET lat = EXCLUDED.lat, lng = EXCLUDED.lng, accuracy_m = EXCLUDED.accuracy_m,
  access_note = EXCLUDED.access_note, version = EXCLUDED.version, capture_id = EXCLUDED.capture_id,
  verified_by = EXCLUDED.verified_by, verified_at = EXCLUDED.verified_at`,
		c.schoolID, c.target, c.at.Lat, c.at.Lng, c.accuracy, c.note, version, c.captureID, c.by, c.when); err != nil {
		return 0, fmt.Errorf("routeplan: recording the location: %w", err)
	}
	changeID, err := newID()
	if err != nil {
		return 0, err
	}
	var prevLat, prevLng any
	if st.Placed {
		prevLat, prevLng = st.At.Lat, st.At.Lng
	}
	if _, err := tx.Exec(ctx, `
INSERT INTO field_routes.location_change (id, school_id, target, version, lat, lng, previous_lat, previous_lng,
  previous_version, capture_id, changed_by, changed_at, country_code)
VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10::uuid, $11, $12,
  (SELECT lc.country_code FROM field_routes.location_capture lc WHERE lc.id = $10::uuid))`,
		changeID, c.schoolID, c.target, version, c.at.Lat, c.at.Lng, prevLat, prevLng, st.Version, c.captureID, c.by, c.when); err != nil {
		return 0, fmt.Errorf("routeplan: recording the change: %w", err)
	}
	return version, nil
}
