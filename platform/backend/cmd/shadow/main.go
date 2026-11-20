// Command shadow compares two copies of the database after the same saves:
// the existing application's on one, Go's on the other (docs/migration/
// 03-database-protection.md, 3.7: a Go write path is proved in shadow on a
// restored copy before any table's writer moves).
//
// Both copies start from the same template, so every difference is the
// saves'. A table whose contents hash the same on both is equal. For the
// rest, each copy's rows the other lacks are compared after the two things
// that legitimately differ are set aside: identifiers the run made (a row
// inserted on one copy carries an id the other cannot share) read as <new>,
// and timestamps inside the run's window read as <now>. The audit chain's
// sequence and hashes follow from those, so they read as <chain>. What is
// left must match row for row.
//
//	shadow -a postgresql://localhost/edify_shadow_a -b postgresql://localhost/edify_shadow_b \
//	  -from 2026-11-12T15:00:00+03:00 -to 2026-11-12T15:10:00+03:00
//
// It only reads. It refuses a database whose name does not start with
// edify_shadow_, so it is never pointed at a database people use.
package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/parity"
	"os"
	"regexp"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

// chainColumns are the audit chain's own columns: they are computed from the
// rows' ids and times, which differ by run. A request's correlation id is a
// random tag per request, and an incident's samples are those tags.
var chainColumns = map[string]map[string]bool{
	"audit_log":             {"seq": true, "hash": true, "prev_hash": true, "correlation_id": true},
	"domain_event_log":      {"correlation_id": true},
	"admin_system_incident": {"samples": true},
}

// noise are tables a request writes about itself rather than about the work:
// the runner's sign-in sessions (Django's, and the gateway's refresh tokens
// when the app's runner signs in through it: a random token, its family and
// a week-ahead expiry) and each request's timing telemetry — and
// the time a person is seen on pages (the session's active seconds on
// login_event, presence_time), which are wall-clock readings two runs can
// never share, and which a Go save, made without opening a page, does not
// touch. They are left out unless -all is given.
var noise = map[string]bool{
	"django_session": true, "interaction_event": true, "login_event": true, "presence_time": true,
	"refresh_token": true,
}

// serialIDs are tables whose id is a database serial the existing
// application hands out in an order Go cannot match: a group training's
// invitations are inserted in a Python set's order (cluster_attendance
// _clean_ids), which differs between processes (docs/migration/38 §38.5).
// A row the run wrote there is compared by what it says (its session, its
// school, its counts), its id read as <new>.
var serialIDs = map[string]bool{"cluster_activity_attendance": true}

func main() {
	a := flag.String("a", "", "the first copy (the existing application's saves)")
	b := flag.String("b", "", "the second copy (Go's saves, or the existing application's again)")
	from := flag.String("from", "", "the run's start (RFC 3339); timestamps from here to -to read as <now>")
	to := flag.String("to", "", "the run's end (RFC 3339)")
	show := flag.Int("show", 3, "rows to print for each table that differs")
	all := flag.Bool("all", false, "compare the request-noise tables too (sessions, timing telemetry)")
	scenario := flag.String("scenario", "", "the save scenario's name (snooze_todo …): rows that differ only as internal/parity/intended.json lists for it are accepted")
	flag.Parse()
	list, err := parity.CheckedIn()
	if err != nil {
		fmt.Fprintln(os.Stderr, "shadow:", err)
		os.Exit(2)
	}
	intended, scenarioName = list, *scenario
	if *all {
		noise = map[string]bool{}
	}
	start, err1 := time.Parse(time.RFC3339, *from)
	end, err2 := time.Parse(time.RFC3339, *to)
	if *a == "" || *b == "" || err1 != nil || err2 != nil || end.Before(start) {
		fmt.Fprintln(os.Stderr, "shadow: -a, -b, -from and -to are required, -from before -to")
		os.Exit(2)
	}
	differing, err := run(context.Background(), *a, *b, window{start, end}, *show)
	if err != nil {
		fmt.Fprintln(os.Stderr, "shadow:", err)
		os.Exit(2)
	}
	if differing > 0 {
		os.Exit(1)
	}
}

// intended is the checked-in list of intended differences and scenarioName
// the scenario they are looked up under (internal/parity).
var (
	intended     *parity.List
	scenarioName string
)

type window struct{ from, to time.Time }

