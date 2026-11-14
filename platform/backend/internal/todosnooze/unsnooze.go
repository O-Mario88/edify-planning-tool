package todosnooze

import (
	"context"
	"fmt"
	"net/url"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// UnsnoozeRequest is the Undo form (partials/today/queue_item_done.html): the
// To-Do's id as the snooze's answer named it. Section is the This Week Me
// tab's field as the view reads it (_include_team: the query string's value,
// else the form's), which only shapes the redraw.
type UnsnoozeRequest struct {
	TodoID  string
	Section string
	// Page is the page the Undo was posted from (HX-Current-URL), which the
	// presence stamp names; empty when unknown.
	Page string
}

// Redraw is what undoing a snooze answers (today_unsnooze): the Today panel,
// drawn again by the existing application at Path (today_panel, which renders
// the same partial from the same context), put in Retarget's place with
// Reswap. Removed is how many rows the undo took away (0 or 1). The redraw
// is read in the background (presence.BackgroundHeader): the person's post
// is stamped by Go, and the read the gateway makes is not theirs.
type Redraw struct {
	Path     string
	Retarget string
	Reswap   string
	Removed  int
}

// UnsnoozePlan is the undo decided before anything is written.
type UnsnoozePlan struct {
	UserID, TodoID string
	Redraw         Redraw
}

// DecideUnsnooze plays today_unsnooze up to the write. It refuses nothing:
// the undo removes whatever matches (often nothing) and draws the panel
// again. The existing undo matches the whole posted id while its snooze
// stores the id cut to the column, so a long id could be snoozed but never
// undone; Go matches the id the snooze stored (owner, 2026-11-13: "Can you
// fix those from the go side"; intended.json go-fix-snooze-id-length).
func DecideUnsnooze(p auth.Principal, r UnsnoozeRequest) (UnsnoozePlan, error) {
	if !Takes(p) {
		return UnsnoozePlan{}, ErrHandOn
	}
	// Postgres refuses a NUL in a text parameter; the existing undo then
	// fails with a server error, which Go does not imitate.
	if strings.ContainsRune(r.TodoID, 0) {
		return UnsnoozePlan{}, ErrHandOn
	}
	path := rules.Unsnooze.Redraw
	if r.Section != "" {
		path += "?" + url.Values{rules.Unsnooze.SectionField: {r.Section}}.Encode()
	}
	return UnsnoozePlan{
		UserID: p.UserID,
		TodoID: cut(r.TodoID, rules.Lengths.TodoID),
		Redraw: Redraw{Path: path, Retarget: rules.Unsnooze.Retarget, Reswap: rules.Unsnooze.Reswap},
	}, nil
}

// Unsnooze makes the save: TodoSnooze.objects.filter(user_id, todo_id).delete()
// through gateway_todos.unsnooze, the one narrow function the gateway may ask
// (deploy/db/todo_unsnooze_roles.sql), in one read-write transaction. The
// answer names the panel the existing application draws again.
func (s *Service) Unsnooze(ctx context.Context, p auth.Principal, r UnsnoozeRequest) (Redraw, error) {
	redraw, err := s.unsnooze(ctx, p, r)
	s.stamp(ctx, p, rules.Posts.Unsnooze, r.Page, err)
	return redraw, err
}

func (s *Service) unsnooze(ctx context.Context, p auth.Principal, r UnsnoozeRequest) (Redraw, error) {
	plan, err := DecideUnsnooze(p, r)
	if err != nil {
		return Redraw{}, err
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return Redraw{}, fmt.Errorf("todosnooze: opening the undo: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var removed int
	if err := tx.QueryRow(ctx, `SELECT gateway_todos.unsnooze($1, $2)`, plan.UserID, plan.TodoID).Scan(&removed); err != nil {
		return Redraw{}, fmt.Errorf("todosnooze: undoing the snooze: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return Redraw{}, fmt.Errorf("todosnooze: committing the undo: %w", err)
	}
	redraw := plan.Redraw
	redraw.Removed = removed
	return redraw, nil
}
