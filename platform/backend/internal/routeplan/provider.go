package routeplan

import (
	"context"
	"errors"
	"fmt"
	"math"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"golang.org/x/sync/singleflight"
)

// Leg is one provider-measured road leg.
type Leg struct {
	Meters, Seconds int64
	// OK is false where the provider found no road between the two points.
	OK bool
}

// Step is one turn-by-turn road navigation maneuver returned by the routing provider.
type Step struct {
	Instruction     string `json:"instruction"`
	RoadName        string `json:"road_name,omitempty"`
	Maneuver        string `json:"maneuver,omitempty"`
	DistanceMeters  int64  `json:"distance_meters"`
	DurationSeconds int64  `json:"duration_seconds"`
	Start           LatLng `json:"start"`
	End             LatLng `json:"end"`
}

// TrafficInterval marks a speed band over a polyline coordinate range when
// returned by Google Routes API TRAFFIC_ON_POLYLINE.
type TrafficInterval struct {
	StartIndex int    `json:"start_index"`
	EndIndex   int    `json:"end_index"`
	Speed      string `json:"speed"` // NORMAL | SLOW | TRAFFIC_JAM
}

// AlternativeRoute is a provider-returned alternative road path.
type AlternativeRoute struct {
	ID               string            `json:"id"`
	Summary          string            `json:"summary"`
	Meters           int64             `json:"meters"`
	Seconds          int64             `json:"seconds"`
	StaticSeconds    int64             `json:"static_seconds,omitempty"`
	TrafficState     string            `json:"traffic_state"` // normal | slow | traffic_jam | unavailable
	TrafficDelaySec  int64             `json:"traffic_delay_seconds"`
	Path             []LatLng          `json:"path"`
	Legs             []Leg             `json:"legs"`
	LegSteps         [][]Step          `json:"leg_steps,omitempty"`
	TrafficIntervals []TrafficInterval `json:"traffic_intervals,omitempty"`
	Warnings         []string          `json:"warnings,omitempty"`
}

// RouteOptions configures detailed road routing (traffic preference, alternatives,
// turn-by-turn steps, transport mode).
type RouteOptions struct {
	// IncludeSteps requests turn-by-turn road maneuvers.
	IncludeSteps bool
	// IncludeAlternatives requests alternative routes where the provider supports them.
	IncludeAlternatives bool
	// TrafficOptimal uses TRAFFIC_AWARE_OPTIMAL on Google Routes API (never
	// combined with optimizeWaypointOrder in the same API request).
	TrafficOptimal bool
	// TransportMode is DRIVE (default), TWO_WHEELER, or WALK.
	TransportMode string
}

// Route is a road route through points in order: one leg per hop, the road
// polyline, and optional detailed turn-by-turn steps, traffic state, and alternatives.
type Route struct {
	Legs             []Leg
	Path             []LatLng
	Summary          string
	StaticSeconds    int64
	TrafficState     string // normal | slow | traffic_jam | unavailable
	TrafficDelaySec  int64
	TrafficIntervals []TrafficInterval
	LegSteps         [][]Step
	Alternatives     []AlternativeRoute
	Warnings         []string
	ProviderSource   string
}

// Router measures roads. Every implementation answers from a real provider
// or not at all: there is no made-up road figure anywhere.
type Router interface {
	Name() string
	// Matrix is the road leg from every point to every other.
	Matrix(ctx context.Context, points []LatLng) ([][]Leg, error)
	// Route is the road route through the points in order.
	Route(ctx context.Context, points []LatLng) (Route, error)
}

// DetailedRouter is an optional extension implemented by Google and OSRM to
// return turn-by-turn maneuvers, traffic intervals, and alternative routes.
type DetailedRouter interface {
	Router
	RouteDetailed(ctx context.Context, points []LatLng, opts RouteOptions) (Route, error)
}

// ErrUnavailable is returned when no road figure can be had: no provider is
// configured, the day's limit is spent, or the provider failed.
var ErrUnavailable = errors.New("routeplan: road distances are unavailable")

