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

// Google is the Google Maps Routes API, optional: used only when a
// restricted server key is configured. Its answers live only in the guard's
// short cache, as its terms allow.
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

// Matrix is computeRouteMatrix with only the fields the planner reads.
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
		map[string]any{"origins": ws, "destinations": ws, "travelMode": "DRIVE"}, &cells); err != nil {
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

// Route is computeRoutes through the points in order.
func (g Google) Route(ctx context.Context, points []LatLng) (Route, error) {
	if len(points) < 2 {
		return Route{}, fmt.Errorf("google route: %d points", len(points))
	}
	mids := []gWaypoint{}
	for _, p := range points[1 : len(points)-1] {
		mids = append(mids, waypoint(p))
	}
	var r struct {
		Routes []struct {
			Legs []struct {
				DistanceMeters int64  `json:"distanceMeters"`
				Duration       string `json:"duration"`
			} `json:"legs"`
			Polyline struct {
				EncodedPolyline string `json:"encodedPolyline"`
			} `json:"polyline"`
		} `json:"routes"`
	}
	if err := g.post(ctx, "/directions/v2:computeRoutes", "routes.legs.distanceMeters,routes.legs.duration,routes.polyline.encodedPolyline",
		map[string]any{"origin": waypoint(points[0]), "destination": waypoint(points[len(points)-1]), "intermediates": mids, "travelMode": "DRIVE"}, &r); err != nil {
		return Route{}, err
	}
	if len(r.Routes) == 0 || len(r.Routes[0].Legs) != len(points)-1 {
		return Route{}, fmt.Errorf("google route: no route through %d points", len(points))
	}
	out := Route{Path: decodePolyline(r.Routes[0].Polyline.EncodedPolyline)}
	for _, l := range r.Routes[0].Legs {
		out.Legs = append(out.Legs, Leg{Meters: l.DistanceMeters, Seconds: duration(l.Duration), OK: true})
	}
	return out, nil
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
