// Command goplay plays a shadow scenario's saves through Go (docs/migration/
// 26-shadow-writes.md, 27): the second half of the comparison, on copy B.
//
// Each step is made with the same drawer fields the existing application's
// runner posted on copy A (its outcomes file records them), as the person
// the step names, through internal/activities' save. A step Go hands on is
// made by the existing application, as the gateway would forward it: the
// Django runner plays that one step on copy B. The pricing that follows a Go
// save is asked of, and settled by, the existing application serving copy B
// (-django), as the gateway asks it.
//
//	go run ./cmd/shadow/goplay -b postgresql:///edify_shadow_b -scenario s.json \
//	  -a-out a.json -out b.json -django http://127.0.0.1:8196 -key "$EDIFY_INTERNAL_KEY" \
//	  -python .venv/bin/python -repo <worktree>
//
// It refuses any database not named edify_shadow_*. Its connection works as
// the gateway's own role (SET ROLE edify_gateway, read-only by default), so
// the save has exactly the gateway's grants.
package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"html"
	"io"
	"log/slog"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreforms"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/identity"
)

type step struct {
	Who  string `json:"who"`
	Open string `json:"open"`
}

type outcome struct {
	OK       bool                `json:"ok"`
	Status   int                 `json:"status,omitempty"`
	Message  string              `json:"message"`
	HandedOn bool                `json:"handed_on,omitempty"`
	Posted   map[string][]string `json:"posted,omitempty"`
	// Flash is a reloading save's flash message (the group actions'), and
	// PostedTexts the posted activity_ids' purpose texts (django_runner.py).
	Flash       []string `json:"flash,omitempty"`
	PostedTexts []string `json:"posted_texts,omitempty"`
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
	aOut := flag.String("a-out", "", "the existing application's outcomes on copy A (with the posted fields)")
	out := flag.String("out", "", "where Go's outcomes are written")
	django := flag.String("django", "", "the existing application serving copy B")
	key := flag.String("key", os.Getenv("EDIFY_INTERNAL_KEY"), "its internal key")
	runner := flag.String("python", "", "the Python that runs manage.py shell (for handed-on steps)")
	repo := flag.String("repo", ".", "the worktree the runner runs in")
	flag.Parse()
	if err := run(*dsn, *scenarioPath, *aOut, *out, *django, *key, *runner, *repo); err != nil {
		fmt.Fprintln(os.Stderr, "goplay:", err)
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

func run(dsn, scenarioPath, aOut, out, django, key, runner, repo string) error {
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
	logger := slog.New(slog.NewTextHandler(os.Stderr, nil))
	svc, err := activities.NewService(pool, activities.NewHTTPPricing(django, key, nil), logger, nil)
	if err != nil {
		return err
	}
	forms := coreforms.NewService(pool, time.Now)
	svc.WithVisitRequests(forms).WithGovernedSupport(forms)
	accounts := identity.NewStore(pool)

	result := outcomes{Database: cfg.ConnConfig.Database, From: time.Now().UTC().Format(time.RFC3339Nano)}
	for i, s := range steps {
		posted := a.Outcomes[i].Posted
		var o outcome
		if posted == nil {
			// The drawer did not open on copy A: there is no save to make,
			// and the gateway reads every drawer from the existing
			// application, so its door is met there on copy B too.
			o, err = handOn(raw[i], dsn, runner, repo)
			if err != nil {
				return fmt.Errorf("step %d (drawer refused): %w", i+1, err)
			}
			o.HandedOn = true
		} else {
			o, err = play(ctx, svc, accounts, pool, s, url.Values(posted), a.Outcomes[i].PostedTexts)
			if err != nil {
				return fmt.Errorf("step %d: %w", i+1, err)
			}
			if o.HandedOn {
				o, err = handOn(raw[i], dsn, runner, repo)
				if err != nil {
					return fmt.Errorf("step %d (handed on): %w", i+1, err)
				}
				o.HandedOn = true
			}
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

func play(ctx context.Context, svc *activities.Service, accounts *identity.Store, pool *pgxpool.Pool,
	s step, form url.Values, texts []string) (outcome, error) {
	if m := groupDrawer.FindStringSubmatch(s.Open); m != nil {
		return playGroup(ctx, svc, accounts, pool, s, m[1], form, texts)
	}
	if m := moveDrawer.FindStringSubmatch(s.Open); m != nil {
		return playMove(ctx, svc, accounts, pool, s, m[1], form)
	}
	if m := cancelDrawer.FindStringSubmatch(s.Open); m != nil {
		return playCancel(ctx, svc, accounts, pool, s, m[1], form)
	}
	if m := editDrawer.FindStringSubmatch(s.Open); m != nil {
		return playEdit(ctx, svc, accounts, pool, s, m[1], form)
	}
	if strings.HasPrefix(s.Open, "/core-schools/schedule-visit?") {
		return playCoreVisit(ctx, svc, accounts, pool, s, form)
	}
	if activities.IsGroupTrainingForm(form) {
		return playGroupTraining(ctx, svc, accounts, pool, s, form)
	}
	if activities.IsClusterMeetingForm(form) {
		return playClusterMeeting(ctx, svc, accounts, pool, s, form)
	}
	req, taken := activities.RequestFromForm(form)
	if !taken {
		return outcome{HandedOn: true}, nil
	}
	var userID string
	if err := pool.QueryRow(ctx, `SELECT id FROM "user" WHERE email = $1`, s.Who).Scan(&userID); err != nil {
		return outcome{}, fmt.Errorf("finding %s: %w", s.Who, err)
	}
	account, err := accounts.LoadAccount(ctx, userID)
	if err != nil {
		return outcome{}, err
	}
	account.InActingAppointment = account.Acting.WorkingIn(account.ActiveRole)
	correlation := newCorrelation()
	answer, err := svc.Schedule(ctx, auth.Principal{Account: account}, req,
		activities.Origin{IP: "127.0.0.1", CorrelationID: correlation})
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		fmt.Fprintln(os.Stderr, "goplay:", s.Who, "→", err)
		return outcome{HandedOn: true}, nil
	case errors.As(err, &refusal):
		status := 400
		if refusal.Forbidden {
			status = 403
		}
		return outcome{OK: false, Status: status, Message: refusal.Message}, nil
	case err != nil:
		return outcome{}, err
	}
	message := answer.Message
	if answer.Notice != "" {
		message += " " + answer.Notice
	}
	return outcome{OK: true, Status: 200, Message: message + " " + answer.PlanLinkLabel}, nil
}

// playCoreVisit makes the Core Schools visit form's save through Go.
func playCoreVisit(ctx context.Context, svc *activities.Service, accounts *identity.Store, pool *pgxpool.Pool,
	s step, form url.Values) (outcome, error) {
	req, taken := activities.CoreVisitRequestFromForm(form.Get("school_id"), form)
	if !taken {
		return outcome{HandedOn: true}, nil
	}
	var userID string
	if err := pool.QueryRow(ctx, `SELECT id FROM "user" WHERE email = $1`, s.Who).Scan(&userID); err != nil {
		return outcome{}, fmt.Errorf("finding %s: %w", s.Who, err)
	}
	account, err := accounts.LoadAccount(ctx, userID)
	if err != nil {
		return outcome{}, err
	}
	account.InActingAppointment = account.Acting.WorkingIn(account.ActiveRole)
	answer, err := svc.ScheduleCoreVisit(ctx, auth.Principal{Account: account}, req,
		activities.Origin{IP: "127.0.0.1", CorrelationID: newCorrelation()})
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		fmt.Fprintln(os.Stderr, "goplay:", s.Who, "→", err)
		return outcome{HandedOn: true}, nil
	case errors.As(err, &refusal):
		status := 400
		if refusal.Forbidden {
			status = 403
		}
		return outcome{OK: false, Status: status, Message: refusal.Message}, nil
	case err != nil:
		return outcome{}, err
	}
	message := answer.Message
	if answer.Notice != "" {
		message += " " + answer.Notice
	}
	if answer.Status == "awaiting_owner_approval" {
		// The form sends a request to the queue: its words carry no link.
		return outcome{OK: true, Status: 200, Message: message}, nil
	}
	return outcome{OK: true, Status: 200, Message: message + " " + answer.PlanLinkLabel}, nil
}

// playGroupTraining makes a cluster's Group Training through Go's save
// (docs/migration/38): the drawer's posted form, the schools ticked by name.
func playGroupTraining(ctx context.Context, svc *activities.Service, accounts *identity.Store, pool *pgxpool.Pool,
	s step, form url.Values) (outcome, error) {
	req, taken := activities.GroupTrainingRequestFromForm(form)
	if !taken {
		return outcome{HandedOn: true}, nil
	}
	var userID string
	if err := pool.QueryRow(ctx, `SELECT id FROM "user" WHERE email = $1`, s.Who).Scan(&userID); err != nil {
		return outcome{}, fmt.Errorf("finding %s: %w", s.Who, err)
	}
	account, err := accounts.LoadAccount(ctx, userID)
	if err != nil {
		return outcome{}, err
	}
	account.InActingAppointment = account.Acting.WorkingIn(account.ActiveRole)
	answer, err := svc.ScheduleGroupTraining(ctx, auth.Principal{Account: account}, req,
		activities.Origin{IP: "127.0.0.1", CorrelationID: newCorrelation()})
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		fmt.Fprintln(os.Stderr, "goplay:", s.Who, "→", err)
		return outcome{HandedOn: true}, nil
	case errors.As(err, &refusal):
		status := 400
		if refusal.Forbidden {
			status = 403
		}
		return outcome{OK: false, Status: status, Message: refusal.Message}, nil
	case err != nil:
		return outcome{}, err
	}
	message := answer.Message
	if answer.Notice != "" {
		message += " " + answer.Notice
	}
	return outcome{OK: true, Status: 200, Message: message + " " + answer.PlanLinkLabel}, nil
}

// playClusterMeeting makes a cluster meeting through Go's save
// (docs/migration/49): the drawer's posted form, the schools ticked by name.
func playClusterMeeting(ctx context.Context, svc *activities.Service, accounts *identity.Store, pool *pgxpool.Pool,
	s step, form url.Values) (outcome, error) {
	req, taken := activities.ClusterMeetingRequestFromForm(form)
	if !taken {
		return outcome{HandedOn: true}, nil
	}
	var userID string
	if err := pool.QueryRow(ctx, `SELECT id FROM "user" WHERE email = $1`, s.Who).Scan(&userID); err != nil {
		return outcome{}, fmt.Errorf("finding %s: %w", s.Who, err)
	}
	account, err := accounts.LoadAccount(ctx, userID)
	if err != nil {
		return outcome{}, err
	}
	account.InActingAppointment = account.Acting.WorkingIn(account.ActiveRole)
	answer, err := svc.ScheduleClusterMeeting(ctx, auth.Principal{Account: account}, req,
		activities.Origin{IP: "127.0.0.1", CorrelationID: newCorrelation()})
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		fmt.Fprintln(os.Stderr, "goplay:", s.Who, "→", err)
		return outcome{HandedOn: true}, nil
	case errors.As(err, &refusal):
		status := 400
		if refusal.Forbidden {
			status = 403
		}
		return outcome{OK: false, Status: status, Message: refusal.Message}, nil
	case err != nil:
		return outcome{}, err
	}
	message := answer.Message
	if answer.Notice != "" {
		message += " " + answer.Notice
	}
	return outcome{OK: true, Status: 200, Message: message + " " + answer.PlanLinkLabel}, nil
}

// moveDrawer is My Plan's Reschedule drawer (docs/migration/29); its
// activity is named as the runner names it, `{activity:<purpose text>}`.
var moveDrawer = regexp.MustCompile(`^/my-plan/([^/]+)/reschedule-drawer$`)

func newCorrelation() string {
	correlation := make([]byte, 16)
	_, _ = rand.Read(correlation)
	return hex.EncodeToString(correlation)
}

// playMove makes a Reschedule step through Go's move: the activity found on
// copy B as the runner finds it, the drawer's posted date and reason.
func playMove(ctx context.Context, svc *activities.Service, accounts *identity.Store, pool *pgxpool.Pool,
	s step, target string, form url.Values) (outcome, error) {
	activityID := target
	if m := placeholder.FindStringSubmatch(target); m != nil {
		activityID = "missing"
		err := pool.QueryRow(ctx, `SELECT id FROM activity WHERE activity_purpose_text = $1
ORDER BY created_at DESC LIMIT 1`, m[1]).Scan(&activityID)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return outcome{}, err
		}
	}
	var userID string
	if err := pool.QueryRow(ctx, `SELECT id FROM "user" WHERE email = $1`, s.Who).Scan(&userID); err != nil {
		return outcome{}, fmt.Errorf("finding %s: %w", s.Who, err)
	}
	account, err := accounts.LoadAccount(ctx, userID)
	if err != nil {
		return outcome{}, err
	}
	account.InActingAppointment = account.Acting.WorkingIn(account.ActiveRole)
	answer, err := svc.Reschedule(ctx, auth.Principal{Account: account},
		activities.MoveRequest{ActivityID: activityID, Date: form.Get("scheduled_date"), Reason: form.Get("reason")},
		activities.Origin{IP: "127.0.0.1", CorrelationID: newCorrelation()})
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		fmt.Fprintln(os.Stderr, "goplay:", s.Who, "→", err)
		return outcome{HandedOn: true}, nil
	case errors.As(err, &refusal):
		return outcome{OK: false, Status: 400, Message: strings.TrimSpace(refusal.Message)}, nil
	case err != nil:
		return outcome{}, err
	}
	return outcome{OK: true, Status: 200, Message: answer.Message}, nil
}

