package routeplan

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"

	routesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/routes/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Verify Location and the review of captures (Smart Route brief parts 2
// and 11; offline GPS capture brief, 2026-11-14). Every report, GPS capture
// and "the location is correct" answer is a row of field_routes
// location_capture. Someone other than the sender approves or rejects
// those that wait; an approved or accepted point becomes the school's
// location in field_routes.school_location, which the planner reads first.
// The existing application's coordinates are never written.

// Limits on what a report carries.
const (
	noteMaxRunes       = 1000
	accessNoteMaxRunes = 300
	idempotencyMaxLen  = 100
	// How often an unready schema is checked again.
	readyRetry = time.Minute
)

// Beginner opens a read-write transaction (a *pgxpool.Pool).
type Beginner interface {
	BeginTx(ctx context.Context, opts pgx.TxOptions) (pgx.Tx, error)
}

// verification is the service's hold on field_routes.
type verification struct {
	db      Beginner
	ready   func(context.Context) error
	mu      sync.Mutex
	checked time.Time
}

// WithVerification turns on location reports and captures, written through
// db once ready reports the field_routes schema at this build's version.
// The gateway never migrates it.
func (s *Service) WithVerification(db Beginner, ready func(context.Context) error) *Service {
	s.verify = &verification{db: db, ready: ready}
	return s
}

// verifyReady is whether field_routes may be read and written now. It
// checks the schema at most once a minute until it is ready, and then
// never again.
func (s *Service) verifyReady(ctx context.Context) bool {
	v := s.verify
	if v == nil {
		return false
	}
	if verifiedLocations.Load() {
		return true
	}
	v.mu.Lock()
	defer v.mu.Unlock()
	if !v.checked.IsZero() && s.now().Sub(v.checked) < readyRetry {
		return false
	}
	v.checked = s.now()
	if err := v.ready(ctx); err != nil {
		s.logger.Warn("field routes schema not ready", slog.String("error", err.Error()))
		return false
	}
	verifiedLocations.Store(true)
	return true
}

func (s *Service) needVerify(ctx context.Context) error {
	if s.verifyReady(ctx) {
		return nil
	}
	return apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable,
		"Location reports are not set up on this server yet.")
}

func newID() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", fmt.Errorf("routeplan: making an id: %w", err)
	}
	return uuidOf(b), nil
}

// keyID is the capture id for an older client's idempotency key: the same
// person and key always give the same id.
func keyID(userID, key string) string {
	sum := sha256.Sum256([]byte(userID + "\x00" + key))
	var b [16]byte
	copy(b[:], sum[:16])
	return uuidOf(b)
}

func uuidOf(b [16]byte) string {
	b[6] = b[6]&0x0f | 0x40
	b[8] = b[8]&0x3f | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:])
}

func bad(ctx context.Context, msg string) error {
	return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, msg)
}

func (s *Service) signedIn(ctx context.Context) (auth.Principal, error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return p, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing, "sign in first")
	}
	return p, nil
}

// ReportSchoolLocation is the profile's Report location form (Verify
// Location): a capture of kind new (no usable point) or correction.
func (s *Service) ReportSchoolLocation(ctx context.Context, req *connect.Request[routesv1.ReportSchoolLocationRequest]) (*connect.Response[routesv1.ReportSchoolLocationResponse], error) {
	p, err := s.signedIn(ctx)
	if err != nil {
		return nil, err
	}
	m := req.Msg
	if len(strings.TrimSpace(m.GetIdempotencyKey())) > idempotencyMaxLen {
		return nil, bad(ctx, "The report could not be sent. Please try again.")
	}
	id := keyID(p.UserID, strings.TrimSpace(m.GetIdempotencyKey()))
	if strings.TrimSpace(m.GetIdempotencyKey()) == "" {
		if id, err = newID(); err != nil {
			return nil, s.fail(ctx, err)
		}
	}
	kind := "correction"
	if m.GetKind() == "missing" {
		kind = "new"
	} else if m.GetKind() != "wrong" {
		return nil, bad(ctx, "Say whether the location is wrong or missing.")
	}
	if strings.TrimSpace(m.GetNote()) == "" {
		return nil, bad(ctx, "Say what is wrong with the location.")
	}
	in := CaptureInput{Target: "school", Kind: kind, Source: m.GetPointSource(), AccuracyM: m.GetAccuracyM(),
		Reason: m.GetNote(), AccessNote: m.GetAccessNote(), BaseVersion: -1}
	if pt := m.GetProposed(); pt != nil {
		in.Point = &LatLng{pt.GetLat(), pt.GetLng()}
	}
	if in.Source == "device" {
		in.CapturedAt = s.now()
	}
	answer, err := s.submit(ctx, p, id, m.GetSchoolId(), in)
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&routesv1.ReportSchoolLocationResponse{Report: answer.GetCapture()}), nil
}