func connect(ctx context.Context, dsn string) (*pgx.Conn, error) {
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		return nil, err
	}
	if name := conn.Config().Database; !strings.HasPrefix(name, "edify_shadow_") {
		_ = conn.Close(ctx)
		return nil, fmt.Errorf("refusing %q: shadow copies are named edify_shadow_…", name)
	}
	if _, err := conn.Exec(ctx, "SET default_transaction_read_only = on"); err != nil {
		_ = conn.Close(ctx)
		return nil, err
	}
	return conn, nil
}

// copies are the two databases' rows the other lacks, by table, and every
// id each holds in the tables that changed.
type copies struct {
	onlyA, onlyB map[string][]map[string]any
	idsA, idsB   map[string]map[string]bool
}

func run(ctx context.Context, dsnA, dsnB string, w window, show int) (int, error) {
	a, err := connect(ctx, dsnA)
	if err != nil {
		return 0, err
	}
	defer a.Close(ctx)
	b, err := connect(ctx, dsnB)
	if err != nil {
		return 0, err
	}
	defer b.Close(ctx)

	tables, err := tablesOf(ctx, a)
	if err != nil {
		return 0, err
	}
	changed, err := changedTables(ctx, a, b, tables)
	if err != nil {
		return 0, err
	}
	c, err := load(ctx, a, b, changed)
	if err != nil {
		return 0, err
	}
	newA, newB := made(c.onlyA, c.idsB), made(c.onlyB, c.idsA)

	differing := 0
	fmt.Printf("%d tables, %d changed by the runs\n", len(tables), len(changed))
	for _, t := range changed {
		na := normalised(c.onlyA[t], t, newA, w)
		nb := normalised(c.onlyB[t], t, newB, w)
		extraA, extraB := minusStrings(na, nb), minusStrings(nb, na)
		if len(extraA) == 0 && len(extraB) == 0 {
			fmt.Printf("  %-40s same (%d rows written on each)\n", t, len(na))
			continue
		}
		pairs, restA, restB := intended.PairRows(parity.Answer{Tool: parity.ToolShadow, Where: scenarioName, Question: t}, extraA, extraB)
		if len(restA) == 0 && len(restB) == 0 {
			fmt.Printf("  %-40s same but as intended (%d rows written on each, %d differing only as listed)\n", t, len(na), len(pairs))
			for _, p := range pairs {
				fmt.Println(parity.IntendedLines(p.Accepted))
			}
			continue
		}
		differing++
		fmt.Printf("  %-40s DIFFERS: %d rows only in a, %d only in b\n", t, len(restA), len(restB))
		printSome("a", restA, show)
		printSome("b", restB, show)
	}
	fmt.Printf("%d of %d changed tables differ\n", differing, len(changed))
	return differing, nil
}

func printSome(side string, rows []string, show int) {
	for i, r := range rows {
		if i == show {
			return
		}
		fmt.Printf("    %s: %s\n", side, r)
	}
}

func changedTables(ctx context.Context, a, b *pgx.Conn, tables []string) ([]string, error) {
	changed := []string{}
	for _, t := range tables {
		if noise[t] {
			continue
		}
		ha, err := digest(ctx, a, t)
		if err != nil {
			return nil, err
		}
		hb, err := digest(ctx, b, t)
		if err != nil {
			return nil, err
		}
		if ha != hb {
			changed = append(changed, t)
		}
	}
	return changed, nil
}

func load(ctx context.Context, a, b *pgx.Conn, changed []string) (copies, error) {
	c := copies{onlyA: map[string][]map[string]any{}, onlyB: map[string][]map[string]any{},
		idsA: map[string]map[string]bool{}, idsB: map[string]map[string]bool{}}
	for _, t := range changed {
		ra, err := rowsOf(ctx, a, t)
		if err != nil {
			return c, err
		}
		rb, err := rowsOf(ctx, b, t)
		if err != nil {
			return c, err
		}
		c.onlyA[t], c.onlyB[t] = minus(ra, rb), minus(rb, ra)
		c.idsA[t], c.idsB[t] = idSet(ra), idSet(rb)
	}
	return c, nil
}

// made is the ids a copy's run made: an inserted row's id the other copy's
// table does not hold.
func made(only map[string][]map[string]any, otherIDs map[string]map[string]bool) map[string]bool {
	out := map[string]bool{}
	for t, rows := range only {
		for _, r := range rows {
			if id, ok := r["id"].(string); ok && !otherIDs[t][id] {
				out[id] = true
			}
		}
	}
	return out
}

