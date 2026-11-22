// Package realtime provides a role- and country-scoped Server-Sent Events (SSE)
// event broker for live operational synchronization across active Edify clients.
//
// Events are published strictly AFTER the originating PostgreSQL transaction
// commits. Every subscriber receives only events authorized for its country,
// role, and user identity. A bounded ring buffer supports Last-Event-ID replay
// on reconnect without duplicates, and non-blocking channels ensure slow
// clients never stall writes or other subscribers.
package realtime

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"slices"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

const (
	defaultRingSize     = 512
	subscriberQueueSize = 64
	heartbeatInterval   = 25 * time.Second
)

// Authenticator verifies a Bearer Authorization header.
type Authenticator interface {
	Authenticate(ctx context.Context, header string) (auth.Principal, error)
}

// Event is a committed operational change published to authorized subscribers.
type Event struct {
	Seq          uint64   `json:"seq"`
	EventID      string   `json:"event_id"`
	Type         string   `json:"type"`
	EntityType   string   `json:"entity_type"`
	EntityID     string   `json:"entity_id"`
	CountryCode  string   `json:"country_code,omitempty"`
	TargetUserID string   `json:"-"`
	TargetRoles  []string `json:"-"`
	ActorUserID  string   `json:"actor_user_id,omitempty"`
	Summary      string   `json:"summary,omitempty"`
	OccurredAt   string   `json:"occurred_at"`
}

// Stats reports live broker health for observability and load benchmarks.
type Stats struct {
	ActiveSubscribers int    `json:"active_subscribers"`
	PublishedTotal    uint64 `json:"published_total"`
	DeliveredTotal    uint64 `json:"delivered_total"`
	DroppedTotal      uint64 `json:"dropped_total"`
	BufferSize        int    `json:"buffer_size"`
}

type subscriber struct {
	id          uint64
	userID      string
	activeRole  string
	countryCode string
	ch          chan Event
}

// Broker fans out committed operational events to scoped SSE subscribers.
type Broker struct {
	now      func() time.Time
	ringSize int

	mu       sync.RWMutex
	seq      uint64
	nextSub  uint64
	ring     []Event
	subs     map[uint64]*subscriber

	published atomic.Uint64
	delivered atomic.Uint64
	dropped   atomic.Uint64
}

// NewBroker constructs a real-time SSE broker.
func NewBroker(now func() time.Time) *Broker {
	if now == nil {
		now = time.Now
	}
	return &Broker{
		now:      now,
		ringSize: defaultRingSize,
		ring:     make([]Event, 0, defaultRingSize),
		subs:     make(map[uint64]*subscriber),
	}
}

// Publish records an event into the replay ring and fans it out non-blockingly
// to all matching authorized subscribers.
func (b *Broker) Publish(ev Event) Event {
	if b == nil {
		return ev
	}
	ts := b.now().UTC()
	b.mu.Lock()
	b.seq++
	ev.Seq = b.seq
	if ev.EventID == "" {
		ev.EventID = fmt.Sprintf("evt-%d", ev.Seq)
	}
	if ev.OccurredAt == "" {
		ev.OccurredAt = ts.Format(time.RFC3339Nano)
	}
	ev.CountryCode = strings.ToUpper(strings.TrimSpace(ev.CountryCode))
	if len(b.ring) >= b.ringSize {
		copy(b.ring, b.ring[1:])
		b.ring[len(b.ring)-1] = ev
	} else {
		b.ring = append(b.ring, ev)
	}
	targets := make([]*subscriber, 0, len(b.subs))
	for _, s := range b.subs {
		if matches(s, ev) {
			targets = append(targets, s)
		}
	}
	b.mu.Unlock()

	b.published.Add(1)
	for _, s := range targets {
		select {
		case s.ch <- ev:
			b.delivered.Add(1)
		default:
			b.dropped.Add(1)
		}
	}
	return ev
}

// matches enforces strict country, user, and role authorization on every event.
func matches(s *subscriber, ev Event) bool {
	// Strict country isolation: a subscriber scoped to a country never receives
	// another country's events (unless subscriber is unscoped global Admin/RVP).
	if ev.CountryCode != "" && s.countryCode != "" && !strings.EqualFold(ev.CountryCode, s.countryCode) {
		return false
	}
	if ev.TargetUserID != "" {
		return s.userID == ev.TargetUserID || s.userID == ev.ActorUserID
	}
	if len(ev.TargetRoles) > 0 {
		if s.userID != "" && s.userID == ev.ActorUserID {
			return true
		}
		return slices.Contains(ev.TargetRoles, s.activeRole)
	}
	// Unscoped events only reach Admins.
	return s.activeRole == "Admin"
}

