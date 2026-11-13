package workplan

import (
	"context"
	"encoding/json"
	"net/url"
	"os"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The existing feed's own Work Plan for synthetic people in every role
// (testdata/work_plan_golden.py, run against a test database), and that
// database: every page must be the feed's, field for field. Skipped
// without both.
const (
	goldenEnv   = "EDIFY_WORKPLAN_GOLDEN"
	goldenDBEnv = "EDIFY_WORKPLAN_DB"
)

type goldenAnswer struct {
	User   string            `json:"user"`
	Query  map[string]string `json:"query"`
	Status int               `json:"status"`
	Body   json.RawMessage   `json:"body"`
}

func TestTheWorkPlanIsTheFeedsOwn(t *testing.T) {
	path, dsn := os.Getenv(goldenEnv), os.Getenv(goldenDBEnv)
	if path == "" || dsn == "" {
		t.Skipf("set %s and %s to compare with the existing feed", goldenEnv, goldenDBEnv)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Now     time.Time      `json:"now"`
		Answers []goldenAnswer `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	db, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	s := NewService(db, func() time.Time { return golden.Now })
	principals := map[string]auth.Principal{}
	compared, differing, rows := 0, 0, 0
	seen := map[string]int{}
	for _, a := range golden.Answers {
		p, ok := principals[a.User]
		if !ok {
			var profile *string
			if err := db.QueryRow(ctx, `SELECT u.id, u.roles, u.active_role, sp.id FROM "user" u
LEFT JOIN staff_profile sp ON sp.user_id = u.id AND sp.deleted_at IS NULL WHERE u.id = $1`, a.User).
				Scan(&p.UserID, &p.Roles, &p.ActiveRole, &profile); err != nil {
				t.Fatal(err)
			}
			p.StaffProfileID = str(profile)
			principals[a.User] = p
		}
		query := url.Values{}
		for k, v := range a.Query {
			query.Set(k, v)
		}
		page, served, err := s.Build(ctx, p, Path, query)
		if err != nil || !served {
			t.Fatalf("%s %v: served %v, %v", a.User, a.Query, served, err)
		}
		if a.Status != 200 {
			t.Errorf("%s %v: the feed answered %d", a.User, a.Query, a.Status)
			continue
		}
		want := &screensv1.GetPageResponse{}
		if err := protojson.Unmarshal(a.Body, want); err != nil {
			t.Fatal(err)
		}
		compared++
		for _, b := range page.GetBlocks() {
			for _, r := range b.GetTable().GetRows() {
				if len(r.GetCells()) != len(detailColumns) {
					continue
				}
				rows++
				seen["tone "+r.GetTone()]++
				if r.GetPickId() != "" {
					seen["ticked"]++
				}
				for _, act := range r.GetCells()[len(detailColumns)-1].GetActions() {
					seen["action "+act.GetKey()+" "+act.GetLabel()]++
				}
			}
			if b.GetPanel() != nil && len(b.GetPanel().GetItems()) > 0 && b.GetPanel().GetItems()[0].GetText() != "" {
				seen["panel "+b.GetPanel().GetItems()[0].GetText()[:min(12, len(b.GetPanel().GetItems()[0].GetText()))]]++
			}
		}
		if !proto.Equal(page, want) {
			differing++
			gotJSON, _ := protojson.Marshal(page)
			if differing <= 1000 {
				t.Errorf("%s %v differs:\n go %s\n feed %s", a.User, a.Query, gotJSON, a.Body)
			} else {
				t.Errorf("%s %v differs", a.User, a.Query)
			}
		}
	}
	t.Logf("%d pages compared (%d rows of the Detailed Activity Plan), %d differing", compared, rows, differing)
	t.Logf("what the compared pages held: %v", seen)
	if compared == 0 {
		t.Error("no page was compared")
	}
}
