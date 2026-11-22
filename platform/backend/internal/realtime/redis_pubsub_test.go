package realtime

import (
	"bufio"
	"context"
	"fmt"
	"net"
	"strings"
	"sync"
	"testing"
	"time"
)

// startMockRedisPubSub spins up an in-process RESP2 Pub/Sub server to prove
// multi-replica SSE event fan-out and strict country/role isolation across
// independent Broker instances.
func startMockRedisPubSub(t *testing.T) string {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	t.Cleanup(func() { _ = ln.Close() })

	var (
		mu   sync.Mutex
		subs = map[string][]*bufio.Writer{}
	)

	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}
			go func(c net.Conn) {
				defer func() { _ = c.Close() }()
				br := bufio.NewReader(c)
				bw := bufio.NewWriter(c)
				var subChannel string
				defer func() {
					if subChannel != "" {
						mu.Lock()
						list := subs[subChannel]
						for i, w := range list {
							if w == bw {
								subs[subChannel] = append(list[:i], list[i+1:]...)
								break
							}
						}
						mu.Unlock()
					}
				}()
				for {
					val, err := readRESP(br)
					if err != nil {
						return
					}
					args, ok := val.([]any)
					if !ok || len(args) == 0 {
						continue
					}
					cmd := strings.ToUpper(fmt.Sprint(args[0]))
					switch cmd {
					case "SUBSCRIBE":
						if len(args) < 2 {
							continue
						}
						ch := fmt.Sprint(args[1])
						subChannel = ch
						mu.Lock()
						subs[ch] = append(subs[ch], bw)
						mu.Unlock()
						_ = writeRESP(bw, "subscribe", ch, "1")
						_ = bw.Flush()
					case "PUBLISH":
						if len(args) < 3 {
							continue
						}
						ch := fmt.Sprint(args[1])
						msg := fmt.Sprint(args[2])
						mu.Lock()
						targets := append([]*bufio.Writer(nil), subs[ch]...)
						mu.Unlock()
						for _, tw := range targets {
							_ = writeRESP(tw, "message", ch, msg)
							_ = tw.Flush()
						}
						_, _ = fmt.Fprintf(bw, ":%d\r\n", len(targets))
						_ = bw.Flush()
					default:
						_, _ = fmt.Fprintf(bw, "+OK\r\n")
						_ = bw.Flush()
					}
				}
			}(conn)
		}
	}()
	return "redis://" + ln.Addr().String()
}

func TestMultiReplicaRedisPubSubFanoutAndIsolation(t *testing.T) {
	redisURL := startMockRedisPubSub(t)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	nodeA := NewBroker(time.Now)
	nodeA.nodeID = "node-A"
	nodeB := NewBroker(time.Now)
	nodeB.nodeID = "node-B"

	if err := nodeA.WithRedisPubSub(ctx, redisURL, nil); err != nil {
		t.Fatalf("nodeA redis: %v", err)
	}
	if err := nodeB.WithRedisPubSub(ctx, redisURL, nil); err != nil {
		t.Fatalf("nodeB redis: %v", err)
	}
	// Give both subscribers a moment to establish SUBSCRIBE.
	time.Sleep(100 * time.Millisecond)

	ugPL := principal("pl-ug-1", "Program Lead", "UG")
	kePL := principal("pl-ke-1", "Program Lead", "KE")
	_, chUG, unsubUG := nodeB.Subscribe(ugPL, 0)
	defer unsubUG()
	_, chKE, unsubKE := nodeB.Subscribe(kePL, 0)
	defer unsubKE()

	_, chLocalA, unsubA := nodeA.Subscribe(ugPL, 0)
	defer unsubA()

	nodeA.Publish(Event{
		Type:        "escalation.created",
		EntityType:  "escalation",
		EntityID:    "esc-42",
		CountryCode: "UG",
		TargetRoles: []string{"Program Lead", "Admin"},
		ActorUserID: "cceo-ug-1",
		Summary:     "New escalation in Uganda",
	})

	// 1. Local subscriber on Node A receives exactly once (no echo loop).
	select {
	case ev := <-chLocalA:
		if ev.EntityID != "esc-42" {
			t.Fatalf("nodeA unexpected event: %+v", ev)
		}
	case <-time.After(time.Second):
		t.Fatal("timed out waiting for local event on nodeA")
	}

	// 2. Remote Uganda subscriber on Node B receives event via Redis Pub/Sub.
	select {
	case ev := <-chUG:
		if ev.EntityID != "esc-42" || ev.CountryCode != "UG" {
			t.Fatalf("nodeB unexpected event: %+v", ev)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for bridged event on nodeB")
	}

	// 3. Remote Kenya subscriber on Node B MUST NOT receive Uganda event, and Node A must not echo.
	select {
	case ev := <-chKE:
		t.Fatalf("cross-country leak to KE subscriber: %+v", ev)
	case ev := <-chLocalA:
		t.Fatalf("echo loop detected on nodeA: %+v", ev)
	case <-time.After(150 * time.Millisecond):
	}
}