// cancelDrawer is My Plan's Cancel drawer (docs/migration/30).
var cancelDrawer = regexp.MustCompile(`^/my-plan/([^/]+)/cancel-drawer$`)

// playCancel makes a Cancel step through Go's cancel: the activity found on
// copy B as the runner finds it, the drawer's posted reason.
func playCancel(ctx context.Context, svc *activities.Service, accounts *identity.Store, pool *pgxpool.Pool,
	s step, target string, form url.Values) (outcome, error) {
	activityID, err := findActivity(ctx, pool, target)
	if err != nil {
		return outcome{}, err
	}
	var userID string
	if err := pool.QueryRow(ctx, `SELECT id FROM "user" WHERE email = $1`, s.Who).Scan(&userID); err != nil {
		return outcome{}, fmt.Errorf("finding %s: %w", s.Who, err)
	}
	account, err := accounts.LoadAccount(ctx, userID)
	if err != nil {
		return outcome{}, err
	}
	account.InActingAppointment = account.Acting.WorkingIn(account.ActiveRole)
	answer, err := svc.Cancel(ctx, auth.Principal{Account: account},
		activities.CancelRequest{ActivityID: activityID, Reason: form.Get("reason")},
		activities.Origin{IP: "127.0.0.1", CorrelationID: newCorrelation()})
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		fmt.Fprintln(os.Stderr, "goplay:", s.Who, "→", err)
		return outcome{HandedOn: true}, nil
	case errors.As(err, &refusal):
		return outcome{OK: false, Status: 400, Message: strings.TrimSpace(refusal.Message)}, nil
	case err != nil:
		return outcome{}, err
	}
	return outcome{OK: true, Status: 200, Message: answer.Message}, nil
}