// None is the planner with no routing provider.
type None struct{}

func (None) Name() string { return "none" }
func (None) Matrix(context.Context, []LatLng) ([][]Leg, error) {
	return nil, ErrUnavailable
}
func (None) Route(context.Context, []LatLng) (Route, error) { return Route{}, ErrUnavailable }

// Guarded wraps a provider with what keeps it cheap and safe: a short
// in-memory cache (results are not stored anywhere else), one request for
// identical concurrent asks, a per-second rate, a daily cap and a timeout.
type Guarded struct {
	inner    Router
	ttl      time.Duration
	timeout  time.Duration
	limit    int64
	perSec   int
	now      func() time.Time
	flight   singleflight.Group
	mu       sync.Mutex
	cache    map[string]cached
	day      string
	used     int64
	second   int64
	inSecond int
	stats    Stats
}

type cached struct {
	value any
	until time.Time
}

// Stats counts what the planner asked of the provider, for monitoring.
type Stats struct {
	Requests, CacheHits, Shared, Failures, Refused atomic.Int64
}

// QuotaSnapshot exposes current daily quota utilization for diagnostics and UI.
type QuotaSnapshot struct {
	Provider   string `json:"provider"`
	DailyLimit int64  `json:"daily_limit"`
	UsedToday  int64  `json:"used_today"`
	Requests   int64  `json:"requests"`
	CacheHits  int64  `json:"cache_hits"`
	Shared     int64  `json:"shared_inflight"`
	Failures   int64  `json:"failures"`
	Refused    int64  `json:"refused"`
}

// Guard wraps inner. limit is the day's request cap.
func Guard(inner Router, limit int, now func() time.Time) *Guarded {
	return &Guarded{inner: inner, ttl: 6 * time.Hour, timeout: 8 * time.Second, limit: int64(limit), perSec: 20,
		now: now, cache: map[string]cached{}}
}

// Name is the provider's name.
func (g *Guarded) Name() string { return g.inner.Name() }

// Stats is the running count.
func (g *Guarded) Stats() *Stats { return &g.stats }

// Quota returns current rate/quota counters safely.
func (g *Guarded) Quota() QuotaSnapshot {
	g.mu.Lock()
	used := g.used
	limit := g.limit
	g.mu.Unlock()
	return QuotaSnapshot{
		Provider:   g.inner.Name(),
		DailyLimit: limit,
		UsedToday:  used,
		Requests:   g.stats.Requests.Load(),
		CacheHits:  g.stats.CacheHits.Load(),
		Shared:     g.stats.Shared.Load(),
		Failures:   g.stats.Failures.Load(),
		Refused:    g.stats.Refused.Load(),
	}
}

func key(kind string, points []LatLng) string {
	var b strings.Builder
	b.WriteString(kind)
	for _, p := range points {
		// About 1 m: the same school asks the same question.
		fmt.Fprintf(&b, "|%.5f,%.5f", p.Lat, p.Lng)
	}
	return b.String()
}

// Matrix is the guarded matrix.
func (g *Guarded) Matrix(ctx context.Context, points []LatLng) ([][]Leg, error) {
	v, err := g.ask(ctx, key("m", points), g.ttl, func(ctx context.Context) (any, error) { return g.inner.Matrix(ctx, points) })
	if err != nil {
		return nil, err
	}
	return v.([][]Leg), nil
}

// Route is the guarded route.
func (g *Guarded) Route(ctx context.Context, points []LatLng) (Route, error) {
	v, err := g.ask(ctx, key("r", points), g.ttl, func(ctx context.Context) (any, error) { return g.inner.Route(ctx, points) })
	if err != nil {
		return Route{}, err
	}
	return v.(Route), nil
}

