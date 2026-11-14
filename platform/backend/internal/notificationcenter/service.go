package notificationcenter

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	commonv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/common/v1"
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ErrNotAvailable is the page refused to the reader's role (the existing
// page answers it with Access Denied).
var ErrNotAvailable = pagegate.ErrNotAvailable

// ErrBodiesWithheld is the page asked of a database role that may not read
// a notice's words (notification.body): the page shows them and searches
// them, so it is not answered at all rather than answered without them.
// The gateway's read-only role is refused them on purpose
// (TestGatewayRoleCanNeitherWriteNorReadSecrets); how the page may read
// them is the coordinator's decision (docs/migration/43, "What is left").
var ErrBodiesWithheld = errors.New("notificationcenter: this database role may not read a notice's words")

// defaultActionLabel is the button's words when a notification names none
// (`n.action_label|default:"Open Record"`).
const defaultActionLabel = "Open Record"

// Service builds the notification centre.
type Service struct {
	db              schooldirectory.Querier
	emailConfigured bool
}

// NewService wires the service to the database it reads. emailConfigured
// is whether the server sends email (EmailConfigured).
func NewService(db schooldirectory.Querier, emailConfigured bool) *Service {
	return &Service{db: db, emailConfigured: emailConfigured}
}

// roleOf is the role the page is opened in: the acting role while the
// person works in an acting appointment, their active role otherwise.
func roleOf(p auth.Principal) string {
	if p.InActingAppointment && p.Acting != nil && p.Acting.ActingRole != "" {
		return p.Acting.ActingRole
	}
	return p.ActiveRole
}

