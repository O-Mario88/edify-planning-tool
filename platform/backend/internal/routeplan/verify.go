package routeplan

import (
	"context"
	"crypto/rand"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"slices"
	"strings"
	"sync"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	routesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/routes/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Verify Location (Smart Route brief, parts 2 and 11). Anyone who may open
// a school's profile reports that its location is wrong or missing; someone
// else, in a reviewing role, approves or rejects the report. An approved
// point is written to field_routes.verified_location, which the planner
// reads first. The existing application's school coordinates are never
// written, and every report and decision stays as history.

// ReviewerRoles are the roles that decide location reports.
var ReviewerRoles = []string{"Program Lead", "CountryDirector", "Admin"}

// MayReview is whether the role decides location reports.
func MayReview(role string) bool { return slices.Contains(ReviewerRoles, role) }

// Limits on what a report carries.
const (
	noteMaxRunes       = 1000
	accessNoteMaxRunes = 300
	idempotencyMaxLen  = 100
	// A device reading coarser than this is not a school's location.
	deviceAccuracyMaxM = 200
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

// WithVerification turns on location reports, written through db once
// ready reports the field_routes schema at this build's version. The
// gateway never migrates it.
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

// ReportInput is a report as asked, before it is checked.
type ReportInput struct {
	Kind, PointSource, AccessNote, Note, IdempotencyKey string
	Proposed                                            *LatLng
	AccuracyM                                           float64
}

// CheckReport is the report's own rules; the message is what the reporter
// reads.
func CheckReport(in ReportInput) (ReportInput, string) {
	out := in
	out.Note = strings.TrimSpace(in.Note)
	out.AccessNote = strings.TrimSpace(in.AccessNote)
	out.IdempotencyKey = strings.TrimSpace(in.IdempotencyKey)
	if out.Kind != "wrong" && out.Kind != "missing" {
		return out, "Say whether the location is wrong or missing."
	}
	if out.Note == "" {
		return out, "Say what is wrong with the location."
	}
	if len([]rune(out.Note)) > noteMaxRunes {
		return out, fmt.Sprintf("Keep the note under %d characters.", noteMaxRunes)
	}
	if len([]rune(out.AccessNote)) > accessNoteMaxRunes {
		return out, fmt.Sprintf("Keep the directions under %d characters.", accessNoteMaxRunes)
	}
	if len(out.IdempotencyKey) > idempotencyMaxLen {
		return out, "The report could not be sent. Please try again."
	}
	switch out.PointSource {
	case "", "none":
		out.PointSource, out.Proposed, out.AccuracyM = "none", nil, 0
		if out.Kind == "missing" {
			return out, "Give the school's location: type it or use your location."
		}
		return out, ""
	case "typed", "device":
	default:
		return out, "The report could not be sent. Please try again."
	}
	if out.Proposed == nil {
		return out, "Give the school's location: type it or use your location."
	}
	if _, status := check(out.Proposed.Lat, out.Proposed.Lng, LocationRecorded); status != LocationRecorded {
		return out, "That point is not in Uganda. Check the latitude and longitude."
	}
	if out.PointSource == "typed" {
		out.AccuracyM = 0
		return out, ""
	}
	if math.IsNaN(out.AccuracyM) || out.AccuracyM <= 0 {
		return out, "Your device did not say how accurate its location is. Please try again."
	}
	if out.AccuracyM > deviceAccuracyMaxM {
		return out, fmt.Sprintf("Your location is only accurate to %.0f m. Move into the open and try again, or type the point.", out.AccuracyM)
	}
	return out, ""
}

// ReviewMessage is why the reader may not decide the report, or "".
func ReviewMessage(reviewer, reporter, status, decision, note string) string {
	switch {
	case status != "pending":
		return "This report has already been decided."
	case reviewer == reporter:
		return "Someone else must review your own report."
	case decision != "approve" && decision != "reject":
		return "Choose approve or reject."
	case decision == "reject" && strings.TrimSpace(note) == "":
		return "Say why the report is rejected."
	case len([]rune(strings.TrimSpace(note))) > noteMaxRunes:
		return fmt.Sprintf("Keep the note under %d characters.", noteMaxRunes)
	}
	return ""
}

func newID() (string, error) {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", fmt.Errorf("routeplan: making a report id: %w", err)
	}
	b[6] = b[6]&0x0f | 0x40
	b[8] = b[8]&0x3f | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:]), nil
}

