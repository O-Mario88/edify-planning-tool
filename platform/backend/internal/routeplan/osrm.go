package routeplan

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
)

// OSRM is an Edify-run or OpenStreetMap OSRM server (open source, real
// road-network routing, no key required).
type OSRM struct {
	Base   string
	Client *http.Client
}

// Name is the provider's name.
func (OSRM) Name() string { return "osrm" }

func (o OSRM) get(ctx context.Context, service string, points []LatLng, query string, into any) error {
	coords := make([]string, len(points))
	for i, p := range points {
		coords[i] = fmt.Sprintf("%.6f,%.6f", p.Lng, p.Lat)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, o.Base+"/"+service+"/v1/driving/"+strings.Join(coords, ";")+"?"+query, nil)
	if err != nil {
		return err
	}
	client := o.Client
	if client == nil {
		client = http.DefaultClient
	}
	res, err := client.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	var body struct {
		Code    string `json:"code"`
		Message string `json:"message"`
	}
	raw := json.NewDecoder(io.LimitReader(res.Body, 8<<20))
	var all json.RawMessage
	if err := raw.Decode(&all); err != nil {
		return fmt.Errorf("osrm %s: reading the answer: %w", service, err)
	}
	if err := json.Unmarshal(all, &body); err != nil || body.Code != "Ok" {
		return fmt.Errorf("osrm %s: %s %s (HTTP %d)", service, body.Code, body.Message, res.StatusCode)
	}
	return json.Unmarshal(all, into)
}

// Matrix is OSRM's table service.
func (o OSRM) Matrix(ctx context.Context, points []LatLng) ([][]Leg, error) {
	var t struct {
		Durations [][]*float64 `json:"durations"`
		Distances [][]*float64 `json:"distances"`
	}
	if err := o.get(ctx, "table", points, "annotations=duration,distance", &t); err != nil {
		return nil, err
	}
	if len(t.Durations) != len(points) || len(t.Distances) != len(points) {
		return nil, fmt.Errorf("osrm table: %d rows for %d points", len(t.Durations), len(points))
	}
	out := make([][]Leg, len(points))
	for i := range points {
		out[i] = make([]Leg, len(points))
		for j := range points {
			if i < len(t.Durations[i]) && j < len(t.Distances[i]) && t.Durations[i][j] != nil && t.Distances[i][j] != nil {
				out[i][j] = Leg{Meters: seconds(*t.Distances[i][j]), Seconds: seconds(*t.Durations[i][j]), OK: true}
			}
		}
	}
	return out, nil
}

// Route is OSRM's route service, with the full road line.
func (o OSRM) Route(ctx context.Context, points []LatLng) (Route, error) {
	return o.RouteDetailed(ctx, points, RouteOptions{IncludeSteps: false, IncludeAlternatives: false})
}

type osrmStep struct {
	Distance float64 `json:"distance"`
	Duration float64 `json:"duration"`
	Name     string  `json:"name"`
	Ref      string  `json:"ref"`
	Maneuver struct {
		Type     string     `json:"type"`
		Modifier string     `json:"modifier"`
		Exit     int        `json:"exit"`
		Location [2]float64 `json:"location"`
	} `json:"maneuver"`
}

