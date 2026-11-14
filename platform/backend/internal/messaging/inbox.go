package messaging

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	messagingv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/messaging/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The page's words that live in its templates.
const (
	eyebrow           = "Communication"
	title             = "Messages"
	description       = "Contextual, workflow-linked communication across roles"
	searchPlaceholder = "Search conversations…"
	emptyTitle        = "No conversations here"
	emptyMessage      = "Threads matching this filter will appear as soon as there is one."
	sortNewest        = "newest"
	sortOldest        = "oldest"
	tabAll            = "all"
	// The pager writes every page up to this one, then a gap.
	pagerLead = 3
)

// countedTabs are the tabs that carry a count (index.html).
var countedTabs = []string{"all", "unread", "assigned"}

var sortOptions = [][2]string{{sortNewest, "Sort: Newest"}, {sortOldest, "Sort: Oldest"}}

// Query is the page's query, as typed.
type Query struct {
	Tab, Q, Sort, Page, Thread string
}

// Inbox is messages_list_view for p.
func Inbox(ctx context.Context, db schooldirectory.Querier, p auth.Principal, query Query, now time.Time) (*messagingv1.ListThreadsResponse, error) {
	if err := mayOpen(p); err != nil {
		return nil, err
	}
	tab := query.Tab
	if tab == "" {
		tab = tabAll
	}
	sortBy := query.Sort
	if sortBy == "" {
		sortBy = sortNewest
	}
	search := strings.TrimSpace(query.Q)
	page := 1
	if n, ok := clusterpage.PyInt(query.Page); ok && n > 1 {
		page = n
	}

	box := &inbox{db: db, userID: p.UserID, gate: newGate(db, p, now)}
	threads, err := box.threads(ctx, tab, search)
	if err != nil {
		return nil, err
	}
	if sortBy == sortOldest {
		for i, j := 0, len(threads)-1; i < j; i, j = i+1, j-1 {
			threads[i], threads[j] = threads[j], threads[i]
		}
	}
	total := len(threads)
	pages := max(1, (total+rules.PageSize-1)/rules.PageSize)
	page = min(page, pages)
	start := (page - 1) * rules.PageSize
	shown := threads[start:min(start+rules.PageSize, total)]

	counts := map[string]int{}
	for _, key := range countedTabs {
		rows, err := box.threads(ctx, key, "")
		if err != nil {
			return nil, err
		}
		counts[key] = len(rows)
	}

	selected := ""
	if query.Thread != "" {
		ok, err := mayOpenThread(ctx, db, box.gate, p, query.Thread)
		if err != nil {
			return nil, err
		}
		if ok {
			selected = query.Thread
		}
	} else if len(shown) > 0 {
		selected = shown[0].id
	}

	answer := &messagingv1.ListThreadsResponse{
		Eyebrow: eyebrow, Title: title, Description: description,
		ActiveTab: tab, Sort: sortBy, Search: search, SearchPlaceholder: searchPlaceholder,
		SelectedThreadId: selected, EmptyTitle: emptyTitle, EmptyMessage: emptyMessage,
		MessageRules: append([]string{}, rules.MessageRules...),
	}
	for _, t := range rules.Tabs {
		item := &messagingv1.InboxTab{Key: t[0], Label: t[1], Active: t[0] == tab}
		if n, counted := counts[t[0]]; counted {
			item.HasCount, item.Count = true, int32(n)
		}
		answer.Tabs = append(answer.Tabs, item)
	}
	for _, o := range sortOptions {
		answer.Sorts = append(answer.Sorts, &messagingv1.SortOption{Value: o[0], Label: o[1], Selected: o[0] == sortBy})
	}
	for _, r := range shown {
		answer.Threads = append(answer.Threads, threadMessage(r, selected))
	}
	answer.Pager = pager(page, pages, total, start, tab, sortBy, search)
	return answer, nil
}

// UnreadCount is unread_thread_count for p.
func UnreadCount(ctx context.Context, db schooldirectory.Querier, p auth.Principal) (int, error) {
	if err := mayOpen(p); err != nil {
		return 0, err
	}
	return unreadCount(ctx, db, p.UserID)
}

// mayOpen is the page's gate: require_page_permission("messages"). A person
// working in an acting capacity is handed on, as every Go page hands them.
func mayOpen(p auth.Principal) error {
	if p.InActingAppointment {
		return ErrHandOn
	}
	if !rules.Roles[p.ActiveRole].Page {
		return pagegate.ErrNotAvailable
	}
	return nil
}

