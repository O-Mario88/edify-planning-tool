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

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// profileRun compares school profiles' Details tab: every school in the
// account's own directory, and a sample of the probe account's schools the
// account may or may not open (a lead's team, a refusal).
type profileRun struct {
	existing  string
	tab       string
	fy        string
	period    string
	sample    int
	directory screensv1connect.SchoolDirectoryScreenServiceClient
	profile   screensv1connect.SchoolProfileServiceClient
	probe     []listed
}

// listed is a school as a directory lists it.
type listed struct {
	id, kind string
}

func (r *profileRun) list(ctx context.Context, token string) ([]listed, error) {
	out := []listed{}
	for page := 1; ; page++ {
		answer, err := ask(ctx, r.directory, token, url.Values{"page": {fmt.Sprint(page)}})
		if err != nil {
			return nil, err
		}
		for _, school := range answer.GetSchools() {
			out = append(out, listed{id: school.GetId(), kind: school.GetSchoolType()})
		}
		if page >= int(answer.GetPage().GetTotalPages()) {
			return out, nil
		}
	}
}

// account compares one signed-in account's profiles; it returns how many
// were compared, how many differ, and how many were of schools Go may
// answer itself (not Core).
func (r *profileRun) account(ctx context.Context, email, token string) (compared, differing, goSchools int) {
	own, err := r.list(ctx, token)
	if err != nil && connect.CodeOf(err) != connect.CodePermissionDenied {
		fmt.Printf("%-28s cannot list schools: %v\n", email, err)
		return 0, 0, 0
	}
	seen := map[string]bool{}
	schools := []listed{}
	add := func(s listed) {
		if !seen[s.id] {
			seen[s.id] = true
			schools = append(schools, s)
		}
	}
	for _, s := range own {
		add(s)
	}
	for i := 0; i < len(r.probe) && i < r.sample; i++ {
		add(r.probe[i])
	}
	for _, s := range schools {
		compared++
		if !strings.EqualFold(s.kind, "core") {
			goSchools++
		}
		goAnswer, goErr := r.goProfile(ctx, token, s.id)
		oldAnswer, oldErr := r.existingProfile(token, s.id)
		if diff := compareProfiles(goAnswer, goErr, oldAnswer, oldErr); diff != "" {
			differing++
			fmt.Printf("%-28s %-26s DIFFERS\n%s\n", email, s.id, diff)
		}
	}
	fmt.Printf("%-28s %d profiles compared, %d differing (%d not Core)\n", email, compared, differing, goSchools)
	return compared, differing, goSchools
}

func (r *profileRun) goProfile(ctx context.Context, token, schoolID string) (*screensv1.GetSchoolProfileResponse, error) {
	call := connect.NewRequest(&screensv1.GetSchoolProfileRequest{SchoolId: schoolID, Tab: r.tab, Fy: r.fy, Period: r.period})
	call.Header().Set("Authorization", "Bearer "+token)
	answer, err := r.profile.GetSchoolProfile(ctx, call)
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

// existingProfile is the existing application's feed of the same profile;
// a refusal is put in the gateway's terms.
func (r *profileRun) existingProfile(token, schoolID string) (*screensv1.GetSchoolProfileResponse, error) {
	request, err := http.NewRequest(http.MethodGet,
		r.existing+"/api/mobile/v1/schools/"+url.PathEscape(schoolID)+"/profile?"+url.Values{
			"tab": {r.tab}, "fy": {r.fy}, "period": {r.period}}.Encode(), nil)
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
	out := &screensv1.GetSchoolProfileResponse{}
	return out, protojson.Unmarshal(body, out)
}

func compareProfiles(goAnswer *screensv1.GetSchoolProfileResponse, goErr error, old *screensv1.GetSchoolProfileResponse, oldErr error) string {
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