func tablesOf(ctx context.Context, conn *pgx.Conn) ([]string, error) {
	rows, err := conn.Query(ctx, `SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name`)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, pgx.RowTo[string])
}

func quote(table string) string { return pgx.Identifier{table}.Sanitize() }

// digest is a hash of the table's rows in a fixed order.
func digest(ctx context.Context, conn *pgx.Conn, table string) (string, error) {
	var h *string
	err := conn.QueryRow(ctx, `SELECT md5(string_agg(t::text, E'\n' ORDER BY t::text)) FROM `+quote(table)+` t`).Scan(&h)
	if err != nil || h == nil {
		return "", err
	}
	return *h, nil
}

func rowsOf(ctx context.Context, conn *pgx.Conn, table string) ([]map[string]any, error) {
	rows, err := conn.Query(ctx, `SELECT to_jsonb(t)::text FROM `+quote(table)+` t`)
	if err != nil {
		return nil, err
	}
	texts, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, err
	}
	out := make([]map[string]any, 0, len(texts))
	for _, text := range texts {
		var row map[string]any
		if err := json.Unmarshal([]byte(text), &row); err != nil {
			return nil, fmt.Errorf("%s: %w", table, err)
		}
		out = append(out, row)
	}
	return out, nil
}

func idSet(rows []map[string]any) map[string]bool {
	out := map[string]bool{}
	for _, r := range rows {
		if id, ok := r["id"].(string); ok {
			out[id] = true
		}
	}
	return out
}

func key(v any) string {
	raw, _ := json.Marshal(v) // maps marshal with sorted keys
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

// minus is the rows of x that y lacks, counting repeats.
func minus(x, y []map[string]any) []map[string]any {
	counts := map[string]int{}
	for _, r := range y {
		counts[key(r)]++
	}
	out := []map[string]any{}
	for _, r := range x {
		k := key(r)
		if counts[k] > 0 {
			counts[k]--
			continue
		}
		out = append(out, r)
	}
	return out
}

func minusStrings(x, y []string) []string {
	counts := map[string]int{}
	for _, s := range y {
		counts[s]++
	}
	out := []string{}
	for _, s := range x {
		if counts[s] > 0 {
			counts[s]--
			continue
		}
		out = append(out, s)
	}
	return out
}

// normalised writes each row as sorted JSON with the run's own values set
// aside, sorted so the two copies' lists compare in order.
func normalised(rows []map[string]any, table string, made map[string]bool, w window) []string {
	out := make([]string, 0, len(rows))
	for _, r := range rows {
		n := map[string]any{}
		for column, v := range r {
			if chainColumns[table][column] {
				n[column] = "<chain>"
				continue
			}
			if serialIDs[table] && column == "id" {
				n[column] = "<new>"
				continue
			}
			n[column] = settle(v, made, w)
		}
		out = append(out, plainJSON(n))
	}
	sort.Strings(out)
	return out
}

// plainJSON is v as sorted JSON, its <new>, <now> and <chain> left readable.
func plainJSON(v any) string {
	var buf strings.Builder
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(v)
	return strings.TrimSuffix(buf.String(), "\n")
}

// pathToken is one word of a path or its query: what an id in it reads as.
var pathToken = regexp.MustCompile(`[A-Za-z0-9]+`)

func settle(v any, made map[string]bool, w window) any {
	switch x := v.(type) {
	case string:
		if made[x] {
			return "<new>"
		}
		if t, err := time.Parse(time.RFC3339Nano, x); err == nil && !t.Before(w.from) && !t.After(w.to) {
			return "<now>"
		}
		if strings.Contains(x, "/") {
			// A path naming a row the run made ("/admin-ops/incidents/<id>",
			// "/pl/review-queue?open=<id>"): each id in it, in its segments
			// or its query.
			return pathToken.ReplaceAllStringFunc(x, func(part string) string {
				if made[part] {
					return "<new>"
				}
				return part
			})
		}
		return x
	case []any:
		out := slices.Clone(x)
		for i := range out {
			out[i] = settle(out[i], made, w)
		}
		return out
	case map[string]any:
		out := map[string]any{}
		for k, item := range x {
			out[k] = settle(item, made, w)
		}
		return out
	}
	return v
}
