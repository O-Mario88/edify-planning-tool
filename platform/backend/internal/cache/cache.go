// Package cache provides a shared key-value cache and distributed rate limiter
// backed by Redis (EDIFY_REDIS_URL) with an in-memory fallback for single-node
// development and tests.
package cache

import (
	"context"
	"log/slog"
	"sync"
	"time"
)

// Store is a key-value cache and fixed-window rate limiter.
type Store interface {
	Get(ctx context.Context, key string) (string, bool, error)
	Set(ctx context.Context, key, value string, ttl time.Duration) error
	Delete(ctx context.Context, key string) error
	// Allow reports whether key is within limit calls per period. It satisfies
	// signin.Limiter and loans.Limiter directly.
	Allow(key string, limit int, period time.Duration) bool
	Ping(ctx context.Context) error
	Backend() string
}

// NewFromURL returns a RedisStore when rawURL is non-empty and valid, or an
// in-memory fallback otherwise.
func NewFromURL(rawURL string, logger *slog.Logger) (Store, error) {
	if rawURL == "" {
		return NewMemory(time.Now), nil
	}
	rs, err := NewRedis(rawURL, logger)
	if err != nil {
		return nil, err
	}
	return rs, nil
}

type memEntry struct {
	value   string
	expires time.Time
}

type rateBucket struct {
	count int
	reset time.Time
}

// MemoryStore is a goroutine-safe in-memory cache and rate limiter.
type MemoryStore struct {
	mu    sync.Mutex
	now   func() time.Time
	items map[string]memEntry
	rates map[string]rateBucket
}

// NewMemory creates an in-memory Store using clock (time.Now if nil).
func NewMemory(clock func() time.Time) *MemoryStore {
	if clock == nil {
		clock = time.Now
	}
	return &MemoryStore{
		now:   clock,
		items: make(map[string]memEntry),
		rates: make(map[string]rateBucket),
	}
}

func (m *MemoryStore) Backend() string { return "memory" }

func (m *MemoryStore) Ping(context.Context) error { return nil }

func (m *MemoryStore) Get(_ context.Context, key string) (string, bool, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	entry, ok := m.items[key]
	if !ok {
		return "", false, nil
	}
	if !entry.expires.IsZero() && m.now().After(entry.expires) {
		delete(m.items, key)
		return "", false, nil
	}
	return entry.value, true, nil
}

func (m *MemoryStore) Set(_ context.Context, key, value string, ttl time.Duration) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	var exp time.Time
	if ttl > 0 {
		exp = m.now().Add(ttl)
	}
	m.items[key] = memEntry{value: value, expires: exp}
	return nil
}

func (m *MemoryStore) Delete(_ context.Context, key string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.items, key)
	return nil
}

func (m *MemoryStore) Allow(key string, limit int, period time.Duration) bool {
	if limit <= 0 {
		return false
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	now := m.now()
	bucket, ok := m.rates[key]
	if !ok || now.After(bucket.reset) {
		m.rates[key] = rateBucket{count: 1, reset: now.Add(period)}
		return true
	}
	if bucket.count >= limit {
		return false
	}
	bucket.count++
	m.rates[key] = bucket
	return true
}
