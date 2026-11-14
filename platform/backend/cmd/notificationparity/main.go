// Command notificationparity compares Go's notification centre with the
// existing web page, as a person sees each, for real accounts on a local
// development database or a shadow copy (docs/migration/43).
//
// The existing page has no JSON answer (the app's feed does not serve it),
// so its side is the page's own HTML, rendered by the existing view and
// template and read by django_reader.py beside this file into what the page
// shows. This command asks Go the same questions and lays its answer out
// the way the template does (the template's own words and choices are
// written here), then compares the two, in order.
//
//	EDIFY_PARITY_PASSWORD=… go run ./cmd/notificationparity -gateway http://localhost:8083 -django pages.json
//	go run ./cmd/notificationparity -db postgresql://localhost:5432/edify_shadow_x -django pages.json
//
// With -gateway each account signs in and asks NotificationCenterService;
// with -db the Go service reads the given database directly as each
// account (for a shadow copy whose rows were made for the comparison).
// Development only: it refuses any address that is not on this machine.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/parity"
	"net/http"
	"net/url"
	"os"
	"reflect"
	"slices"
	"sort"
	"strings"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5/pgxpool"

	identityv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/identity/v1/identityv1connect"
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1/screensv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/notificationcenter"
)

// entry is one page django_reader.py read.
type entry struct {
	Email   string          `json:"email"`
	Refused bool            `json:"refused"`
	Query   [][2]string     `json:"query"`
	Status  int             `json:"status"`
	Page    json.RawMessage `json:"page"`
}

// asker answers one account's questions.
type asker interface {
	ask(ctx context.Context, request *screensv1.GetNotificationCenterRequest) (*screensv1.GetNotificationCenterResponse, error)
}

func main() {
	gateway := flag.String("gateway", "", "the Go gateway (sign in and ask it)")
	database := flag.String("db", "", "or: a local database the Go service reads directly")
	pages := flag.String("django", "", "the existing pages, as django_reader.py read them")
	pause := flag.Duration("pause", 0, "wait between sign-ins, under the gateway's sign-in rate limit")
	emailConfigured := flag.Bool("email-configured", false, "-db: whether the existing server sends email")
	flag.Parse()
	list, err := parity.CheckedIn()
	if err != nil {
		fmt.Fprintln(os.Stderr, "notificationparity:", err)
		os.Exit(2)
	}
	intended = list
	for _, address := range []string{*gateway, *database} {
		if address == "" {
			continue
		}
		if u, err := url.Parse(address); err != nil || (u.Hostname() != "localhost" && u.Hostname() != "127.0.0.1") {
			fmt.Fprintln(os.Stderr, "notificationparity runs against this machine only:", address)
			os.Exit(2)
		}
	}
	raw, err := os.ReadFile(*pages)
	if err != nil || (*gateway == "") == (*database == "") {
		fmt.Fprintln(os.Stderr, "give -django and one of -gateway or -db:", err)
		os.Exit(2)
	}
	var entries []entry
	if err := json.Unmarshal(raw, &entries); err != nil {
		fmt.Fprintln(os.Stderr, "the existing pages are unreadable:", err)
		os.Exit(2)
	}
	ctx := context.Background()
	var open func(email string) (asker, error)
	if *gateway != "" {
		open = gatewayAsker(ctx, *gateway, os.Getenv("EDIFY_PARITY_PASSWORD"))
	} else {
		pool, err := pgxpool.New(ctx, *database)
		if err != nil {
			fmt.Fprintln(os.Stderr, "cannot open the database:", err)
			os.Exit(2)
		}
		defer pool.Close()
		open = databaseAsker(ctx, pool, notificationcenter.NewService(pool, *emailConfigured))
	}
	os.Exit(run(ctx, entries, open, *pause))
}

