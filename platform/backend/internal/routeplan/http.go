package routeplan

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/realtime"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Authenticator validates an Authorization header for REST endpoints.
type Authenticator interface {
	Authenticate(ctx context.Context, header string) (auth.Principal, error)
}

// RegisterHTTP mounts the canonical Go Smart Route Planner & Scheduling Rules
// REST endpoints (Sections 7, 11, 12, 13).
func (s *Service) RegisterHTTP(mux *http.ServeMux, authn Authenticator, broker *realtime.Broker) {
	handle := func(pattern string, fn func(w http.ResponseWriter, r *http.Request, p auth.Principal)) {
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

	handle("GET /api/v1/smart-route/day", s.httpGetDay)
	handle("POST /api/v1/smart-route/optimize", s.httpOptimize)
	handle("POST /api/v1/smart-route/directions", s.httpDirections)
	handle("POST /api/v1/smart-route/save", func(w http.ResponseWriter, r *http.Request, p auth.Principal) {
		s.httpSaveRoute(w, r, p, broker)
	})
	handle("POST /api/v1/smart-route/validate", s.httpValidateRoute)
	handle("GET /api/v1/smart-route/road-conditions", s.httpListRoadConditions)
	handle("POST /api/v1/smart-route/road-conditions", func(w http.ResponseWriter, r *http.Request, p auth.Principal) {
		s.httpReportRoadCondition(w, r, p, broker)
	})
	handle("POST /api/v1/smart-route/road-conditions/{id}/verify", func(w http.ResponseWriter, r *http.Request, p auth.Principal) {
		s.httpVerifyRoadCondition(w, r, p, broker)
	})
	handle("GET /api/v1/scheduling/calendar-rules", s.httpCalendarRules)
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func (s *Service) quotaSnapshot() *QuotaSnapshot {
	if g, ok := s.router.(*Guarded); ok {
		q := g.Quota()
		return &q
	}
	return &QuotaSnapshot{Provider: s.name}
}

// SavedRouteSummary describes a persisted field_routes.route_plan row.
type SavedRouteSummary struct {
	RouteID          string   `json:"route_id"`
	Day              string   `json:"day"`
	Mode             string   `json:"optimization_mode"`
	TransportMode    string   `json:"transport_mode"`
	Status           string   `json:"route_status"`
	Version          int      `json:"route_version"`
	EstimatedMeters  int64    `json:"estimated_meters"`
	EstimatedSeconds int64    `json:"estimated_seconds"`
	VisitMinutes     int      `json:"visit_minutes"`
	FieldMinutes     int      `json:"field_minutes"`
	Provider         string   `json:"provider"`
	SchoolIDs        []string `json:"school_ids"`
	CalculatedAt     string   `json:"calculated_at"`
	UpdatedAt        string   `json:"updated_at"`
}

func (s *Service) loadSavedRoutePlan(ctx context.Context, userID string, day time.Time) (*SavedRouteSummary, error) {
	if !s.verifyReady(ctx) || userID == "" {
		return nil, nil
	}
	var out SavedRouteSummary
	var calcAt, updAt time.Time
	err := s.db.QueryRow(ctx, `
SELECT route_id::text, day::text, optimization_mode, transport_mode, route_status, route_version,
       estimated_meters, estimated_seconds, visit_minutes, field_minutes, provider, calculated_at, updated_at
FROM field_routes.route_plan
WHERE user_id = $1 AND day = $2`, userID, day.Format(time.DateOnly)).Scan(
		&out.RouteID, &out.Day, &out.Mode, &out.TransportMode, &out.Status, &out.Version,
		&out.EstimatedMeters, &out.EstimatedSeconds, &out.VisitMinutes, &out.FieldMinutes,
		&out.Provider, &calcAt, &updAt,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		// Table may not exist yet if 0007 wasn't applied; fall back gracefully.
		return nil, nil
	}
	out.CalculatedAt = calcAt.UTC().Format(time.RFC3339)
	out.UpdatedAt = updAt.UTC().Format(time.RFC3339)
	rows, err := s.db.Query(ctx, `SELECT school_id FROM field_routes.route_stop WHERE route_id = $1::uuid AND route_version = $2 ORDER BY stop_sequence`, out.RouteID, out.Version)
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var sid string
			if rows.Scan(&sid) == nil {
				out.SchoolIDs = append(out.SchoolIDs, sid)
			}
		}
	}
	return &out, nil
}

