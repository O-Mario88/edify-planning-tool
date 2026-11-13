package main

// Coverage: how much of the existing application Go answers itself (owner,
// 2026-11-13: "I want django completely replaced by Go"). Every page Go
// serves is asked of a Go-only gateway as each account; each answer is Go's
// own (a page, or a refusal the page itself makes) or passed on to the
// existing application ("not available here yet"). The migration is complete
// only when nothing is passed on and every route of the existing application
// is in Go.

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"connectrpc.com/connect"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1/identityv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
)

// passedOnText is the gateway's answer for a page it hands to the existing
// application.
const passedOnText = "not available here yet"

// tally is one page's answers.
type tally struct{ built, refused, passedOn, failed int }

// kindOf says what one Go answer was.
func kindOf(err error) string {
	switch {
	case err == nil:
		return "built"
	case strings.Contains(err.Error(), passedOnText):
		return "passed on"
	case connect.CodeOf(err) == connect.CodeNotFound || connect.CodeOf(err) == connect.CodePermissionDenied:
		return "refused"
	default:
		return "failed"
	}
}

func (t *tally) add(err error) {
	switch kindOf(err) {
	case "built":
		t.built++
	case "passed on":
		t.passedOn++
	case "refused":
		t.refused++
	default:
		t.failed++
	}
}

// goPaths are the pages Go serves that can be asked without an id.
func goPaths() []string {
	out := []string{}
	for path := range pageQuestions {
		if !strings.Contains(path, "{id}") {
			out = append(out, path)
		}
	}
	sort.Strings(out)
	return out
}

// inventoryRoute is one routed surface of the existing application
// (docs/platform-page-inventory.json).
type inventoryRoute struct {
	Route string `json:"route"`
	Kind  string `json:"surface_kind"`
}

// ownScreens are full pages Go answers through a screen of its own rather
// than the page contract: the school profile (SchoolProfileService).
var ownScreens = []string{"/schools/<str:school_id>"}

// notInGo are the inventory's full pages that no Go page answers yet, each
// once (a route with and without its trailing slash is one page).
func notInGo(inventory []inventoryRoute, served []string) (pages []string, total int) {
	have := map[string]bool{}
	for _, p := range append(append([]string{}, served...), ownScreens...) {
		have[strings.TrimSuffix(p, "/")] = true
	}
	seen := map[string]bool{}
	for _, r := range inventory {
		key := strings.TrimSuffix(r.Route, "/")
		if r.Kind != "page" || seen[key] {
			continue
		}
		seen[key] = true
		total++
		if !have[key] {
			pages = append(pages, key)
		}
	}
	sort.Strings(pages)
	return pages, total
}

func runCoverage(ctx context.Context, signIn identityv1connect.SignInServiceClient, pages screensv1connect.PageScreenServiceClient,
	existing, password string, users []string, pause time.Duration, inventoryPath, out string) int {
	paths := goPaths()
	tallies := map[string]*tally{}
	for _, p := range paths {
		tallies[p] = &tally{}
	}
	for i, email := range users {
		if i > 0 {
			time.Sleep(pause)
		}
		email = strings.TrimSpace(email)
		answer, err := signIn.SignIn(ctx, connect.NewRequest(&identityv1.SignInRequest{Email: email, Password: password}))
		if err != nil || answer.Msg.GetSession() == nil {
			fmt.Printf("%-34s cannot sign in: %v\n", email, err)
			continue
		}
		token := answer.Msg.GetSession().GetAccessToken()
		for _, p := range paths {
			r := &pageRun{existing: existing, path: p, pages: pages}
			for _, query := range r.queries(ctx, token) {
				_, goErr := r.goPage(ctx, token, query)
				tallies[p].add(goErr)
			}
		}
		fmt.Printf("%-34s asked\n", email)
	}

	var report strings.Builder
	total := tally{}
	fmt.Fprintf(&report, "| Page | Built by Go | Refused by Go | Passed on to Django | Failed |\n|---|---|---|---|---|\n")
	for _, p := range paths {
		t := tallies[p]
		total.built += t.built
		total.refused += t.refused
		total.passedOn += t.passedOn
		total.failed += t.failed
		fmt.Fprintf(&report, "| `%s` | %d | %d | %d | %d |\n", p, t.built, t.refused, t.passedOn, t.failed)
	}
	fmt.Fprintf(&report, "| **all** | %d | %d | **%d** | %d |\n", total.built, total.refused, total.passedOn, total.failed)

	missing := []string{}
	if inventoryPath != "" {
		raw, err := os.ReadFile(inventoryPath)
		if err != nil {
			fmt.Fprintln(os.Stderr, "coverage:", err)
			return 2
		}
		var inv struct {
			Pages []inventoryRoute `json:"pages"`
		}
		if err := json.Unmarshal(raw, &inv); err != nil {
			fmt.Fprintln(os.Stderr, "coverage:", err)
			return 2
		}
		var pageTotal int
		missing, pageTotal = notInGo(inv.Pages, paths)
		fmt.Fprintf(&report, "\nFull pages of the existing application: %d; answered by a Go page: %d; not in Go yet: %d.\n",
			pageTotal, pageTotal-len(missing), len(missing))
	}
	fmt.Print("\n" + report.String())
	if out != "" {
		body := "# Coverage: how much Go answers itself\n\nGenerated by `cmd/parity -screen coverage` against a Go-only gateway.\n" +
			"The migration is complete when \"Passed on to Django\" is 0 everywhere and no page is left below.\n\n" +
			report.String()
		if len(missing) > 0 {
			body += "\n## Full pages not in Go yet\n\n"
			for _, m := range missing {
				body += "- `" + m + "`\n"
			}
		}
		if err := os.WriteFile(out, []byte(body), 0o644); err != nil {
			fmt.Fprintln(os.Stderr, "coverage:", err)
			return 2
		}
	}
	if total.passedOn > 0 || len(missing) > 0 || total.failed > 0 {
		return 1
	}
	return 0
}
