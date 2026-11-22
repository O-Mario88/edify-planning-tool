package routeplan

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
)

// Google is the Google Maps Routes API v2 client, optional: used only when a
// restricted server key is configured. Its answers live only in the guard's
// short in-memory cache, as Google Maps Platform terms allow.
//
// Multi-stage routing compliance (Section 3):
//   - Stage 1 (Matrix / Waypoint Order): uses routingPreference="TRAFFIC_AWARE"
//     (never combined with TRAFFIC_AWARE_OPTIMAL when optimizeWaypointOrder=true).
//   - Stage 2 (Selected Route Geometry, Steps, Traffic & Alternatives): calls
//     computeRoutes with routingPreference="TRAFFIC_AWARE_OPTIMAL",
//     computeAlternativeRoutes=true, and extraComputations=["TRAFFIC_ON_POLYLINE"].
type Google struct {
	Key    string
	Client *http.Client
	// Base is overridden in tests.
	Base string
}

// Name is the provider's name.
func (Google) Name() string { return "google" }

// googleMatrixMax is the Routes API's elements a matrix request may ask.
const googleMatrixMax = 625

type gLatLng struct {
	Latitude  float64 `json:"latitude"`
	Longitude float64 `json:"longitude"`
}
type gWaypoint struct {
	Location struct {
		LatLng gLatLng `json:"latLng"`
	} `json:"location"`
}

func waypoint(p LatLng) gWaypoint {
	var w gWaypoint
	w.Location.LatLng = gLatLng{p.Lat, p.Lng}
	return w
}

func (g Google) post(ctx context.Context, path, mask string, body, into any) error {
	payload, err := json.Marshal(body)
	if err != nil {
		return err
	}
	base := g.Base
	if base == "" {
		base = "https://routes.googleapis.com"
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, base+path, bytes.NewReader(payload))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Goog-Api-Key", g.Key)
	req.Header.Set("X-Goog-FieldMask", mask)
	client := g.Client
	if client == nil {
		client = http.DefaultClient
	}
	res, err := client.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(res.Body, 8<<20))
	if err != nil {
		return err
	}
	if res.StatusCode != http.StatusOK {
		return fmt.Errorf("google %s: HTTP %d", path, res.StatusCode)
	}
	return json.Unmarshal(raw, into)
}

func duration(s string) int64 {
	n, _ := strconv.ParseFloat(strings.TrimSuffix(s, "s"), 64)
	return seconds(n)
}

// Matrix is computeRouteMatrix with TRAFFIC_AWARE preference and minimal field mask.
func (g Google) Matrix(ctx context.Context, points []LatLng) ([][]Leg, error) {
	if len(points)*len(points) > googleMatrixMax {
		return nil, fmt.Errorf("google matrix: %d points is over the request limit", len(points))
	}
	ws := make([]map[string]gWaypoint, len(points))
	for i, p := range points {
		ws[i] = map[string]gWaypoint{"waypoint": waypoint(p)}
	}
	var cells []struct {
		OriginIndex      int    `json:"originIndex"`
		DestinationIndex int    `json:"destinationIndex"`
		DistanceMeters   int64  `json:"distanceMeters"`
		Duration         string `json:"duration"`
		Condition        string `json:"condition"`
	}
	if err := g.post(ctx, "/distanceMatrix/v2:computeRouteMatrix", "originIndex,destinationIndex,distanceMeters,duration,condition",
		map[string]any{
			"origins":           ws,
			"destinations":      ws,
			"travelMode":        "DRIVE",
			"routingPreference": "TRAFFIC_AWARE",
		}, &cells); err != nil {
		return nil, err
	}
	out := make([][]Leg, len(points))
	for i := range out {
		out[i] = make([]Leg, len(points))
	}
	for _, c := range cells {
		if c.OriginIndex < len(points) && c.DestinationIndex < len(points) && c.Condition == "ROUTE_EXISTS" {
			out[c.OriginIndex][c.DestinationIndex] = Leg{Meters: c.DistanceMeters, Seconds: duration(c.Duration), OK: true}
		}
	}
	return out, nil
}