func (s *Service) loadActiveRoadConditions(ctx context.Context) []RoadConditionAlert {
	if !s.verifyReady(ctx) {
		return []RoadConditionAlert{}
	}
	rows, err := s.db.Query(ctx, `
SELECT id::text, road_name, lat, lng, radius_m, category, source, verification_status,
       impact_level, notes, reported_by_name, reported_at, expires_at
FROM field_routes.road_condition_report
WHERE verification_status IN ('unverified', 'verified')
  AND expires_at > $1
ORDER BY (verification_status = 'verified') DESC, reported_at DESC
LIMIT 100`, s.now().UTC())
	if err != nil {
		return []RoadConditionAlert{}
	}
	defer rows.Close()
	out := []RoadConditionAlert{}
	for rows.Next() {
		var r RoadConditionAlert
		if err := rows.Scan(&r.ID, &r.RoadName, &r.Lat, &r.Lng, &r.RadiusMeters, &r.Category, &r.Source,
			&r.VerificationStatus, &r.ImpactLevel, &r.Notes, &r.ReportedByName, &r.ReportedAt, &r.ExpiresAt); err == nil {
			out = append(out, r)
		}
	}
	return out
}

// httpGetDay returns the enriched Smart Route Planner workspace payload.
func (s *Service) httpGetDay(w http.ResponseWriter, r *http.Request, p auth.Principal) {
	if !MayPlan(p.ActiveRole) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "Your active role cannot plan field routes."})
		return
	}
	day, err := s.day(r.Context(), r.URL.Query().Get("date"))
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "date must be YYYY-MM-DD"})
		return
	}
	mode := normalizeSmartMode(r.URL.Query().Get("mode"))
	planned, err := plannedDay(r.Context(), s.db, owners(p), day)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not load planned schools"})
		return
	}
	s.mark(p, planned)
	savedPlan, _ := s.loadSavedRoutePlan(r.Context(), p.UserID, day)
	savedFD, _ := s.savedDay(r.Context(), p, day)
	roadConds := s.loadActiveRoadConditions(r.Context())

	orderedSchools := planned
	if savedPlan != nil && len(savedPlan.SchoolIDs) > 0 {
		if t, err := s.savedTrip(r.Context(), p, s.now(), planned, savedPlan.SchoolIDs); err == nil && len(t.schools) > 0 {
			orderedSchools = t.schools
		}
	} else if len(savedFD.order) > 0 {
		if t, err := s.savedTrip(r.Context(), p, s.now(), planned, savedFD.order); err == nil && len(t.schools) > 0 {
			orderedSchools = t.schools
		}
	}

	prios := loadSchoolPriorities(r.Context(), s.db, s.now(), orderedSchools)
	inputs := make([]SmartStopInput, 0, len(orderedSchools))
	for _, sc := range orderedSchools {
		inputs = append(inputs, SmartStopInput{
			School:            sc,
			PlannedActivityID: sc.pin.ActivityId,
			VisitMinutes:      Rules.Day.VisitMinutes,
			AppointmentMin:    -1,
			Priority:          prios[sc.pin.SchoolId],
		})
	}
	result := s.OptimizeSmart(r.Context(), SmartOptimizeInput{
		Date:           day.Format(time.DateOnly),
		Mode:           mode,
		WorkStart:      Rules.Day.Start,
		WorkEnd:        clock(startMinutes() + Rules.Day.AvailableMinutes),
		BreakMinutes:   Rules.Day.BufferMinutes,
		Stops:          inputs,
		RoadConditions: roadConds,
	})
	calRules := s.loadCalendarRules(r.Context(), p)

	writeJSON(w, http.StatusOK, map[string]any{
		"date":            day.Format(time.DateOnly),
		"date_label":      day.Format("Mon, 02 Jan 2006"),
		"owner_name":      p.Name,
		"owner_role":      p.ActiveRole,
		"result":          result,
		"saved_plan":      savedPlan,
		"road_conditions": roadConds,
		"calendar_rules":  calRules,
		"quota":           s.quotaSnapshot(),
	})
}

type optimizeHTTPRequest struct {
	Date          string   `json:"date"`
	Mode          string   `json:"mode"`
	TransportMode string   `json:"transport_mode"`
	WorkStart     string   `json:"work_start"`
	WorkEnd       string   `json:"work_end"`
	VisitMinutes  int      `json:"visit_minutes"`
	BreakMinutes  int      `json:"break_minutes"`
	Start         *LatLng  `json:"start"`
	StartLabel    string   `json:"start_label"`
	End           *LatLng  `json:"end"`
	EndLabel      string   `json:"end_label"`
	SchoolIDs     []string `json:"school_ids"`
	LockedIDs     []string `json:"locked_school_ids"`
}

