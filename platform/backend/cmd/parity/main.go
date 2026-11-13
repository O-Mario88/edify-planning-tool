// Command parity compares a screen moved to Go with the existing
// application's own answer, field by field, for real accounts on a local
// development database. Both answers are decoded into the same contract
// message, so a difference is a difference the app would show.
//
//	EDIFY_PARITY_PASSWORD=… go run ./cmd/parity -users a@x,b@x
//
// It signs each account in through the gateway and asks both systems the
// same questions. Development only: it refuses any address that is not on
// this machine.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"reflect"
	"slices"
	"sort"
	"strings"
	"time"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1/identityv1connect"
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

func main() {
	gateway := flag.String("gateway", "http://localhost:8090", "the Go gateway")
	existing := flag.String("existing", "http://localhost:8010", "the existing application")
	users := flag.String("users", "", "comma-separated accounts to sign in as")
	pause := flag.Duration("pause", 0, "wait between sign-ins, under the gateway's sign-in rate limit")
	screen := flag.String("screen", "directory", "what to compare: directory, profile, page or navigation")
	pagePath := flag.String("path", "/clusters", "page: the page's web path, {id} filled from -ids")
	pageIDs := flag.String("ids", "", "page: comma-separated ids for a path with {id}")
	tab := flag.String("tab", "details", "profile: the tab to compare")
	fy := flag.String("fy", "", "profile: the year asked (empty for the page's own)")
	period := flag.String("period", "", "profile: the part of the year asked (Q1…Q4, M1…M12)")
	probe := flag.String("probe", "admin@edify.org", "profile: the account whose schools are sampled for every account")
	sample := flag.Int("sample", 40, "profile: how many of the probe's schools each account is also asked")
	flag.Parse()
	password := os.Getenv("EDIFY_PARITY_PASSWORD")
	for _, address := range []string{*gateway, *existing} {
		if u, err := url.Parse(address); err != nil || (u.Hostname() != "localhost" && u.Hostname() != "127.0.0.1") {
			fmt.Fprintln(os.Stderr, "parity runs against this machine only:", address)
			os.Exit(2)
		}
	}
	if password == "" || *users == "" {
		fmt.Fprintln(os.Stderr, "set EDIFY_PARITY_PASSWORD and -users")
		os.Exit(2)
	}
	ctx := context.Background()
	signIn := identityv1connect.NewSignInServiceClient(http.DefaultClient, *gateway)
	directory := screensv1connect.NewSchoolDirectoryScreenServiceClient(http.DefaultClient, *gateway)
	if *screen == "profile" {
		os.Exit(runProfiles(ctx, signIn, &profileRun{
			existing: *existing, tab: *tab, fy: *fy, period: *period, sample: *sample, directory: directory,
			profile: screensv1connect.NewSchoolProfileServiceClient(http.DefaultClient, *gateway),
		}, password, *probe, strings.Split(*users, ","), *pause))
	}
	if *screen == "navigation" {
		os.Exit(runNavigation(ctx, signIn, screensv1connect.NewNavigationServiceClient(http.DefaultClient, *gateway),
			*existing, password, strings.Split(*users, ","), *pause))
	}
	if *screen == "page" {
		os.Exit(runPages(ctx, signIn, &pageRun{
			existing: *existing, path: *pagePath, ids: strings.Split(*pageIDs, ","),
			pages: screensv1connect.NewPageScreenServiceClient(http.DefaultClient, *gateway),
		}, password, strings.Split(*users, ","), *pause))
	}
	compared, differing, existingFails := 0, 0, 0
	for i, email := range strings.Split(*users, ",") {
		if i > 0 {
			time.Sleep(*pause)
		}
		answer, err := signIn.SignIn(ctx, connect.NewRequest(&identityv1.SignInRequest{Email: strings.TrimSpace(email), Password: password}))
		if err != nil || answer.Msg.GetSession() == nil {
			fmt.Printf("%-28s cannot sign in: %v\n", email, err)
			continue
		}
		token := answer.Msg.GetSession().GetAccessToken()
		compared++
		if diff := wholeList(ctx, directory, *existing, token); diff != "" {
			differing++
			fmt.Printf("%-28s %-40s DIFFERS\n%s\n", email, "every page", diff)
		} else {
			fmt.Printf("%-28s %-40s same\n", email, "every page")
		}
		for _, query := range queries(ctx, directory, token) {
			compared++
			goAnswer, goErr := ask(ctx, directory, token, query)
			oldAnswer, oldErr := existingDirectory(*existing, token, query)
			if goErr == nil && oldErr != nil {
				existingFails++
				fmt.Printf("%-28s %-40s existing fails (%v); go answers\n", email, query.Encode(), oldErr)
				continue
			}
			if diff := compare(goAnswer, goErr, oldAnswer, oldErr); diff != "" {
				differing++
				fmt.Printf("%-28s %-40s DIFFERS\n%s\n", email, query.Encode(), diff)
			} else {
				fmt.Printf("%-28s %-40s same\n", email, query.Encode())
			}
		}
	}
	fmt.Printf("\n%d compared, %d differing, %d where only the existing application failed\n", compared, differing, existingFails)
	if differing > 0 {
		os.Exit(1)
	}
}

