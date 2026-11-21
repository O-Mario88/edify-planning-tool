package screens

import (
	"context"
	"log/slog"
	"regexp"
	"strings"
	"sync"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trace"
)

// FallbackOutcome classifies an attempted call to the existing Django app.
// A blocked or failed attempt still counts as an attempted Django dependency.
type FallbackOutcome string

const (
	FallbackForwarded FallbackOutcome = "forwarded"
	FallbackBlocked   FallbackOutcome = "blocked"
	FallbackFailed    FallbackOutcome = "failed"
)

// FallbackKey identifies a stable (service, operation, outcome) counter.
type FallbackKey struct {
	Service   string
	Operation string
	Outcome   FallbackOutcome
}

// FallbackTracker counts every attempted call from Go screens to the existing
// Django application, keyed by stable operation and outcome. It is safe for
// concurrent use.
type FallbackTracker struct {
	mu     sync.Mutex
	counts map[FallbackKey]int64
}

var globalFallbackTracker = NewFallbackTracker()

// GlobalFallbackTracker returns the process-wide Django fallback attempt
// counter aggregated across all screens.Service instances.
func GlobalFallbackTracker() *FallbackTracker {
	return globalFallbackTracker
}

// NewFallbackTracker returns an empty tracker.
func NewFallbackTracker() *FallbackTracker {
	return &FallbackTracker{counts: make(map[FallbackKey]int64)}
}

var idSegment = regexp.MustCompile(`/[A-Za-z0-9_-]{16,}`)

// redactPath strips query strings (which may hold search text, emails or
// tokens) and replaces long identifier segments with /{id}.
func redactPath(raw string) string {
	path, _, _ := strings.Cut(raw, "?")
	return idSegment.ReplaceAllString(path, "/{id}")
}

// operationForPath derives a stable (service, operation) pair from a mobile
// feed path.
func operationForPath(method, rawPath string) (service, op string) {
	redacted := redactPath(rawPath)
	switch {
	case strings.HasPrefix(redacted, pathHome):
		return "HomeScreenService", method + " " + redacted
	case redacted == pathNavigation:
		return "NavigationService", method + " " + redacted
	case redacted == pathSchoolDirectory:
		return "SchoolDirectoryScreenService", method + " " + redacted
	case strings.HasPrefix(redacted, pathPageDrawer), strings.Contains(redacted, "/drawers/"):
		return "DrawerService", method + " " + redacted
	case strings.Contains(redacted, "/planning/"):
		return "PlanningDrawerService", method + " " + redacted
	case strings.HasPrefix(redacted, pathExports):
		return "ExportService", method + " /api/mobile/v1/exports/{id}"
	case redacted == pathPage:
		return "PageScreenService", method + " " + redacted
	default:
		return "ScreensService", method + " " + redacted
	}
}

// Record increments the counter for (service, operation, outcome) and emits a
// structured warning with correlated trace identifiers and redacted path.
func (t *FallbackTracker) Record(
	ctx context.Context, logger *slog.Logger, method, rawPath string, outcome FallbackOutcome,
) {
	service, op := operationForPath(method, rawPath)
	key := FallbackKey{Service: service, Operation: op, Outcome: outcome}
	if t != nil {
		t.mu.Lock()
		t.counts[key]++
		t.mu.Unlock()
	}
	if t != globalFallbackTracker {
		globalFallbackTracker.mu.Lock()
		globalFallbackTracker.counts[key]++
		globalFallbackTracker.mu.Unlock()
	}
	if logger != nil {
		span := trace.FromContext(ctx)
		logger.WarnContext(ctx, "screens: django fallback attempt",
			slog.String("service", service),
			slog.String("operation", op),
			slog.String("outcome", string(outcome)),
			slog.String("request_id", span.RequestID),
			slog.String("trace_id", span.TraceID),
		)
	}
}

// Counts returns a snapshot copy of all recorded fallback attempts.
func (t *FallbackTracker) Counts() map[FallbackKey]int64 {
	out := make(map[FallbackKey]int64)
	if t == nil {
		return out
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	for k, v := range t.counts {
		out[k] = v
	}
	return out
}

// Total returns the sum of all recorded fallback attempts (forwarded, blocked,
// and failed).
func (t *FallbackTracker) Total() int64 {
	if t == nil {
		return 0
	}
	t.mu.Lock()
	defer t.mu.Unlock()
	var total int64
	for _, v := range t.counts {
		total += v
	}
	return total
}

// Reset clears all recorded counts.
func (t *FallbackTracker) Reset() {
	if t == nil {
		return
	}
	t.mu.Lock()
	clear(t.counts)
	t.mu.Unlock()
}