// mayOpenThread is _require_thread_access: the thread exists, the reader
// takes part in it (or is the Admin), and its record is still theirs.
func mayOpenThread(ctx context.Context, db schooldirectory.Querier, g *gate, p auth.Principal, threadID string) (bool, error) {
	var contextType, contextID string
	var member bool
	err := db.QueryRow(ctx, `
SELECT COALESCE(t.context_type, ''), COALESCE(t.context_id, ''),
  EXISTS (SELECT 1 FROM messaging_messageparticipant p WHERE p.thread_id = t.id AND p.user_id = $2)
FROM messaging_messagethread t WHERE t.id = $1`, threadID, p.UserID).Scan(&contextType, &contextID, &member)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("messaging: reading the conversation: %w", err)
	}
	if slug(p.ActiveRole) == slugAdmin {
		return true, nil
	}
	if !member {
		return false, nil
	}
	if contextType == "" || contextID == "" {
		return openWithoutRecord(), nil
	}
	return g.allows(ctx, contextType, contextID)
}

func threadMessage(r threadRow, selected string) *messagingv1.ThreadRow {
	row := &messagingv1.ThreadRow{
		Id: r.id, SenderName: r.senderName, Initials: initials(r.senderName), IsSystem: r.isSystem,
		LastAt: r.lastAt.UTC().Format(time.RFC3339Nano), LastAtLabel: r.lastAt.In(pageZone).Format("Jan 2, 15:04"),
		Subject: r.subject, Snippet: r.snippet, Unread: r.unread, Selected: r.id == selected,
		ContextType: r.contextType, ContextBadge: r.contextBadge, Starred: r.starred,
		Href: "/messages?thread=" + url.QueryEscape(r.id),
	}
	if r.contextBadge != "" {
		row.ContextTone = contextTone(r.contextType)
	}
	switch r.priority {
	case "high", "urgent":
		row.PriorityBadge, row.PriorityTone = "High", "alert"
	case "low":
		row.PriorityBadge, row.PriorityTone = "Low", "plain"
	}
	return row
}

// contextTone is thread_list.html's badge colours.
func contextTone(contextType string) string {
	switch contextType {
	case "fund_request", "finance", "accountant_disbursement":
		return "finance"
	case "leave":
		return "leave"
	case "verification", "ssa_verification", "ia_return":
		return "verification"
	case "evidence", "evidence_upload":
		return "evidence"
	}
	return "primary"
}

// initials is the avatar_initials filter.
func initials(name string) string {
	parts := strings.Fields(name)
	switch {
	case len(parts) >= 2:
		return strings.ToUpper(string([]rune(parts[0])[:1]) + string([]rune(parts[len(parts)-1])[:1]))
	case len(parts) == 1:
		return strings.ToUpper(firstRunes(parts[0], 2))
	}
	return "ED"
}

// pager is thread_list.html's pager: drawn past one page, every page up to
// the third, the last and the current one's neighbours, one gap at the
// fourth when there are more than five.
func pager(page, pages, total, start int, tab, sortBy, search string) *messagingv1.InboxPager {
	showingStart, showingEnd := 0, min(start+rules.PageSize, total)
	if total > 0 {
		showingStart = start + 1
	}
	out := &messagingv1.InboxPager{
		Shown: pages > 1, Page: int32(page), Pages: int32(pages), Total: int32(total),
		ShowingStart: int32(showingStart), ShowingEnd: int32(showingEnd),
		Summary: fmt.Sprintf("Showing %d–%d of %d", showingStart, showingEnd, total),
	}
	if !out.Shown {
		return out
	}
	// One gap for every run of hidden pages. The existing pager drew one only
	// before the fourth page, so page 5 of 9 hid the run before the last
	// (owner, 2026-11-13: "Can you fix those from the go side").
	gap := false
	for p := 1; p <= pages; p++ {
		switch {
		case p == page:
			out.Links = append(out.Links, &messagingv1.PagerLink{Label: strconv.Itoa(p), Page: int32(p), Current: true})
			gap = false
		case p <= pagerLead || p == pages || p == page+1 || p == page-1:
			out.Links = append(out.Links, &messagingv1.PagerLink{Label: strconv.Itoa(p), Page: int32(p), Href: pageHref(tab, sortBy, search, p)})
			gap = false
		case !gap:
			out.Links = append(out.Links, &messagingv1.PagerLink{Label: "…", Gap: true})
			gap = true
		}
	}
	if page < pages {
		out.NextHref = pageHref(tab, sortBy, search, page+1)
	}
	return out
}

func pageHref(tab, sortBy, search string, page int) string {
	values := url.Values{"tab": {tab}, "sort": {sortBy}, "page": {strconv.Itoa(page)}}
	if search != "" {
		values.Set("q", search)
	}
	return "/messages?" + values.Encode()
}

// openWithoutRecord is whether a participant may open a conversation that is
// about no record. The list never shows one, yet the existing page opened it
// by ?thread=; Go refuses it as the list does (owner, 2026-11-13).
func openWithoutRecord() bool { return false }
