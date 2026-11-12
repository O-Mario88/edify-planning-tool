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
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"connectrpc.com/connect"
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
	ctx := context.Background()
	client := &http.Client{Timeout: 2 * time.Minute}
	signIn := identityv1connect.NewSignInServiceClient(client, gateway)
	drawers := screensv1connect.NewPlanningDrawerServiceClient(client, gateway)
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
		a, err := playStep(ctx, drawers, token, s)
		if err != nil {
			return fmt.Errorf("step %d: %w", i+1, err)
		}
		result.Answers = append(result.Answers, a)
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
	return sent
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
