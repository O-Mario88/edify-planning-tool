package analytics

import (
	"context"
	"net"
	"testing"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"

	analyticsv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/analytics/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trace"
)

type fakeAnalyticsServer struct {
	analyticsv1.UnimplementedPortfolioAnalyticsServiceServer
	gotTraceparent string
	gotRequestID   string
	failSummarize  bool
}

func (f *fakeAnalyticsServer) captureTrace(ctx context.Context) {
	if md, ok := metadata.FromIncomingContext(ctx); ok {
		if vals := md.Get(trace.HeaderTraceparent); len(vals) > 0 {
			f.gotTraceparent = vals[0]
		}
		if vals := md.Get("x-request-id"); len(vals) > 0 {
			f.gotRequestID = vals[0]
		}
	}
}

func (f *fakeAnalyticsServer) SummarizePortfolio(ctx context.Context, req *analyticsv1.SummarizePortfolioRequest) (*analyticsv1.SummarizePortfolioResponse, error) {
	f.captureTrace(ctx)
	if f.failSummarize {
		return nil, status.Error(codes.Unavailable, "worker overloaded")
	}
	byType := map[string]int32{}
	var withEnroll int32
	var totalEnroll int64
	for _, s := range req.GetSchools() {
		byType[s.GetSchoolType()]++
		if s.Enrollment != nil && s.GetEnrollment() > 0 {
			withEnroll++
			totalEnroll += int64(s.GetEnrollment())
		}
	}
	return &analyticsv1.SummarizePortfolioResponse{
		SchoolCount:           int32(len(req.GetSchools())),
		SchoolsByType:         byType,
		SchoolsWithEnrollment: withEnroll,
		TotalEnrollment:       totalEnroll,
		MedianEnrollment:      250.0,
	}, nil
}

func (f *fakeAnalyticsServer) AnalyzeSsa(ctx context.Context, req *analyticsv1.AnalyzeSsaRequest) (*analyticsv1.AnalyzeSsaResponse, error) {
	f.captureTrace(ctx)
	return &analyticsv1.AnalyzeSsaResponse{TotalSchools: int32(len(req.GetRecords())), AverageScore: 6.25}, nil
}

func (f *fakeAnalyticsServer) AnalyzeCoverageGaps(ctx context.Context, req *analyticsv1.AnalyzeCoverageGapsRequest) (*analyticsv1.AnalyzeCoverageGapsResponse, error) {
	f.captureTrace(ctx)
	return &analyticsv1.AnalyzeCoverageGapsResponse{TotalSchools: int32(len(req.GetRecords()))}, nil
}

func (f *fakeAnalyticsServer) AnalyzeRouteEfficiency(ctx context.Context, _ *analyticsv1.AnalyzeRouteEfficiencyRequest) (*analyticsv1.AnalyzeRouteEfficiencyResponse, error) {
	f.captureTrace(ctx)
	return &analyticsv1.AnalyzeRouteEfficiencyResponse{}, nil
}

func (f *fakeAnalyticsServer) ComputePredictiveInsights(ctx context.Context, _ *analyticsv1.ComputePredictiveInsightsRequest) (*analyticsv1.ComputePredictiveInsightsResponse, error) {
	f.captureTrace(ctx)
	return &analyticsv1.ComputePredictiveInsightsResponse{
		HighRiskCount: 1,
		Predictions:   []*analyticsv1.SchoolRiskPrediction{{SchoolId: "sch-1"}},
	}, nil
}

func (f *fakeAnalyticsServer) GenerateGlobalReport(ctx context.Context, req *analyticsv1.GenerateGlobalReportRequest) (*analyticsv1.GenerateGlobalReportResponse, error) {
	f.captureTrace(ctx)
	return &analyticsv1.GenerateGlobalReportResponse{CountryCount: int32(len(req.GetCountries()))}, nil
}

func startFakeWorker(t *testing.T, srv *fakeAnalyticsServer) (*Client, func()) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	gs := grpc.NewServer()
	analyticsv1.RegisterPortfolioAnalyticsServiceServer(gs, srv)
	go func() { _ = gs.Serve(ln) }()

	client, err := Dial(ln.Addr().String())
	if err != nil {
		gs.Stop()
		_ = ln.Close()
		t.Fatalf("Dial: %v", err)
	}
	return client, func() {
		_ = client.Close()
		gs.Stop()
		_ = ln.Close()
	}
}

func TestAnalyticsClientAllRPCsAndTracePropagation(t *testing.T) {
	srv := &fakeAnalyticsServer{}
	client, stop := startFakeWorker(t, srv)
	defer stop()

	ctx := trace.WithSpan(context.Background(), trace.Span{
		TraceID:   "0123456789abcdef0123456789abcdef",
		SpanID:    "0123456789abcdef",
		RequestID: "req-analytics-42",
	})

	e1, e2 := int32(300), int32(200)
	summary, err := client.Summarize(ctx, []schools.PortfolioFact{
		{SchoolType: "core", Enrollment: &e1},
		{SchoolType: "client", Enrollment: &e2},
	})
	if err != nil {
		t.Fatalf("Summarize: %v", err)
	}
	if summary.SchoolCount != 2 || summary.TotalEnrollment != 500 || summary.SchoolsByType["core"] != 1 {
		t.Fatalf("unexpected summary: %+v", summary)
	}
	if srv.gotRequestID != "req-analytics-42" || srv.gotTraceparent == "" {
		t.Fatalf("trace headers not propagated: reqID=%q traceparent=%q", srv.gotRequestID, srv.gotTraceparent)
	}

	if resp, err := client.AnalyzeSsa(ctx, &analyticsv1.AnalyzeSsaRequest{}); err != nil || resp.GetAverageScore() != 6.25 {
		t.Fatalf("AnalyzeSsa failed: resp=%v err=%v", resp, err)
	}
	if _, err := client.AnalyzeCoverageGaps(ctx, &analyticsv1.AnalyzeCoverageGapsRequest{}); err != nil {
		t.Fatalf("AnalyzeCoverageGaps failed: %v", err)
	}
	if _, err := client.AnalyzeRouteEfficiency(ctx, &analyticsv1.AnalyzeRouteEfficiencyRequest{}); err != nil {
		t.Fatalf("AnalyzeRouteEfficiency failed: %v", err)
	}
	if pred, err := client.ComputePredictiveInsights(ctx, &analyticsv1.ComputePredictiveInsightsRequest{}); err != nil || len(pred.GetPredictions()) != 1 {
		t.Fatalf("ComputePredictiveInsights failed: pred=%v err=%v", pred, err)
	}
	if _, err := client.GenerateGlobalReport(ctx, &analyticsv1.GenerateGlobalReportRequest{}); err != nil {
		t.Fatalf("GenerateGlobalReport failed: %v", err)
	}

	srv.failSummarize = true
	if _, err := client.Summarize(ctx, nil); err == nil {
		t.Fatalf("expected error when worker returns Unavailable")
	}
}