func bad(ctx context.Context, msg string) error {
	return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, msg)
}

// ReportSchoolLocation files a report. Nothing changes on the map until
// someone else approves it.
func (s *Service) ReportSchoolLocation(ctx context.Context, req *connect.Request[routesv1.ReportSchoolLocationRequest]) (*connect.Response[routesv1.ReportSchoolLocationResponse], error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return nil, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing, "sign in first")
	}
	if !MayOpenProfile(p.ActiveRole) {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: Your active role does not have permission to report school locations.")
	}
	if err := s.needVerify(ctx); err != nil {
		return nil, err
	}
	m := req.Msg
	in := ReportInput{Kind: m.GetKind(), PointSource: m.GetPointSource(), AccessNote: m.GetAccessNote(),
		Note: m.GetNote(), IdempotencyKey: m.GetIdempotencyKey(), AccuracyM: m.GetAccuracyM()}
	if pt := m.GetProposed(); pt != nil {
		in.Proposed = &LatLng{pt.GetLat(), pt.GetLng()}
	}
	in, msg := CheckReport(in)
	if msg != "" {
		return nil, bad(ctx, msg)
	}
	sc, found, err := schoolByRef(ctx, s, p, m.GetSchoolId())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	if !found {
		return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonSchoolNotFound, "school not found")
	}
	id, err := s.fileReport(ctx, p, sc, in)
	if errors.Is(err, errPending) {
		return nil, apierr.New(ctx, connect.CodeAlreadyExists, apierr.ReasonInvalidArgument,
			"A report on this school's location is already waiting for review.")
	}
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	report, err := s.report(ctx, p, id)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&routesv1.ReportSchoolLocationResponse{Report: report}), nil
}

var errPending = errors.New("routeplan: a report is pending")