// Build answers the page for p.
func (s *Service) Build(ctx context.Context, p auth.Principal, request *screensv1.GetNotificationCenterRequest) (*screensv1.GetNotificationCenterResponse, error) {
	if role, ok := rules.Roles[roleOf(p)]; !ok || !role.Page {
		return nil, ErrNotAvailable
	}
	var readsBodies bool
	if err := s.db.QueryRow(ctx, `SELECT has_column_privilege('notification', 'body', 'SELECT')`).Scan(&readsBodies); err != nil {
		return nil, fmt.Errorf("notificationcenter: asking whether a notice's words may be read: %w", err)
	}
	if !readsBodies {
		return nil, ErrBodiesWithheld
	}
	asked := askedOf(request)
	kpis, err := s.kpis(ctx, p.UserID)
	if err != nil {
		return nil, err
	}
	where, args := listFilter(p.UserID, asked)
	var total int
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM notification WHERE `+where, args...).Scan(&total); err != nil {
		return nil, fmt.Errorf("notificationcenter: counting the notifications: %w", err)
	}
	pageCount := max(1, (total+rules.PageSize-1)/rules.PageSize)
	current := min(pageAsked(asked.page), pageCount)
	items := []*screensv1.NotificationItem{}
	if total > 0 {
		if items, err = s.notifications(ctx, where, args, current); err != nil {
			return nil, err
		}
	}
	categories, err := s.categories(ctx, p.UserID)
	if err != nil {
		return nil, err
	}
	delivery, err := s.delivery(ctx, p, categories, request.GetSettingsSaved())
	if err != nil {
		return nil, err
	}
	options := make([]*screensv1.NotificationOption, 0, len(categories))
	for _, c := range categories {
		options = append(options, &screensv1.NotificationOption{Value: c, Label: djangoTitle(c)})
	}
	return &screensv1.GetNotificationCenterResponse{
		Kpis: kpis,
		Filters: &screensv1.NotificationFilters{
			Status: asked.status, Priority: asked.priority, Category: asked.category,
			ActionRequired: asked.actionRequired, Q: asked.q, Categories: options,
		},
		Notifications: items,
		Page: &commonv1.PageInfo{
			Page: int32(current), PageSize: int32(rules.PageSize), //nolint:gosec // bounded by pageAsked and the count
			Total: int64(total), TotalPages: int32(pageCount), //nolint:gosec // a count of one person's notifications
		},
		Delivery:    delivery,
		PageNumbers: pagerNumbers(current, pageCount),
	}, nil
}

// asked is the page's query as the view reads it.
type asked struct {
	status, priority, category, q, page string
	actionRequired                      bool
}

func askedOf(r *screensv1.GetNotificationCenterRequest) asked {
	// request.GET.get("status", "all"): absent is every live one; an empty
	// status is asked as itself and matches nothing.
	status := rules.DefaultStatus
	if r.Status != nil {
		status = r.GetStatus()
	}
	return asked{
		status: status, priority: r.GetPriority(), category: r.GetCategory(), q: r.GetQ(),
		page: r.GetPage(), actionRequired: r.GetActionRequired(),
	}
}

// liveClause, with the archived status as argument n, is `exclude(Q(status="archived") | Q(resolved_at__isnull=False))`.
func liveClause(n int) string {
	return fmt.Sprintf(`NOT (status = $%d OR resolved_at IS NOT NULL)`, n)
}

// kpis are the page's two figures over the live notifications.
func (s *Service) kpis(ctx context.Context, userID string) (*screensv1.NotificationKpis, error) {
	var action, critical int32
	err := s.db.QueryRow(ctx, `
SELECT COUNT(*) FILTER (WHERE action_required AND status = $3),
       COUNT(*) FILTER (WHERE priority = $4 AND status = $3)
  FROM notification
 WHERE recipient_id = $1 AND `+liveClause(2),
		userID, rules.Statuses.Archived, rules.Statuses.Unread, rules.CriticalPriority,
	).Scan(&action, &critical)
	if err != nil {
		return nil, fmt.Errorf("notificationcenter: counting the figures: %w", err)
	}
	return &screensv1.NotificationKpis{ActionRequired: action, Critical: critical}, nil
}

// listFilter is the list's WHERE clause and its arguments, in the view's
// order: the status (all = the live ones), priority, category, action
// required, and the search over title or body.
func listFilter(userID string, a asked) (string, []any) {
	args := []any{userID}
	arg := func(v any) string {
		args = append(args, v)
		return "$" + strconv.Itoa(len(args))
	}
	clauses := []string{"recipient_id = $1"}
	if a.status == rules.DefaultStatus {
		args = append(args, rules.Statuses.Archived)
		clauses = append(clauses, liveClause(len(args)))
	} else {
		clauses = append(clauses, "status = "+arg(a.status))
	}
	if a.priority != "" {
		clauses = append(clauses, "priority = "+arg(a.priority))
	}
	if a.category != "" {
		clauses = append(clauses, "category = "+arg(a.category))
	}
	if a.actionRequired {
		clauses = append(clauses, "action_required")
	}
	if a.q != "" {
		pattern := arg(likeContains(a.q))
		clauses = append(clauses, fmt.Sprintf(`(UPPER(title::text) LIKE UPPER(%s) OR UPPER(body::text) LIKE UPPER(%s))`, pattern, pattern))
	}
	return strings.Join(clauses, " AND "), args
}

// notifications is one page of the list, newest first (the id keeps page
// boundaries stable within one second), each with who asked.
func (s *Service) notifications(ctx context.Context, where string, args []any, page int) ([]*screensv1.NotificationItem, error) {
	limit := len(args) + 1
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT id, title, body, category, priority, status, action_required, created_at,
       context_type, context_id, target_route, action_label,
       (SELECT U0.name FROM "user" U0 WHERE U0.id = notification.sender_id ORDER BY U0.created_at DESC LIMIT 1)
  FROM notification
 WHERE %s
 ORDER BY created_at DESC, id DESC
 LIMIT $%d OFFSET $%d`, where, limit, limit+1), append(args, rules.PageSize, (page-1)*rules.PageSize)...)
	if err != nil {
		return nil, fmt.Errorf("notificationcenter: reading the notifications: %w", err)
	}
	defer rows.Close()
	out := []*screensv1.NotificationItem{}
	for rows.Next() {
		var (
			n                                                                  row
			body, contextType, contextID, targetRoute, actionLabel, senderName *string
		)
		if err := rows.Scan(&n.id, &n.title, &body, &n.category, &n.priority, &n.status, &n.actionRequired,
			&n.createdAt, &contextType, &contextID, &targetRoute, &actionLabel, &senderName); err != nil {
			return nil, fmt.Errorf("notificationcenter: reading a notification: %w", err)
		}
		n.body, n.contextType, n.targetRoute = text(body), text(contextType), text(targetRoute)
		n.actionLabel, n.senderName = text(actionLabel), text(senderName)
		n.contextID = djangoText(contextID)
		out = append(out, item(n))
	}
	return out, rows.Err()
}

// row is one notification as the page reads it.
type row struct {
	id, title, body, category, priority, status      string
	contextType, contextID, targetRoute, actionLabel string
	senderName                                       string
	actionRequired                                   bool
	createdAt                                        time.Time
}

func text(v *string) string {
	if v == nil {
		return ""
	}
	return *v
}

// djangoText is `{{ value }}`: a missing value is written "None".
func djangoText(v *string) string {
	if v == nil {
		return "None"
	}
	return *v
}