// RouteDetailed requests full turn-by-turn steps, traffic state, and alternatives.
// Traffic-aware calls use a shorter cache TTL (5 min) to keep traffic fresh while
// protecting provider quotas and preventing duplicate requests.
func (g *Guarded) RouteDetailed(ctx context.Context, points []LatLng, opts RouteOptions) (Route, error) {
	dr, ok := g.inner.(DetailedRouter)
	if !ok {
		return g.Route(ctx, points)
	}
	mode := opts.TransportMode
	if mode == "" {
		mode = "DRIVE"
	}
	kind := fmt.Sprintf("rd:%t:%t:%t:%s", opts.IncludeSteps, opts.IncludeAlternatives, opts.TrafficOptimal, mode)
	ttl := g.ttl
	if opts.TrafficOptimal {
		ttl = 5 * time.Minute
	}
	v, err := g.ask(ctx, key(kind, points), ttl, func(ctx context.Context) (any, error) {
		return dr.RouteDetailed(ctx, points, opts)
	})
	if err != nil {
		return Route{}, err
	}
	return v.(Route), nil
}

func (g *Guarded) ask(ctx context.Context, k string, ttl time.Duration, call func(context.Context) (any, error)) (any, error) {
	if _, none := g.inner.(None); none {
		return nil, ErrUnavailable
	}
	now := g.now()
	g.mu.Lock()
	if c, ok := g.cache[k]; ok && now.Before(c.until) {
		g.mu.Unlock()
		g.stats.CacheHits.Add(1)
		return c.value, nil
	}
	g.mu.Unlock()
	v, err, shared := g.flight.Do(k, func() (any, error) {
		if !g.admit(now) {
			g.stats.Refused.Add(1)
			return nil, ErrUnavailable
		}
		g.stats.Requests.Add(1)
		ctx, cancel := context.WithTimeout(context.WithoutCancel(ctx), g.timeout)
		defer cancel()
		v, err := call(ctx)
		if err != nil {
			g.stats.Failures.Add(1)
			return nil, fmt.Errorf("%w: %s: %v", ErrUnavailable, g.inner.Name(), err)
		}
		g.mu.Lock()
		g.cache[k] = cached{value: v, until: now.Add(ttl)}
		g.mu.Unlock()
		return v, nil
	})
	if shared {
		g.stats.Shared.Add(1)
	}
	return v, err
}

// admit spends one request of the day's cap and of this second's rate.
func (g *Guarded) admit(now time.Time) bool {
	g.mu.Lock()
	defer g.mu.Unlock()
	if day := now.Format(time.DateOnly); day != g.day {
		g.day, g.used = day, 0
	}
	if sec := now.Unix(); sec != g.second {
		g.second, g.inSecond = sec, 0
	}
	if g.used >= g.limit || g.inSecond >= g.perSec {
		return false
	}
	g.used++
	g.inSecond++
	return true
}

func seconds(s float64) int64 { return int64(math.Round(s)) }

// classifyTrafficState translates live vs static duration and speed intervals
// into the mandated traffic states (normal | slow | traffic_jam | unavailable).
// It never fabricates traffic when the provider supplied no live traffic data.
func classifyTrafficState(liveSec, staticSec int64, intervals []TrafficInterval) (string, int64) {
	for _, iv := range intervals {
		if strings.EqualFold(iv.Speed, "TRAFFIC_JAM") {
			delay := max(int64(0), liveSec-staticSec)
			return "traffic_jam", delay
		}
	}
	if staticSec > 0 && liveSec > 0 {
		delay := max(int64(0), liveSec-staticSec)
		ratio := float64(liveSec) / float64(staticSec)
		switch {
		case ratio >= 1.35 || delay >= 900:
			return "traffic_jam", delay
		case ratio >= 1.12 || delay >= 300:
			return "slow", delay
		default:
			return "normal", delay
		}
	}
	for _, iv := range intervals {
		if strings.EqualFold(iv.Speed, "SLOW") {
			return "slow", 0
		}
		if strings.EqualFold(iv.Speed, "NORMAL") {
			return "normal", 0
		}
	}
	return "unavailable", 0
}
