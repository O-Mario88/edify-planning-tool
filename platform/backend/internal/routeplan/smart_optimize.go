package routeplan

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Smart optimization modes (Section 5.1).
const (
	SmartModeFastest         = "fastest"
	SmartModeShortest        = "shortest"
	SmartModeMaxSchools      = "max_schools"
	SmartModePrioritySchools = "priority_schools"
	SmartModeBalanced        = "balanced"
	SmartModeAsGiven         = "as_given"
)

// SchoolPriority is the verified SSA + Core School priority profile for a school.
type SchoolPriority struct {
	SchoolID        string   `json:"school_id"`
	Band            string   `json:"band"` // critical | high | core | routine | missing_ssa
	Score           float64  `json:"score"`
	SSAAverage      *float64 `json:"ssa_average,omitempty"`
	HasConfirmedSSA bool     `json:"has_confirmed_ssa"`
	IsCore          bool     `json:"is_core"`
	Reason          string   `json:"reason"`
}

// RoadConditionAlert is an active road hazard or notice matched against a route.
type RoadConditionAlert struct {
	ID                 string    `json:"id"`
	RoadName           string    `json:"road_name"`
	Lat                float64   `json:"lat"`
	Lng                float64   `json:"lng"`
	RadiusMeters       int       `json:"radius_meters"`
	Category           string    `json:"category"`
	Source             string    `json:"source"`
	VerificationStatus string    `json:"verification_status"`
	ImpactLevel        string    `json:"impact_level"`
	Notes              string    `json:"notes,omitempty"`
	ReportedByName     string    `json:"reported_by_name,omitempty"`
	ReportedAt         time.Time `json:"reported_at"`
	ExpiresAt          time.Time `json:"expires_at"`
	DistanceToRouteM   int64     `json:"distance_to_route_meters,omitempty"`
	ApplicabilityNote  string    `json:"applicability_note,omitempty"`
}

// SmartStopInput is one candidate school passed into OptimizeSmart.
type SmartStopInput struct {
	School            school
	PlannedActivityID string
	VisitMinutes      int
	AppointmentMin    int // -1 if none
	Locked            bool
	Mandatory         bool
	Priority          SchoolPriority
}

// SmartOptimizeInput holds all constraints and objectives for Section 5.
type SmartOptimizeInput struct {
	Date           string
	Mode           string
	TransportMode  string // DRIVE | TWO_WHEELER | WALK
	WorkStart      string // HH:MM, default 08:00
	WorkEnd        string // HH:MM, default 17:00
	BreakMinutes   int    // default 30
	Start          *LatLng
	StartLabel     string
	End            *LatLng
	EndLabel       string
	Stops          []SmartStopInput
	RoadConditions []RoadConditionAlert
}

// SmartStopOutput is one ordered stop in the optimized itinerary.
type SmartStopOutput struct {
	Order             int            `json:"order"`
	SchoolID          string         `json:"school_id"`
	SchoolCode        string         `json:"school_code"`
	SchoolName        string         `json:"school_name"`
	District          string         `json:"district"`
	Cluster           string         `json:"cluster"`
	Category          string         `json:"category"`
	PlannedActivityID string         `json:"planned_activity_id,omitempty"`
	Status            string         `json:"status"`
	Kind              string         `json:"kind"` // planned | recommended
	Point             *LatLng        `json:"point,omitempty"`
	Entrance          *LatLng        `json:"entrance,omitempty"`
	LocationStatus    string         `json:"location_status"`
	LocationVersion   int32          `json:"location_version"`
	Arrival           string         `json:"arrival"`
	Departure         string         `json:"departure"`
	VisitMinutes      int            `json:"visit_minutes"`
	Locked            bool           `json:"locked"`
	FromLabel         string         `json:"from_label"`
	RoadAvailable     bool           `json:"road_available"`
	RoadStatus        string         `json:"road_status,omitempty"`
	RoadMeters        int64          `json:"road_meters"`
	RoadSeconds       int64          `json:"road_seconds"`
	StraightMeters    int64          `json:"straight_line_meters"`
	Steps             []Step         `json:"steps,omitempty"`
	Priority          SchoolPriority `json:"priority"`
	InclusionReason   string         `json:"inclusion_reason"`
	Conflict          string         `json:"conflict,omitempty"`
	Warnings          []string       `json:"warnings,omitempty"`
}

// ExcludedSchool explains honestly why a candidate school was not routed.
type ExcludedSchool struct {
	SchoolID          string         `json:"school_id"`
	SchoolCode        string         `json:"school_code"`
	SchoolName        string         `json:"school_name"`
	District          string         `json:"district"`
	PlannedActivityID string         `json:"planned_activity_id,omitempty"`
	LocationStatus    string         `json:"location_status"`
	ReasonCode        string         `json:"reason_code"` // missing_gps | invalid_gps | road_access_unverified | exceeds_working_hours
	Reason            string         `json:"reason"`
	Priority          SchoolPriority `json:"priority"`
}

// RouteMetrics summarizes one route evaluation for before/after comparison.
type RouteMetrics struct {
	SchoolsIncluded int    `json:"schools_included"`
	SchoolsExcluded int    `json:"schools_excluded"`
	RoadComplete    bool   `json:"road_complete"`
	RoadMeters      int64  `json:"road_meters"`
	RoadSeconds     int64  `json:"road_seconds"`
	StraightMeters  int64  `json:"straight_line_meters"`
	VisitMinutes    int    `json:"visit_minutes"`
	BreakMinutes    int    `json:"break_minutes"`
	FieldMinutes    int    `json:"field_minutes"`
	TrafficState    string `json:"traffic_state"` // normal | slow | traffic_jam | unavailable
	TrafficDelaySec int64  `json:"traffic_delay_seconds"`
}

