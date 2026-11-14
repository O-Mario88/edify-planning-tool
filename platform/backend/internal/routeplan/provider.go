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

// Route is a road route through points in order: one leg per hop and the
// line to draw.
type Route struct {
	Legs []Leg
	Path []LatLng
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

// Guard wraps inner. limit is the day's request cap.
func Guard(inner Router, limit int, now func() time.Time) *Guarded {
	return &Guarded{inner: inner, ttl: 6 * time.Hour, timeout: 8 * time.Second, limit: int64(limit), perSec: 20,
		now: now, cache: map[string]cached{}}
}

// Name is the provider's name.
func (g *Guarded) Name() string { return g.inner.Name() }

// Stats is the running count.
func (g *Guarded) Stats() *Stats { return &g.stats }

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
	v, err := g.ask(ctx, key("m", points), func(ctx context.Context) (any, error) { return g.inner.Matrix(ctx, points) })
	if err != nil {
		return nil, err
	}
	return v.([][]Leg), nil
}

// Route is the guarded route.
func (g *Guarded) Route(ctx context.Context, points []LatLng) (Route, error) {
	v, err := g.ask(ctx, key("r", points), func(ctx context.Context) (any, error) { return g.inner.Route(ctx, points) })
	if err != nil {
		return Route{}, err
	}
	return v.(Route), nil
}

func (g *Guarded) ask(ctx context.Context, k string, call func(context.Context) (any, error)) (any, error) {
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
		g.cache[k] = cached{value: v, until: now.Add(g.ttl)}
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