// editDrawer is My Plan's Edit drawer (docs/migration/31).
var editDrawer = regexp.MustCompile(`^/my-plan/([^/]+)/edit-drawer$`)

// playEdit makes an Edit step through Go's edit: the activity found on copy
// B as the runner finds it, the drawer's posted form.
func playEdit(ctx context.Context, svc *activities.Service, accounts *identity.Store, pool *pgxpool.Pool,
	s step, target string, form url.Values) (outcome, error) {
	activityID, err := findActivity(ctx, pool, target)
	if err != nil {
		return outcome{}, err
	}
	req, taken := activities.EditRequestFromForm(activityID, form)
	if !taken {
		return outcome{HandedOn: true}, nil
	}
	var userID string
	if err := pool.QueryRow(ctx, `SELECT id FROM "user" WHERE email = $1`, s.Who).Scan(&userID); err != nil {
		return outcome{}, fmt.Errorf("finding %s: %w", s.Who, err)
	}
	account, err := accounts.LoadAccount(ctx, userID)
	if err != nil {
		return outcome{}, err
	}
	account.InActingAppointment = account.Acting.WorkingIn(account.ActiveRole)
	answer, err := svc.Edit(ctx, auth.Principal{Account: account}, req,
		activities.Origin{IP: "127.0.0.1", CorrelationID: newCorrelation()})
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		fmt.Fprintln(os.Stderr, "goplay:", s.Who, "→", err)
		return outcome{HandedOn: true}, nil
	case errors.As(err, &refusal):
		return outcome{OK: false, Status: 400, Message: strings.TrimSpace(refusal.Message)}, nil
	case err != nil:
		return outcome{}, err
	}
	return outcome{OK: true, Status: 200, Message: answer.Message}, nil
}