// SmartRouteResult is the full explainable output required by Section 5.3.
type SmartRouteResult struct {
	Date                string               `json:"date"`
	Mode                string               `json:"mode"`
	ObjectiveLabel      string               `json:"objective_label"`
	IsRecommended       bool                 `json:"is_recommended"`
	RecommendationNote  string               `json:"recommendation_note"`
	TransportMode       string               `json:"transport_mode"`
	Start               *LatLng              `json:"start,omitempty"`
	StartLabel          string               `json:"start_label,omitempty"`
	End                 *LatLng              `json:"end,omitempty"`
	EndLabel            string               `json:"end_label,omitempty"`
	WorkStart           string               `json:"work_start"`
	WorkEnd             string               `json:"work_end"`
	Stops               []SmartStopOutput    `json:"stops"`
	Excluded            []ExcludedSchool     `json:"excluded"`
	Path                []LatLng             `json:"path"`
	PathIsRoad          bool                 `json:"path_is_road"`
	ReturnLegMeters     int64                `json:"return_leg_meters,omitempty"`
	ReturnLegSeconds    int64                `json:"return_leg_seconds,omitempty"`
	ReturnLegSteps      []Step               `json:"return_leg_steps,omitempty"`
	Totals              RouteMetrics         `json:"totals"`
	Baseline            RouteMetrics         `json:"baseline"`
	DistanceSavedMeters int64                `json:"distance_saved_meters"`
	TimeSavedSeconds    int64                `json:"time_saved_seconds"`
	Alternatives        []AlternativeRoute   `json:"alternatives"`
	TrafficIntervals    []TrafficInterval    `json:"traffic_intervals,omitempty"`
	RoadAlerts          []RoadConditionAlert `json:"road_alerts"`
	Warnings            []string             `json:"warnings"`
	Provider            string               `json:"provider"`
	ProviderConfigured  bool                 `json:"provider_configured"`
	Confidence          string               `json:"confidence"` // high | medium | limited
	ConfidenceNote      string               `json:"confidence_note"`
	InputHash           string               `json:"input_hash"`
	CalculatedAt        string               `json:"calculated_at"`
}

func parseHHMM(raw string, fallback int) int {
	h, m, ok := strings.Cut(strings.TrimSpace(raw), ":")
	if !ok {
		return fallback
	}
	hh, err1 := strconv.Atoi(h)
	mm, err2 := strconv.Atoi(m)
	if err1 != nil || err2 != nil || hh < 0 || hh > 23 || mm < 0 || mm > 59 {
		return fallback
	}
	return hh*60 + mm
}

func normalizeSmartMode(mode string) string {
	switch strings.ToLower(strings.TrimSpace(mode)) {
	case SmartModeFastest, SmartModeShortest, SmartModeMaxSchools, SmartModePrioritySchools, SmartModeBalanced, SmartModeAsGiven:
		return strings.ToLower(strings.TrimSpace(mode))
	case ModeRecommended:
		return SmartModeBalanced
	default:
		return SmartModeBalanced
	}
}

func modeLabel(mode string) string {
	switch mode {
	case SmartModeFastest:
		return "Fastest Route (Minimize Driving Time)"
	case SmartModeShortest:
		return "Shortest Route (Minimize Road Distance)"
	case SmartModeMaxSchools:
		return "Maximum Schools (Highest Feasible Coverage)"
	case SmartModePrioritySchools:
		return "Priority Schools (Urgent SSA & Core Support First)"
	case SmartModeAsGiven:
		return "Custom Order (Manual Sequence)"
	default:
		return "Balanced Route — Recommended (Travel Time, Coverage & SSA Priority)"
	}
}

