package routeplan

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func f(v float64) *float64 { return &v }

func TestOnlyRealPointsInsideUgandaArePlaced(t *testing.T) {
	cases := []struct {
		geoLat, geoLng, lat, lng *float64
		status                   string
	}{
		{f(0.35), f(32.75), f(0.1), f(32.1), LocationVerified},
		{nil, nil, f(0.35), f(32.75), LocationRecorded},
		{nil, nil, nil, nil, LocationMissing},
		{nil, nil, f(0), f(0), LocationInvalid},
		{nil, nil, f(51.5), f(-0.12), LocationInvalid},
		{nil, nil, f(32.75), f(0.35), LocationInvalid},
	}
	for _, c := range cases {
		if _, got := Locate(c.geoLat, c.geoLng, c.lat, c.lng); got != c.status {
			t.Errorf("Locate = %q, want %q", got, c.status)
		}
	}
}

func TestStraightLinesAreTheEnginesHaversine(t *testing.T) {
	// Kampala to Mukono, about 21 km as the crow flies.
	m := StraightMeters(LatLng{0.3476, 32.5825}, LatLng{0.3533, 32.7553})
	if m < 19000 || m > 20000 {
		t.Errorf("straight line %d m", m)
	}
	if StraightMeters(LatLng{1, 32}, LatLng{1, 32}) != 0 {
		t.Error("a point is 0 m from itself")
	}
	// 15 km at the engine's 30 km/h is 30 minutes.
	if EstimateSeconds(15000) != 1800 {
		t.Errorf("estimate %d", EstimateSeconds(15000))
	}
}

type countingRouter struct {
	calls atomic.Int64
	wait  chan struct{}
	fail  bool
}

func (c *countingRouter) Name() string { return "test" }
func (c *countingRouter) Matrix(ctx context.Context, p []LatLng) ([][]Leg, error) {
	c.calls.Add(1)
	if c.wait != nil {
		<-c.wait
	}
	if c.fail {
		return nil, errors.New("down")
	}
	return [][]Leg{{{OK: true}}}, nil
}
func (c *countingRouter) Route(context.Context, []LatLng) (Route, error) { return Route{}, nil }

func TestTheGuardCachesSharesAndCaps(t *testing.T) {
	now := time.Date(2026, 11, 14, 9, 0, 0, 0, time.UTC)
	r := &countingRouter{wait: make(chan struct{})}
	g := Guard(r, 2, func() time.Time { return now })
	pts := []LatLng{{0.3, 32.7}}
	var wg sync.WaitGroup
	for range 5 {
		wg.Add(1)
		go func() { defer wg.Done(); _, _ = g.Matrix(context.Background(), pts) }()
	}
	time.Sleep(50 * time.Millisecond)
	close(r.wait)
	wg.Wait()
	if r.calls.Load() != 1 {
		t.Errorf("five identical asks made %d provider calls", r.calls.Load())
	}
	if _, err := g.Matrix(context.Background(), pts); err != nil || r.calls.Load() != 1 {
		t.Errorf("a repeat is answered from the cache: %v, %d calls", err, r.calls.Load())
	}
	if _, err := g.Matrix(context.Background(), []LatLng{{1, 33}}); err != nil {
		t.Fatal(err)
	}
	if _, err := g.Matrix(context.Background(), []LatLng{{2, 33}}); !errors.Is(err, ErrUnavailable) {
		t.Errorf("past the day's cap: %v", err)
	}
	now = now.Add(24 * time.Hour)
	if _, err := g.Matrix(context.Background(), []LatLng{{2, 33}}); err != nil {
		t.Errorf("a new day has a new cap: %v", err)
	}
	failing := Guard(&countingRouter{fail: true}, 10, func() time.Time { return now })
	if _, err := failing.Matrix(context.Background(), pts); !errors.Is(err, ErrUnavailable) {
		t.Errorf("a provider failure is unavailable, never a figure: %v", err)
	}
	if _, err := Guard(None{}, 10, time.Now).Route(context.Background(), pts); !errors.Is(err, ErrUnavailable) {
		t.Errorf("no provider: %v", err)
	}
}

func TestOSRMIsReadAsItAnswers(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasPrefix(r.URL.Path, "/table/v1/driving/32.700000,0.300000;32.800000,0.400000"):
			_, _ = w.Write([]byte(`{"code":"Ok","durations":[[0,600.4],[null,0]],"distances":[[0,8123.6],[null,0]]}`))
		case strings.HasPrefix(r.URL.Path, "/route/v1/driving/"):
			_, _ = w.Write([]byte(`{"code":"Ok","routes":[{"legs":[{"distance":8123.6,"duration":600.4}],"geometry":{"coordinates":[[32.7,0.3],[32.8,0.4]]}}]}`))
		default:
			w.WriteHeader(http.StatusBadRequest)
			_, _ = w.Write([]byte(`{"code":"InvalidUrl","message":"bad"}`))
		}
	}))
	defer srv.Close()
	o := OSRM{Base: srv.URL}
	pts := []LatLng{{0.3, 32.7}, {0.4, 32.8}}
	m, err := o.Matrix(context.Background(), pts)
	if err != nil || m[0][1] != (Leg{Meters: 8124, Seconds: 600, OK: true}) || m[1][0].OK {
		t.Errorf("matrix %v %v", m, err)
	}
	r, err := o.Route(context.Background(), pts)
	if err != nil || len(r.Legs) != 1 || r.Legs[0].Meters != 8124 || len(r.Path) != 2 || r.Path[1] != (LatLng{0.4, 32.8}) {
		t.Errorf("route %+v %v", r, err)
	}
	if _, err := o.Matrix(context.Background(), []LatLng{{1, 1}}); err == nil {
		t.Error("an OSRM error is an error")
	}
}

func TestGoogleIsAskedForOnlyWhatIsRead(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Goog-Api-Key") != "k" || r.Header.Get("X-Goog-FieldMask") == "" {
			w.WriteHeader(http.StatusForbidden)
			return
		}
		if strings.Contains(r.URL.Path, "computeRouteMatrix") {
			_, _ = w.Write([]byte(`[{"originIndex":0,"destinationIndex":1,"distanceMeters":9000,"duration":"700s","condition":"ROUTE_EXISTS"},
{"originIndex":1,"destinationIndex":0,"condition":"ROUTE_NOT_FOUND"}]`))
			return
		}
		_, _ = w.Write([]byte(`{"routes":[{"legs":[{"distanceMeters":9000,"duration":"700s"}],"polyline":{"encodedPolyline":"_p~iF~ps|U_ulLnnqC_mqNvxq` + "`" + `@"}}]}`))
	}))
	defer srv.Close()
	g := Google{Key: "k", Base: srv.URL}
	pts := []LatLng{{0.3, 32.7}, {0.4, 32.8}}
	m, err := g.Matrix(context.Background(), pts)
	if err != nil || m[0][1] != (Leg{Meters: 9000, Seconds: 700, OK: true}) || m[1][0].OK {
		t.Errorf("matrix %v %v", m, err)
	}
	r, err := g.Route(context.Background(), pts)
	if err != nil || r.Legs[0].Seconds != 700 || len(r.Path) != 3 || r.Path[0] != (LatLng{38.5, -120.2}) || r.Path[2] != (LatLng{43.252, -126.453}) {
		t.Errorf("route %+v %v", r, err)
	}
	if _, err := (Google{Key: "wrong", Base: srv.URL}).Matrix(context.Background(), pts); err == nil {
		t.Error("a refused key is an error")
	}
}
