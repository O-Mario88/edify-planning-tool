package routeplan

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/http"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/realtime"
)

// GPSLocationRequest is the payload accepted by POST /api/v1/schools/{schoolId}/gps-location
// and POST /api/schools/{schoolId}/gps-location (Section 6).
type GPSLocationRequest struct {
	CaptureID         string  `json:"capture_id,omitempty"`
	Target            string  `json:"target,omitempty"` // "school" (default) | "entrance"
	Latitude          float64 `json:"latitude"`
	Longitude         float64 `json:"longitude"`
	AccuracyMeters    float64 `json:"accuracy_meters"`
	CapturedAt        string  `json:"captured_at"` // RFC3339 timestamp from device
	SampleCount       int32   `json:"sample_count,omitempty"`
	SpreadMeters      float64 `json:"spread_meters,omitempty"`
	BaseVersion       *int32  `json:"base_version,omitempty"`
	ConfirmedAtSchool bool    `json:"confirmed_at_school"`
	Reason            string  `json:"reason,omitempty"`
	AccessNote        string  `json:"access_note,omitempty"`
	Source            string  `json:"source,omitempty"` // "device" (default)
	IsOfflineSync     bool    `json:"is_offline_sync,omitempty"`
}

// GPSAuditEntry is one historical coordinate change record.
type GPSAuditEntry struct {
	Version         int32    `json:"version"`
	Latitude        float64  `json:"latitude"`
	Longitude       float64  `json:"longitude"`
	PreviousLat     *float64 `json:"previous_latitude,omitempty"`
	PreviousLng     *float64 `json:"previous_longitude,omitempty"`
	PreviousVersion int32    `json:"previous_version"`
	ChangedBy       string   `json:"changed_by"`
	ChangedAt       string   `json:"changed_at"`
}

// GPSLocationState is the authoritative school coordinate state returned by GET/POST.
type GPSLocationState struct {
	SchoolID           string          `json:"school_id"`
	SchoolCode         string          `json:"school_code"`
	SchoolName         string          `json:"school_name"`
	District           string          `json:"district"`
	HasCoordinates     bool            `json:"has_coordinates"`
	Latitude           *float64        `json:"latitude,omitempty"`
	Longitude          *float64        `json:"longitude,omitempty"`
	WGS84PointWKT      string          `json:"wgs84_point_wkt,omitempty"` // POINT(lng lat) EPSG:4326
	AccuracyMeters     *float64        `json:"accuracy_meters,omitempty"`
	LocationStatus     string          `json:"location_status"` // verified | recorded | missing | invalid
	Source             string          `json:"source"`
	Version            int32           `json:"version"`
	VerifiedAt         string          `json:"verified_at,omitempty"`
	VerifiedByName     string          `json:"verified_by_name,omitempty"`
	EntranceLat        *float64        `json:"entrance_latitude,omitempty"`
	EntranceLng        *float64        `json:"entrance_longitude,omitempty"`
	AccessNote         string          `json:"access_note,omitempty"`
	CanCapture         bool            `json:"can_capture"`
	History            []GPSAuditEntry `json:"history,omitempty"`
}

func (s *Service) registerGPSHTTP(mux *http.ServeMux, authn Authenticator, broker *realtime.Broker) {
	wrap := func(pattern string, fn func(w http.ResponseWriter, r *http.Request, p auth.Principal)) {
		mux.HandleFunc(pattern, func(w http.ResponseWriter, r *http.Request) {
			p, err := authn.Authenticate(r.Context(), r.Header.Get("Authorization"))
			if err != nil {
				writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "sign in first"})
				return
			}
			ctx := auth.WithPrincipal(r.Context(), p)
			s.verifyReady(ctx)
			fn(w, r.WithContext(ctx), p)
		})
	}
	// Mount both /api/v1/schools/{schoolId}/gps-location (Edify API convention)
	// and /api/schools/{schoolId}/gps-location (exact path referenced in Section 6).
	wrap("GET /api/v1/schools/{schoolId}/gps-location", s.httpGetSchoolGPS)
	wrap("GET /api/schools/{schoolId}/gps-location", s.httpGetSchoolGPS)
	wrap("POST /api/v1/schools/{schoolId}/gps-location", func(w http.ResponseWriter, r *http.Request, p auth.Principal) {
		s.httpSaveSchoolGPS(w, r, p, broker)
	})
	wrap("POST /api/schools/{schoolId}/gps-location", func(w http.ResponseWriter, r *http.Request, p auth.Principal) {
		s.httpSaveSchoolGPS(w, r, p, broker)
	})
}