// httpOptimize runs the 5-mode Smart Route Optimization Engine and logs a
// route_calculation audit record when field_routes is ready.
func (s *Service) httpOptimize(w http.ResponseWriter, r *http.Request, p auth.Principal) {
	if !MayPlan(p.ActiveRole) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "Your active role cannot optimize field routes."})
		return
	}
	var req optimizeHTTPRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid request body"})
		return
	}
	if len(req.SchoolIDs) == 0 || len(req.SchoolIDs) > maxChosen {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "choose between 1 and 20 schools"})
		return
	}
	day, err := s.day(r.Context(), req.Date)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "date must be YYYY-MM-DD"})
		return
	}
	found, err := schoolsByID(r.Context(), s.db, p, s.now(), req.SchoolIDs)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not load selected schools"})
		return
	}
	planned, _ := plannedDay(r.Context(), s.db, owners(p), day)
	plannedBySchool := map[string]school{}
	for _, sc := range planned {
		plannedBySchool[sc.pin.SchoolId] = sc
	}
	locked := map[string]bool{}
	for _, id := range req.LockedIDs {
		locked[id] = true
	}
	ordered := make([]school, 0, len(req.SchoolIDs))
	seen := map[string]bool{}
	for _, id := range req.SchoolIDs {
		sc, ok := found[id]
		if !ok || seen[id] {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "a selected school is outside your authorized scope"})
			return
		}
		seen[id] = true
		if pl, ok := plannedBySchool[id]; ok {
			sc.pin.ActivityId = pl.pin.ActivityId
			sc.pin.Status = pl.pin.Status
		} else {
			sc.pin.Status = "suggested"
		}
		ordered = append(ordered, sc)
	}
	s.mark(p, ordered)
	prios := loadSchoolPriorities(r.Context(), s.db, s.now(), ordered)
	visitMin := req.VisitMinutes
	if visitMin <= 0 {
		visitMin = Rules.Day.VisitMinutes
	}
	inputs := make([]SmartStopInput, 0, len(ordered))
	for _, sc := range ordered {
		inputs = append(inputs, SmartStopInput{
			School:            sc,
			PlannedActivityID: sc.pin.ActivityId,
			VisitMinutes:      visitMin,
			AppointmentMin:    -1,
			Locked:            locked[sc.pin.SchoolId],
			Priority:          prios[sc.pin.SchoolId],
		})
	}
	if req.Start != nil {
		if _, st := Locate(nil, nil, &req.Start.Lat, &req.Start.Lng); !Placed(st) {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "start location must be a valid point in Uganda"})
			return
		}
	}
	if req.End != nil {
		if _, st := Locate(nil, nil, &req.End.Lat, &req.End.Lng); !Placed(st) {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "end location must be a valid point in Uganda"})
			return
		}
	}
	roadConds := s.loadActiveRoadConditions(r.Context())
	result := s.OptimizeSmart(r.Context(), SmartOptimizeInput{
		Date:           day.Format(time.DateOnly),
		Mode:           req.Mode,
		TransportMode:  req.TransportMode,
		WorkStart:      req.WorkStart,
		WorkEnd:        req.WorkEnd,
		BreakMinutes:   req.BreakMinutes,
		Start:          req.Start,
		StartLabel:     req.StartLabel,
		End:            req.End,
		EndLabel:       req.EndLabel,
		Stops:          inputs,
		RoadConditions: roadConds,
	})
	writeJSON(w, http.StatusOK, map[string]any{
		"result": result,
		"quota":  s.quotaSnapshot(),
	})
}

type directionsHTTPRequest struct {
	Origin        *LatLng  `json:"origin"`
	OriginLabel   string   `json:"origin_label"`
	SchoolIDs     []string `json:"school_ids"`
	TransportMode string   `json:"transport_mode"`
}