// item is a notification as the page draws it.
func item(n row) *screensv1.NotificationItem {
	unread := n.status == rules.Statuses.Unread
	priorityLabel := djangoTitle(n.priority)
	if n.priority == rules.CriticalPriority {
		priorityLabel = "Critical"
	}
	out := &screensv1.NotificationItem{
		Id: n.id, Title: n.title, Body: n.body, Category: n.category, CategoryLabel: djangoTitle(n.category),
		Priority: n.priority, PriorityLabel: priorityLabel, Status: n.status, Unread: unread,
		ActionRequired: n.actionRequired && unread, CreatedLabel: createdLabel(n.createdAt),
		SenderName: n.senderName, CanMarkRead: unread, CanArchive: n.status != rules.Statuses.Archived,
	}
	if n.contextType != "" {
		out.ContextType, out.ContextId = n.contextType, n.contextID
	}
	if n.targetRoute != "" {
		out.TargetRoute, out.ActionLabel = n.targetRoute, n.actionLabel
		if out.ActionLabel == "" {
			out.ActionLabel = defaultActionLabel
		}
	}
	return out
}

// categories are the Category select's options: the reader's categories,
// newest first, empty ones dropped, each once. The existing view's
// `values_list("category").distinct()` runs under the model's ordering, so
// it is distinct on (category, created_at) and lists a category again for
// every moment it was raised; Go lists each once (owner, 2026-11-13: "Can you
// fix those from the go side"; intended.json go-fix-notification-categories).
func (s *Service) categories(ctx context.Context, userID string) ([]string, error) {
	// Asked as an unnamed statement, so it is planned for this reader as the
	// existing application's (client-bound) statement is: a cached generic
	// plan groups by another key and lists the categories raised at the same
	// moment in another order.
	rows, err := s.db.Query(ctx, `
SELECT DISTINCT notification.category AS category, notification.created_at
  FROM notification
 WHERE notification.recipient_id = $1
 ORDER BY notification.created_at DESC`, pgx.QueryExecModeExec, userID)
	if err != nil {
		return nil, fmt.Errorf("notificationcenter: reading the categories: %w", err)
	}
	defer rows.Close()
	out := []string{}
	for rows.Next() {
		var category string
		var at time.Time
		if err := rows.Scan(&category, &at); err != nil {
			return nil, fmt.Errorf("notificationcenter: reading a category: %w", err)
		}
		out = append(out, category)
	}
	return firstSeen(out), rows.Err()
}

// firstSeen keeps each non-empty category once, where it first appears.
func firstSeen(categories []string) []string {
	out := []string{}
	seen := map[string]bool{}
	for _, c := range categories {
		if c != "" && !seen[c] {
			seen[c] = true
			out = append(out, c)
		}
	}
	return out
}

// delivery is the "How you are told" settings: the person's preference (both
// channels on when they have none), the categories they may mute (those of
// their notifications and those already muted, sorted).
func (s *Service) delivery(ctx context.Context, p auth.Principal, categories []string, saved bool) (*screensv1.NotificationDelivery, error) {
	emailOn, pushOn := true, true
	muted := []string{}
	var raw []byte
	err := s.db.QueryRow(ctx, `
SELECT email_enabled, push_enabled, email_muted_categories
  FROM notification_preference WHERE user_id = $1 ORDER BY id LIMIT 1`, p.UserID).Scan(&emailOn, &pushOn, &raw)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		emailOn, pushOn = true, true
	case err != nil:
		return nil, fmt.Errorf("notificationcenter: reading the delivery settings: %w", err)
	default:
		if muted, err = mutedOf(raw); err != nil {
			return nil, err
		}
	}
	set := map[string]bool{}
	for _, c := range categories {
		set[c] = true
	}
	mutedSet := map[string]bool{}
	for _, c := range muted {
		set[c], mutedSet[c] = true, true
	}
	all := make([]string, 0, len(set))
	for c := range set {
		all = append(all, c)
	}
	sort.Strings(all)
	choices := make([]*screensv1.NotificationCategoryChoice, 0, len(all))
	for _, c := range all {
		choices = append(choices, &screensv1.NotificationCategoryChoice{Value: c, Label: djangoTitle(c), Muted: mutedSet[c]})
	}
	return &screensv1.NotificationDelivery{
		EmailEnabled: emailOn, PushEnabled: pushOn, Address: p.Email,
		EmailConfigured: s.emailConfigured, Categories: choices, Saved: saved,
	}, nil
}

// mutedOf is `list(preference.email_muted_categories or [])`. The settings
// save writes only strings; anything else is refused rather than guessed.
func mutedOf(raw []byte) ([]string, error) {
	if len(raw) == 0 || string(raw) == "null" {
		return []string{}, nil
	}
	var values []string
	if err := json.Unmarshal(raw, &values); err != nil {
		return nil, fmt.Errorf("notificationcenter: the muted categories are not a list of words: %w", err)
	}
	if values == nil {
		values = []string{}
	}
	return values, nil
}

// pagerNumbers are the pager's numbers, none for a single page.
func pagerNumbers(current, pageCount int) []int32 {
	if pageCount <= 1 {
		return nil
	}
	return pageWindow(current, pageCount)
}