func run(ctx context.Context, entries []entry, open func(string) (asker, error), pause time.Duration) int {
	compared, differing := 0, 0
	var current asker
	who := ""
	for _, e := range entries {
		if e.Email != who {
			if who != "" {
				time.Sleep(pause)
			}
			who = e.Email
			var err error
			if current, err = open(e.Email); err != nil {
				fmt.Printf("%-34s cannot ask: %v\n", e.Email, err)
				differing++
				current = nil
			}
		}
		if current == nil {
			continue
		}
		compared++
		label := queryLabel(e.Query)
		answer, err := current.ask(ctx, request(e.Query))
		if e.Refused || e.Status != http.StatusOK {
			if connect.CodeOf(err) == connect.CodePermissionDenied {
				fmt.Printf("%-34s %-44s same (refused by both)\n", e.Email, label)
			} else {
				differing++
				fmt.Printf("%-34s %-44s DIFFERS: existing refused (%d), go: %v\n", e.Email, label, e.Status, err)
			}
			continue
		}
		if err != nil {
			differing++
			fmt.Printf("%-34s %-44s DIFFERS: go failed: %v\n", e.Email, label, err)
			continue
		}
		var accepted []parity.Accepted
		diff := compare(parity.Answer{Tool: parity.ToolNotifications, Where: "/notifications", Question: label}, &accepted, view(answer), e.Page)
		if len(accepted) > 0 {
			fmt.Printf("%-34s %-44s INTENDED\n%s\n", e.Email, label, parity.IntendedLines(accepted))
		}
		if diff != "" {
			differing++
			fmt.Printf("%-34s %-44s DIFFERS\n%s\n", e.Email, label, diff)
		} else {
			fmt.Printf("%-34s %-44s same\n", e.Email, label)
		}
	}
	fmt.Printf("\n%d compared, %d differing\n", compared, differing)
	if differing > 0 {
		return 1
	}
	return 0
}

func queryLabel(q [][2]string) string {
	if len(q) == 0 {
		return "(as it opens)"
	}
	parts := make([]string, 0, len(q))
	for _, kv := range q {
		parts = append(parts, kv[0]+"="+kv[1])
	}
	return strings.Join(parts, "&")
}

// request is the question as the web app sends it: what the address holds,
// each key's last value read the way the view reads it.
func request(q [][2]string) *screensv1.GetNotificationCenterRequest {
	last := map[string]string{}
	for _, kv := range q {
		last[kv[0]] = kv[1]
	}
	r := &screensv1.GetNotificationCenterRequest{
		Priority: last["priority"], Category: last["category"], Q: last["q"], Page: last["page"],
		ActionRequired: last["action_required"] == "true", SettingsSaved: last["settings"] == "saved",
	}
	if status, ok := last["status"]; ok {
		r.Status = &status
	}
	return r
}

func gatewayAsker(ctx context.Context, gateway, password string) func(string) (asker, error) {
	signIn := identityv1connect.NewSignInServiceClient(http.DefaultClient, gateway)
	client := screensv1connect.NewNotificationCenterServiceClient(http.DefaultClient, gateway)
	return func(email string) (asker, error) {
		answer, err := signIn.SignIn(ctx, connect.NewRequest(&identityv1.SignInRequest{Email: email, Password: password}))
		if err != nil || answer.Msg.GetSession() == nil {
			return nil, fmt.Errorf("sign-in: %w", err)
		}
		return gatewayClient{client: client, token: answer.Msg.GetSession().GetAccessToken()}, nil
	}
}

type gatewayClient struct {
	client screensv1connect.NotificationCenterServiceClient
	token  string
}

func (g gatewayClient) ask(ctx context.Context, r *screensv1.GetNotificationCenterRequest) (*screensv1.GetNotificationCenterResponse, error) {
	request := connect.NewRequest(r)
	request.Header().Set("Authorization", "Bearer "+g.token)
	answer, err := g.client.GetNotificationCenter(ctx, request)
	if err != nil {
		return nil, err
	}
	return answer.Msg, nil
}