// fileReport inserts the report and returns its id; a retry with the same
// key returns the first report's id.
func (s *Service) fileReport(ctx context.Context, p auth.Principal, sc school, in ReportInput) (string, error) {
	id, err := newID()
	if err != nil {
		return "", err
	}
	var key, lat, lng, acc, prevLat, prevLng any
	if in.IdempotencyKey != "" {
		key = in.IdempotencyKey
	}
	if in.Proposed != nil {
		lat, lng = in.Proposed.Lat, in.Proposed.Lng
	}
	if in.PointSource == "device" {
		acc = in.AccuracyM
	}
	if sc.placed() {
		prevLat, prevLng = sc.at.Lat, sc.at.Lng
	}
	tx, err := s.verify.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return "", fmt.Errorf("routeplan: opening the report: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if key != nil {
		var prior string
		err := tx.QueryRow(ctx, `SELECT id::text FROM field_routes.location_report WHERE idempotency_key = $1 AND reported_by = $2`, key, p.UserID).Scan(&prior)
		if err == nil {
			return prior, nil
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return "", fmt.Errorf("routeplan: reading the report key: %w", err)
		}
	}
	_, err = tx.Exec(ctx, `
INSERT INTO field_routes.location_report (id, school_id, school_code, kind, proposed_lat, proposed_lng,
  point_source, accuracy_m, access_note, note, previous_lat, previous_lng, previous_status,
  reported_by, reported_role, reported_at, idempotency_key)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17)`,
		id, sc.pin.GetSchoolId(), sc.pin.GetCode(), in.Kind, lat, lng, in.PointSource, acc, in.AccessNote, in.Note,
		prevLat, prevLng, sc.pin.GetLocationStatus(), p.UserID, p.ActiveRole, s.now().UTC(), key)
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == "23505" {
		if pgErr.ConstraintName == "location_report_one_pending" {
			return "", errPending
		}
		return "", fmt.Errorf("routeplan: the report key was used by someone else: %w", err)
	}
	if err != nil {
		return "", fmt.Errorf("routeplan: filing the report: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return "", fmt.Errorf("routeplan: committing the report: %w", err)
	}
	return id, nil
}

// reportCols reads a report with its school (schoolCols first) and names.
func reportCols() string {
	return schoolCols() + `, r.id::text, r.kind, r.proposed_lat, r.proposed_lng, r.point_source, COALESCE(r.accuracy_m, 0),
  r.access_note, r.note, r.previous_lat, r.previous_lng, r.status, r.reported_by, COALESCE(ru.name, ''), r.reported_at,
  COALESCE(rv.name, ''), r.reviewed_at, r.review_note`
}

func reportFrom() string {
	return `field_routes.location_report r JOIN ` + schoolFrom() + ` ON s.id = r.school_id
  LEFT JOIN "user" ru ON ru.id = r.reported_by LEFT JOIN "user" rv ON rv.id = r.reviewed_by`
}

func scanReport(row pgx.CollectableRow, reader string) (*routesv1.LocationReport, error) {
	var (
		out                          routesv1.LocationReport
		pLat, pLng, prevLat, prevLng *float64
		reportedBy                   string
		reportedAt                   time.Time
		reviewedAt                   *time.Time
	)
	sc, err := scanSchool(row, &out.Id, &out.Kind, &pLat, &pLng, &out.PointSource, &out.AccuracyM, &out.AccessNote, &out.Note,
		&prevLat, &prevLng, &out.Status, &reportedBy, &out.ReportedByName, &reportedAt, &out.ReviewedByName, &reviewedAt, &out.ReviewNote)
	if err != nil {
		return nil, err
	}
	out.School = sc.pin
	out.ReportedAt = reportedAt.UTC().Format(time.RFC3339)
	if reviewedAt != nil {
		out.ReviewedAt = reviewedAt.UTC().Format(time.RFC3339)
	}
	out.IsOwn = reportedBy == reader
	if pLat != nil && pLng != nil {
		out.Proposed = &routesv1.Point{Lat: *pLat, Lng: *pLng}
	}
	if prevLat != nil && prevLng != nil {
		out.Previous = &routesv1.Point{Lat: *prevLat, Lng: *prevLng}
		if out.Proposed != nil {
			out.MovedMeters = StraightMeters(LatLng{*prevLat, *prevLng}, LatLng{*pLat, *pLng})
		}
	}
	return &out, nil
}

// reports reads reports on schools in the reader's reach; each ? in filter
// takes the next value.
func (s *Service) reports(ctx context.Context, p auth.Principal, filter string, values ...any) ([]*routesv1.LocationReport, error) {
	a := &args{}
	where, err := reach(ctx, s.db, p, s.now(), a)
	if err != nil {
		return nil, err
	}
	cond := filter
	for _, v := range values {
		cond = strings.Replace(cond, "?", a.add(v), 1)
	}
	rows, err := s.db.Query(ctx, `SELECT `+reportCols()+` FROM `+reportFrom()+` WHERE `+where+` AND `+cond, *a...)
	if err != nil {
		return nil, fmt.Errorf("routeplan: reading location reports: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (*routesv1.LocationReport, error) { return scanReport(r, p.UserID) })
	if err != nil {
		return nil, fmt.Errorf("routeplan: reading location reports: %w", err)
	}
	return list, nil
}

func (s *Service) report(ctx context.Context, p auth.Principal, id string) (*routesv1.LocationReport, error) {
	list, err := s.reports(ctx, p, `r.id::text = ?`, id)
	if err != nil {
		return nil, err
	}
	if len(list) == 0 {
		return nil, fmt.Errorf("routeplan: report %s is not in the reader's reach", id)
	}
	return list[0], nil
}

// pendingFor is the open report on the school, if any, and the verified
// location's access note.
func (s *Service) pendingFor(ctx context.Context, p auth.Principal, schoolID string) (*routesv1.LocationReport, string, error) {
	list, err := s.reports(ctx, p, `r.school_id = ? AND r.status = 'pending'`, schoolID)
	if err != nil {
		return nil, "", err
	}
	var note string
	err = s.db.QueryRow(ctx, `SELECT access_note FROM field_routes.verified_location WHERE school_id = $1`, schoolID).Scan(&note)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, "", fmt.Errorf("routeplan: reading the verified location: %w", err)
	}
	if len(list) == 0 {
		return nil, note, nil
	}
	return list[0], note, nil
}

// ListLocationReports is the reviewer's queue: oldest first while pending,
// newest first once decided.
func (s *Service) ListLocationReports(ctx context.Context, req *connect.Request[routesv1.ListLocationReportsRequest]) (*connect.Response[routesv1.ListLocationReportsResponse], error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return nil, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing, "sign in first")
	}
	if !MayReview(p.ActiveRole) {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: Your active role does not review school locations.")
	}
	if err := s.needVerify(ctx); err != nil {
		return nil, err
	}
	status := req.Msg.GetStatus()
	if status == "" {
		status = "pending"
	}
	order := "r.reported_at DESC, r.id"
	switch status {
	case "pending":
		order = "r.reported_at, r.id"
	case "approved", "rejected":
	default:
		return nil, bad(ctx, "status is pending, approved or rejected")
	}
	list, err := s.reports(ctx, p, `r.status = ? ORDER BY `+order+` LIMIT 200`, status)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&routesv1.ListLocationReportsResponse{Reports: list}), nil
}

