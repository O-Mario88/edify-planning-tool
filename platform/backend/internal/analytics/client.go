// Package analytics is the gateway's client for the Python analytics worker.
// The worker is reached over internal gRPC only, holds no database
// connection, and receives nothing but rows the gateway already authorised.
package analytics

import (
	"context"
	"fmt"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"

	analyticsv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/analytics/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trace"
)

// callTimeout bounds one worker call; the gateway answers without the worker
// rather than keep a phone waiting.
const callTimeout = 3 * time.Second

// Client calls PortfolioAnalyticsService.
type Client struct {
	conn   *grpc.ClientConn
	client analyticsv1.PortfolioAnalyticsServiceClient
}

// Dial prepares a client for addr. The connection is made lazily, so a worker
// that is down does not stop the gateway from starting.
//
// Transport security is the private network's: the worker listens on an
// internal address only. Mutual TLS between the two is a staging exit
// criterion (docs/migration/05-environments-and-staging.md).
func Dial(addr string) (*Client, error) {
	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, fmt.Errorf("analytics: preparing the worker connection: %w", err)
	}
	return &Client{conn: conn, client: analyticsv1.NewPortfolioAnalyticsServiceClient(conn)}, nil
}

// Close releases the connection.
func (c *Client) Close() error {
	return c.conn.Close()
}

// Summarize implements schools.Summarizer.
func (c *Client) Summarize(ctx context.Context, facts []schools.PortfolioFact) (schools.Summary, error) {
	ctx, cancel := context.WithTimeout(ctx, callTimeout)
	defer cancel()

	span := trace.FromContext(ctx)
	if span.TraceID != "" {
		ctx = metadata.AppendToOutgoingContext(ctx,
			trace.HeaderTraceparent, span.Traceparent(),
			"x-request-id", span.RequestID,
		)
	}

	request := &analyticsv1.SummarizePortfolioRequest{
		Schools: make([]*analyticsv1.PortfolioSchool, 0, len(facts)),
	}
	for _, fact := range facts {
		request.Schools = append(request.Schools, &analyticsv1.PortfolioSchool{
			SchoolType: fact.SchoolType,
			Enrollment: fact.Enrollment,
		})
	}

	response, err := c.client.SummarizePortfolio(ctx, request)
	if err != nil {
		return schools.Summary{}, fmt.Errorf("analytics: summarizing the portfolio: %w", err)
	}
	return schools.Summary{
		SchoolCount:           response.GetSchoolCount(),
		SchoolsByType:         response.GetSchoolsByType(),
		SchoolsWithEnrollment: response.GetSchoolsWithEnrollment(),
		TotalEnrollment:       response.GetTotalEnrollment(),
		MedianEnrollment:      response.GetMedianEnrollment(),
	}, nil
}