func databaseAsker(ctx context.Context, pool *pgxpool.Pool, service *notificationcenter.Service) func(string) (asker, error) {
	return func(email string) (asker, error) {
		var p auth.Principal
		err := pool.QueryRow(ctx, `SELECT id, email, COALESCE(active_role, '') FROM "user" WHERE email = $1 AND deleted_at IS NULL`, email).
			Scan(&p.UserID, &p.Email, &p.ActiveRole)
		if err != nil {
			return nil, fmt.Errorf("reading the account: %w", err)
		}
		return databaseClient{service: service, principal: p}, nil
	}
}

type databaseClient struct {
	service   *notificationcenter.Service
	principal auth.Principal
}

func (d databaseClient) ask(ctx context.Context, r *screensv1.GetNotificationCenterRequest) (*screensv1.GetNotificationCenterResponse, error) {
	answer, err := d.service.Build(ctx, d.principal, r)
	if err == notificationcenter.ErrNotAvailable {
		return nil, connect.NewError(connect.CodePermissionDenied, err)
	}
	return answer, err
}

// The template's own choices (pages/notifications/index.html).
var (
	statusOptions   = []string{"all", "unread", "read", "archived"}
	priorityOptions = []string{"", "low", "normal", "high", "urgent"}
)

func chosen(value string, options []string) string {
	if slices.Contains(options, value) {
		return value
	}
	return ""
}

func collapse(s string) string { return strings.Join(strings.Fields(s), " ") }

// view lays Go's answer out as the template draws it, in the reader's words.
func view(a *screensv1.GetNotificationCenterResponse) map[string]any {
	f := a.GetFilters()
	categories := []any{}
	values := []string{""}
	for _, c := range f.GetCategories() {
		categories = append(categories, map[string]any{"value": c.GetValue(), "label": c.GetLabel()})
		values = append(values, c.GetValue())
	}
	items := []any{}
	for _, n := range a.GetNotifications() {
		link := ""
		if n.GetContextType() != "" {
			link = n.GetContextType() + " (" + n.GetContextId() + ")"
		}
		items = append(items, map[string]any{
			"id": n.GetId(), "unread": n.GetUnread(), "tone": tone(n.GetPriority()),
			"title": collapse(n.GetTitle()), "categoryLabel": collapse(n.GetCategoryLabel()),
			"priorityLabel": collapse(n.GetPriorityLabel()), "actionRequired": n.GetActionRequired(),
			"body": collapse(n.GetBody()), "createdLabel": n.GetCreatedLabel(), "senderName": collapse(n.GetSenderName()),
			"link": collapse(link), "targetRoute": n.GetTargetRoute(), "actionLabel": collapse(n.GetActionLabel()),
			"canMarkRead": n.GetCanMarkRead(), "canArchive": n.GetCanArchive(),
		})
	}
	var pager any
	if page := a.GetPage(); page.GetTotalPages() > 1 {
		first := int64(page.GetPage()-1)*int64(page.GetPageSize()) + 1
		last := min(first+int64(page.GetPageSize())-1, page.GetTotal())
		numbers := []any{}
		for _, p := range a.GetPageNumbers() {
			if p == 0 {
				numbers = append(numbers, "…")
			} else {
				numbers = append(numbers, fmt.Sprint(p))
			}
		}
		pager = map[string]any{
			"summary": fmt.Sprintf("Showing %d–%d of %d", first, last, page.GetTotal()),
			"pages":   numbers, "current": fmt.Sprint(page.GetPage()),
			"previous": page.GetPage() > 1, "next": page.GetPage() < page.GetTotalPages(),
		}
	}
	d := a.GetDelivery()
	choices := []any{}
	for _, c := range d.GetCategories() {
		choices = append(choices, map[string]any{"value": c.GetValue(), "label": collapse(c.GetLabel()), "muted": c.GetMuted()})
	}
	return map[string]any{
		"kpis": map[string]any{"actionRequired": a.GetKpis().GetActionRequired(), "critical": a.GetKpis().GetCritical()},
		"filters": map[string]any{
			"status": chosen(f.GetStatus(), statusOptions), "priority": chosen(f.GetPriority(), priorityOptions),
			"category": chosen(f.GetCategory(), values), "actionRequired": f.GetActionRequired(), "q": f.GetQ(),
			"categories": categories,
		},
		"notifications": items,
		"empty":         len(items) == 0,
		"pager":         pager,
		"delivery": map[string]any{
			"pushEnabled": d.GetPushEnabled(), "emailEnabled": d.GetEmailEnabled(), "address": d.GetAddress(),
			"emailConfigured": d.GetEmailConfigured(), "categories": choices, "saved": d.GetSaved(),
		},
	}
}

