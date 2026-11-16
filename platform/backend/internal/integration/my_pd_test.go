//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"regexp"
	"strconv"
	"testing"
	"time"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/server"
)

var lastRefreshed = regexp.MustCompile(`^Last refreshed \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}$`)

// withoutRefreshTime blanks the minute the page was built at, once it is
// written as the page writes it.
func withoutRefreshTime(t *testing.T, page *screensv1.GetPageResponse) {
	t.Helper()
	for _, b := range page.GetBlocks() {
		for _, item := range b.GetPanel().GetItems() {
			if tx, ok := item.GetKind().(*screensv1.PagePanelItem_Text); ok && len(tx.Text) > 15 && tx.Text[:15] == "Last refreshed " {
				if !lastRefreshed.MatchString(tx.Text) {
					t.Errorf("the refresh line %q is not written as the page writes it", tx.Text)
				}
				tx.Text = "Last refreshed"
			}
		}
	}
}

// My Professional Development, built by Go with its read's writes switched
// on (owner, 2026-11-16: "Same writes"), against the existing feed's pages
// and the rows the existing read left behind: courses moved on by their
// dates, the reminders that closes, the year's allocation made. Each
// question meets the same rows. Skipped unless EDIFY_MY_PD_GOLDEN names a
// file internal/mypd/testdata/golden.py wrote today.
func TestMyPDMatchesTheExistingFeedAndWritesWhatItsReadWrites(t *testing.T) {
	path := os.Getenv("EDIFY_MY_PD_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_MY_PD_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Today   string                       `json:"today"`
		Rows    map[string][]json.RawMessage `json:"rows"`
		Answers []struct {
			Email  string            `json:"email"`
			Path   string            `json:"path"`
			Query  map[string]string `json:"query"`
			Status int               `json:"status"`
			Body   json.RawMessage   `json:"body"`
			Writes json.RawMessage   `json:"writes"`
		} `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if golden.Today != time.Now().In(mustNairobi(t)).Format(time.DateOnly) {
		t.Skipf("the golden answers were written on %s", golden.Today)
	}
	ctx := context.Background()
	// Children first.
	tables := []string{"pd_certificate", "notification", "message", "messaging_messagethread", "pd_request", "pd_allocation"}
	readers := `(SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
		WHERE u.email IN ('cceo1@edify.org', 'cceo2@edify.org', 'cceo3@edify.org'))`
	clear := func() {
		for _, table := range tables {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gmpd%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
		if _, err := admin.Exec(ctx, `DELETE FROM pd_allocation WHERE staff_id IN `+readers); err != nil {
			t.Errorf("clearing the readers' allocations: %v", err)
		}
	}
	refile := func() {
		clear()
		for i := len(tables) - 1; i >= 0; i-- {
			table := tables[i]
			for _, row := range golden.Rows[table] {
				if _, err := admin.Exec(ctx, `INSERT INTO "`+table+`" SELECT * FROM json_populate_record(NULL::"`+table+`", $1::json)`, string(row)); err != nil {
					t.Fatalf("filing a %s row: %v", table, err)
				}
			}
		}
	}
	t.Cleanup(clear)

	cfg := config.Config{Env: config.Test, Release: "integration", JWTSecret: signingSecret,
		SignIn:     config.SignIn{AppBaseURL: publicBaseURL},
		PageWrites: config.PageWrites{MyProfessionalDevelopment: true}}
	gatewayServer := httptest.NewServer(server.New(cfg, gateway, nil, slog.New(slog.NewTextHandler(io.Discard, nil))))
	t.Cleanup(gatewayServer.Close)
	pages := screensv1connect.NewPageScreenServiceClient(http.DefaultClient, gatewayServer.URL)

	writes := func(email string) string {
		var staffID string
		if err := admin.QueryRow(ctx, `SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.email = $1`,
			email).Scan(&staffID); err != nil {
			t.Fatal(err)
		}
		courses := map[string]string{}
		rows, err := admin.Query(ctx, `SELECT id, status FROM pd_request WHERE id LIKE 'gmpd%' ORDER BY id`)
		if err != nil {
			t.Fatal(err)
		}
		for rows.Next() {
			var id, status string
			if err := rows.Scan(&id, &status); err != nil {
				t.Fatal(err)
			}
			courses[id] = status
		}
		rows.Close()
		reminders := map[string][]any{}
		rows, err = admin.Query(ctx, `SELECT id, status, action_required, resolved_at IS NOT NULL FROM notification
			WHERE id LIKE 'gmpd%' ORDER BY id`)
		if err != nil {
			t.Fatal(err)
		}
		for rows.Next() {
			var id, status string
			var required, resolved bool
			if err := rows.Scan(&id, &status, &required, &resolved); err != nil {
				t.Fatal(err)
			}
			reminders[id] = []any{status, required, resolved}
		}
		rows.Close()
		allocations := [][]any{}
		rows, err = admin.Query(ctx, `SELECT fy, country, currency, annual_allocation, status, set_by FROM pd_allocation
			WHERE staff_id = $1 ORDER BY fy`, staffID)
		if err != nil {
			t.Fatal(err)
		}
		for rows.Next() {
			var fy, country, currency, status string
			var amount int64
			var setBy *string
			if err := rows.Scan(&fy, &country, &currency, &amount, &status, &setBy); err != nil {
				t.Fatal(err)
			}
			allocations = append(allocations, []any{fy, country, currency, amount, status, setBy})
		}
		rows.Close()
		encoded, _ := json.Marshal(map[string]any{"courses": courses, "reminders": reminders, "allocations": allocations})
		return string(encoded)
	}
	normal := func(raw json.RawMessage) string {
		var v any
		_ = json.Unmarshal(raw, &v)
		encoded, _ := json.Marshal(v)
		return string(encoded)
	}

	tokens := map[string]string{}
	compared, differing := 0, 0
	for _, want := range golden.Answers {
		token, ok := tokens[want.Email]
		if !ok {
			borrowAccount(t, want.Email)
			result, err := signIn(t, signInClientAt("10.9.8."+strconv.Itoa(len(tokens)+1)), want.Email, seededPassword)
			if err != nil || result.GetSession() == nil {
				t.Fatalf("signing in %s: %v", want.Email, err)
			}
			token = result.GetSession().GetAccessToken()
			tokens[want.Email] = token
		}
		refile()
		compared++
		answer, err := pages.GetPage(ctx, authed(&screensv1.GetPageRequest{Path: want.Path, Query: want.Query}, token))
		if want.Status == 404 {
			if connect.CodeOf(err) != connect.CodeNotFound {
				differing++
				t.Errorf("%s %v: %v, want not found", want.Email, want.Query, err)
			}
			continue
		}
		if err != nil {
			differing++
			t.Errorf("%s %v: %v", want.Email, want.Query, err)
			continue
		}
		got := answer.Msg
		existing := &screensv1.GetPageResponse{}
		if err := protojson.Unmarshal(want.Body, existing); err != nil {
			t.Fatal(err)
		}
		withoutRefreshTime(t, got)
		withoutRefreshTime(t, existing)
		if !proto.Equal(got, existing) {
			differing++
			g, w := protojson.Format(got), protojson.Format(existing)
			at := 0
			for at < len(g) && at < len(w) && g[at] == w[at] {
				at++
			}
			t.Errorf("%s %v differs at byte %d:\n go:       …%s\n existing: …%s", want.Email, want.Query, at,
				g[max(at-200, 0):min(at+200, len(g))], w[max(at-200, 0):min(at+200, len(w))])
		}
		if g, w := writes(want.Email), normal(want.Writes); g != w {
			differing++
			t.Errorf("%s %v wrote differently\n go:       %s\n existing: %s", want.Email, want.Query, g, w)
		}
	}
	t.Logf("%d answers of %d accounts compared (page and writes), %d differing", compared, len(tokens), differing)
}
