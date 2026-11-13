package messaging

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// snippetLength is how much of the latest message a row shows.
const snippetLength = 90

// membership is a reader's MessageParticipant row and its thread.
type membership struct {
	recipientType string
	lastReadAt    *time.Time
	starred       bool

	threadID, subject, contextType, contextID, contextLabel, priority, createdBy string
	lastReplyAt                                                                  *time.Time
	updatedAt                                                                    time.Time
	isSystem                                                                     bool
}

// lastMessage is a thread's latest message (the prefetch ordered by
// created_at, read last).
type lastMessage struct {
	senderID, body string
}

// threadRow is one of threads_for_user's rows.
type threadRow struct {
	id, subject, snippet, senderID, senderName string
	contextType, contextBadge, contextLabel    string
	priority                                   string
	unread, starred, isSystem                  bool
	lastAt                                     time.Time
}

// inbox is what threads_for_user reads once per reader: their live and
// archived threads with each thread's latest message, and the partner
// accounts and members the Partner tab asks about.
type inbox struct {
	db       schooldirectory.Querier
	userID   string
	gate     *gate
	live     []membership
	archived []membership
	last     map[string]lastMessage
	members  map[string][]string
	partners map[string]bool
}

func (b *inbox) memberships(ctx context.Context, archived bool) ([]membership, error) {
	if archived && b.archived != nil {
		return b.archived, nil
	}
	if !archived && b.live != nil {
		return b.live, nil
	}
	filter := "p.archived_at IS NULL"
	if archived {
		filter = "p.archived_at IS NOT NULL"
	}
	// The statement Django issues (select_related, no ordering): the rows
	// come back in the order the list keeps for equal times.
	rows, err := b.db.Query(ctx, `
SELECT p.recipient_type, p.last_read_at, p.starred,
  t.id, t.subject, COALESCE(t.context_type, ''), COALESCE(t.context_id, ''), COALESCE(t.context_label, ''),
  t.priority, COALESCE(t.created_by, ''), t.last_reply_at, t.updated_at, t.is_system_generated
FROM messaging_messageparticipant p
INNER JOIN messaging_messagethread t ON (p.thread_id = t.id)
WHERE (p.user_id = $1 AND `+filter+`)`, b.userID)
	if err != nil {
		return nil, fmt.Errorf("messaging: reading the reader's threads: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (membership, error) {
		var m membership
		err := row.Scan(&m.recipientType, &m.lastReadAt, &m.starred, &m.threadID, &m.subject, &m.contextType,
			&m.contextID, &m.contextLabel, &m.priority, &m.createdBy, &m.lastReplyAt, &m.updatedAt, &m.isSystem)
		return m, err
	})
	if err != nil {
		return nil, fmt.Errorf("messaging: reading the reader's threads: %w", err)
	}
	if list == nil {
		list = []membership{}
	}
	if err := b.readLast(ctx, list); err != nil {
		return nil, err
	}
	if archived {
		b.archived = list
	} else {
		b.live = list
	}
	return list, nil
}

