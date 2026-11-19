//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"

	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/home"
)

// TestHomeMatchesTheExistingFeed files the work internal/home/testdata/
// golden.py made, and asks Go for each reader's Home at the instant the
// existing feed was asked, against what the feed answered. A reader Go hands
// on (a partner, whose plan is their organisation's) is counted, not
// compared. Skipped unless EDIFY_HOME_GOLDEN names that file.
func TestHomeMatchesTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_HOME_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_HOME_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Now     time.Time         `json:"now"`
		Rows    []json.RawMessage `json:"rows"`
		Answers []struct {
			Email  string          `json:"email"`
			Status int             `json:"status"`
			Body   json.RawMessage `json:"body"`
		} `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM activity WHERE id LIKE 'ghome%'`); err != nil {
			t.Errorf("clearing the work: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	for _, row := range golden.Rows {
		if _, err := admin.Exec(ctx, `INSERT INTO activity SELECT * FROM json_populate_record(NULL::activity, $1::json)`, string(row)); err != nil {
			t.Fatalf("filing the work: %v", err)
		}
	}
	service := home.NewService(gateway, func() time.Time { return golden.Now })
	compared, handedOn, differing := 0, 0, 0
	for _, a := range golden.Answers {
		var p auth.Principal
		if err := admin.QueryRow(ctx, `SELECT u.id, u.email, COALESCE(u.name, ''), u.active_role, COALESCE(sp.id, '')
FROM "user" u LEFT JOIN staff_profile sp ON sp.user_id = u.id WHERE u.email = $1 AND u.deleted_at IS NULL`, a.Email).
			Scan(&p.UserID, &p.Email, &p.Name, &p.ActiveRole, &p.StaffProfileID); err != nil {
			t.Fatalf("the test database needs %s (demo seed): %v", a.Email, err)
		}
		p.Roles = []string{p.ActiveRole}
		got, served, err := service.Build(ctx, p)
		if err != nil {
			t.Fatalf("%s: %v", a.Email, err)
		}
		if !served {
			handedOn++
			continue
		}
		compared++
		want := &screensv1.GetHomeResponse{}
		if err := protojson.Unmarshal(a.Body, want); err != nil {
			t.Fatalf("%s: reading the existing answer: %v", a.Email, err)
		}
		if !proto.Equal(got, want) {
			differing++
			g, w := protojson.Format(got), protojson.Format(want)
			at := 0
			for at < len(g) && at < len(w) && g[at] == w[at] {
				at++
			}
			t.Errorf("%s differs at byte %d:\n go:       …%s\n existing: …%s", a.Email, at,
				g[max(at-200, 0):min(at+200, len(g))], w[max(at-200, 0):min(at+200, len(w))])
		}
	}
	t.Logf("%d answers compared, %d handed on, %d differing", compared, handedOn, differing)
	if compared == 0 {
		t.Fatal("the golden asks Go nothing")
	}
}
