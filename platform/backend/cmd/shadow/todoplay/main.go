// Command todoplay plays a shadow scenario of Today's Snooze through Go
// (docs/migration/26-shadow-writes.md, 50): the second half of the
// comparison, on copy B.
//
// Each step posts Today's Snooze menu (todo, choice, title) or its Undo
// (todo, and the This Week Me tab's today_section) as the person it names. A
// /today/snooze step is made by internal/todosnooze's Snooze; a
// /today/unsnooze step by its Unsnooze (the row removed through
// gateway_todos.unsnooze, docs/migration/63), after which the Today panel the
// answer shows is read from the existing application on copy B (the redraw
// the gateway asks it for). A step Go hands on (a reader it does not take)
// is made by the existing application, as the gateway would forward it: the
// Django runner plays that one step on copy B. Each step's answer is then
// held to copy A's, word for word: what the existing row draws reads
// "{title} — snoozed until {day} Undo", a refusal its words in the row's
// error slot, and an undo the panel's words with the panel as its target.
//
//	go run ./cmd/shadow/todoplay -b postgresql:///edify_shadow_b -scenario s.json \
//	  -a-out a.json -out b.json -python .venv/bin/python -repo <worktree>
//
// It refuses any database not named edify_shadow_*. Its connection works as
// the gateway's own role (SET ROLE edify_gateway, read-only by default), so
// the save has exactly the gateway's grants.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/identity"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/presence"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/todosnooze"
)

type step struct {
	Who  string            `json:"who"`
	Post string            `json:"post"`
	Data map[string]string `json:"data"`
}

type outcome struct {
	OK       bool   `json:"ok"`
	Status   int    `json:"status"`
	Retarget string `json:"retarget"`
	Message  string `json:"message"`
	HandedOn bool   `json:"handed_on,omitempty"`
	// Redrawn is a Go save whose answer is a page the existing
	// application drew afterwards (an undo's Today panel).
	Redrawn bool `json:"redrawn,omitempty"`
}

type outcomes struct {
	Database string    `json:"database"`
	From     string    `json:"from"`
	To       string    `json:"to"`
	Outcomes []outcome `json:"outcomes"`
}

func main() {
	dsn := flag.String("b", "", "copy B (Go's saves)")
	scenarioPath := flag.String("scenario", "", "the scenario")
	aOut := flag.String("a-out", "", "the existing application's outcomes on copy A")
	out := flag.String("out", "", "where Go's outcomes are written")
	runner := flag.String("python", "", "the Python that runs manage.py shell (for handed-on steps)")
	repo := flag.String("repo", ".", "the worktree the runner runs in")
	flag.Parse()
	if err := run(*dsn, *scenarioPath, *aOut, *out, *runner, *repo); err != nil {
		fmt.Fprintln(os.Stderr, "todoplay:", err)
		os.Exit(2)
	}
}

func readJSON(path string, into any) error {
	raw, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(raw, into)
}

func run(dsn, scenarioPath, aOut, out, runner, repo string) error {
	ctx := context.Background()
	var steps []step
	var raw []json.RawMessage
	if err := readJSON(scenarioPath, &steps); err != nil {
		return err
	}
	if err := readJSON(scenarioPath, &raw); err != nil {
		return err
	}
	var a outcomes
	if err := readJSON(aOut, &a); err != nil {
		return err
	}
	if len(a.Outcomes) != len(steps) {
		return fmt.Errorf("copy A has %d outcomes for %d steps", len(a.Outcomes), len(steps))
	}
	cfg, err := pgxpool.ParseConfig(dsn)
	if err != nil {
		return err
	}
	if !strings.HasPrefix(cfg.ConnConfig.Database, "edify_shadow_") {
		return fmt.Errorf("refusing %q: shadow copies are named edify_shadow_…", cfg.ConnConfig.Database)
	}
	cfg.AfterConnect = func(ctx context.Context, c *pgx.Conn) error {
		_, err := c.Exec(ctx, "SET ROLE edify_gateway; SET default_transaction_read_only = on")
		return err
	}
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return err
	}
	defer pool.Close()
	svc, err := todosnooze.NewService(pool, nil)
	if err != nil {
		return err
	}
	// Each Go save stamps the person's presence as the middleware stamps the
	// post on copy A (docs/migration/65).
	svc.WithPresence(presence.NewStamper(pool), slog.New(slog.NewTextHandler(os.Stderr, nil)))
	accounts := identity.NewStore(pool)

	result := outcomes{Database: cfg.ConnConfig.Database, From: time.Now().UTC().Format(time.RFC3339Nano)}
	for i, s := range steps {
		o, redraw, err := play(ctx, svc, accounts, pool, s)
		if err == nil && redraw != nil {
			o, err = drawn(s.Who, *redraw, dsn, runner, repo)
		}
		if errors.Is(err, todosnooze.ErrHandOn) {
			o, err = handOn(raw[i], dsn, runner, repo)
			o.HandedOn = true
		}
		if err != nil {
			return fmt.Errorf("step %d: %w", i+1, err)
		}
		result.Outcomes = append(result.Outcomes, o)
	}
	result.To = time.Now().UTC().Format(time.RFC3339Nano)
	encoded, _ := json.MarshalIndent(result, "", "  ")
	if err := os.WriteFile(out, encoded, 0o600); err != nil {
		return err
	}
	return compare(a, result)
}