// OptimizeWaypointOrder asks Google Routes API Stage 1 waypoint optimization.
// Strictly uses TRAFFIC_AWARE (never TRAFFIC_AWARE_OPTIMAL, per Google API constraint).
func (g Google) OptimizeWaypointOrder(ctx context.Context, origin, destination LatLng, intermediates []LatLng) ([]int, error) {
	if len(intermediates) <= 1 {
		out := make([]int, len(intermediates))
		for i := range intermediates {
			out[i] = i
		}
		return out, nil
	}
	mids := make([]gWaypoint, len(intermediates))
	for i, p := range intermediates {
		mids[i] = waypoint(p)
	}
	var r struct {
		Routes []struct {
			OptimizedIntermediateWaypointIndex []int `json:"optimizedIntermediateWaypointIndex"`
		} `json:"routes"`
	}
	body := map[string]any{
		"origin":                waypoint(origin),
		"destination":           waypoint(destination),
		"intermediates":         mids,
		"travelMode":            "DRIVE",
		"routingPreference":     "TRAFFIC_AWARE",
		"optimizeWaypointOrder": true,
	}
	if err := g.post(ctx, "/directions/v2:computeRoutes", "routes.optimizedIntermediateWaypointIndex", body, &r); err != nil {
		return nil, err
	}
	if len(r.Routes) == 0 || len(r.Routes[0].OptimizedIntermediateWaypointIndex) != len(intermediates) {
		return nil, fmt.Errorf("google optimizeWaypointOrder: unexpected response length")
	}
	return r.Routes[0].OptimizedIntermediateWaypointIndex, nil
}

// Route is computeRoutes through the points in order (compact legacy call).
func (g Google) Route(ctx context.Context, points []LatLng) (Route, error) {
	return g.RouteDetailed(ctx, points, RouteOptions{
		IncludeSteps:        false,
		IncludeAlternatives: false,
		TrafficOptimal:      false,
		TransportMode:       "DRIVE",
	})
}

type googleComputeResponse struct {
	Routes []struct {
		Description    string   `json:"description"`
		DistanceMeters int64    `json:"distanceMeters"`
		Duration       string   `json:"duration"`
		StaticDuration string   `json:"staticDuration"`
		Warnings       []string `json:"warnings"`
		TravelAdvisory struct {
			SpeedReadingIntervals []struct {
				StartPolylinePointIndex int    `json:"startPolylinePointIndex"`
				EndPolylinePointIndex   int    `json:"endPolylinePointIndex"`
				Speed                   string `json:"speed"`
			} `json:"speedReadingIntervals"`
		} `json:"travelAdvisory"`
		Legs []struct {
			DistanceMeters int64  `json:"distanceMeters"`
			Duration       string `json:"duration"`
			StaticDuration string `json:"staticDuration"`
			Steps          []struct {
				DistanceMeters        int64  `json:"distanceMeters"`
				StaticDuration        string `json:"staticDuration"`
				NavigationInstruction struct {
					Maneuver     string `json:"maneuver"`
					Instructions string `json:"instructions"`
				} `json:"navigationInstruction"`
				StartLocation struct {
					LatLng gLatLng `json:"latLng"`
				} `json:"startLocation"`
				EndLocation struct {
					LatLng gLatLng `json:"latLng"`
				} `json:"endLocation"`
			} `json:"steps"`
		} `json:"legs"`
		Polyline struct {
			EncodedPolyline string `json:"encodedPolyline"`
		} `json:"polyline"`
	} `json:"routes"`
}

