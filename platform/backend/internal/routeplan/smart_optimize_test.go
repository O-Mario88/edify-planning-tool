package routeplan

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	routesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/routes/v1"
)

// mockRoadRouter returns controlled road distances (explicitly different from
// straight-line Haversine) plus road-following polylines, turn-by-turn steps,
// traffic delays, and alternative routes.
type mockRoadRouter struct {
	name             string
	roadMultiplier   float64 // e.g., 2.4x straight-line to simulate river/detour
	trafficState     string
	trafficDelaySec  int64
	alternatives     []AlternativeRoute
	unroutablePoints map[LatLng]bool
}

func (m *mockRoadRouter) Name() string { return m.name }

func (m *mockRoadRouter) Matrix(_ context.Context, pts []LatLng) ([][]Leg, error) {
	out := make([][]Leg, len(pts))
	for i := range pts {
		out[i] = make([]Leg, len(pts))
		for j := range pts {
			if i == j {
				out[i][j] = Leg{Meters: 0, Seconds: 0, OK: true}
				continue
			}
			if m.unroutablePoints[pts[i]] || m.unroutablePoints[pts[j]] {
				out[i][j] = Leg{OK: false}
				continue
			}
			sm := StraightMeters(pts[i], pts[j])
			mult := m.roadMultiplier
			if mult <= 0 {
				mult = 1.6
			}
			rm := int64(float64(sm) * mult)
			sec := int64(float64(rm) / 10.0) // ~36 km/h
			out[i][j] = Leg{Meters: rm, Seconds: sec, OK: true}
		}
	}
	return out, nil
}

func (m *mockRoadRouter) Route(ctx context.Context, pts []LatLng) (Route, error) {
	return m.RouteDetailed(ctx, pts, RouteOptions{IncludeSteps: true, IncludeAlternatives: true, TrafficOptimal: true})
}

func (m *mockRoadRouter) RouteDetailed(_ context.Context, pts []LatLng, _ RouteOptions) (Route, error) {
	if len(pts) < 2 {
		return Route{}, ErrUnavailable
	}
	out := Route{
		TrafficState:    m.trafficState,
		TrafficDelaySec: m.trafficDelaySec,
		Alternatives:    m.alternatives,
		ProviderSource:  m.name,
	}
	if out.TrafficState == "" {
		out.TrafficState = "normal"
	}
	for i := 0; i < len(pts)-1; i++ {
		if m.unroutablePoints[pts[i]] || m.unroutablePoints[pts[i+1]] {
			return Route{}, ErrUnavailable
		}
		sm := StraightMeters(pts[i], pts[i+1])
		mult := m.roadMultiplier
		if mult <= 0 {
			mult = 1.6
		}
		rm := int64(float64(sm) * mult)
		sec := int64(float64(rm)/10.0) + m.trafficDelaySec
		out.Legs = append(out.Legs, Leg{Meters: rm, Seconds: sec, OK: true})
		mid := LatLng{
			Lat: (pts[i].Lat+pts[i+1].Lat)/2 + 0.012, // road bend (never straight line)
			Lng: (pts[i].Lng+pts[i+1].Lng)/2 - 0.008,
		}
		if i == 0 {
			out.Path = append(out.Path, pts[i])
		}
		out.Path = append(out.Path, mid, pts[i+1])
		out.LegSteps = append(out.LegSteps, []Step{
			{
				Instruction:     "Depart east on Kampala–Jinja Highway",
				RoadName:        "Kampala–Jinja Highway",
				Maneuver:        "depart",
				DistanceMeters:  rm / 2,
				DurationSeconds: sec / 2,
				Start:           pts[i],
				End:             mid,
			},
			{
				Instruction:     "Turn right onto School Access Road and arrive",
				RoadName:        "School Access Road",
				Maneuver:        "turn right",
				DistanceMeters:  rm - rm/2,
				DurationSeconds: sec - sec/2,
				Start:           mid,
				End:             pts[i+1],
			},
		})
	}
	return out, nil
}