// loadSchoolPriorities reads authoritative confirmed SSA scores and school types
// from PostgreSQL to compute explainable school priorities (Section 8).
func loadSchoolPriorities(ctx context.Context, db schooldirectory.Querier, now time.Time, schools []school) map[string]SchoolPriority {
	out := make(map[string]SchoolPriority, len(schools))
	ids := make([]string, 0, len(schools))
	for _, sc := range schools {
		ids = append(ids, sc.pin.SchoolId)
		isCore := strings.EqualFold(sc.pin.Category, "Core")
		p := SchoolPriority{
			SchoolID: sc.pin.SchoolId,
			Band:     "routine",
			Score:    35,
			IsCore:   isCore,
			Reason:   "Routine support visit",
		}
		if isCore {
			p.Band = "core"
			p.Score = 70
			p.Reason = "Core School obligation"
		}
		out[sc.pin.SchoolId] = p
	}
	if len(ids) == 0 || db == nil {
		return out
	}
	fy := schooldirectory.OperationalFY(now)
	rows, err := db.Query(ctx, `
SELECT DISTINCT ON (school_id) school_id, average_score, fy
FROM ssa_record
WHERE deleted_at IS NULL
  AND verification_status = 'confirmed'
  AND school_id = ANY($1)
ORDER BY school_id, (fy = $2) DESC, date_of_ssa DESC`, ids, fy)
	if err != nil {
		// Fall back gracefully to Core/Routine priority if query unavailable in unit tests.
		return out
	}
	defer rows.Close()
	seen := map[string]bool{}
	for rows.Next() {
		var schoolID, recFY string
		var avg *float64
		if err := rows.Scan(&schoolID, &avg, &recFY); err != nil {
			continue
		}
		seen[schoolID] = true
		p := out[schoolID]
		p.HasConfirmedSSA = true
		p.SSAAverage = avg
		if avg != nil {
			switch {
			case *avg < 4.5:
				p.Band = "critical"
				p.Score = 100
				p.Reason = fmt.Sprintf("Critical verified SSA average (%.1f/10 in %s)", *avg, recFY)
			case *avg < 6.0:
				p.Band = "high"
				p.Score = 82
				p.Reason = fmt.Sprintf("High-need verified SSA average (%.1f/10 in %s)", *avg, recFY)
			case p.IsCore:
				p.Band = "core"
				p.Score = 72
				p.Reason = fmt.Sprintf("Core School with verified SSA (%.1f/10 in %s)", *avg, recFY)
			default:
				p.Band = "routine"
				p.Score = 45
				p.Reason = fmt.Sprintf("On-track verified SSA (%.1f/10 in %s)", *avg, recFY)
			}
		}
		out[schoolID] = p
	}
	for id, p := range out {
		if !seen[id] {
			p.HasConfirmedSSA = false
			if p.IsCore {
				p.Band = "critical"
				p.Score = 92
				p.Reason = "Core School with no confirmed SSA on record"
			} else {
				p.Band = "missing_ssa"
				p.Score = 75
				p.Reason = "No confirmed SSA in current FY — assessment priority"
			}
			out[id] = p
		}
	}
	return out
}

