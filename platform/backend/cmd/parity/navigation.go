package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
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

// runNavigation compares each account's bar and menu (GetNavigation) with
// the existing feed of them (apps.mobile_feed NavigationFeedView).
func runNavigation(ctx context.Context, signIn identityv1connect.SignInServiceClient, navigation screensv1connect.NavigationServiceClient,
	existing, password string, users []string, pause time.Duration,
) int {
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
		call := connect.NewRequest(&screensv1.GetNavigationRequest{})
		call.Header().Set("Authorization", "Bearer "+token)
		var goAnswer *screensv1.GetNavigationResponse
		got, goErr := navigation.GetNavigation(ctx, call)
		if goErr == nil {
			goAnswer = got.Msg
		}
		oldAnswer, oldErr := existingNavigation(existing, token)
		compared++
		diff := ""
		if goErr != nil || oldErr != nil {
			diff = fmt.Sprintf("  go error: %v\n  existing error: %v", goErr, oldErr)
		} else {
			diffs := []string{}
			walk("", asMap(goAnswer), asMap(oldAnswer), &diffs)
			sort.Strings(diffs)
			if len(diffs) > 12 {
				diffs = append(diffs[:12], fmt.Sprintf("… and %d more", len(diffs)-12))
			}
			diff = strings.Join(diffs, "\n")
		}
		if diff != "" {
			differing++
			fmt.Printf("%-34s DIFFERS\n%s\n", email, diff)
			continue
		}
		items := len(goAnswer.GetBottom())
		for _, s := range goAnswer.GetSections() {
			items += len(s.GetItems())
		}
		fmt.Printf("%-34s same (%d bar items, %d sections, %d items in all)\n", email,
			len(goAnswer.GetBottom()), len(goAnswer.GetSections()), items)
	}
	fmt.Printf("\n%d answers compared, %d differing\n", compared, differing)
	if differing > 0 || compared == 0 {
		return 1
	}
	return 0
}

func existingNavigation(base, token string) (*screensv1.GetNavigationResponse, error) {
	request, err := http.NewRequest(http.MethodGet, base+"/api/mobile/v1/navigation", nil)
	if err != nil {
		return nil, err
	}
	request.Header.Set("Authorization", "Bearer "+token)
	response, err := (&http.Client{Timeout: 60 * time.Second}).Do(request)
	if err != nil {
		return nil, err
	}
	defer func() { _ = response.Body.Close() }()
	body, _ := io.ReadAll(response.Body)
	if response.StatusCode != http.StatusOK {
		return nil, errors.New("status " + response.Status)
	}
	out := &screensv1.GetNavigationResponse{}
	return out, protojson.Unmarshal(body, out)
}