// httpDirections powers Edify's 100% in-app "Get Directions" experience (Section 6)
// on web and mobile: real road-following polyline, turn-by-turn steps, road names,
// ETA, traffic state, alternative routes, and active road-condition warnings.
func (s *Service) httpDirections(w http.ResponseWriter, r *http.Request, p auth.Principal) {
	if !MayPlan(p.ActiveRole) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "Your active role cannot request field directions."})
		return
	}
	var req directionsHTTPRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid directions request"})
		return
	}
	if len(req.SchoolIDs) == 0 || len(req.SchoolIDs) > maxChosen {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "provide 1 to 20 destination schools"})
		return
	}
	found, err := schoolsByID(r.Context(), s.db, p, s.now(), req.SchoolIDs)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not load destination schools"})
		return
	}
	pts := []LatLng{}
	labels := []string{}
	stopsMeta := []map[string]any{}
	if req.Origin != nil {
		if _, st := Locate(nil, nil, &req.Origin.Lat, &req.Origin.Lng); !Placed(st) {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": "origin location is outside valid bounds"})
			return
		}
		pts = append(pts, *req.Origin)
		ol := strings.TrimSpace(req.OriginLabel)
		if ol == "" {
			ol = "Current Location"
		}
		labels = append(labels, ol)
	}
	for _, id := range req.SchoolIDs {
		sc, ok := found[id]
		if !ok {
			writeJSON(w, http.StatusNotFound, map[string]string{"error": "school not found in your scope"})
			return
		}
		if !sc.placed() {
			writeJSON(w, http.StatusUnprocessableEntity, map[string]string{
				"error": fmt.Sprintf("%s has no verified GPS coordinates; directions cannot be calculated.", sc.pin.Name),
			})
			return
		}
		target := sc.road()
		pts = append(pts, target)
		labels = append(labels, sc.pin.Name)
		stopsMeta = append(stopsMeta, map[string]any{
			"school_id":       sc.pin.SchoolId,
			"school_code":     sc.pin.Code,
			"school_name":     sc.pin.Name,
			"district":        sc.pin.District,
			"point":           sc.at,
			"entrance":        sc.entrance,
			"using_entrance":  sc.entrance != nil,
			"location_status": sc.pin.LocationStatus,
		})
	}

	if len(pts) < 2 {
		// Single school without GPS origin: return school profile & prompt for origin without fabricating a route.
		writeJSON(w, http.StatusOK, map[string]any{
			"in_app":             true,
			"road_available":     false,
			"needs_origin":       true,
			"message":            "Allow device location or select a starting point to compute turn-by-turn road directions.",
			"stops":              stopsMeta,
			"path":               []LatLng{},
			"legs":               []any{},
			"alternatives":       []AlternativeRoute{},
			"road_alerts":        matchRoadConditions(nil, pts, s.loadActiveRoadConditions(r.Context())),
			"provider":           s.name,
			"traffic_state":      "unavailable",
			"calculated_at":      s.now().UTC().Format(time.RFC3339),
		})
		return
	}

	opts := RouteOptions{
		IncludeSteps:        true,
		IncludeAlternatives: true,
		TrafficOptimal:      true,
		TransportMode:       req.TransportMode,
	}
	var route Route
	if dr, ok := s.router.(DetailedRouter); ok {
		route, err = dr.RouteDetailed(r.Context(), pts, opts)
	} else {
		route, err = s.router.Route(r.Context(), pts)
	}
	roadConds := s.loadActiveRoadConditions(r.Context())
	if err != nil || len(route.Legs) != len(pts)-1 || len(route.Path) < 2 {
		writeJSON(w, http.StatusOK, map[string]any{
			"in_app":         true,
			"road_available": false,
			"road_status":    "Road access requires verification",
			"message":        "Road access requires verification — routing provider could not return a drivable road route.",
			"stops":          stopsMeta,
			"path":           []LatLng{},
			"legs":           []any{},
			"alternatives":   []AlternativeRoute{},
			"road_alerts":    matchRoadConditions(nil, pts, roadConds),
			"provider":       s.name,
			"traffic_state":  "unavailable",
			"calculated_at":  s.now().UTC().Format(time.RFC3339),
		})
		return
	}

	legsOut := make([]map[string]any, 0, len(route.Legs))
	var totalMeters, totalSec int64
	eta := s.now().In(kampala)
	for i, l := range route.Legs {
		totalMeters += l.Meters
		totalSec += l.Seconds
		eta = eta.Add(time.Duration(l.Seconds) * time.Second)
		var steps []Step
		if i < len(route.LegSteps) {
			steps = route.LegSteps[i]
		}
		legsOut = append(legsOut, map[string]any{
			"index":            i,
			"from_label":       labels[i],
			"to_label":         labels[i+1],
			"distance_meters":  l.Meters,
			"duration_seconds": l.Seconds,
			"eta":              eta.Format("15:04"),
			"steps":            steps,
		})
	}
	alerts := matchRoadConditions(route.Path, pts, roadConds)
	trafficState := route.TrafficState
	if trafficState == "" {
		trafficState = "unavailable"
	}
	alts := route.Alternatives
	if alts == nil {
		alts = []AlternativeRoute{}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"in_app":                true,
		"road_available":        true,
		"provider":              s.name,
		"provider_source":       route.ProviderSource,
		"summary":               route.Summary,
		"total_meters":          totalMeters,
		"total_seconds":         totalSec,
		"static_seconds":        route.StaticSeconds,
		"traffic_state":         trafficState,
		"traffic_delay_seconds": route.TrafficDelaySec,
		"traffic_intervals":     route.TrafficIntervals,
		"eta_final":             eta.Format("15:04"),
		"path":                  Simplify(route.Path, lineTolerance),
		"stops":                 stopsMeta,
		"legs":                  legsOut,
		"alternatives":          alts,
		"road_alerts":           alerts,
		"warnings":              route.Warnings,
		"calculated_at":         s.now().UTC().Format(time.RFC3339),
	})
}

type saveRouteHTTPRequest struct {
	Date             string             `json:"date"`
	Mode             string             `json:"optimization_mode"`
	TransportMode    string             `json:"transport_mode"`
	Start            *LatLng            `json:"start"`
	StartLabel       string             `json:"start_label"`
	End              *LatLng            `json:"end"`
	EndLabel         string             `json:"end_label"`
	EstimatedMeters  int64              `json:"estimated_meters"`
	EstimatedSeconds int64              `json:"estimated_seconds"`
	VisitMinutes     int                `json:"visit_minutes"`
	FieldMinutes     int                `json:"field_minutes"`
	InputHash        string             `json:"input_hash"`
	AlternativesCnt  int                `json:"alternatives_count"`
	Stops            []SmartStopOutput  `json:"stops"`
}

