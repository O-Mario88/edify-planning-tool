package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"sort"
	"strings"
	"time"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/encoding/protojson"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1/identityv1connect"
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// pageRun compares one page the app draws from its components (GetPage)
// with the existing feed of it (apps.mobile_feed PageFeedView).
type pageRun struct {
	existing, path string
	pages          screensv1connect.PageScreenServiceClient
}

// queries are the questions each account is asked: the page as it opens,
// every filter value the page offers, a search, later pages and pages that
// are not pages, and two filters together.
func (r *pageRun) queries(ctx context.Context, token string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"page", "2"}, {"page", "3"}, {"page", "999"}, {"page", "0"}, {"page", "abc"}, {"page", " 2 "},
		{"fy", "2026"}, {"fy", "2025"}, {"fy", "1999"}, {"quarter", "Q2"}, {"quarter", "Q9"},
		{"q", "cluster b"}, {"q", "MUKONO"}, {"q", "%"}, {"q", "zzz"},
		{"ssa_status", "done"}, {"ssa_status", "not_done"},
		{"cluster_risk", "critical"}, {"cluster_risk", "needs_attention"}, {"cluster_risk", "healthy"},
		{"activity_status", "pending"}, {"activity_status", "completed"},
		{"district", "nonsense"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	out = append(out, map[string]string{"cluster_risk": "critical", "page": "2"})
	first, err := r.goPage(ctx, token, map[string]string{})
	if err != nil {
		return out
	}
	for _, block := range first.GetBlocks() {
		for _, f := range block.GetFilters().GetFilters() {
			switch f.GetName() {
			case "district", "sub_county", "staff":
				for i, o := range f.GetOptions() {
					if o.GetValue() != "" && (f.GetName() != "staff" || i <= 3) {
						out = append(out, map[string]string{f.GetName(): o.GetValue()})
					}
				}
			}
		}
	}
	return out
}

func (r *pageRun) goPage(ctx context.Context, token string, query map[string]string) (*screensv1.GetPageResponse, error) {
	call := connect.NewRequest(&screensv1.GetPageRequest{Path: r.path, Query: query})
	call.Header().Set("Authorization", "Bearer "+token)
	answer, err := r.pages.GetPage(ctx, call)
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

// existingPage is the existing feed of the same page; a refusal is put in
// the gateway's terms.
func (r *pageRun) existingPage(token string, query map[string]string) (*screensv1.GetPageResponse, error) {
	values := url.Values{"path": {r.path}}
	for k, v := range query {
		values.Set(k, v)
	}
	request, err := http.NewRequest(http.MethodGet, r.existing+"/api/mobile/v1/page?"+values.Encode(), nil)
	if err != nil {
		return nil, err
	}
	request.Header.Set("Authorization", "Bearer "+token)
	response, err := (&http.Client{Timeout: 120 * time.Second}).Do(request)
	if err != nil {
		return nil, err
	}
	defer func() { _ = response.Body.Close() }()
	body, _ := io.ReadAll(response.Body)
	switch response.StatusCode {
	case http.StatusOK:
	case http.StatusNotFound:
		return nil, connect.NewError(connect.CodeNotFound, errors.New("not found"))
	case http.StatusForbidden:
		return nil, connect.NewError(connect.CodePermissionDenied, errors.New("forbidden"))
	default:
		return nil, fmt.Errorf("status %d", response.StatusCode)
	}
	out := &screensv1.GetPageResponse{}
	return out, protojson.Unmarshal(body, out)
}

func comparePages(goAnswer *screensv1.GetPageResponse, goErr error, old *screensv1.GetPageResponse, oldErr error) string {
	if goErr != nil || oldErr != nil {
		if (goErr == nil) != (oldErr == nil) || connect.CodeOf(goErr) != connect.CodeOf(oldErr) {
			return fmt.Sprintf("  go error: %v\n  existing error: %v", goErr, oldErr)
		}
		return ""
	}
	diffs := []string{}
	walk("", asMap(goAnswer), asMap(old), &diffs)
	sort.Strings(diffs)
	if len(diffs) > 12 {
		diffs = append(diffs[:12], fmt.Sprintf("… and %d more", len(diffs)-12))
	}
	return strings.Join(diffs, "\n")
}

func queryText(q map[string]string) string {
	values := url.Values{}
	for k, v := range q {
		values.Set(k, v)
	}
	if len(values) == 0 {
		return "(as it opens)"
	}
	return values.Encode()
}

func runPages(ctx context.Context, signIn identityv1connect.SignInServiceClient, r *pageRun, password string, users []string, pause time.Duration) int {
	compared, differing := 0, 0
	for i, email := range users {
		if i > 0 {
			time.Sleep(pause)
		}
		email = strings.TrimSpace(email)
		answer, err := signIn.SignIn(ctx, connect.NewRequest(&identityv1.SignInRequest{Email: email, Password: password}))
		if err != nil || answer.Msg.GetSession() == nil {
			fmt.Printf("%-34s cannot sign in: %v\n", email, err)
			continue
		}
		token := answer.Msg.GetSession().GetAccessToken()
		mine, theirs := 0, 0
		for _, query := range r.queries(ctx, token) {
			goAnswer, goErr := r.goPage(ctx, token, query)
			oldAnswer, oldErr := r.existingPage(token, query)
			compared++
			mine++
			if diff := comparePages(goAnswer, goErr, oldAnswer, oldErr); diff != "" {
				differing++
				theirs++
				fmt.Printf("%-34s %-40s DIFFERS\n%s\n", email, queryText(query), diff)
			}
		}
		fmt.Printf("%-34s %d questions, %d differing\n", email, mine, theirs)
	}
	fmt.Printf("\n%d answers compared, %d differing\n", compared, differing)
	if differing > 0 {
		return 1
	}
	return 0
}