func makeTestSchool(id, code, name string, lat, lng float64, status string, activityID string) school {
	pin := &routesv1.SchoolPin{
		SchoolId:       id,
		Code:           code,
		Name:           name,
		District:       "Mukono",
		Category:       "Core",
		LocationStatus: status,
		ActivityId:     activityID,
		Status:         "planned",
	}
	var at LatLng
	if Placed(status) {
		at = LatLng{Lat: lat, Lng: lng}
		pin.Point = &routesv1.Point{Lat: lat, Lng: lng}
	}
	return school{pin: pin, at: at}
}

// Test A — Road distance versus straight-line distance (Section 16).
func TestSmartRoute_RoadDistanceVsStraightLine(t *testing.T) {
	now := time.Date(2026, 11, 23, 8, 0, 0, 0, kampala)
	router := &mockRoadRouter{name: "google", roadMultiplier: 2.6, trafficState: "normal"}
	svc := NewService(nil, router, func() time.Time { return now }, slog.New(slog.NewTextHandler(io.Discard, nil)))

	// Two schools ~5 km straight line across river/wetland, ~13 km by road.
	sA := makeTestSchool("sA", "ED-001", "River West Primary", 0.3400, 32.6000, LocationVerified, "act-1")
	sB := makeTestSchool("sB", "ED-002", "River East Primary", 0.3400, 32.6450, LocationVerified, "act-2")

	res := svc.OptimizeSmart(context.Background(), SmartOptimizeInput{
		Date:      "2026-11-23",
		Mode:      SmartModeFastest,
		WorkStart: "08:00",
		WorkEnd:   "17:00",
		Stops: []SmartStopInput{
			{School: sA, PlannedActivityID: "act-1", VisitMinutes: 60, AppointmentMin: -1, Priority: SchoolPriority{Band: "core", Score: 70}},
			{School: sB, PlannedActivityID: "act-2", VisitMinutes: 60, AppointmentMin: -1, Priority: SchoolPriority{Band: "core", Score: 70}},
		},
	})

	if !res.PathIsRoad || !res.Totals.RoadComplete {
		t.Fatalf("expected road-following route, got PathIsRoad=%v RoadComplete=%v", res.PathIsRoad, res.Totals.RoadComplete)
	}
	if len(res.Path) < 3 {
		t.Fatalf("expected road geometry polyline (>=3 points), got %d", len(res.Path))
	}
	if res.Totals.RoadMeters <= res.Totals.StraightMeters*2 {
		t.Fatalf("expected road distance > 2x straight-line: road=%d straight=%d", res.Totals.RoadMeters, res.Totals.StraightMeters)
	}
	if len(res.Stops[1].Steps) < 2 {
		t.Fatalf("expected turn-by-turn steps on leg, got %d", len(res.Stops[1].Steps))
	}
}