// httpSaveRoute persists Route Plan, Route Stops (with planned_activity_id),
// Route Calculation, and field_routes.field_day inside one ReadWrite tx (Section 13).
// Never mutates public.activity.
func (s *Service) httpSaveRoute(w http.ResponseWriter, r *http.Request, p auth.Principal, broker *realtime.Broker) {
	if !MayPlan(p.ActiveRole) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "Your active role cannot save field routes."})
		return
	}
	if !s.verifyReady(r.Context()) {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "field_routes schema is not ready"})
		return
	}
	var req saveRouteHTTPRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid save payload"})
		return
	}
	if len(req.Stops) == 0 || len(req.Stops) > maxDayStops {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "choose between 1 and 30 stops to save"})
		return
	}
	day, err := s.day(r.Context(), req.Date)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "date must be YYYY-MM-DD"})
		return
	}
	schoolIDs := make([]string, 0, len(req.Stops))
	for _, st := range req.Stops {
		schoolIDs = append(schoolIDs, st.SchoolID)
	}
	ok, err := mayVisit(r.Context(), s.db, p, s.now(), schoolIDs)
	if err != nil || !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "one or more schools are outside your scope"})
		return
	}
	mode := normalizeSmartMode(req.Mode)
	transport := strings.ToUpper(strings.TrimSpace(req.TransportMode))
	if transport != "TWO_WHEELER" && transport != "WALK" {
		transport = "DRIVE"
	}
	country := workingCode(p)
	if country == "" {
		country = "UG"
	}
	fy := "FY" + schooldirectory.OperationalFY(day)
	now := s.now().UTC()
	routeUUID, err := newID()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to allocate route id"})
		return
	}
	calcUUID, err := newID()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to allocate calculation id"})
		return
	}

	tx, err := s.verify.db.BeginTx(r.Context(), pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not open transaction"})
		return
	}
	defer func() { _ = tx.Rollback(r.Context()) }()

	// Keep legacy field_day table synchronized so mobile & ConnectRPC read the exact same order.
	d, err := loadDay(r.Context(), tx, p.UserID, day, true)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not load field day"})
		return
	}
	if d.started == nil {
		next, refused := d.apply(dayEvent{kind: "save", order: schoolIDs}, now)
		if refused != "" {
			writeJSON(w, http.StatusConflict, map[string]string{"error": refused})
			return
		}
		if err := storeDay(r.Context(), tx, p.UserID, country, day, next); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not save field day"})
			return
		}
	}

	var startLat, startLng, endLat, endLng *float64
	if req.Start != nil {
		startLat, startLng = &req.Start.Lat, &req.Start.Lng
	}
	if req.End != nil {
		endLat, endLng = &req.End.Lat, &req.End.Lng
	}
	var savedID string
	var version int
	err = tx.QueryRow(r.Context(), `
INSERT INTO field_routes.route_plan (
  route_id, user_id, day, country_code, financial_year,
  start_lat, start_lng, start_label, end_lat, end_lng, end_label,
  transport_mode, optimization_mode, route_status,
  estimated_meters, estimated_seconds, visit_minutes, field_minutes,
  provider, route_version, calculated_at, updated_at
) VALUES (
  $1::uuid, $2, $3, COALESCE(NULLIF($4, ''), `+registry.HeldCode+`), $5,
  $6, $7, $8, $9, $10, $11,
  $12, $13, 'saved',
  $14, $15, $16, $17,
  $18, 1, $19, $19
)
ON CONFLICT (user_id, day) DO UPDATE SET
  start_lat = EXCLUDED.start_lat,
  start_lng = EXCLUDED.start_lng,
  start_label = EXCLUDED.start_label,
  end_lat = EXCLUDED.end_lat,
  end_lng = EXCLUDED.end_lng,
  end_label = EXCLUDED.end_label,
  transport_mode = EXCLUDED.transport_mode,
  optimization_mode = EXCLUDED.optimization_mode,
  route_status = 'saved',
  estimated_meters = EXCLUDED.estimated_meters,
  estimated_seconds = EXCLUDED.estimated_seconds,
  visit_minutes = EXCLUDED.visit_minutes,
  field_minutes = EXCLUDED.field_minutes,
  provider = EXCLUDED.provider,
  route_version = field_routes.route_plan.route_version + 1,
  calculated_at = EXCLUDED.calculated_at,
  updated_at = EXCLUDED.updated_at
RETURNING route_id::text, route_version`,
		routeUUID, p.UserID, day.Format(time.DateOnly), country, fy,
		startLat, startLng, req.StartLabel, endLat, endLng, req.EndLabel,
		transport, mode,
		req.EstimatedMeters, req.EstimatedSeconds, req.VisitMinutes, req.FieldMinutes,
		s.name, now,
	).Scan(&savedID, &version)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": fmt.Sprintf("could not persist route plan: %v", err)})
		return
	}

	for i, st := range req.Stops {
		_, err := tx.Exec(r.Context(), `
INSERT INTO field_routes.route_stop (
  route_id, route_version, stop_sequence, planned_activity_id, school_id,
  arrival_estimate, departure_estimate, visit_minutes,
  leg_meters, leg_seconds, road_available, completion_status,
  ssa_priority_band, ssa_priority_score, country_code
) VALUES (
  $1::uuid, $2, $3, $4, $5,
  $6, $7, $8,
  $9, $10, $11, $12,
  $13, $14, COALESCE(NULLIF($15, ''), `+registry.HeldCode+`)
)`,
			savedID, version, i+1, st.PlannedActivityID, st.SchoolID,
			st.Arrival, st.Departure, st.VisitMinutes,
			st.RoadMeters, st.RoadSeconds, st.RoadAvailable, st.Status,
			st.Priority.Band, st.Priority.Score, country,
		)
		if err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not persist route stop"})
			return
		}
	}

	fallback := "none"
	if s.name == "none" {
		fallback = "no_provider"
	}
	_, _ = tx.Exec(r.Context(), `
INSERT INTO field_routes.route_calculation (
  calculation_id, route_id, user_id, day, route_version, provider,
  input_hash, alternatives_count, fallback_status, calculated_at, country_code
) VALUES (
  $1::uuid, $2::uuid, $3, $4, $5, $6,
  $7, $8, $9, $10, COALESCE(NULLIF($11, ''), `+registry.HeldCode+`)
)`, calcUUID, savedID, p.UserID, day.Format(time.DateOnly), version, s.name,
		req.InputHash, req.AlternativesCnt, fallback, now, country)

	if err := tx.Commit(r.Context()); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not commit route plan"})
		return
	}

	if broker != nil {
		broker.Publish(realtime.Event{
			Type:         "route_plan.saved",
			EntityType:   "route_plan",
			EntityID:     savedID,
			CountryCode:  country,
			TargetUserID: p.UserID,
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"route_id":      savedID,
		"route_version": version,
		"saved_at":      now.Format(time.RFC3339),
		"school_ids":    schoolIDs,
	})
}

