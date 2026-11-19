//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/home"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/todos"
)

// homeGoldenTables are the tables besides activity that golden.py files rows
// in (its TABLES).
var homeGoldenTables = []string{"monthly_work_plan_budget", "country_annual_budget", "rvp_strategy_note"}

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
		Now     time.Time                    `json:"now"`
		Rows    []json.RawMessage            `json:"rows"`
		Tables  map[string][]json.RawMessage `json:"tables"`
		Answers []struct {
			Email       string          `json:"email"`
			Status      int             `json:"status"`
			Body        json.RawMessage `json:"body"`
			Queue       json.RawMessage `json:"queue"`
			TodoFigures json.RawMessage `json:"todo_figures"`
			TodoRows    json.RawMessage `json:"todo_rows"`
			// Each answer's HTTP status (403: the role may not open Home).
			BodyStatus        int `json:"body_status"`
			QueueStatus       int `json:"queue_status"`
			TodoFiguresStatus int `json:"todo_figures_status"`
		} `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	// The work, then the RVP's budgets and strategy note golden.py files.
	tables := append([]string{"activity"}, homeGoldenTables...)
	filed := map[string][]json.RawMessage{"activity": golden.Rows}
	for _, table := range homeGoldenTables {
		filed[table] = golden.Tables[table]
	}
	clear := func() {
		for _, table := range tables {
			if _, err := admin.Exec(ctx, `DELETE FROM `+pgx.Identifier{table}.Sanitize()+` WHERE id LIKE 'ghome%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range tables {
		name := pgx.Identifier{table}.Sanitize()
		for _, row := range filed[table] {
			if _, err := admin.Exec(ctx, `INSERT INTO `+name+` SELECT * FROM json_populate_record(NULL::`+name+`, $1::json)`, string(row)); err != nil {
				t.Fatalf("filing %s: %v", table, err)
			}
		}
	}
	at := func() time.Time { return golden.Now }
	service := home.NewService(gateway, at)
	queues := todos.NewService(gateway, at)
	compared, handedOn, differing := 0, 0, 0
	var passed []string
	for _, a := range golden.Answers {
		var p auth.Principal
		if err := admin.QueryRow(ctx, `SELECT u.id, u.email, COALESCE(u.name, ''), u.active_role, COALESCE(sp.id, '')
FROM "user" u LEFT JOIN staff_profile sp ON sp.user_id = u.id WHERE u.email = $1 AND u.deleted_at IS NULL`, a.Email).
			Scan(&p.UserID, &p.Email, &p.Name, &p.ActiveRole, &p.StaffProfileID); err != nil {
			t.Fatalf("the test database needs %s (demo seed): %v", a.Email, err)
		}
		p.Roles = []string{p.ActiveRole}
		// The To-Do rows Home's Priority actions are drawn from, word for word.
		switch d, asked, err := todoRowsDiffer(ctx, queues, p, a.TodoRows); {
		case err != nil:
			t.Fatalf("%s to-do rows: %v", a.Email, err)
		case !asked:
			handedOn++
			passed = append(passed, a.Email+" to-do rows")
		case d != "":
			compared++
			differing++
			t.Errorf("%s to-do rows differ: %s", a.Email, d)
		default:
			compared++
		}
		// Each of Home's three answers, where Go answers it.
		for _, part := range []struct {
			name     string
			build    func() (proto.Message, bool, error)
			existing json.RawMessage
			status   int
			want     proto.Message
		}{
			{"home", func() (proto.Message, bool, error) { return service.Build(ctx, p) }, a.Body, a.BodyStatus, &screensv1.GetHomeResponse{}},
			{"queue", func() (proto.Message, bool, error) { return service.BuildQueue(ctx, p) }, a.Queue, a.QueueStatus, &screensv1.GetHomeQueueResponse{}},
			{"to-do figures", func() (proto.Message, bool, error) { return service.BuildTodoFigures(ctx, p) }, a.TodoFigures, a.TodoFiguresStatus, &screensv1.GetHomeTodoFiguresResponse{}},
		} {
			got, served, err := part.build()
			// A refusal is compared as one: Go refuses exactly where the
			// existing feed answered 403.
			if refusedByGo, refusedByFeed := errors.Is(err, home.ErrForbidden), part.status == http.StatusForbidden; refusedByGo || refusedByFeed {
				compared++
				if refusedByGo != refusedByFeed {
					differing++
					t.Errorf("%s %s: go refused %v, the existing feed answered %d", a.Email, part.name, refusedByGo, part.status)
				}
				continue
			}
			if err != nil {
				t.Fatalf("%s %s: %v", a.Email, part.name, err)
			}
			if !served {
				handedOn++
				passed = append(passed, a.Email+" "+part.name)
				continue
			}
			compared++
			if err := protojson.Unmarshal(part.existing, part.want); err != nil {
				t.Fatalf("%s %s: reading the existing answer: %v", a.Email, part.name, err)
			}
			if !proto.Equal(got, part.want) {
				differing++
				g, w := protojson.Format(got), protojson.Format(part.want)
				at := 0
				for at < len(g) && at < len(w) && g[at] == w[at] {
					at++
				}
				t.Errorf("%s %s differs at byte %d:\n go:       …%s\n existing: …%s", a.Email, part.name, at,
					g[max(at-200, 0):min(at+200, len(g))], w[max(at-200, 0):min(at+200, len(w))])
			}
		}
	}
	t.Logf("%d answers compared, %d handed on, %d differing", compared, handedOn, differing)
	t.Logf("handed on: %s", strings.Join(passed, "; "))
	if compared == 0 {
		t.Fatal("the golden asks Go nothing")
	}
}

// todoRowsDiffer compares Go's queue for p with the rows the existing queue
// gave (golden.py's todo_rows): "" when they agree. compared is false when
// Go hands the queue on. A description is compared only on a row with no
// link, the only place Home reads it.
func todoRowsDiffer(ctx context.Context, queues *todos.Service, p auth.Principal, existing json.RawMessage) (string, bool, error) {
	q, served, err := queues.HomeQueue(ctx, p)
	if err != nil || !served {
		return "", false, err
	}
	var want []map[string]string
	if err := json.Unmarshal(existing, &want); err != nil {
		return "", true, fmt.Errorf("the existing queue gave no rows (%s): %w", existing, err)
	}
	if len(q.Rows) != len(want) {
		return fmt.Sprintf("go has %d rows, the existing queue %d", len(q.Rows), len(want)), true, nil
	}
	for i, r := range q.Rows {
		got := map[string]string{"title": r.Title, "category": r.Category, "priority": r.Priority,
			"status_key": r.StatusKey, "status_label": r.StatusLabel, "status_tone": r.StatusTone,
			"due_label": r.DueLabel, "due_tone": r.DueTone, "linked": r.Linked,
			"action_label": r.ActionLabel, "action_url": r.ActionURL, "description": r.Description}
		w := want[i]
		if w["linked"] != "" {
			got["description"] = w["description"]
		}
		for k, v := range w {
			if got[k] != v {
				return fmt.Sprintf("row %d (%s) %s: go %q, existing %q", i, w["title"], k, got[k], v), true, nil
			}
		}
	}
	return "", true, nil
}