// readLast reads the latest message of each thread not yet read.
func (b *inbox) readLast(ctx context.Context, list []membership) error {
	if b.last == nil {
		b.last = map[string]lastMessage{}
	}
	var ids []string
	for _, m := range list {
		if _, done := b.last[m.threadID]; !done {
			ids = append(ids, m.threadID)
		}
	}
	if len(ids) == 0 {
		return nil
	}
	rows, err := b.db.Query(ctx, `SELECT thread_id, sender_id, body FROM message WHERE thread_id = ANY($1) ORDER BY created_at ASC`, ids)
	if err != nil {
		return fmt.Errorf("messaging: reading the threads' messages: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var thread string
		var m lastMessage
		if err := rows.Scan(&thread, &m.senderID, &m.body); err != nil {
			return fmt.Errorf("messaging: reading the threads' messages: %w", err)
		}
		b.last[thread] = m
	}
	return rows.Err()
}

// unread is _is_unread: the thread moved since the reader last read it, and
// not by their own message.
func unread(m membership, last lastMessage, hasLast bool, userID string) bool {
	if m.lastReplyAt == nil {
		return false
	}
	if m.lastReadAt == nil || m.lastReadAt.Before(*m.lastReplyAt) {
		return hasLast && last.senderID != userID
	}
	return false
}

// threads is threads_for_user(user, tab, search).
func (b *inbox) threads(ctx context.Context, tab, search string) ([]threadRow, error) {
	list, err := b.memberships(ctx, tab == "archived")
	if err != nil {
		return nil, err
	}
	needle := strings.ToLower(search)
	rows := []threadRow{}
	for _, m := range list {
		last, hasLast := b.last[m.threadID]
		isUnread := unread(m, last, hasLast, b.userID)
		if !hasLast {
			continue
		}
		keep, err := b.onTab(ctx, tab, m, isUnread)
		if err != nil {
			return nil, err
		}
		if !keep {
			continue
		}
		if search != "" && !strings.Contains(strings.ToLower(m.subject), needle) &&
			!strings.Contains(strings.ToLower(m.contextLabel), needle) {
			continue
		}
		allowed, err := b.gate.allows(ctx, m.contextType, m.contextID)
		if err != nil {
			return nil, err
		}
		if !allowed {
			continue
		}
		lastAt := m.updatedAt
		if m.lastReplyAt != nil {
			lastAt = *m.lastReplyAt
		}
		badge, labelled := rules.ContextLabels[m.contextType]
		if !labelled {
			badge = m.contextType
		}
		rows = append(rows, threadRow{
			id: m.threadID, subject: m.subject, snippet: firstRunes(last.body, snippetLength), senderID: last.senderID,
			contextType: m.contextType, contextBadge: badge, contextLabel: m.contextLabel, priority: m.priority,
			unread: isUnread, starred: m.starred, isSystem: m.isSystem, lastAt: lastAt,
		})
	}
	if err := b.name(ctx, rows); err != nil {
		return nil, err
	}
	// sorted(reverse=True) keeps equal times in their order.
	sort.SliceStable(rows, func(i, j int) bool { return rows[i].lastAt.After(rows[j].lastAt) })
	return rows, nil
}

// onTab is threads_for_user's tab filters.
func (b *inbox) onTab(ctx context.Context, tab string, m membership, isUnread bool) (bool, error) {
	switch tab {
	case "unread":
		return isUnread, nil
	case "assigned":
		return m.recipientType == rules.RecipientTo, nil
	case "sent":
		return m.createdBy == b.userID, nil
	case "finance":
		return in(rules.FinanceContexts, m.contextType), nil
	case "ia_review":
		return in(rules.IAContexts, m.contextType), nil
	case "partner":
		return b.hasPartner(ctx, m.threadID)
	}
	return true, nil
}

// hasPartner is whether a partner's account takes part in the thread.
func (b *inbox) hasPartner(ctx context.Context, threadID string) (bool, error) {
	if b.partners == nil {
		rows, err := b.db.Query(ctx, `SELECT id FROM "user" WHERE deleted_at IS NULL AND (roles @> $1::varchar[] OR roles @> $2::varchar[])`,
			[]string{rules.PartnerRoles[0]}, []string{rules.PartnerRoles[1]})
		if err != nil {
			return false, fmt.Errorf("messaging: reading the partner accounts: %w", err)
		}
		ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
		if err != nil {
			return false, fmt.Errorf("messaging: reading the partner accounts: %w", err)
		}
		b.partners = map[string]bool{}
		for _, id := range ids {
			b.partners[id] = true
		}
	}
	if b.members == nil {
		if err := b.readMembers(ctx); err != nil {
			return false, err
		}
	}
	for _, member := range b.members[threadID] {
		if b.partners[member] {
			return true, nil
		}
	}
	return false, nil
}

func (b *inbox) readMembers(ctx context.Context) error {
	var ids []string
	for _, m := range append(append([]membership{}, b.live...), b.archived...) {
		ids = append(ids, m.threadID)
	}
	rows, err := b.db.Query(ctx, `SELECT thread_id, user_id FROM messaging_messageparticipant WHERE thread_id = ANY($1)`, ids)
	if err != nil {
		return fmt.Errorf("messaging: reading the threads' members: %w", err)
	}
	defer rows.Close()
	b.members = map[string][]string{}
	for rows.Next() {
		var thread, user string
		if err := rows.Scan(&thread, &user); err != nil {
			return fmt.Errorf("messaging: reading the threads' members: %w", err)
		}
		b.members[thread] = append(b.members[thread], user)
	}
	return rows.Err()
}

// name gives each row its latest sender's name: a live account's, or
// "System".
func (b *inbox) name(ctx context.Context, rows []threadRow) error {
	if len(rows) == 0 {
		return nil
	}
	ids := make([]string, 0, len(rows))
	for _, r := range rows {
		ids = append(ids, r.senderID)
	}
	result, err := b.db.Query(ctx, `SELECT id, name FROM "user" WHERE deleted_at IS NULL AND id = ANY($1)`, ids)
	if err != nil {
		return fmt.Errorf("messaging: reading the senders: %w", err)
	}
	defer result.Close()
	names := map[string]string{}
	for result.Next() {
		var id, name string
		if err := result.Scan(&id, &name); err != nil {
			return fmt.Errorf("messaging: reading the senders: %w", err)
		}
		names[id] = name
	}
	if err := result.Err(); err != nil {
		return fmt.Errorf("messaging: reading the senders: %w", err)
	}
	for i := range rows {
		name, ok := names[rows[i].senderID]
		if !ok {
			name = "System"
		}
		rows[i].senderName = name
	}
	return nil
}

// firstRunes is Python's text[:n].
func firstRunes(text string, n int) string {
	runes := []rune(text)
	if len(runes) <= n {
		return text
	}
	return string(runes[:n])
}

// unreadCount is services.unread_thread_count: live threads that moved since
// the reader last read them, whose latest message is not their own.
func unreadCount(ctx context.Context, db schooldirectory.Querier, userID string) (int, error) {
	var n int
	err := db.QueryRow(ctx, `
SELECT COUNT(*) FROM messaging_messageparticipant p
INNER JOIN messaging_messagethread t ON (p.thread_id = t.id)
WHERE p.user_id = $1 AND p.archived_at IS NULL AND t.last_reply_at IS NOT NULL
  AND (p.last_read_at IS NULL OR p.last_read_at < t.last_reply_at)
  AND (SELECT m.sender_id FROM message m WHERE m.thread_id = p.thread_id ORDER BY m.created_at DESC LIMIT 1) IS DISTINCT FROM $1`,
		userID).Scan(&n)
	if err != nil {
		return 0, fmt.Errorf("messaging: counting the unread threads: %w", err)
	}
	return n, nil
}