// play makes one step through Go. An undo answers no outcome of its own but
// the redraw the existing application is asked for.
func play(ctx context.Context, svc *todosnooze.Service, accounts *identity.Store, pool *pgxpool.Pool, s step) (outcome, *todosnooze.Redraw, error) {
	if s.Post != "/today/snooze" && s.Post != "/today/unsnooze" {
		return outcome{}, nil, todosnooze.ErrHandOn
	}
	var userID string
	if err := pool.QueryRow(ctx, `SELECT id FROM "user" WHERE email = $1`, s.Who).Scan(&userID); err != nil {
		return outcome{}, nil, fmt.Errorf("finding %s: %w", s.Who, err)
	}
	account, err := accounts.LoadAccount(ctx, userID)
	if err != nil {
		return outcome{}, nil, err
	}
	p := auth.Principal{Account: account}
	if s.Post == "/today/unsnooze" {
		redraw, err := svc.Unsnooze(ctx, p, todosnooze.UnsnoozeRequest{TodoID: s.Data["todo"], Section: s.Data["today_section"]})
		if err != nil {
			return outcome{}, nil, err
		}
		return outcome{}, &redraw, nil
	}
	answer, err := svc.Snooze(ctx, p,
		todosnooze.Request{TodoID: s.Data["todo"], Choice: s.Data["choice"], Title: s.Data["title"]})
	var refusal *todosnooze.Refusal
	switch {
	case errors.As(err, &refusal):
		// _refusal: the words, escaped, into the row's error slot.
		return outcome{OK: true, Status: 200, Retarget: "#" + refusal.Slug + " [data-today-error]",
			Message: readAs(escape(refusal.Message))}, nil, nil
	case err != nil:
		return outcome{}, nil, err
	}
	// queue_item_done.html: "✓ {title} — {message}" and the Undo button.
	return outcome{OK: true, Status: 200, Message: readAs(escape(answer.Title) + " — " + answer.Message + " Undo")}, nil, nil
}

// drawn reads the page an undo's answer shows from the existing application
// on copy B, as the person, and puts it where Go's answer says.
func drawn(who string, redraw todosnooze.Redraw, dsn, runner, repo string) (outcome, error) {
	read, err := json.Marshal(map[string]any{"who": who, "get": redraw.Path, "background": true})
	if err != nil {
		return outcome{}, err
	}
	o, err := handOn(read, dsn, runner, repo)
	if err != nil {
		return outcome{}, err
	}
	o.Retarget, o.Redrawn = redraw.Retarget, true
	return o, nil
}

// escape is Django's escape (conditional_escape on a str).
func escape(s string) string {
	return strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;", `"`, "&quot;", "'", "&#x27;").Replace(s)
}

// readAs is the runner's message(): the text with its spaces collapsed, at
// most 400 characters.
func readAs(s string) string {
	s = strings.Join(strings.Fields(s), " ")
	if r := []rune(s); len(r) > 400 {
		s = string(r[:400])
	}
	return s
}

func handOn(rawStep json.RawMessage, dsn, runner, repo string) (outcome, error) {
	dir, err := os.MkdirTemp("", "todoplay-")
	if err != nil {
		return outcome{}, err
	}
	defer os.RemoveAll(dir)
	scenario := filepath.Join(dir, "step.json")
	result := filepath.Join(dir, "out.json")
	if err := os.WriteFile(scenario, []byte("["+string(rawStep)+"]"), 0o600); err != nil {
		return outcome{}, err
	}
	script, err := os.Open(filepath.Join(repo, "platform/backend/cmd/shadow/django_runner.py"))
	if err != nil {
		return outcome{}, err
	}
	defer script.Close()
	cmd := exec.Command(runner, "manage.py", "shell") // #nosec G204 -- the operator's own Python
	cmd.Dir = repo
	cmd.Stdin = script
	cmd.Stdout, cmd.Stderr = io.Discard, os.Stderr
	cmd.Env = append(os.Environ(), "DATABASE_URL="+dsn, "SCENARIO="+scenario, "OUT="+result)
	if err := cmd.Run(); err != nil {
		return outcome{}, err
	}
	var played outcomes
	if err := readJSON(result, &played); err != nil {
		return outcome{}, err
	}
	return played.Outcomes[0], nil
}

// compare holds every step's answer to copy A's: the same status and
// retarget, and the same words (a handed-on panel's words up to the first
// 120 characters, since it draws the time of day the run reached it).
func compare(a, b outcomes) error {
	differing, byGo := 0, 0
	for i := range a.Outcomes {
		x, y := a.Outcomes[i], b.Outcomes[i]
		how := "Go"
		if y.Redrawn {
			how = "Go, panel redrawn"
		}
		if !y.HandedOn {
			byGo++
		}
		same := x.OK == y.OK && x.Status == y.Status && x.Retarget == y.Retarget && x.Message == y.Message
		if y.HandedOn {
			how = "handed on"
			same = x.OK == y.OK && x.Status == y.Status && x.Retarget == y.Retarget && head(x.Message) == head(y.Message)
		}
		mark := "same"
		if !same {
			mark = "DIFFERS"
			differing++
		}
		fmt.Printf("step %d (%s): %s — a: %d %q; b: %d %q\n", i+1, how, mark, x.Status, head(x.Message), y.Status, head(y.Message))
	}
	fmt.Printf("%d of %d steps made by Go, %d handed on\n", byGo, len(a.Outcomes), len(a.Outcomes)-byGo)
	fmt.Printf("%d of %d steps answered differently\n", differing, len(a.Outcomes))
	if differing > 0 {
		return errors.New("the outcomes differ")
	}
	return nil
}

func head(s string) string {
	if r := []rune(s); len(r) > 120 {
		return string(r[:120])
	}
	return s
}