// RouteDetailed calls Google Routes API v2 computeRoutes with Stage 2 options:
// TRAFFIC_AWARE_OPTIMAL (never combined with optimizeWaypointOrder), turn-by-turn
// steps, TRAFFIC_ON_POLYLINE speed intervals, and alternative routes.
func (g Google) RouteDetailed(ctx context.Context, points []LatLng, opts RouteOptions) (Route, error) {
	if len(points) < 2 {
		return Route{}, fmt.Errorf("google route: %d points", len(points))
	}
	mids := []gWaypoint{}
	for _, p := range points[1 : len(points)-1] {
		mids = append(mids, waypoint(p))
	}
	mode := opts.TransportMode
	if mode == "" {
		mode = "DRIVE"
	}
	body := map[string]any{
		"origin":        waypoint(points[0]),
		"destination":   waypoint(points[len(points)-1]),
		"intermediates": mids,
		"travelMode":    mode,
	}
	fields := []string{
		"routes.description",
		"routes.distanceMeters",
		"routes.duration",
		"routes.staticDuration",
		"routes.warnings",
		"routes.legs.distanceMeters",
		"routes.legs.duration",
		"routes.legs.staticDuration",
		"routes.polyline.encodedPolyline",
	}
	if opts.TrafficOptimal && (mode == "DRIVE" || mode == "TWO_WHEELER") {
		body["routingPreference"] = "TRAFFIC_AWARE_OPTIMAL"
		body["extraComputations"] = []string{"TRAFFIC_ON_POLYLINE"}
		fields = append(fields, "routes.travelAdvisory.speedReadingIntervals")
	} else if mode == "DRIVE" || mode == "TWO_WHEELER" {
		body["routingPreference"] = "TRAFFIC_AWARE"
	}
	// Google Routes API only allows computeAlternativeRoutes when there are no intermediates.
	if opts.IncludeAlternatives && len(mids) == 0 {
		body["computeAlternativeRoutes"] = true
	}
	if opts.IncludeSteps {
		fields = append(fields,
			"routes.legs.steps.distanceMeters",
			"routes.legs.steps.staticDuration",
			"routes.legs.steps.navigationInstruction",
			"routes.legs.steps.startLocation",
			"routes.legs.steps.endLocation",
		)
	}

	var r googleComputeResponse
	if err := g.post(ctx, "/directions/v2:computeRoutes", strings.Join(fields, ","), body, &r); err != nil {
		return Route{}, err
	}
	if len(r.Routes) == 0 || len(r.Routes[0].Legs) != len(points)-1 {
		return Route{}, fmt.Errorf("google route: no route through %d points", len(points))
	}

	convert := func(idx int) (Route, int64) {
		raw := r.Routes[idx]
		out := Route{
			Path:           decodePolyline(raw.Polyline.EncodedPolyline),
			Summary:        raw.Description,
			Warnings:       raw.Warnings,
			ProviderSource: "google_routes_v2",
		}
		var liveTotal, staticTotal int64
		for _, l := range raw.Legs {
			sec := duration(l.Duration)
			stat := duration(l.StaticDuration)
			liveTotal += sec
			staticTotal += stat
			out.Legs = append(out.Legs, Leg{Meters: l.DistanceMeters, Seconds: sec, OK: true})
			if len(l.Steps) > 0 {
				legSteps := make([]Step, 0, len(l.Steps))
				for _, st := range l.Steps {
					instr := strings.TrimSpace(st.NavigationInstruction.Instructions)
					if instr == "" {
						instr = "Continue along road"
					}
					legSteps = append(legSteps, Step{
						Instruction:     instr,
						Maneuver:        st.NavigationInstruction.Maneuver,
						DistanceMeters:  st.DistanceMeters,
						DurationSeconds: duration(st.StaticDuration),
						Start:           LatLng{Lat: st.StartLocation.LatLng.Latitude, Lng: st.StartLocation.LatLng.Longitude},
						End:             LatLng{Lat: st.EndLocation.LatLng.Latitude, Lng: st.EndLocation.LatLng.Longitude},
					})
				}
				out.LegSteps = append(out.LegSteps, legSteps)
			}
		}
		if raw.StaticDuration != "" && staticTotal == 0 {
			staticTotal = duration(raw.StaticDuration)
		}
		if raw.Duration != "" && liveTotal == 0 {
			liveTotal = duration(raw.Duration)
		}
		for _, iv := range raw.TravelAdvisory.SpeedReadingIntervals {
			out.TrafficIntervals = append(out.TrafficIntervals, TrafficInterval{
				StartIndex: iv.StartPolylinePointIndex,
				EndIndex:   iv.EndPolylinePointIndex,
				Speed:      iv.Speed,
			})
		}
		out.StaticSeconds = staticTotal
		out.TrafficState, out.TrafficDelaySec = classifyTrafficState(liveTotal, staticTotal, out.TrafficIntervals)
		return out, raw.DistanceMeters
	}

	primary, _ := convert(0)
	for i := 1; i < len(r.Routes); i++ {
		altRoute, altDist := convert(i)
		var altSec int64
		for _, l := range altRoute.Legs {
			altSec += l.Seconds
			if altDist == 0 {
				altDist += l.Meters
			}
		}
		summary := altRoute.Summary
		if summary == "" {
			summary = fmt.Sprintf("Alternative %d", i)
		}
		primary.Alternatives = append(primary.Alternatives, AlternativeRoute{
			ID:               fmt.Sprintf("alt-%d", i),
			Summary:          summary,
			Meters:           altDist,
			Seconds:          altSec,
			StaticSeconds:    altRoute.StaticSeconds,
			TrafficState:     altRoute.TrafficState,
			TrafficDelaySec:  altRoute.TrafficDelaySec,
			Path:             altRoute.Path,
			Legs:             altRoute.Legs,
			LegSteps:         altRoute.LegSteps,
			TrafficIntervals: altRoute.TrafficIntervals,
			Warnings:         altRoute.Warnings,
		})
	}
	return primary, nil
}

// decodePolyline is Google's encoded polyline format (precision 5).
func decodePolyline(s string) []LatLng {
	var out []LatLng
	lat, lng := 0, 0
	for i := 0; i < len(s); {
		for _, into := range []*int{&lat, &lng} {
			shift, result := 0, 0
			for i < len(s) {
				b := int(s[i]) - 63
				i++
				result |= (b & 0x1f) << shift
				shift += 5
				if b < 0x20 {
					break
				}
			}
			if result&1 != 0 {
				*into += ^(result >> 1)
			} else {
				*into += result >> 1
			}
		}
		out = append(out, LatLng{Lat: float64(lat) / 1e5, Lng: float64(lng) / 1e5})
	}
	return out
}
