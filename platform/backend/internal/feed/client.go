// Package feed reads screen view-models from the existing Edify application.
//
// It forwards the caller's own verified access token, so the existing
// application applies its own permission and scope rules to the same person,
// and it decodes the answer strictly against the Protocol Buffer contract: a
// field the contract does not know is an error, not something passed on.
package feed

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trace"
)

const (
	// A Programme Lead's Home queue takes several seconds on the existing
	// application; the page itself waits for it.
	requestTimeout  = 25 * time.Second
	maxResponseSize = 4 << 20
)

// Client calls the existing application's screen feeds.
type Client struct {
	baseURL string
	http    *http.Client
	logger  *slog.Logger
}

// NewClient returns a client for the existing application at baseURL, which
// config has already confirmed belongs to this environment.
func NewClient(baseURL string, logger *slog.Logger) *Client {
	return &Client{
		baseURL: baseURL,
		logger:  logger,
		http: &http.Client{
			Timeout: requestTimeout,
			// A feed never redirects; following one could carry the token
			// to another host.
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
		},
	}
}

// Get reads path into out. Every error is a structured API error.
func (c *Client) Get(ctx context.Context, path string, out proto.Message) error {
	return c.do(ctx, http.MethodGet, path, nil, out)
}

// Post sends in to path as the contract's JSON and reads the answer into out.
func (c *Client) Post(ctx context.Context, path string, in, out proto.Message) error {
	body, err := protojson.Marshal(in)
	if err != nil {
		return c.unavailable(ctx, fmt.Errorf("encoding the request: %w", err))
	}
	return c.do(ctx, http.MethodPost, path, body, out)
}

func (c *Client) do(ctx context.Context, method, path string, payload []byte, out proto.Message) error {
	var reader io.Reader
	if payload != nil {
		reader = bytes.NewReader(payload)
	}
	request, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, reader)
	if err != nil {
		return c.unavailable(ctx, fmt.Errorf("building the request: %w", err))
	}
	if payload != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	request.Header.Set("Authorization", "Bearer "+auth.BearerFrom(ctx))
	request.Header.Set("Accept", "application/json")
	if span := trace.FromContext(ctx); span.TraceID != "" {
		request.Header.Set(trace.HeaderTraceparent, span.Traceparent())
		request.Header.Set(trace.HeaderRequestID, span.RequestID)
	}

	response, err := c.http.Do(request)
	if err != nil {
		return c.unavailable(ctx, fmt.Errorf("calling the existing application: %w", err))
	}
	defer func() { _ = response.Body.Close() }()

	switch {
	case response.StatusCode == http.StatusUnauthorized:
		return apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthInvalid,
			"Your session has expired. Please sign in again.")
	case response.StatusCode == http.StatusForbidden:
		return apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Your role does not have permission to view this.")
	case response.StatusCode == http.StatusNotFound:
		// The record is not there, or not in the reader's scope: the existing
		// application answers both alike, and so does the app.
		return apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound,
			"This was not found, or it is not yours to view.")
	case response.StatusCode == http.StatusNotImplemented:
		// A page of the web the reader may open that the feed does not draw:
		// not a failure, and not the reader's refusal. The app opens it in
		// the existing web.
		return apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable,
			"This screen is not available here yet. Use the Edify web app.")
	case response.StatusCode != http.StatusOK:
		return c.unavailable(ctx, fmt.Errorf("%s answered %d", path, response.StatusCode))
	}

	body, err := io.ReadAll(io.LimitReader(response.Body, maxResponseSize+1))
	if err != nil {
		return c.unavailable(ctx, fmt.Errorf("reading %s: %w", path, err))
	}
	if len(body) > maxResponseSize {
		return c.unavailable(ctx, fmt.Errorf("%s answered more than %d bytes", path, maxResponseSize))
	}
	if err := (protojson.UnmarshalOptions{}).Unmarshal(body, out); err != nil {
		return c.unavailable(ctx, fmt.Errorf("%s does not match its contract: %w", path, err))
	}
	return nil
}

// unavailable logs the cause with the request's ids and tells the caller
// only that the screen could not be loaded.
func (c *Client) unavailable(ctx context.Context, cause error) error {
	span := trace.FromContext(ctx)
	c.logger.ErrorContext(ctx, "screen feed failed",
		slog.String("error", cause.Error()),
		slog.String("request_id", span.RequestID),
		slog.String("trace_id", span.TraceID),
	)
	return apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable,
		"This screen could not be loaded. Please try again.")
}
