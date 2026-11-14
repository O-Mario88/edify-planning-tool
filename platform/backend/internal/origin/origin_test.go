package origin

import (
	"context"
	"net/http"
	"strings"
	"testing"
)

func TestTheCallerIsThePeerUnlessTheProxyIsTrusted(t *testing.T) {
	h := http.Header{}
	h.Set("X-Forwarded-For", "203.0.113.9, 10.0.0.1")
	h.Set("User-Agent", "EdifyApp/1")
	if got := Read("10.0.0.5:4431", h, false, "r1"); got != (Origin{IP: "10.0.0.5", UserAgent: "EdifyApp/1", CorrelationID: "r1"}) {
		t.Errorf("untrusted: %+v", got)
	}
	if got := Read("10.0.0.5:4431", h, true, "r1"); got.IP != "203.0.113.9" {
		t.Errorf("trusted: %+v", got)
	}
	h.Set("X-Forwarded-For", "not an address")
	if got := Read("10.0.0.5:4431", h, true, ""); got.IP != "" {
		t.Errorf("a forwarded value that is no address is dropped: %+v", got)
	}
	h.Set("User-Agent", strings.Repeat("a", 900))
	if got := Read("[::1]:80", h, false, ""); got.IP != "::1" || len(got.UserAgent) != maxAgentLength {
		t.Errorf("long agent or IPv6 peer: %q %d", got.IP, len(got.UserAgent))
	}
}

func TestTheContextCarriesTheOrigin(t *testing.T) {
	if _, ok := From(context.Background()); ok {
		t.Fatal("an empty context carries no origin")
	}
	o := Origin{IP: "127.0.0.1"}
	if got, ok := From(With(context.Background(), o)); !ok || got != o {
		t.Fatalf("%+v %v", got, ok)
	}
}