// queries are the questions each account is asked: the page's defaults,
// each tab, filter and gap, a search, a later page, a page past the end,
// and the first district the page offers.
func queries(ctx context.Context, directory screensv1connect.SchoolDirectoryScreenServiceClient, token string) []url.Values {
	out := []url.Values{{}}
	for _, kv := range [][2]string{
		{"tab", "unclustered"}, {"tab", "clustered"}, {"tab", "not_assigned"}, {"tab", "assigned"},
		{"q", "primary"}, {"q", "uMeA"}, {"gap", "any"}, {"gap", "no_ssa"}, {"gap", "no_cluster"}, {"gap", "unheld"},
		{"page", "2"}, {"page", "999"}, {"school_type", "client"}, {"school_type", "core"},
		{"cluster_status", "clustered"}, {"project_status", "assigned"}, {"project_status", "unassigned"},
		{"fy", "2026"}, {"fy", "1999"},
	} {
		out = append(out, url.Values{kv[0]: {kv[1]}})
	}
	if first, err := ask(ctx, directory, token, url.Values{}); err == nil && len(first.GetFilters().GetDistricts()) > 0 {
		d := first.GetFilters().GetDistricts()[0].GetValue()
		out = append(out, url.Values{"district": {d}}, url.Values{"district": {d}, "sub_county": {"nonsense"}})
	}
	return out
}

func ask(ctx context.Context, directory screensv1connect.SchoolDirectoryScreenServiceClient, token string, q url.Values) (*screensv1.GetSchoolDirectoryResponse, error) {
	request := &screensv1.GetSchoolDirectoryRequest{
		Q: q.Get("q"), Fy: q.Get("fy"), District: q.Get("district"), SubCounty: q.Get("sub_county"),
		SchoolType: q.Get("school_type"), ClusterStatus: q.Get("cluster_status"), ProjectStatus: q.Get("project_status"),
		Gap: q.Get("gap"), Tab: q.Get("tab"),
	}
	if page := q.Get("page"); page != "" {
		var n int32
		_, _ = fmt.Sscanf(page, "%d", &n)
		request.Page = n
	}
	call := connect.NewRequest(request)
	call.Header().Set("Authorization", "Bearer "+token)
	answer, err := directory.GetSchoolDirectory(ctx, call)
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

// existingDirectory is the existing application's feed of the same page.
func existingDirectory(base, token string, q url.Values) (*screensv1.GetSchoolDirectoryResponse, error) {
	request, err := http.NewRequest(http.MethodGet, base+"/api/mobile/v1/school-directory?"+q.Encode(), nil)
	if err != nil {
		return nil, err
	}
	request.Header.Set("Authorization", "Bearer "+token)
	client := &http.Client{Timeout: 120 * time.Second}
	response, err := client.Do(request)
	if err != nil {
		return nil, err
	}
	defer func() { _ = response.Body.Close() }()
	body, _ := io.ReadAll(response.Body)
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("status %d", response.StatusCode)
	}
	out := &screensv1.GetSchoolDirectoryResponse{}
	return out, protojson.Unmarshal(body, out)
}

func normalize(m *screensv1.GetSchoolDirectoryResponse) map[string]any {
	for _, school := range m.GetSchools() {
		slices.Sort(school.ProjectIds)
	}
	raw, _ := protojson.MarshalOptions{EmitUnpopulated: true}.Marshal(m)
	var out map[string]any
	_ = json.Unmarshal(raw, &out)
	return out
}