// Test B — Five-school optimization across all 5 modes (Section 16).
func TestSmartRoute_FiveSchoolOptimizationAllModes(t *testing.T) {
	now := time.Date(2026, 11, 23, 8, 0, 0, 0, kampala)
	router := &mockRoadRouter{name: "google", roadMultiplier: 1.5, trafficState: "normal"}
	svc := NewService(nil, router, func() time.Time { return now }, slog.New(slog.NewTextHandler(io.Discard, nil)))

	start := LatLng{0.3136, 32.5811} // Kampala
	// Deliberately scrambled order (East -> West -> Far East -> Close North -> Far South)
	stops := []SmartStopInput{
		{School: makeTestSchool("s1", "ED-101", "Mukono East", 0.3550, 32.7550, LocationVerified, "a1"), PlannedActivityID: "a1", VisitMinutes: 60, AppointmentMin: -1, Priority: SchoolPriority{Band: "routine", Score: 40, Reason: "Routine"}},
		{School: makeTestSchool("s2", "ED-102", "Wakiso West", 0.3900, 32.4700, LocationVerified, "a2"), PlannedActivityID: "a2", VisitMinutes: 60, AppointmentMin: -1, Priority: SchoolPriority{Band: "critical", Score: 100, Reason: "Critical SSA 3.2/10"}},
		{School: makeTestSchool("s3", "ED-103", "Lugazi Far East", 0.3700, 32.9200, LocationVerified, "a3"), PlannedActivityID: "a3", VisitMinutes: 60, AppointmentMin: -1, Priority: SchoolPriority{Band: "high", Score: 85, Reason: "High SSA need"}},
		{School: makeTestSchool("s4", "ED-104", "Gayaza North", 0.4500, 32.6100, LocationVerified, "a4"), PlannedActivityID: "a4", VisitMinutes: 60, AppointmentMin: -1, Priority: SchoolPriority{Band: "core", Score: 72, Reason: "Core School"}},
		{School: makeTestSchool("s5", "ED-105", "Entebbe South", 0.0640, 32.4460, LocationVerified, "a5"), PlannedActivityID: "a5", VisitMinutes: 60, AppointmentMin: -1, Priority: SchoolPriority{Band: "routine", Score: 35, Reason: "Routine"}},
	}

	for _, mode := range []string{SmartModeFastest, SmartModeShortest, SmartModeMaxSchools, SmartModePrioritySchools, SmartModeBalanced} {
		res := svc.OptimizeSmart(context.Background(), SmartOptimizeInput{
			Date:         "2026-11-23",
			Mode:         mode,
			Start:        &start,
			StartLabel:   "Kampala Office",
			WorkStart:    "08:00",
			WorkEnd:      "17:00",
			BreakMinutes: 30,
			Stops:        stops,
		})
		if len(res.Stops) == 0 {
			t.Fatalf("mode %s returned 0 stops", mode)
		}
		if !res.PathIsRoad {
			t.Fatalf("mode %s missing road polyline", mode)
		}
		if mode == SmartModeFastest || mode == SmartModeShortest {
			if res.Totals.RoadMeters >= res.Baseline.RoadMeters {
				t.Errorf("mode %s did not improve over scrambled baseline: opt=%d base=%d", mode, res.Totals.RoadMeters, res.Baseline.RoadMeters)
			}
		}
		// Verify PlannedActivityID preservation on every stop.
		for _, st := range res.Stops {
			if st.PlannedActivityID == "" {
				t.Errorf("mode %s lost PlannedActivityID on stop %s", mode, st.SchoolID)
			}
		}
	}

	// Tight working day (4h) with PrioritySchools must keep Critical school s2 over routine schools.
	tight := svc.OptimizeSmart(context.Background(), SmartOptimizeInput{
		Date:         "2026-11-23",
		Mode:         SmartModePrioritySchools,
		Start:        &start,
		WorkStart:    "08:00",
		WorkEnd:      "12:30",
		BreakMinutes: 30,
		Stops:        stops,
	})
	foundCritical := false
	for _, st := range tight.Stops {
		if st.SchoolID == "s2" {
			foundCritical = true
		}
	}
	if !foundCritical {
		t.Fatalf("priority_schools mode dropped critical SSA school s2; stops=%+v", tight.Stops)
	}
	if len(tight.Excluded) == 0 {
		t.Fatalf("expected tight 4h window to exclude overflow schools with explicit reasons")
	}
}

