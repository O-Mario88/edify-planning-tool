// Command appplay plays a shadow scenario's saves as the app makes them
// (docs/migration/27 §27.10): through a gateway, signed in as each step's
// person, opening the school's Schedule drawer (GetPlanningDrawer) and
// saving it with the values the app sends (SavePlanningDrawer, the fields
// planningLogic.scheduleValues posts for a visit). Run it once against a
// gateway with the Go save switched off (copy A: every save is the existing
// application's) and once against one with EDIFY_GO_SAVES=schedule_visit
// (copy B), then compare the two answers step by step:
//
//	go run ./cmd/shadow/appplay -gateway http://127.0.0.1:8096 -scenario s.json -out a.json
//	go run ./cmd/shadow/appplay -gateway http://127.0.0.1:8097 -scenario s.json -out b.json
//	go run ./cmd/shadow/appplay -compare a.json,b.json
//
// The password is read from EDIFY_SHADOW_PASSWORD (the local seed's). It
// writes nothing itself: the gateways' saves are the run.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"
	"google.golang.org/protobuf/proto"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1/identityv1connect"
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// step is a scenario step (cmd/shadow/scenarios): who, the drawer opened
// (its school_id), and the person's choices.
type step struct {
	Who  string            `json:"who"`
	Open string            `json:"open"`
	Set  map[string]string `json:"set"`
	// ConfirmAdvance is a step that is not a drawer (django_runner.py
	// confirm_advances): played by the existing application on the run's
	// own copy, alike on both.
	ConfirmAdvance string `json:"confirm_advance"`
}

// answer is one step's SavePlanningDrawerResponse, or the error the app got.
type answer struct {
	Saved    bool              `json:"saved"`
	Message  string            `json:"message,omitempty"`
	Redirect string            `json:"redirect,omitempty"`
	Error    string            `json:"error,omitempty"`
	Code     string            `json:"code,omitempty"` // a connect error's code
	Values   map[string]string `json:"values,omitempty"`
}

type run struct {
	Gateway string   `json:"gateway"`
	From    string   `json:"from"`
	To      string   `json:"to"`
	Answers []answer `json:"answers"`
}

func main() {
	gateway := flag.String("gateway", "", "the gateway the app calls")
	scenario := flag.String("scenario", "", "the scenario")
	out := flag.String("out", "", "where the answers are written")
	compare := flag.String("compare", "", "a.json,b.json: compare two runs")
	flag.StringVar(&copyDSN, "db", "", "the copy the gateway serves, read to find a step's activity by its purpose text")
	flag.StringVar(&runnerPython, "python", "", "the Python that runs manage.py shell (for a step that is not a drawer)")
	flag.StringVar(&runnerRepo, "repo", ".", "the worktree that Python runs in")
	flag.DurationVar(&settle, "settle", 0, "a pause after each step: the existing application prices a save in a thread after its answer, "+
		"and the app's next request does not wait for it as the web's does (its cookie)")
	flag.Parse()
	var err error
	if *compare != "" {
		err = compareRuns(*compare)
	} else {
		err = play(*gateway, *scenario, *out, os.Getenv("EDIFY_SHADOW_PASSWORD"))
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "appplay:", err)
		os.Exit(1)
	}
}

func readJSON(path string, into any) error {
	raw, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	return json.Unmarshal(raw, into)
}