// captureCols reads a capture with its school (schoolCols first) and names.
func captureCols() string {
	return schoolCols() + `, lc.id::text, lc.target, lc.kind, lc.point_source, lc.lat, lc.lng, COALESCE(lc.accuracy_m, 0),
  lc.captured_at, lc.sample_count, COALESCE(lc.spread_m, 0), lc.received_at, lc.base_version, lc.previous_lat, lc.previous_lng,
  lc.displacement_m, lc.reason, lc.access_note, lc.flags, lc.status, lc.captured_by, COALESCE(cu.name, ''),
  COALESCE(rv.name, ''), lc.reviewed_at, lc.review_note, COALESCE(lc.result_version, 0)`
}

func captureFrom() string {
	return `field_routes.location_capture lc JOIN ` + schoolFrom() + ` ON s.id = lc.school_id
  LEFT JOIN "user" cu ON cu.id = lc.captured_by LEFT JOIN "user" rv ON rv.id = lc.reviewed_by`
}

// legacyKind is the Verify Location word for a capture kind.
func legacyKind(kind string) string {
	switch kind {
	case "new":
		return "missing"
	case "correction":
		return "wrong"
	}
	return kind
}

func scanCapture(row pgx.CollectableRow, reader string) (*routesv1.LocationReport, error) {
	var (
		out                                      routesv1.LocationReport
		lat, lng, prevLat, prevLng, displacement *float64
		capturedAt, reviewedAt                   *time.Time
		receivedAt                               time.Time
		capturedBy                               string
	)
	sc, err := scanSchool(row, &out.Id, &out.Target, &out.CaptureKind, &out.PointSource, &lat, &lng, &out.AccuracyM,
		&capturedAt, &out.SampleCount, &out.SpreadM, &receivedAt, &out.BaseVersion, &prevLat, &prevLng,
		&displacement, &out.Note, &out.AccessNote, &out.Flags, &out.Status, &capturedBy, &out.ReportedByName,
		&out.ReviewedByName, &reviewedAt, &out.ReviewNote, &out.ResultVersion)
	if err != nil {
		return nil, err
	}
	out.School = sc.pin
	out.Kind = legacyKind(out.CaptureKind)
	out.ReportedAt = receivedAt.UTC().Format(time.RFC3339)
	if capturedAt != nil {
		out.CapturedAt = capturedAt.UTC().Format(time.RFC3339)
	}
	if reviewedAt != nil {
		out.ReviewedAt = reviewedAt.UTC().Format(time.RFC3339)
	}
	out.IsOwn = capturedBy == reader
	if lat != nil && lng != nil {
		out.Proposed = &routesv1.Point{Lat: *lat, Lng: *lng}
	}
	if prevLat != nil && prevLng != nil {
		out.Previous = &routesv1.Point{Lat: *prevLat, Lng: *prevLng}
	}
	if displacement != nil {
		out.MovedMeters = int64(*displacement + 0.5)
	}
	return &out, nil
}