func compare(goAnswer *screensv1.GetSchoolDirectoryResponse, goErr error, old *screensv1.GetSchoolDirectoryResponse, oldErr error) string {
	if goErr != nil || oldErr != nil {
		if (goErr == nil) != (oldErr == nil) {
			return fmt.Sprintf("  go error: %v\n  existing error: %v", goErr, oldErr)
		}
		return ""
	}
	diffs := []string{}
	goMap, oldMap := normalize(goAnswer), normalize(old)
	goRows, _ := goMap["schools"].([]any)
	oldRows, _ := oldMap["schools"].([]any)
	delete(goMap, "schools")
	delete(oldMap, "schools")
	walk("", goMap, oldMap, &diffs)
	compareRows(goRows, oldRows, &diffs)
	sort.Strings(diffs)
	if len(diffs) > 12 {
		diffs = append(diffs[:12], fmt.Sprintf("… and %d more", len(diffs)-12))
	}
	return strings.Join(diffs, "\n")
}

// wholeList walks every page of the default view on both sides and compares
// the complete list of schools, which a tie split across a page boundary
// could otherwise hide.
func wholeList(ctx context.Context, directory screensv1connect.SchoolDirectoryScreenServiceClient, existing, token string) string {
	collect := func(get func(page int) (*screensv1.GetSchoolDirectoryResponse, error)) ([]string, error) {
		ids := []string{}
		for page := 1; ; page++ {
			answer, err := get(page)
			if err != nil {
				return nil, err
			}
			for _, school := range answer.GetSchools() {
				ids = append(ids, school.GetId())
			}
			if page >= int(answer.GetPage().GetTotalPages()) {
				break
			}
		}
		slices.Sort(ids)
		return ids, nil
	}
	goIDs, err := collect(func(page int) (*screensv1.GetSchoolDirectoryResponse, error) {
		return ask(ctx, directory, token, url.Values{"page": {fmt.Sprint(page)}})
	})
	if err != nil {
		return "  go: " + err.Error()
	}
	oldIDs, err := collect(func(page int) (*screensv1.GetSchoolDirectoryResponse, error) {
		return existingDirectory(existing, token, url.Values{"page": {fmt.Sprint(page)}})
	})
	if err != nil {
		return "  existing: " + err.Error()
	}
	goUnique := slices.Compact(slices.Clone(goIDs))
	oldUnique := slices.Compact(slices.Clone(oldIDs))
	if len(goUnique) != len(goIDs) {
		return fmt.Sprintf("  go lists %d schools on two pages", len(goIDs)-len(goUnique))
	}
	if len(goIDs) != len(oldIDs) {
		return fmt.Sprintf("  go lists %d schools, existing %d", len(goIDs), len(oldIDs))
	}
	for _, id := range oldUnique {
		if _, found := slices.BinarySearch(goIDs, id); !found {
			return "  existing lists a school go does not: " + id
		}
	}
	if len(oldUnique) != len(oldIDs) {
		// The existing page orders by name alone, so schools sharing a name
		// fall differently on each page: some are listed twice, some never.
		fmt.Printf("  note: the existing pages list %d schools twice and %d never; go lists each once\n",
			len(oldIDs)-len(oldUnique), len(oldIDs)-len(oldUnique))
	}
	return ""
}

