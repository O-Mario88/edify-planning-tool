// Package httpmw holds the HTTP middleware every gateway request passes
// through: request tracing, structured access logs, panic recovery and
// response hardening headers.
package httpmw

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"runtime/debug"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trace"
)

// Chain applies the gateway's middleware to next, outermost first.
func Chain(logger *slog.Logger, next http.Handler) http.Handler {
	return Trace(AccessLog(logger, Recover(logger, SecurityHeaders(next))))
}

// Trace starts the request's span and echoes its ids on the response.
func Trace(next http.Handler) http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		span := trace.Start(
			request.Header.Get(trace.HeaderRequestID),
			request.Header.Get(trace.HeaderTraceparent),
		)
		writer.Header().Set(trace.HeaderRequestID, span.RequestID)
		writer.Header().Set(trace.HeaderTraceparent, span.Traceparent())
		next.ServeHTTP(writer, request.WithContext(trace.WithSpan(request.Context(), span)))
	})
}

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(status int) {
	r.status = status
	r.ResponseWriter.WriteHeader(status)
}

// Unwrap lets http.ResponseController reach the underlying writer.
func (r *statusRecorder) Unwrap() http.ResponseWriter {
	return r.ResponseWriter
}

// redactLogPath strips shared secrets embedded in webhook paths (such as
// /sms/delivery-report/{secret}) before they reach structured access logs.
func redactLogPath(path string) string {
	const smsPrefix = "/sms/delivery-report/"
	if strings.HasPrefix(path, smsPrefix) && len(path) > len(smsPrefix) {
		return smsPrefix + "[redacted]"
	}
	return path
}

// AccessLog writes one structured line per request. It never logs headers,
// query strings, webhook secrets or bodies, so no token or personal data
// reaches the log.
func AccessLog(logger *slog.Logger, next http.Handler) http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		started := time.Now()
		recorder := &statusRecorder{ResponseWriter: writer, status: http.StatusOK}
		next.ServeHTTP(recorder, request)

		span := trace.FromContext(request.Context())
		logger.LogAttrs(request.Context(), slog.LevelInfo, "request",
			slog.String("method", request.Method),
			slog.String("path", redactLogPath(request.URL.Path)),
			slog.Int("status", recorder.status),
			slog.Duration("duration", time.Since(started)),
			slog.String("request_id", span.RequestID),
			slog.String("trace_id", span.TraceID),
			slog.String("span_id", span.SpanID),
			slog.String("parent_span_id", span.ParentSpanID),
		)
	})
}

// Recover turns a panic into a structured 500 and logs the stack.
func Recover(logger *slog.Logger, next http.Handler) http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		defer func() {
			recovered := recover()
			if recovered == nil {
				return
			}
			span := trace.FromContext(request.Context())
			logger.ErrorContext(request.Context(), "panic",
				slog.Any("panic", recovered),
				slog.String("stack", string(debug.Stack())),
				slog.String("request_id", span.RequestID),
				slog.String("trace_id", span.TraceID),
			)
			WriteJSON(writer, http.StatusInternalServerError, map[string]string{
				"code":       "internal",
				"message":    "Something went wrong on our side. Please try again.",
				"request_id": span.RequestID,
			})
		}()
		next.ServeHTTP(writer, request)
	})
}

// SecurityHeaders sets headers that are right for a JSON/protobuf API.
func SecurityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		header := writer.Header()
		header.Set("X-Content-Type-Options", "nosniff")
		header.Set("Cache-Control", "no-store")
		header.Set("Referrer-Policy", "no-referrer")
		next.ServeHTTP(writer, request)
	})
}

const (
	corsAllowedMethods = "POST, GET, OPTIONS"
	corsAllowedHeaders = "Authorization, Content-Type, Connect-Protocol-Version, Connect-Timeout-Ms, X-Request-Id, traceparent"
	corsExposedHeaders = "X-Request-Id, traceparent"
	corsMaxAgeSeconds  = "600"
)

// CORS answers browsers from an explicit list of origins. With an empty list
// it adds nothing, which is the default: a native app sends no Origin and
// needs none of this. Credentials (cookies) are never allowed; the gateway
// authenticates by bearer token only.
func CORS(allowedOrigins []string, next http.Handler) http.Handler {
	if len(allowedOrigins) == 0 {
		return next
	}
	allowed := make(map[string]bool, len(allowedOrigins))
	for _, origin := range allowedOrigins {
		allowed[origin] = true
	}
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		origin := request.Header.Get("Origin")
		header := writer.Header()
		header.Add("Vary", "Origin")
		if !allowed[origin] {
			// Not an allowed origin: no CORS headers, so the browser blocks
			// the page from reading the answer. A preflight gets a refusal.
			if request.Method == http.MethodOptions && request.Header.Get("Access-Control-Request-Method") != "" {
				writer.WriteHeader(http.StatusForbidden)
				return
			}
			next.ServeHTTP(writer, request)
			return
		}
		header.Set("Access-Control-Allow-Origin", origin)
		header.Set("Access-Control-Expose-Headers", corsExposedHeaders)
		if request.Method == http.MethodOptions && request.Header.Get("Access-Control-Request-Method") != "" {
			header.Set("Access-Control-Allow-Methods", corsAllowedMethods)
			header.Set("Access-Control-Allow-Headers", corsAllowedHeaders)
			header.Set("Access-Control-Max-Age", corsMaxAgeSeconds)
			writer.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(writer, request)
	})
}

// WriteJSON writes body as JSON with the given status.
func WriteJSON(writer http.ResponseWriter, status int, body any) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	// The response is already committed; an encode error has no recipient.
	_ = json.NewEncoder(writer).Encode(body)
}
