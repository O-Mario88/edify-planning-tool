package trace

import (
	"context"
	"testing"
)

func TestStart(t *testing.T) {
	const (
		traceID = "4bf92f3577b34da6a3ce929d0e0e4736"
		spanID  = "00f067aa0ba902b7"
	)
	tests := []struct {
		name          string
		requestID     string
		traceparent   string
		keepRequestID bool
		continueTrace bool
	}{
		{name: "nothing supplied"},
		{name: "valid ids are continued", requestID: "req-12345678", traceparent: "00-" + traceID + "-" + spanID + "-01", keepRequestID: true, continueTrace: true},
		{name: "log injection in the request id is replaced", requestID: "abc\n{\"level\":\"ERROR\"}"},
		{name: "malformed traceparent starts a new trace", traceparent: "00-xyz-" + spanID + "-01"},
		{name: "all-zero trace id starts a new trace", traceparent: "00-00000000000000000000000000000000-" + spanID + "-01"},
		{name: "unknown version starts a new trace", traceparent: "ff-" + traceID + "-" + spanID + "-01"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			span := Start(test.requestID, test.traceparent)

			if (span.RequestID == test.requestID) != test.keepRequestID {
				t.Errorf("request id %q (supplied %q)", span.RequestID, test.requestID)
			}
			if !requestIDPattern.MatchString(span.RequestID) {
				t.Errorf("request id %q is not safe to log", span.RequestID)
			}
			if (span.TraceID == traceID) != test.continueTrace {
				t.Errorf("trace id %q", span.TraceID)
			}
			if test.continueTrace && span.ParentSpanID != spanID {
				t.Errorf("parent span %q", span.ParentSpanID)
			}
			if span.SpanID == spanID {
				t.Error("the caller's span id must not be reused")
			}
			if !traceparentPattern.MatchString(span.Traceparent()) {
				t.Errorf("outgoing traceparent %q is malformed", span.Traceparent())
			}
		})
	}
}

func TestContextRoundTrip(t *testing.T) {
	span := Start("", "")
	if got := FromContext(WithSpan(context.Background(), span)); got != span {
		t.Fatalf("got %+v, want %+v", got, span)
	}
	if got := FromContext(context.Background()); got != (Span{}) {
		t.Fatalf("a context without a span must return the zero Span, got %+v", got)
	}
}