// Test C, D, E — Traffic delay, verified/unverified road closures, missing GPS, and no-provider honesty.
func TestSmartRoute_TrafficClosuresAndMissingGPS(t *testing.T) {
	now := time.Date(2026, 11, 23, 8, 0, 0, 0, kampala)
	router := &mockRoadRouter{
		name:            "google",
		roadMultiplier:  1.4,
		trafficState:    "traffic_jam",
		trafficDelaySec: 1200,
		alternatives: []AlternativeRoute{
			{ID: "alt-1", Summary: "Northern Bypass", Meters: 18500, Seconds: 1620, TrafficState: "slow"},
		},
	}
	svc := NewService(nil, router, func() time.Time { return now }, slog.New(slog.NewTextHandler(io.Discard, nil)))

	s1 := makeTestSchool("s1", "ED-1", "Kampala School A", 0.3400, 32.6000, LocationVerified, "a1")
	s2 := makeTestSchool("s2", "ED-2", "Mukono School B", 0.3533, 32.7553, LocationVerified, "a2")
	sMissing := makeTestSchool("s3", "ED-3", "No GPS School C", 0, 0, LocationMissing, "a3")

	closure := RoadConditionAlert{
		ID:                 "rc-1",
		RoadName:           "Jinja Road Bridge",
		Lat:                0.3580,
		Lng:                32.6700,
		RadiusMeters:       3000,
		Category:           "road_closed",
		Source:             "staff_report",
		VerificationStatus: "verified",
		ImpactLevel:        "impassable",
		ReportedAt:         now.Add(-1 * time.Hour),
		ExpiresAt:          now.Add(24 * time.Hour),
	}

	res := svc.OptimizeSmart(context.Background(), SmartOptimizeInput{
		Date:           "2026-11-23",
		Mode:           SmartModeBalanced,
		WorkStart:      "08:00",
		WorkEnd:        "17:00",
		RoadConditions: []RoadConditionAlert{closure},
		Stops: []SmartStopInput{
			{School: s1, PlannedActivityID: "a1", VisitMinutes: 60, AppointmentMin: -1},
			{School: s2, PlannedActivityID: "a2", VisitMinutes: 60, AppointmentMin: -1},
			{School: sMissing, PlannedActivityID: "a3", VisitMinutes: 60, AppointmentMin: -1},
		},
	})

	if res.Totals.TrafficState != "traffic_jam" || res.Totals.TrafficDelaySec != 1200 {
		t.Fatalf("expected traffic_jam with 1200s delay, got %s (%ds)", res.Totals.TrafficState, res.Totals.TrafficDelaySec)
	}
	if len(res.Alternatives) != 1 || res.Alternatives[0].Summary != "Northern Bypass" {
		t.Fatalf("expected 1 alternative route, got %+v", res.Alternatives)
	}
	if len(res.RoadAlerts) != 1 || res.RoadAlerts[0].RoadName != "Jinja Road Bridge" {
		t.Fatalf("expected verified road closure warning matched on route, got %+v", res.RoadAlerts)
	}
	if len(res.Excluded) != 1 || res.Excluded[0].SchoolID != "s3" || res.Excluded[0].ReasonCode != "missing_gps" {
		t.Fatalf("expected missing GPS school excluded honestly without inventing location, got %+v", res.Excluded)
	}

	// Verify None provider NEVER draws a straight line as a road path.
	noneSvc := NewService(nil, None{}, func() time.Time { return now }, slog.New(slog.NewTextHandler(io.Discard, nil)))
	noneRes := noneSvc.OptimizeSmart(context.Background(), SmartOptimizeInput{
		Date: "2026-11-23",
		Mode: SmartModeFastest,
		Stops: []SmartStopInput{
			{School: s1, PlannedActivityID: "a1", VisitMinutes: 60, AppointmentMin: -1},
			{School: s2, PlannedActivityID: "a2", VisitMinutes: 60, AppointmentMin: -1},
		},
	})
	if noneRes.PathIsRoad || len(noneRes.Path) != 0 {
		t.Fatalf("None provider must never fabricate a straight-line road path: PathIsRoad=%v len=%d", noneRes.PathIsRoad, len(noneRes.Path))
	}
}