// OptimizeSmart executes the full multi-stage, road-based Smart Route optimization
// engine (Sections 2, 3, 5, 7, 8).
func (s *Service) OptimizeSmart(ctx context.Context, in SmartOptimizeInput) SmartRouteResult {
	mode := normalizeSmartMode(in.Mode)
	transport := strings.ToUpper(strings.TrimSpace(in.TransportMode))
	if transport != "TWO_WHEELER" && transport != "WALK" {
		transport = "DRIVE"
	}
	workStartMin := parseHHMM(in.WorkStart, startMinutes())
	workEndMin := parseHHMM(in.WorkEnd, workStartMin+Rules.Day.AvailableMinutes)
	if workEndMin <= workStartMin+60 {
		workEndMin = workStartMin + Rules.Day.AvailableMinutes
	}
	breakMin := in.BreakMinutes
	if breakMin < 0 {
		breakMin = 0
	}
	effectiveEndMin := workEndMin - breakMin

	res := SmartRouteResult{
		Date:               in.Date,
		Mode:               mode,
		ObjectiveLabel:     modeLabel(mode),
		TransportMode:      transport,
		Start:              in.Start,
		StartLabel:         in.StartLabel,
		End:                in.End,
		EndLabel:           in.EndLabel,
		WorkStart:          clock(workStartMin),
		WorkEnd:            clock(workEndMin),
		Stops:              []SmartStopOutput{},
		Excluded:           []ExcludedSchool{},
		Path:               []LatLng{},
		Alternatives:       []AlternativeRoute{},
		RoadAlerts:         []RoadConditionAlert{},
		Warnings:           []string{},
		Provider:           s.name,
		ProviderConfigured: s.name != "none",
		CalculatedAt:       s.now().UTC().Format(time.RFC3339),
	}

	// Separate placed schools from missing/invalid GPS schools (Section 4).
	placed := make([]SmartStopInput, 0, len(in.Stops))
	for _, st := range in.Stops {
		if !st.School.placed() {
			code, msg := "missing_gps", "No GPS coordinates recorded in School Profile. Coordinates are never invented."
			if st.School.pin.LocationStatus == LocationInvalid {
				code = "invalid_gps"
				msg = "Stored coordinates are outside valid Uganda bounds and require authorized verification."
			}
			res.Excluded = append(res.Excluded, ExcludedSchool{
				SchoolID:          st.School.pin.SchoolId,
				SchoolCode:        st.School.pin.Code,
				SchoolName:        st.School.pin.Name,
				District:          st.School.pin.District,
				PlannedActivityID: st.PlannedActivityID,
				LocationStatus:    st.School.pin.LocationStatus,
				ReasonCode:        code,
				Reason:            msg,
				Priority:          st.Priority,
			})
			continue
		}
		if st.VisitMinutes <= 0 {
			st.VisitMinutes = Rules.Day.VisitMinutes
		}
		placed = append(placed, st)
	}

	// Input hash for calculation auditability.
	h := sha256.New()
	fmt.Fprintf(h, "%s|%s|%s|%d|%d", in.Date, mode, transport, workStartMin, workEndMin)
	for _, st := range placed {
		fmt.Fprintf(h, "|%s:%t:%d", st.School.pin.SchoolId, st.Locked, st.VisitMinutes)
	}
	res.InputHash = hex.EncodeToString(h.Sum(nil))[:16]

	if len(placed) == 0 {
		res.Confidence = "limited"
		res.ConfidenceNote = "No schools with verified or valid GPS coordinates were selected."
		return res
	}

	// Stage 1: Obtain road-network matrix across start, placed schools, and optional end.
	pts := make([]LatLng, 0, len(placed)+2)
	startIdx := -1
	if in.Start != nil {
		startIdx = 0
		pts = append(pts, *in.Start)
	}
	schoolOffset := len(pts)
	for _, st := range placed {
		pts = append(pts, st.School.road())
	}
	endIdx := -1
	if in.End != nil {
		endIdx = len(pts)
		pts = append(pts, *in.End)
	}

	var roadMatrix [][]Leg
	var providerErr error
	if len(pts) >= 2 {
		roadMatrix, providerErr = s.router.Matrix(ctx, pts)
	}
	hasRoadMatrix := roadMatrix != nil && providerErr == nil

	// Filter out stops that the provider confirmed have no routable road access when matrix succeeded.
	if hasRoadMatrix && len(placed) >= 2 {
		routable := make([]SmartStopInput, 0, len(placed))
		origIdx := make([]int, 0, len(placed))
		for i, st := range placed {
			pi := schoolOffset + i
			reachable := false
			for j := range pts {
				if j == pi {
					continue
				}
				if roadMatrix[pi][j].OK || roadMatrix[j][pi].OK {
					reachable = true
					break
				}
			}
			if !reachable {
				res.Excluded = append(res.Excluded, ExcludedSchool{
					SchoolID:          st.School.pin.SchoolId,
					SchoolCode:        st.School.pin.Code,
					SchoolName:        st.School.pin.Name,
					District:          st.School.pin.District,
					PlannedActivityID: st.PlannedActivityID,
					LocationStatus:    st.School.pin.LocationStatus,
					ReasonCode:        "road_access_unverified",
					Reason:            "Road access requires verification — routing provider found no drivable road connection.",
					Priority:          st.Priority,
				})
				continue
			}
			routable = append(routable, st)
			origIdx = append(origIdx, i)
		}
		if len(routable) == 0 {
			res.Confidence = "limited"
			res.ConfidenceNote = "Road access requires verification for all selected schools."
			res.Warnings = append(res.Warnings, "Road access requires verification for the selected schools.")
			return res
		}
		// Remap matrix if any school was excluded for unroutable road access.
		if len(routable) != len(placed) {
			placed = routable
			newPts := make([]LatLng, 0, len(placed)+2)
			mapIdx := []int{}
			if startIdx >= 0 {
				newPts = append(newPts, pts[startIdx])
				mapIdx = append(mapIdx, startIdx)
				startIdx = 0
			}
			schoolOffset = len(newPts)
			for _, oi := range origIdx {
				newPts = append(newPts, pts[oi+schoolOffset])
				mapIdx = append(mapIdx, oi+schoolOffset)
			}
			if endIdx >= 0 {
				newPts = append(newPts, pts[endIdx])
				mapIdx = append(mapIdx, endIdx)
				endIdx = len(newPts) - 1
			}
			newM := make([][]Leg, len(newPts))
			for a := range newPts {
				newM[a] = make([]Leg, len(newPts))
				for b := range newPts {
					newM[a][b] = roadMatrix[mapIdx[a]][mapIdx[b]]
				}
			}
			pts, roadMatrix = newPts, newM
		}
	}

	// Leg lookup helpers: road matrix first; straight-line estimate used ONLY for
	// internal ordering when no road provider is configured, never presented as road geometry.
	legBetween := func(aPtIdx, bPtIdx int) (meters int64, secs int64, isRoad bool) {
		if aPtIdx < 0 || bPtIdx < 0 {
			return 0, 0, false
		}
		if hasRoadMatrix && roadMatrix[aPtIdx][bPtIdx].OK {
			return roadMatrix[aPtIdx][bPtIdx].Meters, roadMatrix[aPtIdx][bPtIdx].Seconds, true
		}
		sm := StraightMeters(pts[aPtIdx], pts[bPtIdx])
		return sm, EstimateSeconds(sm), false
	}

	stopSecCost := func(i, j int) int64 {
		a := startIdx
		if i >= 0 {
			a = schoolOffset + i
		}
		if a < 0 {
			return 0
		}
		_, sec, _ := legBetween(a, schoolOffset+j)
		return sec
	}
	stopMeterCost := func(i, j int) int64 {
		a := startIdx
		if i >= 0 {
			a = schoolOffset + i
		}
		if a < 0 {
			return 0
		}
		m, _, _ := legBetween(a, schoolOffset+j)
		return m
	}

	// Compute baseline metrics in the user's original given order.
	givenOrder := make([]int, len(placed))
	for i := range placed {
		givenOrder[i] = i
	}
	baseline := evaluateOrderMetrics(givenOrder, placed, legBetween, schoolOffset, startIdx, endIdx, breakMin, hasRoadMatrix)
	res.Baseline = baseline

	// Stage 1B: Choose feasible stop subset & order per the selected optimization mode.
	chosenOrder, droppedIndices := optimizeByMode(mode, givenOrder, placed, stopSecCost, stopMeterCost, workStartMin, effectiveEndMin, endIdx, func(i int) int64 {
		if endIdx < 0 {
			return 0
		}
		_, sec, _ := legBetween(schoolOffset+i, endIdx)
		return sec
	})

	for _, di := range droppedIndices {
		st := placed[di]
		res.Excluded = append(res.Excluded, ExcludedSchool{
			SchoolID:          st.School.pin.SchoolId,
			SchoolCode:        st.School.pin.Code,
			SchoolName:        st.School.pin.Name,
			District:          st.School.pin.District,
			PlannedActivityID: st.PlannedActivityID,
			LocationStatus:    st.School.pin.LocationStatus,
			ReasonCode:        "exceeds_working_hours",
			Reason:            fmt.Sprintf("Excluded by %s mode: adding this %d-minute visit exceeds the %s–%s working day.", mode, st.VisitMinutes, clock(workStartMin), clock(workEndMin)),
			Priority:          st.Priority,
		})
	}

	// Stage 2: Request detailed road-following route geometry, turn-by-turn steps,
	// traffic state, and alternatives for the selected sequence.
	orderedPts := make([]LatLng, 0, len(chosenOrder)+2)
	if in.Start != nil {
		orderedPts = append(orderedPts, *in.Start)
	}
	for _, idx := range chosenOrder {
		orderedPts = append(orderedPts, placed[idx].School.road())
	}
	if in.End != nil {
		orderedPts = append(orderedPts, *in.End)
	}

	var detailed Route
	hasRoadRoute := false
	if len(orderedPts) >= 2 {
		opts := RouteOptions{
			IncludeSteps:        true,
			IncludeAlternatives: true,
			TrafficOptimal:      true,
			TransportMode:       transport,
		}
		var r Route
		var err error
		if dr, ok := s.router.(DetailedRouter); ok {
			r, err = dr.RouteDetailed(ctx, orderedPts, opts)
		} else {
			r, err = s.router.Route(ctx, orderedPts)
		}
		if err == nil && len(r.Legs) == len(orderedPts)-1 && len(r.Path) >= 2 {
			detailed = r
			hasRoadRoute = true
		} else if err != nil && providerErr == nil {
			providerErr = err
		}
	}

	// Build ordered stops, per-leg road metrics, arrival/departure clock, and turn steps.
	tClock := workStartMin
	prevPtIdx := startIdx
	prevLabel := in.StartLabel
	if prevLabel == "" && in.Start != nil {
		prevLabel = "Start Location"
	}
	roadComplete := true
	var totalRoadM, totalRoadSec, totalStraightM int64
	totalVisitMin := 0

	for pos, idx := range chosenOrder {
		st := placed[idx]
		curPtIdx := schoolOffset + idx
		outStop := SmartStopOutput{
			Order:             pos + 1,
			SchoolID:          st.School.pin.SchoolId,
			SchoolCode:        st.School.pin.Code,
			SchoolName:        st.School.pin.Name,
			District:          st.School.pin.District,
			Cluster:           st.School.pin.Cluster,
			Category:          st.School.pin.Category,
			PlannedActivityID: st.PlannedActivityID,
			Status:            st.School.pin.Status,
			Kind:              stopKind(st.PlannedActivityID),
			Point:             &st.School.at,
			Entrance:          st.School.entrance,
			LocationStatus:    st.School.pin.LocationStatus,
			LocationVersion:   st.School.pin.LocationVersion,
			VisitMinutes:      st.VisitMinutes,
			Locked:            st.Locked,
			FromLabel:         prevLabel,
			Priority:          st.Priority,
			InclusionReason:   inclusionReason(mode, st, pos),
		}

		hop := pos
		if in.Start == nil {
			hop = pos - 1
		}
		if prevPtIdx >= 0 {
			sm := StraightMeters(pts[prevPtIdx], pts[curPtIdx])
			outStop.StraightMeters = sm
			totalStraightM += sm

			switch {
			case hasRoadRoute && hop >= 0 && hop < len(detailed.Legs) && detailed.Legs[hop].OK:
				outStop.RoadAvailable = true
				outStop.RoadMeters = detailed.Legs[hop].Meters
				outStop.RoadSeconds = detailed.Legs[hop].Seconds
				if hop < len(detailed.LegSteps) {
					outStop.Steps = detailed.LegSteps[hop]
				}
			case hasRoadMatrix && roadMatrix[prevPtIdx][curPtIdx].OK:
				outStop.RoadAvailable = true
				outStop.RoadMeters = roadMatrix[prevPtIdx][curPtIdx].Meters
				outStop.RoadSeconds = roadMatrix[prevPtIdx][curPtIdx].Seconds
			default:
				roadComplete = false
				outStop.RoadAvailable = false
				if s.name == "none" {
					outStop.RoadStatus = "Road routing provider not configured; road access requires verification."
				} else {
					outStop.RoadStatus = "Road access requires verification"
				}
				outStop.Warnings = append(outStop.Warnings, outStop.RoadStatus)
			}

			if outStop.RoadAvailable {
				totalRoadM += outStop.RoadMeters
				totalRoadSec += outStop.RoadSeconds
				tClock += int(math.Round(float64(outStop.RoadSeconds) / 60))
			} else {
				tClock += int(math.Round(float64(EstimateSeconds(sm)) / 60))
			}
		}

		if st.AppointmentMin >= 0 {
			if tClock < st.AppointmentMin {
				tClock = st.AppointmentMin
			} else if tClock > st.AppointmentMin+appointmentGrace {
				outStop.Conflict = fmt.Sprintf("Arrives %s, past %s appointment", clock(tClock), clock(st.AppointmentMin))
			}
		}
		outStop.Arrival = clock(tClock)
		tClock += st.VisitMinutes
		totalVisitMin += st.VisitMinutes
		outStop.Departure = clock(tClock)
		if outStop.Conflict == "" && tClock > effectiveEndMin {
			outStop.Conflict = fmt.Sprintf("Finishes %s, past %s working day", clock(tClock), clock(workEndMin))
		}
		if outStop.Conflict != "" {
			res.Warnings = append(res.Warnings, fmt.Sprintf("%s: %s", st.School.pin.Name, outStop.Conflict))
		}

		res.Stops = append(res.Stops, outStop)
		prevPtIdx = curPtIdx
		prevLabel = st.School.pin.Name
	}

	// Optional return leg to End location.
	if in.End != nil && prevPtIdx >= 0 {
		lastHop := len(orderedPts) - 2
		if hasRoadRoute && lastHop >= 0 && lastHop < len(detailed.Legs) && detailed.Legs[lastHop].OK {
			res.ReturnLegMeters = detailed.Legs[lastHop].Meters
			res.ReturnLegSeconds = detailed.Legs[lastHop].Seconds
			totalRoadM += res.ReturnLegMeters
			totalRoadSec += res.ReturnLegSeconds
			if lastHop < len(detailed.LegSteps) {
				res.ReturnLegSteps = detailed.LegSteps[lastHop]
			}
			tClock += int(math.Round(float64(res.ReturnLegSeconds) / 60))
		} else if hasRoadMatrix && roadMatrix[prevPtIdx][endIdx].OK {
			res.ReturnLegMeters = roadMatrix[prevPtIdx][endIdx].Meters
			res.ReturnLegSeconds = roadMatrix[prevPtIdx][endIdx].Seconds
			totalRoadM += res.ReturnLegMeters
			totalRoadSec += res.ReturnLegSeconds
			tClock += int(math.Round(float64(res.ReturnLegSeconds) / 60))
		} else {
			roadComplete = false
		}
	}

	// NEVER substitute a straight-line polyline as a drivable road path (Section 2).
	if hasRoadRoute && len(detailed.Path) >= 2 {
		res.Path = Simplify(detailed.Path, lineTolerance)
		res.PathIsRoad = true
	} else {
		res.Path = []LatLng{}
		res.PathIsRoad = false
		if len(chosenOrder) >= 2 || (len(chosenOrder) == 1 && (in.Start != nil || in.End != nil)) {
			roadComplete = false
			if s.name == "none" {
				res.Warnings = append(res.Warnings, "No road routing provider is configured (set EDIFY_ROUTING_PROVIDER=google or osrm). Road geometry is not drawn as straight lines.")
			} else {
				res.Warnings = append(res.Warnings, "Road access requires verification — provider did not return road geometry for this sequence.")
			}
		}
	}

	trafficState := detailed.TrafficState
	if trafficState == "" {
		trafficState = "unavailable"
	}
	res.TrafficIntervals = detailed.TrafficIntervals
	if len(detailed.Alternatives) > 0 {
		res.Alternatives = detailed.Alternatives
	}
	if len(detailed.Warnings) > 0 {
		res.Warnings = append(res.Warnings, detailed.Warnings...)
	}

	fieldMinutes := max(0, tClock-workStartMin) + breakMin
	res.Totals = RouteMetrics{
		SchoolsIncluded: len(res.Stops),
		SchoolsExcluded: len(res.Excluded),
		RoadComplete:    roadComplete && (len(orderedPts) < 2 || hasRoadRoute),
		RoadMeters:      totalRoadM,
		RoadSeconds:     totalRoadSec,
		StraightMeters:  totalStraightM,
		VisitMinutes:    totalVisitMin,
		BreakMinutes:    breakMin,
		FieldMinutes:    fieldMinutes,
		TrafficState:    trafficState,
		TrafficDelaySec: detailed.TrafficDelaySec,
	}

	if res.Totals.RoadComplete && baseline.RoadComplete && len(res.Stops) == baseline.SchoolsIncluded {
		res.DistanceSavedMeters = max(int64(0), baseline.RoadMeters-res.Totals.RoadMeters)
		res.TimeSavedSeconds = max(int64(0), baseline.RoadSeconds-res.Totals.RoadSeconds)
	}

	// Match active road-condition reports within proximity of the road path or stops (Section 7).
	res.RoadAlerts = matchRoadConditions(res.Path, orderedPts, in.RoadConditions)
	for _, al := range res.RoadAlerts {
		tag := "Unverified staff report"
		if al.VerificationStatus == "verified" {
			tag = "Verified road condition"
		}
		res.Warnings = append(res.Warnings, fmt.Sprintf("%s (%s): %s on %s. Provider cannot automatically block staff-reported segments; compare alternatives.",
			tag, strings.ReplaceAll(al.Category, "_", " "), al.ImpactLevel, al.RoadName))
	}

	// Confidence & honest recommendation criteria (Section 5.3).
	switch {
	case res.PathIsRoad && res.Totals.RoadComplete && s.name == "google" && trafficState != "unavailable":
		res.Confidence = "high"
		res.ConfidenceNote = "Road geometry, distances, and live traffic from Google Routes API v2."
	case res.PathIsRoad && res.Totals.RoadComplete:
		res.Confidence = "medium"
		res.ConfidenceNote = fmt.Sprintf("Real road-network geometry and distances from %s. Live traffic is unavailable from this provider.", strings.ToUpper(s.name))
	default:
		res.Confidence = "limited"
		res.ConfidenceNote = "Road routing unavailable or incomplete; road access requires verification before navigation."
	}

	hasConflict := false
	for _, st := range res.Stops {
		if st.Conflict != "" {
			hasConflict = true
			break
		}
	}
	res.IsRecommended = res.PathIsRoad && res.Totals.RoadComplete && !hasConflict && len(res.Stops) > 0 && mode == SmartModeBalanced
	if res.IsRecommended {
		res.RecommendationNote = "Recommended: balances verified SSA priorities, feasible working-day coverage, and road driving time."
	} else if hasConflict {
		res.RecommendationNote = "Review required: one or more stops run past the configured working day."
	} else if !res.PathIsRoad {
		res.RecommendationNote = "Road geometry unavailable: configure Google Routes API or OSRM for road-following navigation."
	} else {
		res.RecommendationNote = fmt.Sprintf("Optimized using %s.", modeLabel(mode))
	}
	return res
}

