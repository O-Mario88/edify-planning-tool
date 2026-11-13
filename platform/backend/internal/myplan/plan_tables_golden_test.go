package myplan

import (
	"context"
	"encoding/json"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// The existing feed's own My Plan for synthetic people
// (testdata/plan_tables_golden.py, run against the test database), and that
// database: every page Go answers must be the feed's, field for field. A
// page Go passes is counted as passed. Skipped without both.
const (
	tablesGoldenEnv   = "EDIFY_MYPLAN_TABLES_GOLDEN"
	tablesGoldenDBEnv = "EDIFY_MYPLAN_TABLES_DB"
)

type tablesAnswer struct {
	User   string            `json:"user"`
	Query  map[string]string `json:"query"`
	Status int               `json:"status"`
	Body   json.RawMessage   `json:"body"`
}

func TestMyPlansTablesAreTheFeedsOwn(t *testing.T) {
	path, dsn := os.Getenv(tablesGoldenEnv), os.Getenv(tablesGoldenDBEnv)
	if path == "" || dsn == "" {
		t.Skipf("set %s and %s to compare with the existing feed", tablesGoldenEnv, tablesGoldenDBEnv)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Now     time.Time      `json:"now"`
		Answers []tablesAnswer `json:"answers"`
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
	compared, differing, passed, rows := 0, 0, 0, 0
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
		if err != nil {
			t.Fatalf("%s %v: %v", a.User, a.Query, err)
		}
		if !served {
			passed++
			continue
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
			table := b.GetTable()
			switch table.GetTitle() {
			case "Returned — Needs Correction", "Waiting on Approval", "Finance / Accountability Pending":
				seen["card "+table.GetTitle()] += len(table.GetRows())
				for _, r := range table.GetRows() {
					seen["card cell "+r.GetCells()[len(r.GetCells())-1].GetText()]++
				}
			}
			if strings.HasPrefix(table.GetTitle(), "Reschedule — ") {
				seen["day-off card rows"] += len(table.GetRows())
				for _, r := range table.GetRows() {
					seen["day off "+r.GetCells()[3].GetText()]++
				}
			}
			if !strings.Contains(table.GetTitle(), " Planned for ") && !strings.Contains(table.GetTitle(), "Trainings Planned (") {
				continue
			}
			rows += len(table.GetRows())
			for _, r := range table.GetRows() {
				seen["table "+strings.SplitN(table.GetTitle(), " Planned", 2)[0]]++
				seen["tone "+r.GetTone()]++
				if r.GetPickId() != "" {
					seen["ticked"]++
				}
				for _, c := range r.GetCells() {
					if c.GetBadge() {
						seen["pill "+c.GetText()]++
					}
					for _, act := range c.GetActions() {
						seen["action "+act.GetLabel()]++
					}
					if c.GetText() == "Monitoring — partner-owned" {
						seen["monitoring"]++
					}
				}
			}
		}
		if !proto.Equal(page, want) {
			differing++
			gotJSON, _ := protojson.Marshal(page)
			t.Errorf("%s %v differs:\n go %s\n feed %s", a.User, a.Query, gotJSON, a.Body)
		}
	}
	t.Logf("%d pages compared (%d rows of the plan's tables), %d differing; %d passed to the existing application", compared, rows, differing, passed)
	t.Logf("what the compared rows held: %v", seen)
	if compared == 0 {
		t.Error("no page was answered by Go")
	}
}
