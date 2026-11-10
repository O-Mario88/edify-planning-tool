// Package trace carries a request's identity through the gateway: a request
// id for support, and a W3C Trace Context (traceparent) so a call can be
// followed from the mobile app through the gateway into a worker.
package trace

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"regexp"
	"strings"
)

const (
	// HeaderRequestID is echoed on every response.
	HeaderRequestID = "X-Request-Id"
	// HeaderTraceparent is the W3C Trace Context header.
	HeaderTraceparent = "traceparent"

	traceIDBytes = 16
	spanIDBytes  = 8
	version      = "00"
	flagSampled  = "01"
)

var (
	requestIDPattern   = regexp.MustCompile(`^[A-Za-z0-9_-]{8,64}$`)
	traceparentPattern = regexp.MustCompile(`^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$`)
	zeroTraceID        = strings.Repeat("0", traceIDBytes*2)
	zeroSpanID         = strings.Repeat("0", spanIDBytes*2)
)

// Span identifies one request inside one trace.
type Span struct {
	RequestID string
	TraceID   string
	SpanID    string
	// ParentSpanID is the caller's span, empty when this request starts the trace.
	ParentSpanID string
}

// Traceparent renders the span as an outgoing W3C traceparent header.
func (s Span) Traceparent() string {
	return version + "-" + s.TraceID + "-" + s.SpanID + "-" + flagSampled
}

// Start builds the span for an incoming request. A valid caller-supplied
// request id and traceparent are continued; anything else is replaced, so a
// client can never inject arbitrary text into the logs.
func Start(incomingRequestID, incomingTraceparent string) Span {
	span := Span{RequestID: incomingRequestID, SpanID: randomHex(spanIDBytes)}
	if !requestIDPattern.MatchString(span.RequestID) {
		span.RequestID = randomHex(traceIDBytes)
	}
	traceID, parentSpanID, ok := parseTraceparent(incomingTraceparent)
	if !ok {
		span.TraceID = randomHex(traceIDBytes)
		return span
	}
	span.TraceID = traceID
	span.ParentSpanID = parentSpanID
	return span
}

func parseTraceparent(header string) (traceID, spanID string, ok bool) {
	match := traceparentPattern.FindStringSubmatch(strings.TrimSpace(header))
	if match == nil || match[1] == zeroTraceID || match[2] == zeroSpanID {
		return "", "", false
	}
	return match[1], match[2], true
}

func randomHex(size int) string {
	buffer := make([]byte, size)
	// crypto/rand.Read never returns an error on supported platforms.
	_, _ = rand.Read(buffer)
	return hex.EncodeToString(buffer)
}

type contextKey struct{}

// WithSpan returns a context carrying span.
func WithSpan(ctx context.Context, span Span) context.Context {
	return context.WithValue(ctx, contextKey{}, span)
}

// FromContext returns the span of the current request, or a zero Span.
func FromContext(ctx context.Context) Span {
	span, _ := ctx.Value(contextKey{}).(Span)
	return span
}