// findActivity is the runner's resolve(): a `{activity:<purpose text>}`
// placeholder names the latest activity with that purpose text on the copy.
func findActivity(ctx context.Context, pool *pgxpool.Pool, target string) (string, error) {
	m := placeholder.FindStringSubmatch(target)
	if m == nil {
		return target, nil
	}
	activityID := "missing"
	err := pool.QueryRow(ctx, `SELECT id FROM activity WHERE activity_purpose_text = $1
ORDER BY created_at DESC LIMIT 1`, m[1]).Scan(&activityID)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", err
	}
	return activityID, nil
}

var placeholder = regexp.MustCompile(`^\{activity:([^}]*)\}$`)

// handOn makes one step through the existing application on copy B, as the
// gateway forwards a request it does not take.
func handOn(rawStep json.RawMessage, dsn, runner, repo string) (outcome, error) {
	dir, err := os.MkdirTemp("", "goplay-")
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
	o := played.Outcomes[0]
	o.Posted = nil
	return o, nil
}

// groupDrawer is the bar for ticked rows' group drawers (docs/migration/33).
var groupDrawer = regexp.MustCompile(`^/activity-selection/(reschedule|cancel)\?ids=`)

// playGroup makes a group step through Go's group: the activities copy A's
// drawer posted, found on copy B by their purpose text as the runner finds
// a step's activity (a seed activity keeps its id on both copies), with the
// posted date and reason.
func playGroup(ctx context.Context, svc *activities.Service, accounts *identity.Store, pool *pgxpool.Pool,
	s step, kind string, form url.Values, texts []string) (outcome, error) {
	ids := []string{}
	for i, id := range form["activity_ids"] {
		if i < len(texts) && strings.HasPrefix(texts[i], "[shadow") {
			found, err := findActivity(ctx, pool, "{activity:"+texts[i]+"}")
			if err != nil {
				return outcome{}, err
			}
			id = found
		}
		ids = append(ids, id)
	}
	var userID string
	if err := pool.QueryRow(ctx, `SELECT id FROM "user" WHERE email = $1`, s.Who).Scan(&userID); err != nil {
		return outcome{}, fmt.Errorf("finding %s: %w", s.Who, err)
	}
	account, err := accounts.LoadAccount(ctx, userID)
	if err != nil {
		return outcome{}, err
	}
	account.InActingAppointment = account.Acting.WorkingIn(account.ActiveRole)
	req := activities.GroupRequest{ActivityIDs: ids, Date: form.Get("scheduled_date"), Reason: form.Get("reason")}
	origin := activities.Origin{IP: "127.0.0.1", CorrelationID: newCorrelation()}
	var answer activities.GroupAnswer
	verb := "moved"
	if kind == "cancel" {
		answer, err = svc.GroupCancel(ctx, auth.Principal{Account: account}, req, origin)
		verb = "cancelled"
	} else {
		answer, err = svc.GroupReschedule(ctx, auth.Principal{Account: account}, req, origin)
	}
	var refusal *activities.Refusal
	switch {
	case errors.Is(err, activities.ErrHandOn):
		fmt.Fprintln(os.Stderr, "goplay:", s.Who, "→", err)
		return outcome{HandedOn: true}, nil
	case errors.As(err, &refusal):
		return outcome{OK: false, Status: 400, Message: strings.TrimSpace(refusal.Message)}, nil
	case err != nil:
		return outcome{}, err
	}
	if len(answer.Done) > 0 {
		return outcome{OK: true, Status: 204, Message: answer.Message}, nil
	}
	// The drawer's outcome partial as the runner reads it (its tags turned
	// to spaces): "Nothing was moved. {title} · {where} : {why} …".
	said := "Nothing was " + verb + "."
	for _, pick := range answer.Refused {
		said += " " + pick.Title + " · " + pick.Where + " : " + pick.Refusal
	}
	return outcome{OK: true, Status: 200, Message: strings.Join(strings.Fields(said), " ")}, nil
}