// RouteDetailed calls OSRM with road-following geometry, optional turn-by-turn
// road maneuvers, and optional alternative routes. Traffic is honestly marked
// "unavailable" because OSRM does not include live traffic feeds.
func (o OSRM) RouteDetailed(ctx context.Context, points []LatLng, opts RouteOptions) (Route, error) {
	var r struct {
		Routes []struct {
			Distance float64 `json:"distance"`
			Duration float64 `json:"duration"`
			Legs     []struct {
				Summary  string     `json:"summary"`
				Distance float64    `json:"distance"`
				Duration float64    `json:"duration"`
				Steps    []osrmStep `json:"steps"`
			} `json:"legs"`
			Geometry struct {
				Coordinates [][2]float64 `json:"coordinates"`
			} `json:"geometry"`
		} `json:"routes"`
	}
	q := "overview=full&geometries=geojson"
	if opts.IncludeSteps {
		q += "&steps=true"
	} else {
		q += "&steps=false"
	}
	if opts.IncludeAlternatives && len(points) == 2 {
		q += "&alternatives=true"
	}
	if err := o.get(ctx, "route", points, q, &r); err != nil {
		return Route{}, err
	}
	if len(r.Routes) == 0 || len(r.Routes[0].Legs) != len(points)-1 {
		return Route{}, fmt.Errorf("osrm route: no route through %d points", len(points))
	}

	buildSteps := func(raw []osrmStep) []Step {
		if len(raw) == 0 {
			return nil
		}
		steps := make([]Step, 0, len(raw))
		for i, st := range raw {
			road := strings.TrimSpace(st.Name)
			if road == "" {
				road = strings.TrimSpace(st.Ref)
			}
			endLoc := st.Maneuver.Location
			if i+1 < len(raw) {
				endLoc = raw[i+1].Maneuver.Location
			}
			steps = append(steps, Step{
				Instruction:     formatOSRMManeuver(st.Maneuver.Type, st.Maneuver.Modifier, road, st.Maneuver.Exit),
				RoadName:        road,
				Maneuver:        strings.TrimSpace(st.Maneuver.Type + " " + st.Maneuver.Modifier),
				DistanceMeters:  seconds(st.Distance),
				DurationSeconds: seconds(st.Duration),
				Start:           LatLng{Lat: st.Maneuver.Location[1], Lng: st.Maneuver.Location[0]},
				End:             LatLng{Lat: endLoc[1], Lng: endLoc[0]},
			})
		}
		return steps
	}

	convert := func(idx int) Route {
		raw := r.Routes[idx]
		out := Route{
			TrafficState:   "unavailable",
			ProviderSource: "osrm_osm",
		}
		var summaries []string
		for _, l := range raw.Legs {
			out.Legs = append(out.Legs, Leg{Meters: seconds(l.Distance), Seconds: seconds(l.Duration), OK: true})
			out.StaticSeconds += seconds(l.Duration)
			if s := strings.TrimSpace(l.Summary); s != "" {
				summaries = append(summaries, s)
			}
			if len(l.Steps) > 0 {
				out.LegSteps = append(out.LegSteps, buildSteps(l.Steps))
			}
		}
		if len(summaries) > 0 {
			out.Summary = strings.Join(summaries, " → ")
		}
		for _, c := range raw.Geometry.Coordinates {
			out.Path = append(out.Path, LatLng{Lat: c[1], Lng: c[0]})
		}
		return out
	}

	primary := convert(0)
	for i := 1; i < len(r.Routes); i++ {
		alt := convert(i)
		summary := alt.Summary
		if summary == "" {
			summary = fmt.Sprintf("Alternative road route %d", i)
		}
		primary.Alternatives = append(primary.Alternatives, AlternativeRoute{
			ID:            fmt.Sprintf("alt-%d", i),
			Summary:       summary,
			Meters:        seconds(r.Routes[i].Distance),
			Seconds:       seconds(r.Routes[i].Duration),
			StaticSeconds: alt.StaticSeconds,
			TrafficState:  "unavailable",
			Path:          alt.Path,
			Legs:          alt.Legs,
			LegSteps:      alt.LegSteps,
		})
	}
	return primary, nil
}

func formatOSRMManeuver(kind, mod, road string, exit int) string {
	onRoad := ""
	if road != "" {
		onRoad = " onto " + road
	}
	alongRoad := ""
	if road != "" {
		alongRoad = " on " + road
	}
	switch kind {
	case "depart":
		if road != "" {
			return "Depart on " + road
		}
		return "Depart toward destination"
	case "arrive":
		return "Arrive at destination"
	case "roundabout", "rotary":
		if exit > 0 {
			return fmt.Sprintf("Take exit %d at roundabout%s", exit, onRoad)
		}
		return "Enter roundabout" + onRoad
	case "fork":
		if mod != "" {
			return "Keep " + mod + " at fork" + onRoad
		}
		return "Continue at fork" + onRoad
	case "merge":
		return "Merge" + onRoad
	case "end of road":
		if mod != "" {
			return "Turn " + mod + " at end of road" + onRoad
		}
		return "Turn at end of road" + onRoad
	case "new name", "continue":
		return "Continue" + alongRoad
	default:
		if mod == "uturn" {
			return "Make a U-turn" + onRoad
		}
		if mod != "" && mod != "straight" {
			return "Turn " + mod + onRoad
		}
		if road != "" {
			return "Continue on " + road
		}
		return "Continue straight"
	}
}
