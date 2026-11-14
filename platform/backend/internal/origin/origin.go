// Package origin carries the request facts the audit chain records beside an
// act (apps.core.middleware's request context: the caller's address, their
// browser and the request's correlation id) from the Connect handler to the
// code that appends the row, for a read that is itself audited.
package origin

import (
	"context"
	"net"
	"net/http"
	"strings"
)

// maxAgentLength is the longest user agent kept, as sign-in keeps it.
const maxAgentLength = 512

// Origin is one request's facts. An empty field is one the request did not
// give.
type Origin struct {
	IP, UserAgent, CorrelationID string
}

type key struct{}

// With returns ctx carrying o.
func With(ctx context.Context, o Origin) context.Context { return context.WithValue(ctx, key{}, o) }

// From is the origin ctx carries; false when none was set.
func From(ctx context.Context) (Origin, bool) {
	o, ok := ctx.Value(key{}).(Origin)
	return o, ok
}

// Read is the caller as the gateway sees it: the peer's address (the first
// X-Forwarded-For entry when the gateway trusts its proxy), its user agent
// and the request's id.
func Read(peerAddr string, header http.Header, trustProxy bool, requestID string) Origin {
	address := peerAddr
	if host, _, err := net.SplitHostPort(address); err == nil {
		address = host
	}
	if trustProxy {
		if forwarded := header.Get("X-Forwarded-For"); forwarded != "" {
			address = strings.TrimSpace(strings.Split(forwarded, ",")[0])
		}
	}
	if net.ParseIP(address) == nil {
		address = ""
	}
	agent := header.Get("User-Agent")
	if len(agent) > maxAgentLength {
		agent = agent[:maxAgentLength]
	}
	return Origin{IP: address, UserAgent: agent, CorrelationID: requestID}
}