// captures reads captures on schools in the reader's reach; each ? in
// filter takes the next value.
func (s *Service) captures(ctx context.Context, p auth.Principal, filter string, values ...any) ([]*routesv1.LocationReport, error) {
	a := &args{}
	where, err := reach(ctx, s.db, p, s.now(), a)
	if err != nil {
		return nil, err
	}
	cond := filter
	for _, v := range values {
		cond = strings.Replace(cond, "?", a.add(v), 1)
	}
	rows, err := s.db.Query(ctx, `SELECT `+captureCols()+` FROM `+captureFrom()+` WHERE `+where+` AND `+cond, *a...)
	if err != nil {
		return nil, fmt.Errorf("routeplan: reading location captures: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (*routesv1.LocationReport, error) { return scanCapture(r, p.UserID) })
	if err != nil {
		return nil, fmt.Errorf("routeplan: reading location captures: %w", err)
	}
	return list, nil
}

func (s *Service) capture(ctx context.Context, p auth.Principal, id string) (*routesv1.LocationReport, error) {
	list, err := s.captures(ctx, p, `lc.id::text = ?`, id)
	if err != nil {
		return nil, err
	}
	if len(list) == 0 {
		return nil, fmt.Errorf("routeplan: capture %s is not in the reader's reach", id)
	}
	return list[0], nil
}

// ListLocationReports is the reviewer's queue: oldest first while pending,
// newest first once decided (Approved holds those accepted at once too).
func (s *Service) ListLocationReports(ctx context.Context, req *connect.Request[routesv1.ListLocationReportsRequest]) (*connect.Response[routesv1.ListLocationReportsResponse], error) {
	p, err := s.signedIn(ctx)
	if err != nil {
		return nil, err
	}
	if !MayReview(p.ActiveRole) {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: Your active role does not review school locations.")
	}
	if err := s.needVerify(ctx); err != nil {
		return nil, err
	}
	var statuses []string
	order := "lc.received_at DESC, lc.id"
	switch req.Msg.GetStatus() {
	case "", "pending":
		statuses, order = []string{CapturePending}, "lc.received_at, lc.id"
	case "approved":
		statuses = []string{CaptureApproved, CaptureAccepted}
	case "rejected":
		statuses = []string{CaptureRejected}
	default:
		return nil, bad(ctx, "status is pending, approved or rejected")
	}
	list, err := s.captures(ctx, p, `lc.status = ANY(?) ORDER BY `+order+` LIMIT 200`, statuses)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&routesv1.ListLocationReportsResponse{Reports: list}), nil
}

// ReviewLocationReport approves or rejects a capture. Approving makes its
// point the school's (or entrance's) location, one version up.
func (s *Service) ReviewLocationReport(ctx context.Context, req *connect.Request[routesv1.ReviewLocationReportRequest]) (*connect.Response[routesv1.ReviewLocationReportResponse], error) {
	p, err := s.signedIn(ctx)
	if err != nil {
		return nil, err
	}
	if !MayReview(p.ActiveRole) {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: Your active role does not review school locations.")
	}
	if err := s.needVerify(ctx); err != nil {
		return nil, err
	}
	id := req.Msg.GetReportId()
	// The capture's school must be in the reader's reach before anything is decided.
	found, err := s.captures(ctx, p, `lc.id::text = ?`, id)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	if len(found) == 0 {
		return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "report not found")
	}
	decision, note := req.Msg.GetDecision(), strings.TrimSpace(req.Msg.GetNote())
	if err := s.decide(ctx, p, id, found[0].GetSchool(), decision, note); err != nil {
		var refused refusal
		if errors.As(err, &refused) {
			return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument, string(refused))
		}
		return nil, s.fail(ctx, err)
	}
	report, err := s.capture(ctx, p, id)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&routesv1.ReviewLocationReportResponse{Report: report}), nil
}

type refusal string

func (r refusal) Error() string { return string(r) }

// decide locks the capture, checks it still waits and is not the reader's,
// and records the decision (and, on approval, the new location).
func (s *Service) decide(ctx context.Context, p auth.Principal, id string, pin *routesv1.SchoolPin, decision, note string) error {
	tx, err := s.verify.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("routeplan: opening the review: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var (
		schoolID, target, by, status, access string
		lat, lng, accuracy                   *float64
	)
	err = tx.QueryRow(ctx, `
SELECT school_id, target, captured_by, status, lat, lng, accuracy_m, access_note
FROM field_routes.location_capture WHERE id::text = $1 FOR UPDATE`, id).Scan(&schoolID, &target, &by, &status, &lat, &lng, &accuracy, &access)
	if err != nil {
		return fmt.Errorf("routeplan: locking the capture: %w", err)
	}
	if msg := ReviewMessage(p.UserID, by, status, decision, note); msg != "" {
		return refusal(msg)
	}
	if decision == "approve" && lat == nil {
		return refusal("This report gives no point to approve. Reject it with a note, or ask for a point.")
	}
	now := s.now().UTC()
	final, version := CaptureRejected, int32(0)
	if decision == "approve" {
		final = CaptureApproved
		version, err = s.apply(ctx, tx, change{schoolID: schoolID, target: target, captureID: id, at: LatLng{*lat, *lng},
			accuracy: accuracy, note: access, by: p.UserID, when: now, fallback: pin})
		if err != nil {
			return err
		}
	}
	var result any
	if version > 0 {
		result = version
	}
	if _, err := tx.Exec(ctx, `
UPDATE field_routes.location_capture SET status = $2, reviewed_by = $3, reviewed_role = $4, reviewed_at = $5,
  review_note = $6, result_version = $7 WHERE id::text = $1`, id, final, p.UserID, p.ActiveRole, now, note, result); err != nil {
		return fmt.Errorf("routeplan: recording the review: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("routeplan: committing the review: %w", err)
	}
	return nil
}
