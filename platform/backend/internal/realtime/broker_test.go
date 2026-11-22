package realtime

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

type stubAuth struct {
	p   auth.Principal
	err error
}

func (s stubAuth) Authenticate(_ context.Context, _ string) (auth.Principal, error) {
	return s.p, s.err
}

func principal(userID, role, countryCode string) auth.Principal {
	p := auth.Principal{Account: auth.Account{UserID: userID, ActiveRole: role}}
	if countryCode != "" {
		p.Country = &country.Work{Code: countryCode}
	}
	return p
}

func TestBrokerRoleUserAndCountryIsolation(t *testing.T) {
	b := NewBroker(time.Now)

	_, ugPL, unsubUGPL := b.Subscribe(principal("pl-ug", "Program Lead", "UG"), 0)
	defer unsubUGPL()
	_, kePL, unsubKEPL := b.Subscribe(principal("pl-ke", "Program Lead", "KE"), 0)
	defer unsubKEPL()
	_, ugCCEO, unsubCCEO := b.Subscribe(principal("cceo-ug", "CCEO", "UG"), 0)
	defer unsubCCEO()

	// Publish UG Program Lead escalation event.
	b.Publish(Event{
		Type:        "escalation.raised",
		EntityType:  "leadership_escalation",
		EntityID:    "esc-1",
		CountryCode: "UG",
		TargetRoles: []string{"Program Lead", "Admin"},
		ActorUserID: "cceo-other",
	})

	select {
	case ev := <-ugPL:
		if ev.EntityID != "esc-1" {
			t.Fatalf("unexpected event: %+v", ev)
		}
	case <-time.After(time.Second):
		t.Fatal("expected UG PL to receive event")
	}

	// KE PL must NOT receive UG event (cross-country isolation).
	select {
	case ev := <-kePL:
		t.Fatalf("cross-country leak to KE PL: %+v", ev)
	default:
	}

	// UG CCEO must NOT receive PL-only event.
	select {
	case ev := <-ugCCEO:
		t.Fatalf("role leak to UG CCEO: %+v", ev)
	default:
	}

	// Direct user-targeted notification (message) goes ONLY to target user.
	b.Publish(Event{
		Type:         "message.sent",
		EntityType:   "messaging_thread",
		EntityID:     "thr-1",
		CountryCode:  "UG",
		TargetUserID: "cceo-ug",
		ActorUserID:  "pl-ug",
	})
	select {
	case ev := <-ugCCEO:
		if ev.EntityID != "thr-1" {
			t.Fatalf("unexpected direct message event: %+v", ev)
		}
	case <-time.After(time.Second):
		t.Fatal("expected UG CCEO to receive direct message")
	}
}

func TestBrokerLastEventIDReplay(t *testing.T) {
	b := NewBroker(time.Now)
	e1 := b.Publish(Event{Type: "a", EntityID: "1", CountryCode: "UG", TargetRoles: []string{"Admin"}})
	e2 := b.Publish(Event{Type: "b", EntityID: "2", CountryCode: "UG", TargetRoles: []string{"Admin"}})
	e3 := b.Publish(Event{Type: "c", EntityID: "3", CountryCode: "KE", TargetRoles: []string{"Admin"}})
	_ = e3

	replay, _, unsub := b.Subscribe(principal("adm-1", "Admin", "UG"), e1.Seq)
	defer unsub()
	if len(replay) != 1 || replay[0].Seq != e2.Seq {
		t.Fatalf("expected only UG event %d replayed, got %+v", e2.Seq, replay)
	}
}

func TestRegisterHTTPRequiresAuth(t *testing.T) {
	b := NewBroker(time.Now)
	mux := http.NewServeMux()
	b.RegisterHTTP(mux, stubAuth{err: errors.New("unauth")})

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/realtime/stream", nil)
	mux.ServeHTTP(rec, req)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("got %d, want 401", rec.Code)
	}

	// Non-admin cannot view broker stats.
	mux2 := http.NewServeMux()
	b.RegisterHTTP(mux2, stubAuth{p: principal("u1", "CCEO", "UG")})
	rec2 := httptest.NewRecorder()
	req2 := httptest.NewRequest(http.MethodGet, "/api/v1/realtime/stats", nil)
	mux2.ServeHTTP(rec2, req2)
	if rec2.Code != http.StatusForbidden {
		t.Fatalf("got %d, want 403", rec2.Code)
	}
}

func TestSSEStreamDeliversReadyAndLiveEvent(t *testing.T) {
	b := NewBroker(time.Now)
	mux := http.NewServeMux()
	b.RegisterHTTP(mux, stubAuth{p: principal("pl-1", "Program Lead", "UG")})

	ctx, cancel := context.WithCancel(context.Background())
	req := httptest.NewRequest(http.MethodGet, "/api/v1/realtime/stream", nil).WithContext(ctx)
	rec := httptest.NewRecorder()

	done := make(chan struct{})
	go func() {
		defer close(done)
		mux.ServeHTTP(rec, req)
	}()

	// Wait briefly for subscription to register, then publish and cancel.
	deadline := time.Now().Add(time.Second)
	for time.Now().Before(deadline) && b.Stats().ActiveSubscribers == 0 {
		time.Sleep(5 * time.Millisecond)
	}
	b.Publish(Event{
		Type:        "leave.requested",
		EntityType:  "leave",
		EntityID:    "lv-9",
		CountryCode: "UG",
		TargetRoles: []string{"Program Lead"},
	})
	time.Sleep(25 * time.Millisecond)
	cancel()
	<-done

	body := rec.Body.String()
	if !strings.Contains(body, "event: ready") || !strings.Contains(body, "event: leave.requested") || !strings.Contains(body, `"entity_id":"lv-9"`) {
		t.Fatalf("unexpected SSE body: %s", body)
	}
}
