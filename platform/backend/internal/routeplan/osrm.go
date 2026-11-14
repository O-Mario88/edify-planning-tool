package routeplan

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
)

// OSRM is an Edify-run OSRM server (open source, OpenStreetMap roads, no key).
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
	var r struct {
		Routes []struct {
			Legs []struct {
				Distance float64 `json:"distance"`
				Duration float64 `json:"duration"`
			} `json:"legs"`
			Geometry struct {
				Coordinates [][2]float64 `json:"coordinates"`
			} `json:"geometry"`
		} `json:"routes"`
	}
	if err := o.get(ctx, "route", points, "overview=full&geometries=geojson&steps=false", &r); err != nil {
		return Route{}, err
	}
	if len(r.Routes) == 0 || len(r.Routes[0].Legs) != len(points)-1 {
		return Route{}, fmt.Errorf("osrm route: no route through %d points", len(points))
	}
	out := Route{}
	for _, l := range r.Routes[0].Legs {
		out.Legs = append(out.Legs, Leg{Meters: seconds(l.Distance), Seconds: seconds(l.Duration), OK: true})
	}
	for _, c := range r.Routes[0].Geometry.Coordinates {
		out.Path = append(out.Path, LatLng{Lat: c[1], Lng: c[0]})
	}
	return out, nil
}