// compare holds Go's outcomes to the existing application's, step by step:
// the same answer, and Go's words inside the words the web painted.
func compare(a, b outcomes) error {
	differing := 0
	for i := range a.Outcomes {
		x, y := a.Outcomes[i], b.Outcomes[i]
		x.Message, y.Message = withFlash(x), withFlash(y)
		x.Message, y.Message = html.UnescapeString(x.Message), html.UnescapeString(y.Message)
		how := "Go"
		if y.HandedOn {
			how = "handed on"
		}
		same := x.OK == y.OK && (y.HandedOn || strings.Contains(x.Message, y.Message))
		if y.HandedOn {
			same = x.OK == y.OK && tail(x.Message) == tail(y.Message)
		}
		mark := "same"
		if !same {
			mark = "DIFFERS"
			differing++
		}
		fmt.Printf("step %d (%s): %s — a: ok=%v %q; b: ok=%v %q\n", i+1, how, mark, x.OK, tail(x.Message), y.OK, tail(y.Message))
	}
	fmt.Printf("%d of %d steps answered differently\n", differing, len(a.Outcomes))
	if differing > 0 {
		return errors.New("the outcomes differ")
	}
	return nil
}

// withFlash is what a step said: its flash message, then its answer.
func withFlash(o outcome) string {
	if len(o.Flash) == 0 {
		return o.Message
	}
	return strings.TrimSpace(strings.Join(o.Flash, " ") + " " + o.Message)
}

func tail(s string) string {
	if i := strings.LastIndex(s, "> "); i >= 0 {
		s = s[i+2:]
	}
	if len(s) > 110 {
		s = s[:110]
	}
	return s
}