// httpValidateRoute checks whether a saved route is still synchronized with
// My Plan activities, school GPS coordinates, approved leave, and road conditions (Section 12).
func (s *Service) httpValidateRoute(w http.ResponseWriter, r *http.Request, p auth.Principal) {
	if !MayPlan(p.ActiveRole) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	var req struct {
		Date string `json:"date"`
	}
	_ = json.NewDecoder(r.Body).Decode(&req)
	day, err := s.day(r.Context(), req.Date)
	if err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "date must be YYYY-MM-DD"})
		return
	}
	savedPlan, _ := s.loadSavedRoutePlan(r.Context(), p.UserID, day)
	planned, err := plannedDay(r.Context(), s.db, owners(p), day)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not inspect planned activities"})
		return
	}
	reasons := []string{}
	plannedSet := map[string]school{}
	for _, sc := range planned {
		plannedSet[sc.pin.SchoolId] = sc
	}
	if savedPlan != nil {
		savedSet := map[string]bool{}
		for _, sid := range savedPlan.SchoolIDs {
			savedSet[sid] = true
			if _, stillPlanned := plannedSet[sid]; !stillPlanned {
				reasons = append(reasons, fmt.Sprintf("School %s was rescheduled or cancelled in My Plan.", sid))
			}
		}
		for sid, sc := range plannedSet {
			if !savedSet[sid] {
				reasons = append(reasons, fmt.Sprintf("New planned visit added in My Plan: %s.", sc.pin.Name))
			}
		}
	}
	// Check if date falls on Sunday, public holiday, or approved leave.
	calRules := s.loadCalendarRules(r.Context(), p)
	iso := day.Format(time.DateOnly)
	if day.Weekday() == time.Sunday {
		reasons = append(reasons, "Selected planning date is a Sunday (non-working day).")
	}
	for _, h := range calRules.Holidays {
		if h.Date == iso {
			reasons = append(reasons, fmt.Sprintf("Selected date is a public holiday: %s.", h.Name))
		}
	}
	for _, lv := range calRules.ApprovedLeaveDates {
		if lv == iso {
			reasons = append(reasons, "Staff member has approved leave on this date.")
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"date":           iso,
		"stale":          len(reasons) > 0,
		"reasons":        reasons,
		"planned_count":  len(planned),
		"saved_plan":     savedPlan,
		"checked_at":     s.now().UTC().Format(time.RFC3339),
	})
}

