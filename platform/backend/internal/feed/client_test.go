package feed

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"connectrpc.com/connect"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trace"
)

func client(t *testing.T, handler http.HandlerFunc) *Client {
	t.Helper()
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	return NewClient(server.URL, slog.New(slog.NewTextHandler(io.Discard, nil)))
}

func caller() context.Context {
	ctx := auth.WithBearer(context.Background(), "the-callers-token")
	return trace.WithSpan(ctx, trace.Start("mobile-req-0001", ""))
}

func TestGetForwardsTheCallersTokenAndDecodesTheContract(t *testing.T) {
	var gotAuth, gotRequestID, gotPath string
	feed := client(t, func(writer http.ResponseWriter, request *http.Request) {
		gotAuth, gotRequestID, gotPath = request.Header.Get("Authorization"), request.Header.Get("X-Request-Id"), request.URL.Path
		_, _ = writer.Write([]byte(`{"greeting":"Good morning","firstName":"Ada","hasPlan":true,
			"figures":[{"key":"upcoming","label":"Planned","value":"3","tone":"brand"}]}`))
	})

	var home screensv1.GetHomeResponse
	if err := feed.Get(caller(), "/api/mobile/v1/home", &home); err != nil {
		t.Fatal(err)
	}
	if gotAuth != "Bearer the-callers-token" || gotRequestID != "mobile-req-0001" || gotPath != "/api/mobile/v1/home" {
		t.Fatalf("forwarded %q %q %q", gotAuth, gotRequestID, gotPath)
	}
	if home.GetFirstName() != "Ada" || !home.GetHasPlan() || home.GetFigures()[0].GetValue() != "3" {
		t.Fatalf("decoded %v", &home)
	}
}

func TestGetMapsFailures(t *testing.T) {
	tests := []struct {
		name       string
		status     int
		body       string
		wantCode   connect.Code
		wantReason string
	}{
		{name: "session no longer valid", status: 401, wantCode: connect.CodeUnauthenticated, wantReason: apierr.ReasonAuthInvalid},
		{name: "role may not view the page", status: 403, wantCode: connect.CodePermissionDenied, wantReason: apierr.ReasonPermissionDenied},
		{name: "not there or not the reader's", status: 404, wantCode: connect.CodeNotFound, wantReason: apierr.ReasonNotFound},
		{name: "a web page the feed does not draw yet", status: 501, wantCode: connect.CodeUnavailable, wantReason: apierr.ReasonScreenUnavailable},
		{name: "existing application error", status: 500, body: "Traceback: secret detail", wantCode: connect.CodeUnavailable, wantReason: apierr.ReasonScreenUnavailable},
		{name: "a field the contract does not know", status: 200, body: `{"greeting":"Hi","passwordHash":"x"}`, wantCode: connect.CodeUnavailable, wantReason: apierr.ReasonScreenUnavailable},
		{name: "not JSON", status: 200, body: "<html>", wantCode: connect.CodeUnavailable, wantReason: apierr.ReasonScreenUnavailable},
		{name: "a redirect is not followed", status: 302, wantCode: connect.CodeUnavailable, wantReason: apierr.ReasonScreenUnavailable},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			feed := client(t, func(writer http.ResponseWriter, _ *http.Request) {
				if test.status == http.StatusFound {
					writer.Header().Set("Location", "https://elsewhere.example/")
				}
				writer.WriteHeader(test.status)
				_, _ = writer.Write([]byte(test.body))
			})

			var home screensv1.GetHomeResponse
			err := feed.Get(caller(), "/api/mobile/v1/home", &home)

			if connect.CodeOf(err) != test.wantCode || apierr.Reason(err) != test.wantReason {
				t.Fatalf("got %v / %q", connect.CodeOf(err), apierr.Reason(err))
			}
			if strings.Contains(err.Error(), "secret detail") || strings.Contains(err.Error(), "passwordHash") {
				t.Fatalf("the cause reached the caller: %v", err)
			}
		})
	}
}

func TestGetReportsAnUnreachableApplication(t *testing.T) {
	feed := NewClient("http://127.0.0.1:1", slog.New(slog.NewTextHandler(io.Discard, nil)))

	var home screensv1.GetHomeResponse
	err := feed.Get(caller(), "/api/mobile/v1/home", &home)

	if connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("got %v", err)
	}
}

func TestPostSendsTheContractsJSON(t *testing.T) {
	var gotMethod, gotType string
	var gotBody []byte
	feed := client(t, func(writer http.ResponseWriter, request *http.Request) {
		gotMethod, gotType = request.Method, request.Header.Get("Content-Type")
		gotBody, _ = io.ReadAll(request.Body)
		_, _ = writer.Write([]byte(`{"result":{"saved":true,"message":"Added."}}`))
	})

	var answer screensv1.AddToClusterResponse
	err := feed.Post(caller(), "/api/mobile/v1/schools/s1/add-to-cluster",
		&screensv1.AddToClusterRequest{ActionType: "existing", ClusterId: "c1", ConfirmChange: true}, &answer)

	if err != nil {
		t.Fatal(err)
	}
	if gotMethod != http.MethodPost || gotType != "application/json" {
		t.Fatalf("sent %s %q", gotMethod, gotType)
	}
	for _, want := range []string{`"actionType":"existing"`, `"clusterId":"c1"`, `"confirmChange":true`} {
		if !strings.Contains(strings.ReplaceAll(string(gotBody), " ", ""), want) {
			t.Fatalf("body %s lacks %s", gotBody, want)
		}
	}
	if !answer.GetResult().GetSaved() || answer.GetResult().GetMessage() != "Added." {
		t.Fatalf("decoded %v", &answer)
	}
}
