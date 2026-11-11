package loans

import (
	"sync"
	"time"
)

// Limiter counts requests per key in fixed windows, in memory. It is the
// public pages' rate limit: generous for a person, tight for a script. Each
// gateway instance counts on its own, which is enough to blunt abuse; the
// idempotency key and the duplicate check stop repeated applications
// whatever instance they reach.
type Limiter struct {
	mu      sync.Mutex
	windows map[string]*window
	now     func() time.Time
	sweep   time.Time
}

type window struct {
	started time.Time
	count   int
}

// NewLimiter returns an empty Limiter.
func NewLimiter(now func() time.Time) *Limiter {
	if now == nil {
		now = time.Now
	}
	return &Limiter{windows: map[string]*window{}, now: now}
}

// Allow says whether one more request under key fits in limit per period.
func (l *Limiter) Allow(key string, limit int, period time.Duration) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := l.now()
	if now.Sub(l.sweep) > time.Hour {
		for k, w := range l.windows {
			if now.Sub(w.started) > time.Hour {
				delete(l.windows, k)
			}
		}
		l.sweep = now
	}
	w, ok := l.windows[key]
	if !ok || now.Sub(w.started) >= period {
		l.windows[key] = &window{started: now, count: 1}
		return true
	}
	if w.count >= limit {
		return false
	}
	w.count++
	return true
}