func play(gateway, scenarioPath, out, password string) error {
	if gateway == "" || out == "" || password == "" {
		return errors.New("-gateway, -out and EDIFY_SHADOW_PASSWORD are required")
	}
	var steps []step
	if err := readJSON(scenarioPath, &steps); err != nil {
		return err
	}
	var raw []json.RawMessage
	if err := readJSON(scenarioPath, &raw); err != nil {
		return err
	}
	ctx := context.Background()
	client := &http.Client{Timeout: 2 * time.Minute}
	signIn := identityv1connect.NewSignInServiceClient(client, gateway)
	drawers := screensv1connect.NewPlanningDrawerServiceClient(client, gateway)
	pageDrawers := screensv1connect.NewPageDrawerServiceClient(client, gateway)
	tokens := map[string]string{}
	result := run{Gateway: gateway, From: time.Now().UTC().Format(time.RFC3339Nano)}
	for i, s := range steps {
		token, ok := tokens[s.Who]
		if !ok {
			signedIn, err := signIn.SignIn(ctx, connect.NewRequest(&identityv1.SignInRequest{Email: s.Who, Password: password}))
			if err != nil || signedIn.Msg.GetSession() == nil {
				return fmt.Errorf("step %d: %s cannot sign in: %v", i+1, s.Who, err)
			}
			token = signedIn.Msg.GetSession().GetAccessToken()
			tokens[s.Who] = token
		}
		var a answer
		var err error
		if s.ConfirmAdvance != "" {
			a, err = playOutside(raw[i])
		} else if m := groupDrawer.FindStringSubmatch(s.Open); m != nil {
			a, err = playGroup(ctx, pageDrawers, token, m[1], m[2], s)
		} else if m := moveDrawer.FindStringSubmatch(s.Open); m != nil {
			a, err = playMove(ctx, pageDrawers, token, m[1], m[2], s)
		} else if m := editDrawer.FindStringSubmatch(s.Open); m != nil {
			a, err = playEdit(ctx, pageDrawers, token, m[1], m[2], s)
		} else {
			a, err = playStep(ctx, drawers, token, s)
		}
		if err != nil {
			return fmt.Errorf("step %d: %w", i+1, err)
		}
		result.Answers = append(result.Answers, a)
		time.Sleep(settle)
	}
	result.To = time.Now().UTC().Format(time.RFC3339Nano)
	encoded, _ := json.MarshalIndent(result, "", "  ")
	return os.WriteFile(out, encoded, 0o600)
}

func withToken[T any](message *T, token string) *connect.Request[T] {
	request := connect.NewRequest(message)
	request.Header().Set("Authorization", "Bearer "+token)
	return request
}

func playStep(ctx context.Context, drawers screensv1connect.PlanningDrawerServiceClient, token string, s step) (answer, error) {
	opened, err := url.Parse(s.Open)
	if err != nil {
		return answer{}, err
	}
	schoolID := opened.Query().Get("school_id")
	got, err := drawers.GetPlanningDrawer(ctx, withToken(&screensv1.GetPlanningDrawerRequest{SchoolId: schoolID, Kind: "schedule"}, token))
	if err != nil {
		return failed(err), nil
	}
	drawer := got.Msg.GetDrawer()
	if drawer == nil {
		return answer{Error: "(no drawer) " + got.Msg.GetRefusal()}, nil
	}
	values := scheduleValues(drawer, s.Set)
	saved, err := drawers.SavePlanningDrawer(ctx, withToken(&screensv1.SavePlanningDrawerRequest{
		SchoolId: schoolID, Kind: "schedule", Values: values,
	}, token))
	if err != nil {
		a := failed(err)
		a.Values = values
		return a, nil
	}
	m := saved.Msg
	return answer{Saved: m.GetSaved(), Message: m.GetMessage(), Redirect: m.GetRedirect(), Error: m.GetError(), Values: values}, nil
}

func failed(err error) answer {
	return answer{Code: connect.CodeOf(err).String(), Error: err.Error()}
}

// scheduleValues is planningLogic.scheduleValues for a visit (no training
// picker): the person's purpose, day and goal, the drawer's own activity
// type, recommendation reason and catalogue item, staff delivery. A choice
// the step makes (a catalogue item cleared, a deviation reason) replaces
// the drawer's. The goal's outcome field is not one the app saves.
func scheduleValues(drawer *screensv1.PlanningDrawer, set map[string]string) map[string]string {
	sent := map[string]string{
		"purpose_of_visit":      set["purpose_of_visit"],
		"activity_type":         drawer.GetActivityType(),
		"recommendation_reason": drawer.GetRecommendationReason(),
		"scheduled_date":        set["scheduled_date"],
		"executor_type":         "staff",
		"delivery_type":         "staff",
		"activity_purpose_text": set["activity_purpose_text"],
	}
	if item := drawer.GetDefaultCatalogueItem(); item != "" {
		sent["catalogue_item_id"] = item
	}
	if drawer.GetHasJustification() {
		sent["visit_justification"] = set["visit_justification"]
	}
	for _, name := range []string{"catalogue_item_id", "ssa_deviation_reason"} {
		if value, chosen := set[name]; chosen {
			sent[name] = value
		}
	}
	if purpose := set["purpose_of_visit"]; purpose == "in_school_training" || purpose == "in_school_training_ssa" {
		trainingValues(drawer, set, sent)
	}
	return sent
}

