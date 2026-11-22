package cache

import (
	"bufio"
	"context"
	"crypto/tls"
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

// RedisStore speaks standard RESP2 over TCP/TLS with zero third-party
// dependencies. If a Redis round-trip fails during Allow, it degrades to a
// local fallback limiter so transient network blips never lock out sign-ins.
type RedisStore struct {
	addr     string
	username string
	password string
	db       int
	useTLS   bool
	timeout  time.Duration
	logger   *slog.Logger
	fallback *MemoryStore
}

// NewRedis parses a redis:// or rediss:// URL.
func NewRedis(rawURL string, logger *slog.Logger) (*RedisStore, error) {
	parsed, err := url.Parse(strings.TrimSpace(rawURL))
	if err != nil {
		return nil, fmt.Errorf("cache: invalid redis url")
	}
	if parsed.Scheme != "redis" && parsed.Scheme != "rediss" {
		return nil, fmt.Errorf("cache: redis url scheme must be redis or rediss (got %q)", parsed.Scheme)
	}
	host := parsed.Hostname()
	if host == "" {
		return nil, fmt.Errorf("cache: redis url missing host")
	}
	port := parsed.Port()
	if port == "" {
		port = "6379"
	}
	var db int
	if path := strings.TrimPrefix(parsed.Path, "/"); path != "" {
		n, convErr := strconv.Atoi(path)
		if convErr != nil || n < 0 {
			return nil, fmt.Errorf("cache: invalid redis db index %q", path)
		}
		db = n
	}
	var username, password string
	if parsed.User != nil {
		username = parsed.User.Username()
		password, _ = parsed.User.Password()
	}
	return &RedisStore{
		addr:     net.JoinHostPort(host, port),
		username: username,
		password: password,
		db:       db,
		useTLS:   parsed.Scheme == "rediss",
		timeout:  3 * time.Second,
		logger:   logger,
		fallback: NewMemory(time.Now),
	}, nil
}

func (r *RedisStore) Backend() string { return "redis" }

func (r *RedisStore) dial(ctx context.Context) (net.Conn, error) {
	dialer := &net.Dialer{Timeout: r.timeout}
	var (
		conn net.Conn
		err  error
	)
	if r.useTLS {
		host, _, _ := net.SplitHostPort(r.addr)
		conn, err = tls.DialWithDialer(dialer, "tcp", r.addr, &tls.Config{
			ServerName: host,
			MinVersion: tls.VersionTLS12,
		})
	} else {
		conn, err = dialer.DialContext(ctx, "tcp", r.addr)
	}
	if err != nil {
		return nil, err
	}
	_ = conn.SetDeadline(time.Now().Add(r.timeout))
	return conn, nil
}

func (r *RedisStore) exec(ctx context.Context, args ...string) (any, error) {
	conn, err := r.dial(ctx)
	if err != nil {
		return nil, err
	}
	defer func() { _ = conn.Close() }()

	br := bufio.NewReader(conn)
	bw := bufio.NewWriter(conn)

	send := func(cmd ...string) (any, error) {
		if err := writeCommand(bw, cmd...); err != nil {
			return nil, err
		}
		if err := bw.Flush(); err != nil {
			return nil, err
		}
		return readReply(br)
	}

	if r.password != "" {
		if r.username != "" {
			if _, err := send("AUTH", r.username, r.password); err != nil {
				return nil, err
			}
		} else {
			if _, err := send("AUTH", r.password); err != nil {
				return nil, err
			}
		}
	}
	if r.db > 0 {
		if _, err := send("SELECT", strconv.Itoa(r.db)); err != nil {
			return nil, err
		}
	}
	return send(args...)
}

func (r *RedisStore) Ping(ctx context.Context) error {
	_, err := r.exec(ctx, "PING")
	return err
}

func (r *RedisStore) Get(ctx context.Context, key string) (string, bool, error) {
	reply, err := r.exec(ctx, "GET", key)
	if err != nil {
		return "", false, err
	}
	if reply == nil {
		return "", false, nil
	}
	s, ok := reply.(string)
	return s, ok, nil
}

func (r *RedisStore) Set(ctx context.Context, key, value string, ttl time.Duration) error {
	if ttl > 0 {
		secs := max(1, int(ttl.Seconds()))
		_, err := r.exec(ctx, "SET", key, value, "EX", strconv.Itoa(secs))
		return err
	}
	_, err := r.exec(ctx, "SET", key, value)
	return err
}

func (r *RedisStore) Delete(ctx context.Context, key string) error {
	_, err := r.exec(ctx, "DEL", key)
	return err
}

// Allow increments a fixed-window counter in Redis and sets expiry on the
// first hit. Falls back to MemoryStore if Redis is temporarily unreachable.
func (r *RedisStore) Allow(key string, limit int, period time.Duration) bool {
	if limit <= 0 {
		return false
	}
	ctx, cancel := context.WithTimeout(context.Background(), r.timeout)
	defer cancel()
	rk := "edify:rl:" + key
	reply, err := r.exec(ctx, "INCR", rk)
	if err != nil {
		if r.logger != nil {
			r.logger.Warn("cache: redis rate limit unavailable, using local fallback", slog.String("error", err.Error()))
		}
		return r.fallback.Allow(key, limit, period)
	}
	count, ok := reply.(int64)
	if !ok {
		return r.fallback.Allow(key, limit, period)
	}
	if count == 1 {
		secs := max(1, int(period.Seconds()))
		_, _ = r.exec(ctx, "EXPIRE", rk, strconv.Itoa(secs))
	}
	return int(count) <= limit
}

func writeCommand(w *bufio.Writer, args ...string) error {
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

func readReply(r *bufio.Reader) (any, error) {
	line, err := r.ReadString('\n')
	if err != nil {
		return nil, err
	}
	line = strings.TrimSuffix(line, "\r\n")
	if len(line) == 0 {
		return nil, errors.New("cache: empty redis reply")
	}
	switch line[0] {
	case '+':
		return line[1:], nil
	case '-':
		return nil, fmt.Errorf("cache: redis error: %s", line[1:])
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
	default:
		return nil, fmt.Errorf("cache: unsupported RESP prefix %q", line[0])
	}
}