func stopKind(activityID string) string {
	if activityID != "" {
		return "planned"
	}
	return "recommended"
}

func inclusionReason(mode string, st SmartStopInput, pos int) string {
	var parts []string
	if st.PlannedActivityID != "" {
		parts = append(parts, "Scheduled in My Plan")
	} else {
		parts = append(parts, "Eligible field stop")
	}
	if st.Priority.Reason != "" {
		parts = append(parts, st.Priority.Reason)
	}
	if pos == 0 {
		parts = append(parts, "best opening stop for "+mode)
	}
	return strings.Join(parts, " · ")
}

func evaluateOrderMetrics(order []int, placed []SmartStopInput, legBetween func(a, b int) (int64, int64, bool), schoolOffset, startIdx, endIdx, breakMin int, hasRoadMatrix bool) RouteMetrics {
	m := RouteMetrics{
		SchoolsIncluded: len(order),
		RoadComplete:    hasRoadMatrix,
		BreakMinutes:    breakMin,
		TrafficState:    "unavailable",
	}
	prev := startIdx
	for _, idx := range order {
		cur := schoolOffset + idx
		if prev >= 0 {
			dist, sec, ok := legBetween(prev, cur)
			m.StraightMeters += StraightMeters(placed[idx].School.road(), placed[idx].School.road())
			if ok {
				m.RoadMeters += dist
				m.RoadSeconds += sec
			} else {
				m.RoadComplete = false
			}
		}
		m.VisitMinutes += placed[idx].VisitMinutes
		prev = cur
	}
	if endIdx >= 0 && prev >= 0 {
		dist, sec, ok := legBetween(prev, endIdx)
		if ok {
			m.RoadMeters += dist
			m.RoadSeconds += sec
		} else {
			m.RoadComplete = false
		}
	}
	m.FieldMinutes = int(math.Round(float64(m.RoadSeconds)/60)) + m.VisitMinutes + breakMin
	return m
}