// trainingValues is the training picker's part of scheduleValues
// (docs/migration/32): the course chosen, its facilitator (blank is Staff),
// and the reason withTrainingChosen gives the course.
func trainingValues(drawer *screensv1.PlanningDrawer, set, sent map[string]string) {
	sent["catalogue_item_id"] = set["catalogue_item_id"]
	sent["facilitating_partner_id"] = set["facilitating_partner_id"]
	for _, t := range drawer.GetTrainings() {
		if t.GetId() != set["catalogue_item_id"] {
			continue
		}
		if titles := t.GetPriorityTitles(); len(titles) > 0 {
			sent["recommendation_reason"] = "Priority activity: " + strings.Join(titles, ", ")
		} else {
			sent["recommendation_reason"] = "Governed " + t.GetCategory() + " training."
		}
	}
}

// compareRuns holds run B's answers to run A's: every field the app reads
// must be identical, and so must the values sent.
func compareRuns(pair string) error {
	paths := strings.Split(pair, ",")
	if len(paths) != 2 {
		return errors.New("-compare takes a.json,b.json")
	}
	var a, b run
	if err := readJSON(paths[0], &a); err != nil {
		return err
	}
	if err := readJSON(paths[1], &b); err != nil {
		return err
	}
	if len(a.Answers) != len(b.Answers) {
		return fmt.Errorf("%d answers against %d", len(a.Answers), len(b.Answers))
	}
	differing := 0
	for i := range a.Answers {
		x, y := a.Answers[i], b.Answers[i]
		mark := "same"
		if !sameAnswer(x, y) {
			mark = "DIFFERS"
			differing++
		}
		fmt.Printf("step %d: %s — a: saved=%v %q; b: saved=%v %q\n", i+1, mark, x.Saved, said(x), y.Saved, said(y))
	}
	fmt.Printf("%d of %d steps answered differently\n", differing, len(a.Answers))
	if differing > 0 {
		return errors.New("the answers differ")
	}
	return nil
}

func sameAnswer(x, y answer) bool {
	xv, _ := json.Marshal(x.Values)
	yv, _ := json.Marshal(y.Values)
	return proto.Equal(response(x), response(y)) && x.Code == y.Code && string(xv) == string(yv)
}

func response(a answer) *screensv1.SavePlanningDrawerResponse {
	return &screensv1.SavePlanningDrawerResponse{Saved: a.Saved, Message: a.Message, Redirect: a.Redirect, Error: a.Error}
}

func said(a answer) string {
	if a.Saved {
		return a.Message
	}
	if a.Code != "" {
		return a.Code + ": " + a.Error
	}
	return a.Error
}

// copyDSN is the copy a run's gateway serves (-db).
var copyDSN string

// settle is the pause after each step (-settle).
var settle time.Duration

// runnerPython and runnerRepo run django_runner.py for a step that is not a
// drawer (-python, -repo).
var runnerPython, runnerRepo string