// tone is the icon's colour the template picks by priority.
func tone(priority string) string {
	switch priority {
	case "urgent":
		return "critical"
	case "high":
		return "high"
	case "normal":
		return "normal"
	}
	return "other"
}

// compare is "" when the two pages are the same, key by key, rows in order.
func compare(answer parity.Answer, accepted *[]parity.Accepted, goView map[string]any, existing json.RawMessage) string {
	encoded, _ := json.Marshal(goView)
	var goPage, oldPage map[string]any
	_ = json.Unmarshal(encoded, &goPage)
	if err := json.Unmarshal(existing, &oldPage); err != nil {
		return "  the existing page is unreadable: " + err.Error()
	}
	diffs := []string{}
	for _, key := range []string{"kpis", "empty", "pager", "delivery"} {
		if !reflect.DeepEqual(goPage[key], oldPage[key]) {
			diffs = append(diffs, fmt.Sprintf("  %s\n    go:       %v\n    existing: %v", key, goPage[key], oldPage[key]))
		}
	}
	// The filters, field by field, so a difference the intended list names
	// (internal/parity) is set aside alone.
	goFilters, _ := goPage["filters"].(map[string]any)
	oldFilters, _ := oldPage["filters"].(map[string]any)
	fields := map[string]bool{}
	for k := range goFilters {
		fields[k] = true
	}
	for k := range oldFilters {
		fields[k] = true
	}
	names := make([]string, 0, len(fields))
	for k := range fields {
		names = append(names, k)
	}
	sort.Strings(names)
	for _, k := range names {
		if reflect.DeepEqual(goFilters[k], oldFilters[k]) {
			continue
		}
		goText, _ := json.Marshal(goFilters[k])
		oldText, _ := json.Marshal(oldFilters[k])
		d := parity.Diff{Field: "filters." + k, Go: string(goText), Existing: string(oldText),
			Text: fmt.Sprintf("  filters.%s\n    go:       %s\n    existing: %s", k, goText, oldText)}
		if e, ok := intended.Match(answer, d); ok {
			*accepted = append(*accepted, parity.Accepted{Diff: d, Entry: e.ID})
			continue
		}
		diffs = append(diffs, d.Text)
	}
	goRows, _ := goPage["notifications"].([]any)
	oldRows, _ := oldPage["notifications"].([]any)
	if len(goRows) != len(oldRows) {
		diffs = append(diffs, fmt.Sprintf("  notifications: go %d, existing %d", len(goRows), len(oldRows)))
	}
	for i := range min(len(goRows), len(oldRows)) {
		// A row that is neither unread nor archivable shows no id.
		if old, ok := oldRows[i].(map[string]any); ok && old["id"] == nil {
			if goRow, ok := goRows[i].(map[string]any); ok {
				goRow["id"] = nil
			}
		}
		if !reflect.DeepEqual(goRows[i], oldRows[i]) {
			diffs = append(diffs, fmt.Sprintf("  notification %d\n    go:       %v\n    existing: %v", i+1, goRows[i], oldRows[i]))
			if len(diffs) > 6 {
				break
			}
		}
	}
	return strings.Join(diffs, "\n")
}

// intended is the checked-in list of intended differences (internal/parity).
var intended *parity.List
