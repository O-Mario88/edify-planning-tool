package realtime

import (
	"bufio"
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/url"
	"strconv"
	"strings"
	"time"
)

const redisChannel = "edify:realtime:events"

// wireEnvelope carries the full authorization routing metadata across gateway
// replicas over Redis Pub/Sub so remote nodes enforce identical country, user,
// and role isolation while avoiding self-echo loops via NodeID.
type wireEnvelope struct {
	NodeID       string   `json:"node_id"`
	EventID      string   `json:"event_id"`
	Type         string   `json:"type"`
	EntityType   string   `json:"entity_type"`
	EntityID     string   `json:"entity_id"`
	CountryCode  string   `json:"country_code,omitempty"`
	TargetUserID string   `json:"target_user_id,omitempty"`
	TargetRoles  []string `json:"target_roles,omitempty"`
	ActorUserID  string   `json:"actor_user_id,omitempty"`
	Summary      string   `json:"summary,omitempty"`
	OccurredAt   string   `json:"occurred_at"`
}

type redisPubSub struct {
	addr     string
	username string
	password string
	db       int
	useTLS   bool
	timeout  time.Duration
	logger   *slog.Logger
}

// WithRedisPubSub attaches a pure-Go RESP2 Redis Pub/Sub bridge to b for
// multi-replica SSE event synchronization. When rawURL is empty it is a no-op
// (single-node in-memory mode). The subscriber goroutine exits cleanly when
// ctx is cancelled.
func (b *Broker) WithRedisPubSub(ctx context.Context, rawURL string, logger *slog.Logger) error {
	rawURL = strings.TrimSpace(rawURL)
	if rawURL == "" {
		return nil
	}
	ps, err := parseRedisPubSub(rawURL, logger)
	if err != nil {
		return err
	}
	b.mu.Lock()
	b.pubsub = ps
	b.mu.Unlock()
	go b.runRedisSubscriber(ctx, ps)
	return nil
}

func parseRedisPubSub(rawURL string, logger *slog.Logger) (*redisPubSub, error) {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return nil, fmt.Errorf("realtime: invalid redis url")
	}
	if parsed.Scheme != "redis" && parsed.Scheme != "rediss" {
		return nil, fmt.Errorf("realtime: redis scheme must be redis or rediss (got %q)", parsed.Scheme)
	}
	host := parsed.Hostname()
	if host == "" {
		return nil, fmt.Errorf("realtime: redis url missing host")
	}
	port := parsed.Port()
	if port == "" {
		port = "6379"
	}
	var db int
	if p := strings.TrimPrefix(parsed.Path, "/"); p != "" {
		n, err := strconv.Atoi(p)
		if err != nil || n < 0 {
			return nil, fmt.Errorf("realtime: invalid redis db index %q", p)
		}
		db = n
	}
	var username, password string
	if parsed.User != nil {
		username = parsed.User.Username()
		password, _ = parsed.User.Password()
	}
	return &redisPubSub{
		addr:     net.JoinHostPort(host, port),
		username: username,
		password: password,
		db:       db,
		useTLS:   parsed.Scheme == "rediss",
		timeout:  3 * time.Second,
		logger:   logger,
	}, nil
}

func (ps *redisPubSub) dial(ctx context.Context) (net.Conn, error) {
	d := &net.Dialer{Timeout: ps.timeout}
	if ps.useTLS {
		host, _, _ := net.SplitHostPort(ps.addr)
		return tls.DialWithDialer(d, "tcp", ps.addr, &tls.Config{
			ServerName: host,
			MinVersion: tls.VersionTLS12,
		})
	}
	return d.DialContext(ctx, "tcp", ps.addr)
}

func (ps *redisPubSub) handshake(br *bufio.Reader, bw *bufio.Writer) error {
	send := func(args ...string) error {
		if err := writeRESP(bw, args...); err != nil {
			return err
		}
		if err := bw.Flush(); err != nil {
			return err
		}
		_, err := readRESP(br)
		return err
	}
	if ps.password != "" {
		if ps.username != "" {
			if err := send("AUTH", ps.username, ps.password); err != nil {
				return err
			}
		} else if err := send("AUTH", ps.password); err != nil {
			return err
		}
	}
	if ps.db > 0 {
		if err := send("SELECT", strconv.Itoa(ps.db)); err != nil {
			return err
		}
	}
	return nil
}