func (s *Service) httpListRoadConditions(w http.ResponseWriter, r *http.Request, p auth.Principal) {
	if !MayPlan(p.ActiveRole) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "forbidden"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"reports": s.loadActiveRoadConditions(r.Context()),
	})
}

func (s *Service) httpReportRoadCondition(w http.ResponseWriter, r *http.Request, p auth.Principal, broker *realtime.Broker) {
	if !MayPlan(p.ActiveRole) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "Your active role cannot submit road condition reports."})
		return
	}
	if !s.verifyReady(r.Context()) {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "road condition storage is not ready"})
		return
	}
	var req struct {
		RoadName     string  `json:"road_name"`
		Lat          float64 `json:"lat"`
		Lng          float64 `json:"lng"`
		RadiusMeters int     `json:"radius_meters"`
		Category     string  `json:"category"`
		ImpactLevel  string  `json:"impact_level"`
		Notes        string  `json:"notes"`
		ExpiresHours int     `json:"expires_hours"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid road condition payload"})
		return
	}
	req.RoadName = strings.TrimSpace(req.RoadName)
	if req.RoadName == "" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "road_name is required"})
		return
	}
	if _, st := Locate(nil, nil, &req.Lat, &req.Lng); !Placed(st) {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "coordinates must be a valid location inside Uganda"})
		return
	}
	validCats := map[string]bool{
		"road_closed": true, "road_flooded": true, "bridge_damaged": true,
		"under_construction": true, "poor_condition": true, "severe_congestion": true, "road_reopened": true,
	}
	if !validCats[req.Category] {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid road condition category"})
		return
	}
	if req.ImpactLevel != "advisory" && req.ImpactLevel != "delay" && req.ImpactLevel != "impassable" {
		if req.Category == "road_closed" || req.Category == "bridge_damaged" || req.Category == "road_flooded" {
			req.ImpactLevel = "impassable"
		} else {
			req.ImpactLevel = "delay"
		}
	}
	if req.RadiusMeters < 100 || req.RadiusMeters > 25000 {
		req.RadiusMeters = 1500
	}
	if req.ExpiresHours < 1 || req.ExpiresHours > 720 {
		req.ExpiresHours = 72
	}
	id, err := newID()
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "failed to allocate report id"})
		return
	}
	now := s.now().UTC()
	exp := now.Add(time.Duration(req.ExpiresHours) * time.Hour)
	country := workingCode(p)
	if country == "" {
		country = "UG"
	}

	tx, err := s.verify.db.BeginTx(r.Context(), pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not open transaction"})
		return
	}
	defer func() { _ = tx.Rollback(r.Context()) }()
	// Staff reports ALWAYS start as 'unverified' (Section 7 safety rule).
	_, err = tx.Exec(r.Context(), `
INSERT INTO field_routes.road_condition_report (
  id, road_name, lat, lng, radius_m, category, source, verification_status,
  impact_level, notes, reported_by, reported_by_name, reported_at, expires_at, country_code
) VALUES (
  $1::uuid, $2, $3, $4, $5, $6, 'staff_report', 'unverified',
  $7, $8, $9, $10, $11, $12, COALESCE(NULLIF($13, ''), `+registry.HeldCode+`)
)`, id, req.RoadName, req.Lat, req.Lng, req.RadiusMeters, req.Category,
		req.ImpactLevel, strings.TrimSpace(req.Notes), p.UserID, p.Name, now, exp, country)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not store road condition report"})
		return
	}
	if err := tx.Commit(r.Context()); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not commit road condition report"})
		return
	}
	if broker != nil {
		broker.Publish(realtime.Event{
			Type:        "road_condition.reported",
			EntityType:  "road_condition_report",
			EntityID:    id,
			CountryCode: country,
		})
	}
	writeJSON(w, http.StatusCreated, map[string]any{
		"report": RoadConditionAlert{
			ID:                 id,
			RoadName:           req.RoadName,
			Lat:                req.Lat,
			Lng:                req.Lng,
			RadiusMeters:       req.RadiusMeters,
			Category:           req.Category,
			Source:             "staff_report",
			VerificationStatus: "unverified",
			ImpactLevel:        req.ImpactLevel,
			Notes:              strings.TrimSpace(req.Notes),
			ReportedByName:     p.Name,
			ReportedAt:         now,
			ExpiresAt:          exp,
		},
	})
}

func (s *Service) httpVerifyRoadCondition(w http.ResponseWriter, r *http.Request, p auth.Principal, broker *realtime.Broker) {
	if !MayReview(p.ActiveRole) {
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "Your active role cannot verify road condition reports."})
		return
	}
	if !s.verifyReady(r.Context()) {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "road condition storage is not ready"})
		return
	}
	id := r.PathValue("id")
	var req struct {
		Status string `json:"status"` // verified | resolved | expired
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid payload"})
		return
	}
	if req.Status != "verified" && req.Status != "resolved" && req.Status != "expired" {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "status must be verified, resolved, or expired"})
		return
	}
	now := s.now().UTC()
	tx, err := s.verify.db.BeginTx(r.Context(), pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not open transaction"})
		return
	}
	defer func() { _ = tx.Rollback(r.Context()) }()
	tag, err := tx.Exec(r.Context(), `
UPDATE field_routes.road_condition_report
SET verification_status = $2, reviewed_by = $3, reviewed_at = $4
WHERE id::text = $1`, id, req.Status, p.UserID, now)
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not update road condition report"})
		return
	}
	if tag.RowsAffected() == 0 {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "road condition report not found"})
		return
	}
	if err := tx.Commit(r.Context()); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "could not commit update"})
		return
	}
	if broker != nil {
		broker.Publish(realtime.Event{
			Type:        "road_condition.verified",
			EntityType:  "road_condition_report",
			EntityID:    id,
			CountryCode: workingCode(p),
		})
	}
	writeJSON(w, http.StatusOK, map[string]any{"id": id, "verification_status": req.Status, "reviewed_at": now.Format(time.RFC3339)})
}

// CalendarRulesPayload gives the shared EdifyDatePicker authoritative Uganda FY
// boundaries, public holidays, approved leave, and Sunday/Saturday policy (Section 11).
type CalendarRulesPayload struct {
	CountryCode        string            `json:"country_code"`
	Timezone           string            `json:"timezone"`
	Today              string            `json:"today"`
	CurrentFY          string            `json:"current_fy"`
	FYStart            string            `json:"fy_start"`
	FYEnd              string            `json:"fy_end"`
	SundaysDisabled    bool              `json:"sundays_disabled"`
	SaturdaysEnabled   bool              `json:"saturdays_enabled"`
	Holidays           []HolidayItem     `json:"holidays"`
	ApprovedLeaveDates []string          `json:"approved_leave_dates"`
	BlackoutDates      []string          `json:"blackout_dates"`
}

// HolidayItem is one configured public holiday.
type HolidayItem struct {
	Date string `json:"date"`
	Name string `json:"name"`
}

func (s *Service) loadCalendarRules(ctx context.Context, p auth.Principal) CalendarRulesPayload {
	nowK := s.now().In(kampala)
	fyNum := schooldirectory.OperationalFY(nowK)
	fyYear, _ := strconv.Atoi(fyNum)
	if fyYear == 0 {
		fyYear = nowK.Year()
		if nowK.Month() >= time.October {
			fyYear++
		}
	}
	country := workingCode(p)
	if country == "" {
		country = "UG"
	}
	out := CalendarRulesPayload{
		CountryCode:        country,
		Timezone:           "Africa/Kampala",
		Today:              nowK.Format(time.DateOnly),
		CurrentFY:          fmt.Sprintf("FY%d", fyYear),
		FYStart:            fmt.Sprintf("%04d-10-01", fyYear-1),
		FYEnd:              fmt.Sprintf("%04d-09-30", fyYear),
		SundaysDisabled:    true,
		SaturdaysEnabled:   true,
		Holidays:           []HolidayItem{},
		ApprovedLeaveDates: []string{},
		BlackoutDates:      []string{},
	}
	if s.db == nil {
		return out
	}
	if rows, err := s.db.Query(ctx, `SELECT date::text, name FROM public_holiday ORDER BY date LIMIT 200`); err == nil {
		defer rows.Close()
		for rows.Next() {
			var h HolidayItem
			if rows.Scan(&h.Date, &h.Name) == nil {
				out.Holidays = append(out.Holidays, h)
			}
		}
	}
	staffIDs := owners(p)
	if len(staffIDs) > 0 {
		if rows, err := s.db.Query(ctx, `
SELECT start_date, end_date FROM leave
WHERE staff_id = ANY($1) AND LOWER(status) = 'approved'`, staffIDs); err == nil {
			defer rows.Close()
			seen := map[string]bool{}
			for rows.Next() {
				var st, en string
				if rows.Scan(&st, &en) != nil {
					continue
				}
				d1, err1 := time.Parse(time.DateOnly, strings.TrimSpace(st))
				d2, err2 := time.Parse(time.DateOnly, strings.TrimSpace(en))
				if err1 != nil || err2 != nil || d2.Before(d1) {
					continue
				}
				for cur := d1; !cur.After(d2) && len(seen) < 90; cur = cur.AddDate(0, 0, 1) {
					iso := cur.Format(time.DateOnly)
					if !seen[iso] {
						seen[iso] = true
						out.ApprovedLeaveDates = append(out.ApprovedLeaveDates, iso)
					}
				}
			}
		}
	}
	return out
}

func (s *Service) httpCalendarRules(w http.ResponseWriter, r *http.Request, p auth.Principal) {
	writeJSON(w, http.StatusOK, s.loadCalendarRules(r.Context(), p))
}