// playOutside plays one step through django_runner.py on the run's own copy
// (-db), as the existing application makes it on both copies alike.
func playOutside(rawStep json.RawMessage) (answer, error) {
	if runnerPython == "" || !strings.HasPrefix(copyDSN, "postgresql://localhost:5432/edify_shadow_") {
		return answer{}, errors.New("a step that is not a drawer needs -python and a shadow -db")
	}
	dir, err := os.MkdirTemp("", "appplay-")
	if err != nil {
		return answer{}, err
	}
	defer os.RemoveAll(dir)
	scenario, result := filepath.Join(dir, "step.json"), filepath.Join(dir, "out.json")
	if err := os.WriteFile(scenario, []byte("["+string(rawStep)+"]"), 0o600); err != nil {
		return answer{}, err
	}
	script, err := os.Open(filepath.Join(runnerRepo, "platform/backend/cmd/shadow/django_runner.py"))
	if err != nil {
		return answer{}, err
	}
	defer script.Close()
	cmd := exec.Command(runnerPython, "manage.py", "shell") // #nosec G204 -- the operator's own Python
	cmd.Dir, cmd.Stdin, cmd.Stdout, cmd.Stderr = runnerRepo, script, io.Discard, os.Stderr
	cmd.Env = append(os.Environ(), "DATABASE_URL="+copyDSN, "SCENARIO="+scenario, "OUT="+result)
	if err := cmd.Run(); err != nil {
		return answer{}, err
	}
	var played struct {
		Outcomes []struct {
			OK      bool   `json:"ok"`
			Message string `json:"message"`
		} `json:"outcomes"`
	}
	if err := readJSON(result, &played); err != nil || len(played.Outcomes) != 1 {
		return answer{}, fmt.Errorf("the runner's outcome: %v", err)
	}
	return answer{Saved: played.Outcomes[0].OK, Message: played.Outcomes[0].Message}, nil
}

// moveDrawer is My Plan's Reschedule drawer (docs/migration/29) or its
// Cancel drawer (30); its
// activity may be named by its purpose text, `{activity:<text>}`, since each
// copy makes its own ids.
var (
	moveDrawer  = regexp.MustCompile(`^/my-plan/([^/]+)/(reschedule|cancel)-drawer$`)
	placeholder = regexp.MustCompile(`^\{activity:([^}]*)\}$`)
)

// playMove plays a Reschedule or Cancel step as the app does: the page
// drawer read, then saved with the fields the person fills (the new date and
// the reason; for a cancel, the reason).
func playMove(ctx context.Context, drawers screensv1connect.PageDrawerServiceClient, token, target, kind string, s step) (answer, error) {
	activityID, err := findActivity(ctx, target)
	if err != nil {
		return answer{}, err
	}
	path := "/my-plan/" + activityID + "/" + kind + "-drawer"
	got, err := drawers.GetDrawer(ctx, withToken(&screensv1.GetDrawerRequest{Path: path}, token))
	if err != nil {
		return failed(err), nil
	}
	if got.Msg.GetDrawer() == nil {
		return answer{Error: "(no drawer) " + got.Msg.GetRefusal()}, nil
	}
	values := map[string]string{"scheduled_date": s.Set["scheduled_date"], "reason": s.Set["reason"]}
	if kind == "cancel" {
		values = map[string]string{"reason": s.Set["reason"]}
	}
	saved, err := drawers.SaveDrawer(ctx, withToken(&screensv1.SaveDrawerRequest{Path: path, Values: values}, token))
	if err != nil {
		a := failed(err)
		a.Values = values
		return a, nil
	}
	m := saved.Msg
	return answer{Saved: m.GetSaved(), Message: m.GetMessage(), Redirect: m.GetRedirect(), Error: m.GetError(), Values: values}, nil
}

// groupDrawer is the bar for ticked rows' group drawers (docs/migration/33).
var groupDrawer = regexp.MustCompile(`^/activity-selection/(reschedule|cancel)\?ids=(.*)$`)