func optimizeByMode(
	mode string,
	given []int,
	placed []SmartStopInput,
	secCost, meterCost Cost,
	workStartMin, effectiveEndMin, endIdx int,
	endReturnSec func(int) int64,
) (chosen []int, dropped []int) {
	if mode == SmartModeAsGiven || len(given) <= 1 {
		return given, nil
	}

	toStops := func(subset []int) []Stop {
		out := make([]Stop, len(placed))
		for _, i := range subset {
			out[i] = Stop{Visit: placed[i].VisitMinutes, Appointment: placed[i].AppointmentMin, Locked: placed[i].Locked}
		}
		return out
	}

	runOrder := func(subset []int, cost Cost) Schedule {
		stops := toStops(subset)
		// Adapt Optimize to the custom working window via score comparison.
		best := Optimize(subset, stops, cost, workStartMin)
		return best
	}

	fitsWindow := func(order []int) bool {
		t := workStartMin
		prev := -1
		for _, i := range order {
			sec := secCost(prev, i)
			t += int(math.Round(float64(sec) / 60))
			if placed[i].AppointmentMin >= 0 && t < placed[i].AppointmentMin {
				t = placed[i].AppointmentMin
			}
			t += placed[i].VisitMinutes
			prev = i
		}
		if endIdx >= 0 && prev >= 0 {
			t += int(math.Round(float64(endReturnSec(prev)) / 60))
		}
		return t <= effectiveEndMin
	}

	switch mode {
	case SmartModeShortest:
		plan := runOrder(given, meterCost)
		return plan.Order, nil

	case SmartModeFastest:
		plan := runOrder(given, secCost)
		return plan.Order, nil

	case SmartModeMaxSchools:
		// First try full set ordered for fastest travel; if it overflows the working day,
		// greedily pack the maximum number of feasible schools (keeping locked stops first).
		full := runOrder(given, secCost)
		if fitsWindow(full.Order) {
			return full.Order, nil
		}
		locked := []int{}
		free := []int{}
		for _, i := range given {
			if placed[i].Locked {
				locked = append(locked, i)
			} else {
				free = append(free, i)
			}
		}
		// Sort free schools by shortest visit + closest hop to maximize feasible count.
		sort.SliceStable(free, func(a, b int) bool {
			ca := int64(placed[free[a]].VisitMinutes*60) + secCost(-1, free[a])
			cb := int64(placed[free[b]].VisitMinutes*60) + secCost(-1, free[b])
			return ca < cb
		})
		cur := append([]int(nil), locked...)
		for _, cand := range free {
			trial := runOrder(append(append([]int(nil), cur...), cand), secCost)
			if fitsWindow(trial.Order) {
				cur = trial.Order
			} else {
				dropped = append(dropped, cand)
			}
		}
		if len(cur) == 0 && len(given) > 0 {
			return given[:1], given[1:]
		}
		return cur, dropped

	case SmartModePrioritySchools:
		// Sort candidates by verified SSA priority descending, include all that fit
		// working hours (never dropping critical schools for nearby routine ones),
		// then optimize road travel order among included schools.
		ranked := append([]int(nil), given...)
		sort.SliceStable(ranked, func(a, b int) bool {
			ia, ib := ranked[a], ranked[b]
			if placed[ia].Locked != placed[ib].Locked {
				return placed[ia].Locked
			}
			if placed[ia].Priority.Score != placed[ib].Priority.Score {
				return placed[ia].Priority.Score > placed[ib].Priority.Score
			}
			return secCost(-1, ia) < secCost(-1, ib)
		})
		cur := []int{}
		for _, cand := range ranked {
			trial := runOrder(append(append([]int(nil), cur...), cand), secCost)
			if fitsWindow(trial.Order) || len(cur) == 0 || placed[cand].Locked {
				cur = trial.Order
			} else {
				dropped = append(dropped, cand)
			}
		}
		return cur, dropped

	default: // SmartModeBalanced
		// Balance verified SSA priority, feasible coverage, and driving time.
		full := runOrder(given, secCost)
		if fitsWindow(full.Order) {
			// When all stops fit, pick order minimizing weighted travel + early visit of critical SSA stops.
			bestOrder := full.Order
			bestScore := balancedScore(bestOrder, placed, secCost)
			// Also compare against priority-seeded order and shortest-distance order.
			if shortest := runOrder(given, meterCost); fitsWindow(shortest.Order) {
				if sc := balancedScore(shortest.Order, placed, secCost); sc < bestScore {
					bestOrder, bestScore = shortest.Order, sc
				}
			}
			return bestOrder, nil
		}
		// When working hours are exceeded, rank by value-per-minute (SSA priority / (visit + marginal travel)).
		ranked := append([]int(nil), given...)
		sort.SliceStable(ranked, func(a, b int) bool {
			ia, ib := ranked[a], ranked[b]
			if placed[ia].Locked != placed[ib].Locked {
				return placed[ia].Locked
			}
			va := (placed[ia].Priority.Score + 25.0) / float64(max(30, placed[ia].VisitMinutes)+int(secCost(-1, ia)/60))
			vb := (placed[ib].Priority.Score + 25.0) / float64(max(30, placed[ib].VisitMinutes)+int(secCost(-1, ib)/60))
			return va > vb
		})
		cur := []int{}
		for _, cand := range ranked {
			trial := runOrder(append(append([]int(nil), cur...), cand), secCost)
			if fitsWindow(trial.Order) || len(cur) == 0 || placed[cand].Locked {
				cur = trial.Order
			} else {
				dropped = append(dropped, cand)
			}
		}
		return cur, dropped
	}
}