// Test Google Routes API v2 multi-stage compliance: Stage 1 optimizeWaypointOrder
// MUST NOT combine TRAFFIC_AWARE_OPTIMAL; Stage 2 RouteDetailed uses TRAFFIC_AWARE_OPTIMAL,
// TRAFFIC_ON_POLYLINE, steps, and alternatives.
func TestGoogleRoutesV2_MultiStageCompliance(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		if opt, _ := body["optimizeWaypointOrder"].(bool); opt {
			if body["routingPreference"] == "TRAFFIC_AWARE_OPTIMAL" {
				t.Errorf("VIOLATION: optimizeWaypointOrder combined with TRAFFIC_AWARE_OPTIMAL")
			}
			_, _ = w.Write([]byte(`{"routes":[{"optimizedIntermediateWaypointIndex":[1,0]}]}`))
			return
		}
		if body["routingPreference"] != "TRAFFIC_AWARE_OPTIMAL" {
			t.Errorf("Stage 2 expected TRAFFIC_AWARE_OPTIMAL, got %v", body["routingPreference"])
		}
		if !strings.Contains(r.Header.Get("X-Goog-FieldMask"), "navigationInstruction") {
			t.Errorf("Stage 2 missing step instructions field mask: %s", r.Header.Get("X-Goog-FieldMask"))
		}
		_, _ = w.Write([]byte(`{
			"routes": [
				{
					"description": "Kampala–Jinja Hwy",
					"distanceMeters": 17200,
					"duration": "2400s",
					"staticDuration": "1500s",
					"travelAdvisory": {"speedReadingIntervals": [{"startPolylinePointIndex":0,"endPolylinePointIndex":2,"speed":"TRAFFIC_JAM"}]},
					"legs": [{
						"distanceMeters": 17200,
						"duration": "2400s",
						"staticDuration": "1500s",
						"steps": [{"distanceMeters": 17200, "staticDuration": "1500s", "navigationInstruction": {"maneuver": "TURN_RIGHT", "instructions": "Turn right onto Jinja Road"}}]
					}],
					"polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC_mqNvxq` + "`" + `@"}
				},
				{
					"description": "Northern Bypass",
					"distanceMeters": 20100,
					"duration": "1950s",
					"staticDuration": "1800s",
					"legs": [{"distanceMeters": 20100, "duration": "1950s", "staticDuration": "1800s"}],
					"polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC_mqNvxq` + "`" + `@"}
				}
			]
		}`))
	}))
	defer srv.Close()

	g := Google{Key: "test-key", Base: srv.URL}
	order, err := g.OptimizeWaypointOrder(context.Background(), LatLng{0.31, 32.58}, LatLng{0.36, 32.75}, []LatLng{{0.33, 32.62}, {0.34, 32.68}})
	if err != nil || len(order) != 2 || order[0] != 1 {
		t.Fatalf("Stage 1 OptimizeWaypointOrder failed: %v %v", order, err)
	}
	r, err := g.RouteDetailed(context.Background(), []LatLng{{0.31, 32.58}, {0.36, 32.75}}, RouteOptions{
		IncludeSteps:        true,
		IncludeAlternatives: true,
		TrafficOptimal:      true,
	})
	if err != nil {
		t.Fatalf("Stage 2 RouteDetailed failed: %v", err)
	}
	if r.TrafficState != "traffic_jam" || r.TrafficDelaySec != 900 {
		t.Fatalf("expected traffic_jam delay 900s, got %s %ds", r.TrafficState, r.TrafficDelaySec)
	}
	if len(r.LegSteps) != 1 || len(r.LegSteps[0]) != 1 || !strings.Contains(r.LegSteps[0][0].Instruction, "Jinja Road") {
		t.Fatalf("expected turn-by-turn steps, got %+v", r.LegSteps)
	}
	if len(r.Alternatives) != 1 || r.Alternatives[0].Summary != "Northern Bypass" {
		t.Fatalf("expected 1 alternative route, got %+v", r.Alternatives)
	}
}