// playGroup plays a group step as the app does (selectionPath, then the
// drawer saved with the fields the person fills): the ticked activities found
// on the run's own copy, the drawer read, then saved with the new date and
// the reason (for a cancel, the reason).
func playGroup(ctx context.Context, drawers screensv1connect.PageDrawerServiceClient, token, kind, ticked string, s step) (answer, error) {
	ids := []string{}
	for _, target := range strings.Split(ticked, ",") {
		id, err := findActivity(ctx, target)
		if err != nil {
			return answer{}, err
		}
		ids = append(ids, id)
	}
	path := "/activity-selection/" + kind + "?ids=" + strings.Join(ids, ",")
	got, err := drawers.GetDrawer(ctx, withToken(&screensv1.GetDrawerRequest{Path: path}, token))
	if err != nil {
		return failed(err), nil
	}
	if got.Msg.GetDrawer() == nil {
		return answer{Error: "(no drawer) " + got.Msg.GetRefusal()}, nil
	}
	values := map[string]string{"scheduled_date": s.Set["scheduled_date"], "reason": s.Set["reason"]}
	if kind == "cancel" {
		values = map[string]string{"reason": s.Set["reason"]}
	}
	saved, err := drawers.SaveDrawer(ctx, withToken(&screensv1.SaveDrawerRequest{Path: path, Values: values}, token))
	if err != nil {
		a := failed(err)
		a.Values = values
		return a, nil
	}
	m := saved.Msg
	return answer{Saved: m.GetSaved(), Message: m.GetMessage(), Redirect: m.GetRedirect(), Error: m.GetError(), Values: values}, nil
}

// findActivity finds a `{activity:<text>}` step's activity on its own copy.
func findActivity(ctx context.Context, target string) (string, error) {
	m := placeholder.FindStringSubmatch(target)
	if m == nil {
		return target, nil
	}
	if !strings.HasPrefix(copyDSN, "postgresql://localhost:5432/edify_shadow_") {
		return "", errors.New("-db must name a local shadow copy")
	}
	conn, err := pgx.Connect(ctx, copyDSN)
	if err != nil {
		return "", err
	}
	defer conn.Close(ctx)
	activityID := "missing"
	err = conn.QueryRow(ctx, `SELECT id FROM activity WHERE activity_purpose_text = $1
ORDER BY created_at DESC LIMIT 1`, m[1]).Scan(&activityID)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", err
	}
	return activityID, nil
}

// editDrawer is My Plan's Edit drawer (docs/migration/31), or its Complete
// drawer (docs/migration/183), which the app fills the same way.
var editDrawer = regexp.MustCompile(`^/my-plan/([^/]+)/(edit|complete)-drawer$`)

// playEdit plays an Edit or Complete step as the app does (drawerLogic.ts):
// every field's value as the drawer gives it, the step's choices over them,
// and then only the fields shown for those values sent.
func playEdit(ctx context.Context, drawers screensv1connect.PageDrawerServiceClient, token, target, kind string, s step) (answer, error) {
	activityID, err := findActivity(ctx, target)
	if err != nil {
		return answer{}, err
	}
	path := "/my-plan/" + activityID + "/" + kind + "-drawer"
	got, err := drawers.GetDrawer(ctx, withToken(&screensv1.GetDrawerRequest{Path: path}, token))
	if err != nil {
		return failed(err), nil
	}
	drawer := got.Msg.GetDrawer()
	if drawer == nil {
		return answer{Error: "(no drawer) " + got.Msg.GetRefusal()}, nil
	}
	values := map[string]string{}
	for _, item := range drawer.GetItems() {
		if field := item.GetField(); field != nil {
			values[field.GetName()] = field.GetValue()
		}
	}
	for name, value := range s.Set {
		values[name] = value
	}
	sent := map[string]string{}
	for _, item := range drawer.GetItems() {
		field := item.GetField()
		if field != nil && shown(item.GetShowWhen(), values) && shown(field.GetShowWhen(), values) {
			sent[field.GetName()] = values[field.GetName()]
		}
	}
	saved, err := drawers.SaveDrawer(ctx, withToken(&screensv1.SaveDrawerRequest{Path: path, Values: sent}, token))
	if err != nil {
		a := failed(err)
		a.Values = sent
		return a, nil
	}
	m := saved.Msg
	return answer{Saved: m.GetSaved(), Message: m.GetMessage(), Redirect: m.GetRedirect(), Error: m.GetError(), Values: sent}, nil
}

// shown is drawerLogic.isShown: no condition, or one the values meet.
func shown(conditions []*screensv1.DrawerCondition, values map[string]string) bool {
	if len(conditions) == 0 {
		return true
	}
	for _, c := range conditions {
		if slices.Contains(c.GetValues(), values[c.GetField()]) {
			return true
		}
	}
	return false
}
