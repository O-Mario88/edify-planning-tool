package cache

import (
	"bufio"
	"context"
	"fmt"
	"net"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestMemoryStoreCacheAndRateLimit(t *testing.T) {
	now := time.Date(2026, 11, 22, 10, 0, 0, 0, time.UTC)
	m := NewMemory(func() time.Time { return now })
	ctx := context.Background()

	if err := m.Set(ctx, "route:1", "ok", 5*time.Minute); err != nil {
		t.Fatalf("set: %v", err)
	}
	if v, ok, _ := m.Get(ctx, "route:1"); !ok || v != "ok" {
		t.Fatalf("get: got (%q, %v)", v, ok)
	}
	now = now.Add(6 * time.Minute)
	if _, ok, _ := m.Get(ctx, "route:1"); ok {
		t.Fatal("expected expired entry to miss")
	}

	if !m.Allow("ip1", 2, time.Minute) || !m.Allow("ip1", 2, time.Minute) {
		t.Fatal("first two hits should be allowed")
	}
	if m.Allow("ip1", 2, time.Minute) {
		t.Fatal("third hit should be rate-limited")
	}
	now = now.Add(2 * time.Minute)
	if !m.Allow("ip1", 2, time.Minute) {
		t.Fatal("hit after window reset should be allowed")
	}
}

func TestRedisStoreAgainstMockRESPServer(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	defer func() { _ = ln.Close() }()

	var mu sync.Mutex
	kv := map[string]string{}
	counters := map[string]int64{}

	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) {
				defer func() { _ = c.Close() }()
				r := bufio.NewReader(c)
				for {
					hdr, err := r.ReadString('\n')
					if err != nil {
						return
					}
					n, _ := strconv.Atoi(strings.TrimSpace(strings.TrimPrefix(hdr, "*")))
					args := make([]string, 0, n)
					for i := 0; i < n; i++ {
						_, _ = r.ReadString('\n')
						val, _ := r.ReadString('\n')
						args = append(args, strings.TrimSuffix(val, "\r\n"))
					}
					if len(args) == 0 {
						return
					}
					cmd := strings.ToUpper(args[0])
					mu.Lock()
					switch cmd {
					case "PING":
						_, _ = fmt.Fprint(c, "+PONG\r\n")
					case "AUTH", "SELECT", "EXPIRE":
						_, _ = fmt.Fprint(c, "+OK\r\n")
					case "SET":
						kv[args[1]] = args[2]
						_, _ = fmt.Fprint(c, "+OK\r\n")
					case "GET":
						if v, ok := kv[args[1]]; ok {
							_, _ = fmt.Fprintf(c, "$%d\r\n%s\r\n", len(v), v)
						} else {
							_, _ = fmt.Fprint(c, "$-1\r\n")
						}
					case "DEL":
						delete(kv, args[1])
						_, _ = fmt.Fprint(c, ":1\r\n")
					case "INCR":
						counters[args[1]]++
						_, _ = fmt.Fprintf(c, ":%d\r\n", counters[args[1]])
					}
					mu.Unlock()
				}
			}(conn)
		}
	}()

	store, err := NewRedis("redis://:secret@"+ln.Addr().String()+"/2", nil)
	if err != nil {
		t.Fatalf("NewRedis: %v", err)
	}
	ctx := context.Background()
	if err := store.Ping(ctx); err != nil {
		t.Fatalf("Ping: %v", err)
	}
	if err := store.Set(ctx, "k1", "hello", 30*time.Second); err != nil {
		t.Fatalf("Set: %v", err)
	}
	if v, ok, err := store.Get(ctx, "k1"); err != nil || !ok || v != "hello" {
		t.Fatalf("Get: (%q, %v, %v)", v, ok, err)
	}
	if err := store.Delete(ctx, "k1"); err != nil {
		t.Fatalf("Delete: %v", err)
	}
	if _, ok, _ := store.Get(ctx, "k1"); ok {
		t.Fatal("expected deleted key to miss")
	}
	if !store.Allow("login|1.2.3.4", 2, time.Minute) || !store.Allow("login|1.2.3.4", 2, time.Minute) {
		t.Fatal("first two redis rate-limit hits should pass")
	}
	if store.Allow("login|1.2.3.4", 2, time.Minute) {
		t.Fatal("third redis rate-limit hit should be blocked")
	}
}