// Subscribe registers a scoped subscriber and returns any missed events strictly
// after lastSeq, the live event channel, and an unsubscribe callback.
func (b *Broker) Subscribe(p auth.Principal, lastSeq uint64) ([]Event, <-chan Event, func()) {
	countryCode := ""
	if p.Country != nil {
		countryCode = strings.ToUpper(strings.TrimSpace(p.Country.Code))
	}
	b.mu.Lock()
	b.nextSub++
	sub := &subscriber{
		id:          b.nextSub,
		userID:      p.UserID,
		activeRole:  p.ActiveRole,
		countryCode: countryCode,
		ch:          make(chan Event, subscriberQueueSize),
	}
	b.subs[sub.id] = sub

	var replay []Event
	if lastSeq > 0 {
		for _, ev := range b.ring {
			if ev.Seq > lastSeq && matches(sub, ev) {
				replay = append(replay, ev)
			}
		}
	}
	b.mu.Unlock()

	unsub := func() {
		b.mu.Lock()
		delete(b.subs, sub.id)
		b.mu.Unlock()
	}
	return replay, sub.ch, unsub
}

// Stats returns live subscriber & throughput counters.
func (b *Broker) Stats() Stats {
	b.mu.RLock()
	active := len(b.subs)
	buf := len(b.ring)
	b.mu.RUnlock()
	return Stats{
		ActiveSubscribers: active,
		PublishedTotal:    b.published.Load(),
		DeliveredTotal:    b.delivered.Load(),
		DroppedTotal:      b.dropped.Load(),
		BufferSize:        buf,
	}
}

// RegisterHTTP mounts GET /api/v1/realtime/stream (SSE) and GET /api/v1/realtime/stats.
func (b *Broker) RegisterHTTP(mux *http.ServeMux, auther Authenticator) {
	mux.HandleFunc("GET /api/v1/realtime/stream", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusUnauthorized)
			_ = json.NewEncoder(w).Encode(map[string]string{"error": "Sign in first."})
			return
		}
		// Clear server-wide WriteTimeout for this long-lived SSE connection only,
		// and use ResponseController so Flush unwraps through logging middleware.
		rc := http.NewResponseController(w)
		_ = rc.SetWriteDeadline(time.Time{})

		var lastSeq uint64
		if raw := strings.TrimSpace(r.Header.Get("Last-Event-ID")); raw != "" {
			if parsed, err := strconv.ParseUint(raw, 10, 64); err == nil {
				lastSeq = parsed
			}
		} else if raw := strings.TrimSpace(r.URL.Query().Get("last_event_id")); raw != "" {
			if parsed, err := strconv.ParseUint(raw, 10, 64); err == nil {
				lastSeq = parsed
			}
		}

		replay, ch, unsub := b.Subscribe(p, lastSeq)
		defer unsub()

		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache, no-store, must-revalidate")
		w.Header().Set("Connection", "keep-alive")
		w.Header().Set("X-Accel-Buffering", "no")
		w.WriteHeader(http.StatusOK)

		_, _ = fmt.Fprintf(w, "event: ready\ndata: {\"role\":%q,\"connected_at\":%q}\n\n", p.ActiveRole, b.now().UTC().Format(time.RFC3339))
		_ = rc.Flush()

		writeEvent := func(ev Event) error {
			raw, err := json.Marshal(ev)
			if err != nil {
				return err
			}
			if _, err := fmt.Fprintf(w, "id: %d\nevent: %s\ndata: %s\n\n", ev.Seq, ev.Type, raw); err != nil {
				return err
			}
			return rc.Flush()
		}

		for _, ev := range replay {
			if err := writeEvent(ev); err != nil {
				return
			}
		}

		ticker := time.NewTicker(heartbeatInterval)
		defer ticker.Stop()

		for {
			select {
			case <-r.Context().Done():
				return
			case ev := <-ch:
				if err := writeEvent(ev); err != nil {
					return
				}
			case <-ticker.C:
				if _, err := fmt.Fprint(w, ": ping\n\n"); err != nil {
					return
				}
				_ = rc.Flush()
			}
		}
	})

	mux.HandleFunc("GET /api/v1/realtime/stats", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusUnauthorized)
			_ = json.NewEncoder(w).Encode(map[string]string{"error": "Sign in first."})
			return
		}
		if p.ActiveRole != "Admin" {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusForbidden)
			_ = json.NewEncoder(w).Encode(map[string]string{"error": "Admin access required."})
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(b.Stats())
	})
}