func (s *Service) invalidateRouteCaches() {
	if g, ok := s.router.(*Guarded); ok {
		g.ClearCache()
	}
	if s.onLocationUpdated != nil {
		s.onLocationUpdated()
	}
}

func (s *Service) loadGPSState(ctx context.Context, p auth.Principal, schoolRef string) (GPSLocationState, bool, error) {
	sc, found, err := schoolByRef(ctx, s, p, schoolRef)
	if err != nil || !found {
		return GPSLocationState{}, found, err
	}
	st := GPSLocationState{
		SchoolID:       sc.pin.SchoolId,
		SchoolCode:     sc.pin.Code,
		SchoolName:     sc.pin.Name,
		District:       sc.pin.District,
		HasCoordinates: sc.placed(),
		LocationStatus: sc.pin.LocationStatus,
		Source:         "directory",
		Version:        sc.pin.LocationVersion,
		CanCapture:     MayCaptureGPS(p.ActiveRole),
		History:        []GPSAuditEntry{},
	}
	if sc.placed() {
		lat, lng := sc.at.Lat, sc.at.Lng
		st.Latitude, st.Longitude = &lat, &lng
		// Strictly WGS84 / EPSG:4326 longitude-first POINT(lng lat)
		st.WGS84PointWKT = fmt.Sprintf("SRID=4326;POINT(%.6f %.6f)", lng, lat)
	}
	if sc.entrance != nil {
		eLat, eLng := sc.entrance.Lat, sc.entrance.Lng
		st.EntranceLat, st.EntranceLng = &eLat, &eLng
	}
	if s.verifyReady(ctx) {
		var acc *float64
		var note, byName string
		var verAt *time.Time
		if err := s.db.QueryRow(ctx, `
SELECT sl.accuracy_m, COALESCE(sl.access_note, ''), sl.verified_at, COALESCE(u.name, '')
FROM field_routes.school_location sl
LEFT JOIN "user" u ON u.id = sl.verified_by
WHERE sl.school_id = $1 AND sl.target = 'school'`, sc.pin.SchoolId).Scan(&acc, &note, &verAt, &byName); err == nil {
			st.AccuracyMeters = acc
			st.AccessNote = note
			st.VerifiedByName = byName
			st.Source = "device_gps"
			if verAt != nil {
				st.VerifiedAt = verAt.UTC().Format(time.RFC3339)
			}
		}
		if rows, err := s.db.Query(ctx, `
SELECT lc.version, lc.lat, lc.lng, lc.previous_lat, lc.previous_lng, lc.previous_version,
       COALESCE(u.name, lc.changed_by), lc.changed_at
FROM field_routes.location_change lc
LEFT JOIN "user" u ON u.id = lc.changed_by
WHERE lc.school_id = $1 AND lc.target = 'school'
ORDER BY lc.version DESC LIMIT 20`, sc.pin.SchoolId); err == nil {
			defer rows.Close()
			for rows.Next() {
				var e GPSAuditEntry
				var at time.Time
				if rows.Scan(&e.Version, &e.Latitude, &e.Longitude, &e.PreviousLat, &e.PreviousLng,
					&e.PreviousVersion, &e.ChangedBy, &at) == nil {
					e.ChangedAt = at.UTC().Format(time.RFC3339)
					st.History = append(st.History, e)
				}
			}
		}
	}
	return st, true, nil
}

func (s *Service) httpGetSchoolGPS(w http.ResponseWriter, r *http.Request, p auth.Principal) {
	schoolID := strings.TrimSpace(r.PathValue("schoolId"))
	if schoolID == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "schoolId is required"})
		return
	}
	st, found, err := s.loadGPSState(r.Context(), p, schoolID)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not load school GPS state"})
		return
	}
	if !found {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "school not found in your authorized scope"})
		return
	}
	writeJSON(w, http.StatusOK, st)
}