// compareRows compares a page of schools. The existing page orders by name
// alone, so schools sharing a name come in no particular order: the names
// must follow each other exactly; a run of one name wholly inside the page
// must hold the same schools; and each school present on both sides must
// read the same.
func compareRows(goRows, oldRows []any, diffs *[]string) {
	name := func(row any) string { return fmt.Sprint(row.(map[string]any)["name"]) }
	id := func(row any) string { return fmt.Sprint(row.(map[string]any)["id"]) }
	if len(goRows) != len(oldRows) {
		*diffs = append(*diffs, fmt.Sprintf("  .schools: go %d rows, existing %d", len(goRows), len(oldRows)))
		return
	}
	for i := range goRows {
		if name(goRows[i]) != name(oldRows[i]) {
			*diffs = append(*diffs, fmt.Sprintf("  .schools[%d].name: go %s, existing %s", i, name(goRows[i]), name(oldRows[i])))
			return
		}
	}
	for start := 0; start < len(goRows); {
		end := start
		for end < len(goRows) && name(goRows[end]) == name(goRows[start]) {
			end++
		}
		if start > 0 && end < len(goRows) {
			a, b := []string{}, []string{}
			for i := start; i < end; i++ {
				a, b = append(a, id(goRows[i])), append(b, id(oldRows[i]))
			}
			slices.Sort(a)
			slices.Sort(b)
			if !slices.Equal(a, b) {
				*diffs = append(*diffs, fmt.Sprintf("  .schools[%d:%d] %q: different schools", start, end, name(goRows[start])))
			}
		}
		start = end
	}
	byID := map[string]any{}
	for _, row := range oldRows {
		byID[id(row)] = row
	}
	for _, row := range goRows {
		if other, ok := byID[id(row)]; ok {
			walk(".schools["+id(row)+"]", row, other, diffs)
		}
	}
}

func walk(path string, a, b any, diffs *[]string) {
	switch av := a.(type) {
	case map[string]any:
		bv, ok := b.(map[string]any)
		if !ok {
			*diffs = append(*diffs, fmt.Sprintf("  %s: go %v, existing %v", path, a, b))
			return
		}
		keys := map[string]bool{}
		for k := range av {
			keys[k] = true
		}
		for k := range bv {
			keys[k] = true
		}
		for k := range keys {
			walk(path+"."+k, av[k], bv[k], diffs)
		}
	case []any:
		bv, ok := b.([]any)
		if !ok || len(av) != len(bv) {
			*diffs = append(*diffs, fmt.Sprintf("  %s: go %d items, existing %v items", path, len(av), lenOf(b)))
			return
		}
		for i := range av {
			walk(fmt.Sprintf("%s[%d]", path, i), av[i], bv[i], diffs)
		}
	default:
		if !reflect.DeepEqual(a, b) {
			*diffs = append(*diffs, fmt.Sprintf("  %s: go %v, existing %v", path, a, b))
		}
	}
}

func lenOf(v any) any {
	if list, ok := v.([]any); ok {
		return len(list)
	}
	return v
}

// runProfiles signs the probe and each account in and compares their
// profiles; it returns the exit status.
func runProfiles(ctx context.Context, signIn identityv1connect.SignInServiceClient, r *profileRun, password, probe string, users []string, pause time.Duration) int {
	token := func(email string) (string, error) {
		answer, err := signIn.SignIn(ctx, connect.NewRequest(&identityv1.SignInRequest{Email: strings.TrimSpace(email), Password: password}))
		if err != nil || answer.Msg.GetSession() == nil {
			return "", fmt.Errorf("cannot sign in: %v", err)
		}
		return answer.Msg.GetSession().GetAccessToken(), nil
	}
	probeToken, err := token(probe)
	if err != nil {
		fmt.Fprintln(os.Stderr, probe, err)
		return 2
	}
	if r.probe, err = r.list(ctx, probeToken); err != nil {
		fmt.Fprintln(os.Stderr, probe, err)
		return 2
	}
	// A spread of the probe's schools, not its first page alone.
	if step := len(r.probe) / max(r.sample, 1); step > 1 {
		spread := []listed{}
		for i := 0; i < len(r.probe); i += step {
			spread = append(spread, r.probe[i])
		}
		r.probe = spread
	}
	compared, differing, goSchools := 0, 0, 0
	for _, email := range users {
		time.Sleep(pause)
		t, err := token(email)
		if err != nil {
			fmt.Printf("%-28s %v\n", email, err)
			continue
		}
		c, d, g := r.account(ctx, email, t)
		compared, differing, goSchools = compared+c, differing+d, goSchools+g
	}
	fmt.Printf("\n%d profiles compared (%d not Core), %d differing\n", compared, goSchools, differing)
	if differing > 0 {
		return 1
	}
	return 0
}

// asMap is a contract message as JSON values, every field present.
func asMap(m proto.Message) map[string]any {
	raw, _ := protojson.MarshalOptions{EmitUnpopulated: true}.Marshal(m)
	var out map[string]any
	_ = json.Unmarshal(raw, &out)
	return out
}