func (ps *redisPubSub) publish(nodeID string, ev Event) {
	ctx, cancel := context.WithTimeout(context.Background(), ps.timeout)
	defer cancel()
	payload, err := json.Marshal(wireEnvelope{
		NodeID:       nodeID,
		EventID:      ev.EventID,
		Type:         ev.Type,
		EntityType:   ev.EntityType,
		EntityID:     ev.EntityID,
		CountryCode:  ev.CountryCode,
		TargetUserID: ev.TargetUserID,
		TargetRoles:  ev.TargetRoles,
		ActorUserID:  ev.ActorUserID,
		Summary:      ev.Summary,
		OccurredAt:   ev.OccurredAt,
	})
	if err != nil {
		return
	}
	conn, err := ps.dial(ctx)
	if err != nil {
		if ps.logger != nil {
			ps.logger.Warn("realtime: redis publish dial failed", slog.String("error", err.Error()))
		}
		return
	}
	defer func() { _ = conn.Close() }()
	_ = conn.SetDeadline(time.Now().Add(ps.timeout))

	br := bufio.NewReader(conn)
	bw := bufio.NewWriter(conn)
	if err := ps.handshake(br, bw); err != nil {
		return
	}
	if err := writeRESP(bw, "PUBLISH", redisChannel, string(payload)); err != nil {
		return
	}
	if err := bw.Flush(); err != nil {
		return
	}
	_, _ = readRESP(br)
}

func (b *Broker) runRedisSubscriber(ctx context.Context, ps *redisPubSub) {
	backoff := 200 * time.Millisecond
	for {
		if ctx.Err() != nil {
			return
		}
		err := b.subscribeOnce(ctx, ps)
		if ctx.Err() != nil {
			return
		}
		if err != nil && ps.logger != nil {
			ps.logger.Warn("realtime: redis pubsub disconnected, reconnecting", slog.String("error", err.Error()))
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(backoff):
		}
		if backoff < 5*time.Second {
			backoff *= 2
		}
	}
}

func (b *Broker) subscribeOnce(ctx context.Context, ps *redisPubSub) error {
	conn, err := ps.dial(ctx)
	if err != nil {
		return err
	}
	done := make(chan struct{})
	defer close(done)
	go func() {
		select {
		case <-ctx.Done():
			_ = conn.Close()
		case <-done:
		}
	}()
	defer func() { _ = conn.Close() }()

	br := bufio.NewReader(conn)
	bw := bufio.NewWriter(conn)
	_ = conn.SetDeadline(time.Now().Add(ps.timeout))
	if err := ps.handshake(br, bw); err != nil {
		return err
	}
	if err := writeRESP(bw, "SUBSCRIBE", redisChannel); err != nil {
		return err
	}
	if err := bw.Flush(); err != nil {
		return err
	}
	// Clear deadline for long-lived subscription stream.
	_ = conn.SetDeadline(time.Time{})

	for {
		val, err := readRESP(br)
		if err != nil {
			return err
		}
		items, ok := val.([]any)
		if !ok || len(items) != 3 {
			continue
		}
		kind, _ := items[0].(string)
		if kind != "message" {
			continue
		}
		raw, _ := items[2].(string)
		var env wireEnvelope
		if err := json.Unmarshal([]byte(raw), &env); err != nil {
			continue
		}
		if env.NodeID == b.nodeID {
			continue
		}
		b.publishLocal(Event{
			EventID:      env.EventID,
			Type:         env.Type,
			EntityType:   env.EntityType,
			EntityID:     env.EntityID,
			CountryCode:  env.CountryCode,
			TargetUserID: env.TargetUserID,
			TargetRoles:  env.TargetRoles,
			ActorUserID:  env.ActorUserID,
			Summary:      env.Summary,
			OccurredAt:   env.OccurredAt,
		})
	}
}

func writeRESP(w *bufio.Writer, args ...string) error {
	if _, err := fmt.Fprintf(w, "*%d\r\n", len(args)); err != nil {
		return err
	}
	for _, arg := range args {
		if _, err := fmt.Fprintf(w, "$%d\r\n%s\r\n", len(arg), arg); err != nil {
			return err
		}
	}
	return nil
}

func readRESP(r *bufio.Reader) (any, error) {
	line, err := r.ReadString('\n')
	if err != nil {
		return nil, err
	}
	line = strings.TrimSuffix(line, "\r\n")
	if len(line) == 0 {
		return nil, errors.New("realtime: empty redis reply")
	}
	switch line[0] {
	case '+':
		return line[1:], nil
	case '-':
		return nil, fmt.Errorf("realtime: redis error: %s", line[1:])
	case ':':
		return strconv.ParseInt(line[1:], 10, 64)
	case '$':
		n, err := strconv.Atoi(line[1:])
		if err != nil {
			return nil, err
		}
		if n < 0 {
			return nil, nil
		}
		buf := make([]byte, n+2)
		if _, err := io.ReadFull(r, buf); err != nil {
			return nil, err
		}
		return string(buf[:n]), nil
	case '*':
		n, err := strconv.Atoi(line[1:])
		if err != nil {
			return nil, err
		}
		if n < 0 {
			return nil, nil
		}
		items := make([]any, n)
		for i := 0; i < n; i++ {
			v, err := readRESP(r)
			if err != nil {
				return nil, err
			}
			items[i] = v
		}
		return items, nil
	default:
		return nil, fmt.Errorf("realtime: unsupported RESP prefix %q", line[0])
	}
}