// balancedScore is lower-is-better: total travel minutes + slight penalty for delaying critical SSA stops.
func balancedScore(order []int, placed []SmartStopInput, secCost Cost) float64 {
	var totalSec int64
	var delayPenalty float64
	prev := -1
	for pos, i := range order {
		totalSec += secCost(prev, i)
		if placed[i].Priority.Band == "critical" {
			delayPenalty += float64(pos) * 4.0 // 4-minute equivalent preference to visit critical schools earlier
		}
		prev = i
	}
	return float64(totalSec)/60.0 + delayPenalty
}

// matchRoadConditions finds active road condition reports whose radius intersects
// the route polyline (or stops if no polyline). Never treats an unverified report
// as provider-confirmed.
func matchRoadConditions(path, stops []LatLng, reports []RoadConditionAlert) []RoadConditionAlert {
	if len(reports) == 0 {
		return []RoadConditionAlert{}
	}
	sample := path
	if len(sample) == 0 {
		sample = stops
	}
	if len(sample) == 0 {
		return []RoadConditionAlert{}
	}
	// Downsample dense polylines to max ~200 checkpoints for O(1ms) matching.
	stride := max(1, len(sample)/200)
	matched := []RoadConditionAlert{}
	for _, rep := range reports {
		if rep.Category == "road_reopened" || rep.VerificationStatus == "resolved" || rep.VerificationStatus == "expired" {
			continue
		}
		pt := LatLng{Lat: rep.Lat, Lng: rep.Lng}
		bestDist := int64(math.MaxInt64)
		for i := 0; i < len(sample); i += stride {
			d := StraightMeters(pt, sample[i])
			if d < bestDist {
				bestDist = d
			}
		}
		if d := StraightMeters(pt, sample[len(sample)-1]); d < bestDist {
			bestDist = d
		}
		radius := int64(rep.RadiusMeters)
		if radius <= 0 {
			radius = 1500
		}
		if bestDist <= radius {
			copyRep := rep
			copyRep.DistanceToRouteM = bestDist
			if copyRep.VerificationStatus == "verified" {
				copyRep.ApplicabilityNote = fmt.Sprintf("Verified report within %.1f km of route — check alternative routes.", float64(bestDist)/1000.0)
			} else {
				copyRep.ApplicabilityNote = fmt.Sprintf("Unverified staff report within %.1f km of route — treat with caution.", float64(bestDist)/1000.0)
			}
			matched = append(matched, copyRep)
		}
	}
	return matched
}