func (s *Service) httpSaveSchoolGPS(w http.ResponseWriter, r *http.Request, p auth.Principal, broker *realtime.Broker) {
	if !MayCaptureGPS(p.ActiveRole) {
		writeJSON(w, http.StatusForbidden, map[string]string{
			"error": "Access Denied: Your active role does not have permission to capture school GPS coordinates.",
		})
		return
	}
	if !s.verifyReady(r.Context()) {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "location storage is not ready on this server"})
		return
	}
	schoolRef := strings.TrimSpace(r.PathValue("schoolId"))
	if schoolRef == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "schoolId is required"})
		return
	}
	var req GPSLocationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid GPS capture payload"})
		return
	}
	if !req.ConfirmedAtSchool {
		writeJSON(w, http.StatusBadRequest, map[string]string{
			"error": "Confirm that you are physically at the school premises before saving GPS coordinates.",
		})
		return
	}
	if math.IsNaN(req.Latitude) || math.IsInf(req.Latitude, 0) || math.IsNaN(req.Longitude) || math.IsInf(req.Longitude, 0) {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "valid numeric WGS84 latitude and longitude are required"})
		return
	}
	countryCode := workingCode(p)
	if countryCode == "" {
		countryCode = "UG"
	}
	if _, status := CheckForCountry(countryCode, req.Latitude, req.Longitude, LocationVerified); !Placed(status) {
		writeJSON(w, http.StatusBadRequest, map[string]string{
			"error": fmt.Sprintf("GPS coordinates (%.6f, %.6f) fall outside plausible geographic bounds for %s.", req.Latitude, req.Longitude, countryCode),
		})
		return
	}
	if math.IsNaN(req.AccuracyMeters) || math.IsInf(req.AccuracyMeters, 0) || req.AccuracyMeters <= 0 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "GPS accuracy metadata (metres) is required from device location services"})
		return
	}
	if req.AccuracyMeters > DefaultPolicy.MaxAccuracyM {
		writeJSON(w, http.StatusBadRequest, map[string]string{
			"error": fmt.Sprintf("GPS reading accuracy (±%.0f m) is too coarse. Move outdoors into clear sky and retake.", req.AccuracyMeters),
		})
		return
	}
	capturedAt, err := time.Parse(time.RFC3339, strings.TrimSpace(req.CapturedAt))
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "valid RFC3339 captured_at timestamp is required"})
		return
	}
	now := s.now().UTC()
	ageSec := now.Sub(capturedAt.UTC()).Seconds()
	if !req.IsOfflineSync && ageSec > float64(DefaultPolicy.FreshSeconds) {
		writeJSON(w, http.StatusBadRequest, map[string]string{
			"error": fmt.Sprintf("GPS reading is stale (%.0f seconds old; max %d seconds). Retake a fresh reading.", ageSec, DefaultPolicy.FreshSeconds),
		})
		return
	}
	if capturedAt.UTC().Sub(now) > DefaultPolicy.ClockSkew {
		writeJSON(w, http.StatusBadRequest, map[string]string{
			"error": "GPS capture timestamp is ahead of server clock. Check device clock and retake.",
		})
		return
	}

	// Enforce per-user / partner school access strictly — prevents ID tampering (Section 9).
	sc, found, err := schoolByRef(r.Context(), s, p, schoolRef)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not verify school authorization"})
		return
	}
	if !found {
		writeJSON(w, http.StatusForbidden, map[string]string{
			"error": "Access Denied: This school is outside your authorized scope.",
		})
		return
	}

	target := strings.TrimSpace(req.Target)
	if target == "" {
		target = "school"
	}
	if target != "school" && target != "entrance" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "target must be school or entrance"})
		return
	}
	captureID := strings.ToLower(strings.TrimSpace(req.CaptureID))
	if captureID == "" {
		if captureID, err = newID(); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to generate capture id"})
			return
		}
	} else if !uuidPattern.MatchString(captureID) {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "capture_id must be a valid UUID"})
		return
	}

	centre, err := s.districtCentre(r.Context(), sc.pin.SchoolId)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not evaluate district bounds"})
		return
	}

	tx, err := s.verify.db.BeginTx(r.Context(), pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not open transaction"})
		return
	}
	defer func() { _ = tx.Rollback(r.Context()) }()

	schoolID := sc.pin.SchoolId
	if err := lockSchool(r.Context(), tx, schoolID, target); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not lock school location"})
		return
	}
	st, err := current(r.Context(), tx, schoolID, target, sc.pin)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not read current school location"})
		return
	}
	st.DistrictCentre = centre

	// Idempotent retry check for offline sync queues.
	var existingBy, existingStatus string
	var existingResultVer *int32
	if err := tx.QueryRow(r.Context(), `SELECT captured_by, status, result_version FROM field_routes.location_capture WHERE id = $1::uuid`, captureID).Scan(&existingBy, &existingStatus, &existingResultVer); err == nil {
		if existingBy != p.UserID {
			writeJSON(w, http.StatusConflict, map[string]string{"error": "duplicate capture_id owned by another user"})
			return
		}
		_ = tx.Rollback(r.Context())
		freshState, _, _ := s.loadGPSState(r.Context(), p, schoolID)
		writeJSON(w, http.StatusOK, map[string]any{
			"capture_id": captureID,
			"outcome":    existingStatus,
			"idempotent": true,
			"location":   freshState,
		})
		return
	}

	// Optimistic concurrency conflict check (Section 6 & Acceptance Test 8).
	baseVer := st.Version
	if req.BaseVersion != nil {
		baseVer = *req.BaseVersion
		if baseVer != st.Version {
			writeJSON(w, http.StatusConflict, map[string]any{
				"error":           fmt.Sprintf("Concurrency conflict: this school's coordinates were already updated (version %d -> %d). Refresh and review before saving.", baseVer, st.Version),
				"code":            "version_conflict",
				"current_version": st.Version,
				"current_point":   st.At,
			})
			return
		}
	}

	kind := "new"
	if st.Placed {
		kind = "correction"
	}
	reason := strings.TrimSpace(req.Reason)
	if kind == "correction" && reason == "" {
		reason = "On-site GPS coordinate update"
	}
	pt := LatLng{Lat: req.Latitude, Lng: req.Longitude}
	in := CaptureInput{
		Target:      target,
		Kind:        kind,
		Source:      "device",
		Point:       &pt,
		AccuracyM:   req.AccuracyMeters,
		CapturedAt:  capturedAt.UTC(),
		SampleCount: max(int32(1), req.SampleCount),
		SpreadM:     req.SpreadMeters,
		BaseVersion: baseVer,
		Reason:      reason,
		AccessNote:  strings.TrimSpace(req.AccessNote),
	}
	d := DecideGPSCapture(in, st, p.ActiveRole, now, DefaultPolicy)
	flags := d.Flags
	if req.IsOfflineSync {
		flags = append(flags, "offline_sync")
	}
	if flags == nil {
		flags = []string{}
	}
	var prevLat, prevLng any
	if st.Placed {
		prevLat, prevLng = st.At.Lat, st.At.Lng
	}

	_, err = tx.Exec(r.Context(), `
INSERT INTO field_routes.location_capture (
  id, school_id, school_code, target, kind, point_source, lat, lng, accuracy_m,
  captured_at, sample_count, spread_m, received_at, base_version, previous_lat, previous_lng,
  previous_status, displacement_m, reason, access_note, flags, status, captured_by, captured_role, country_code
) VALUES (
  $1::uuid, $2, $3, $4, $5, 'device', $6, $7, $8,
  $9, $10, $11, $12, $13, $14, $15,
  $16, $17, $18, $19, $20, $21, $22, $23, `+registry.SchoolCountryCode("$2")+`
)`, captureID, schoolID, sc.pin.Code, target, kind, pt.Lat, pt.Lng, in.AccuracyM,
		in.CapturedAt, in.SampleCount, in.SpreadM, now, baseVer, prevLat, prevLng,
		sc.pin.LocationStatus, d.DisplacementM, in.Reason, in.AccessNote, flags, d.Status, p.UserID, p.ActiveRole)
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == "23505" {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "duplicate capture submission"})
		return
	}
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not record GPS capture"})
		return
	}

	var resultVersion int32
	if d.Status == CaptureAccepted {
		acc := in.AccuracyM
		resultVersion, err = s.apply(r.Context(), tx, change{
			schoolID:  schoolID,
			target:    target,
			captureID: captureID,
			at:        pt,
			accuracy:  &acc,
			note:      in.AccessNote,
			by:        p.UserID,
			when:      now,
			fallback:  sc.pin,
		})
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not persist school GPS coordinates"})
			return
		}
		if _, err := tx.Exec(r.Context(), `UPDATE field_routes.location_capture SET result_version = $2 WHERE id = $1::uuid`, captureID, resultVersion); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not record version on capture"})
			return
		}
	}

	if err := tx.Commit(r.Context()); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not commit GPS coordinate update"})
		return
	}

	// Immediately invalidate cached road routes & broadcast live SSE update (Section 7).
	if d.Status == CaptureAccepted {
		s.invalidateRouteCaches()
		if broker != nil {
			broker.Publish(realtime.Event{
				Type:        "school_location.updated",
				EntityType:  "school",
				EntityID:    schoolID,
				CountryCode: countryCode,
			})
		}
	}

	updatedState, _, _ := s.loadGPSState(r.Context(), p, schoolID)
	outcome := "saved"
	msg := "School GPS coordinates saved and synchronized across Edify."
	if d.Status != CaptureAccepted {
		outcome = "pending_review"
		msg = "GPS reading recorded and queued for supervisor verification due to accuracy, large displacement, or role policy."
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"capture_id":           captureID,
		"outcome":              outcome,
		"message":              msg,
		"flags":                flags,
		"displacement_meters":  d.DisplacementM,
		"previous_point":       func() *LatLng { if st.Placed { return &st.At }; return nil }(),
		"version":              resultVersion,
		"saved_at":             now.Format(time.RFC3339),
		"location":             updatedState,
	})
}
