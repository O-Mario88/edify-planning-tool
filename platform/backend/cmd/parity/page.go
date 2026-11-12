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
	// ids fill a path's {id} (a cluster's schools list, one per cluster);
	// each is asked in turn.
	ids []string
	// question is the path with {id} its questions are registered under.
	question string
	pages    screensv1connect.PageScreenServiceClient
}

// pageQuestions are the questions each account is asked of a page, by the
// page's web path; a page with none registered is asked only as it opens.
// Each page's set lives in its own file (page_clusters.go) and registers
// itself here.
var pageQuestions = map[string]func(ctx context.Context, r *pageRun, token string) []map[string]string{}

func (r *pageRun) queries(ctx context.Context, token string) []map[string]string {
	key := r.path
	if r.question != "" {
		key = r.question
	}
	if questions, ok := pageQuestions[key]; ok {
		return questions(ctx, r, token)
	}
	return []map[string]string{{}}
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

// each is the run once per id for a path with {id}, else the run itself.
func (r *pageRun) each() []*pageRun {
	if !strings.Contains(r.path, "{id}") {
		return []*pageRun{r}
	}
	out := []*pageRun{}
	for _, id := range r.ids {
		one := *r
		one.path = strings.ReplaceAll(r.path, "{id}", id)
		one.question = r.path
		out = append(out, &one)
	}
	return out
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
		for _, one := range r.each() {
			for _, query := range one.queries(ctx, token) {
				goAnswer, goErr := one.goPage(ctx, token, query)
				oldAnswer, oldErr := one.existingPage(token, query)
				compared++
				mine++
				if diff := comparePages(goAnswer, goErr, oldAnswer, oldErr); diff != "" {
					differing++
					theirs++
					fmt.Printf("%-34s %-40s DIFFERS\n%s\n", email, one.path+" "+queryText(query), diff)
				}
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