// ReviewLocationReport approves or rejects a report. Approving makes the
// proposed point the school's verified location.
func (s *Service) ReviewLocationReport(ctx context.Context, req *connect.Request[routesv1.ReviewLocationReportRequest]) (*connect.Response[routesv1.ReviewLocationReportResponse], error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return nil, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing, "sign in first")
	}
	if !MayReview(p.ActiveRole) {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: Your active role does not review school locations.")
	}
	if err := s.needVerify(ctx); err != nil {
		return nil, err
	}
	id := req.Msg.GetReportId()
	// The report must be in the reader's reach before anything is decided.
	list, err := s.reports(ctx, p, `r.id::text = ?`, id)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	if len(list) == 0 {
		return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "report not found")
	}
	decision, note := req.Msg.GetDecision(), strings.TrimSpace(req.Msg.GetNote())
	if err := s.decide(ctx, p, id, decision, note); err != nil {
		var refused refusal
		if errors.As(err, &refused) {
			return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument, string(refused))
		}
		return nil, s.fail(ctx, err)
	}
	report, err := s.report(ctx, p, id)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&routesv1.ReviewLocationReportResponse{Report: report}), nil
}

type refusal string

func (r refusal) Error() string { return string(r) }

// decide locks the report, checks it is still open and not the reader's,
// and records the decision (and, on approval, the verified location).
func (s *Service) decide(ctx context.Context, p auth.Principal, id, decision, note string) error {
	tx, err := s.verify.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("routeplan: opening the review: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var (
		schoolID, reporter, status, access string
		lat, lng                           *float64
	)
	err = tx.QueryRow(ctx, `
SELECT school_id, reported_by, status, proposed_lat, proposed_lng, access_note
FROM field_routes.location_report WHERE id::text = $1 FOR UPDATE`, id).Scan(&schoolID, &reporter, &status, &lat, &lng, &access)
	if err != nil {
		return fmt.Errorf("routeplan: locking the report: %w", err)
	}
	if msg := ReviewMessage(p.UserID, reporter, status, decision, note); msg != "" {
		return refusal(msg)
	}
	if decision == "approve" && lat == nil {
		return refusal("This report gives no point to approve. Reject it with a note, or ask for a point.")
	}
	now := s.now().UTC()
	final := map[string]string{"approve": "approved", "reject": "rejected"}[decision]
	if _, err := tx.Exec(ctx, `
UPDATE field_routes.location_report SET status = $2, reviewed_by = $3, reviewed_role = $4, reviewed_at = $5, review_note = $6
WHERE id::text = $1`, id, final, p.UserID, p.ActiveRole, now, note); err != nil {
		return fmt.Errorf("routeplan: recording the review: %w", err)
	}
	if decision == "approve" {
		if _, err := tx.Exec(ctx, `
INSERT INTO field_routes.verified_location (school_id, lat, lng, access_note, report_id, verified_by, verified_at)
VALUES ($1, $2, $3, $4, $5::uuid, $6, $7)
ON CONFLICT (school_id) DO UPDATE SET lat = EXCLUDED.lat, lng = EXCLUDED.lng, access_note = EXCLUDED.access_note,
  report_id = EXCLUDED.report_id, verified_by = EXCLUDED.verified_by, verified_at = EXCLUDED.verified_at`,
			schoolID, *lat, *lng, access, id, p.UserID, now); err != nil {
			return fmt.Errorf("routeplan: recording the verified location: %w", err)
		}
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("routeplan: committing the review: %w", err)
	}
	return nil
}
