package todosnooze

import (
	"context"
	"crypto/sha1" // #nosec G505 -- row_slug's element id, not a secret
	"encoding/hex"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/presence"
)

// ErrHandOn means Go does not take this snooze: the existing application
// makes it, exactly as before.
var ErrHandOn = errors.New("todosnooze: handed on to the existing application")

// Refusal is a snooze the existing application refuses, in its words (the
// view writes them into the row the request came from; nothing is saved).
// Slug is the row's element id the refusal is written into
// ("#{Slug} [data-today-error]").
type Refusal struct{ Message, Slug string }

func (r *Refusal) Error() string { return r.Message }

// doneTitleLength is what the answer shows of the posted title
// (today_views.today_snooze: request.POST.get("title", "")[:120]).
const doneTitleLength = 120

// Request is the Snooze menu's form (partials/today/queue_row.html): the
// To-Do's id, the choice and the row's title.
type Request struct {
	TodoID string
	Choice string
	Title  string
	// Page is the page the menu was posted from (HX-Current-URL), which the
	// presence stamp names; empty when unknown (the post's own path).
	Page string
}

// Answer is what the view draws in the row's place
// (partials/today/queue_item_done.html): "{Title} — {Message}" and an Undo
// for TodoID.
type Answer struct {
	Title   string
	Message string
	Until   time.Time
	TodoID  string
	// Slug is the row's element id the answer replaces (row_slug).
	Slug string
}

// Service makes the save.
type Service struct {
	db       *pgxpool.Pool
	now      func() time.Time
	kampala  *time.Location
	presence *presence.Stamper
	logger   *slog.Logger
}

// WithPresence stamps the person's presence after every save Go makes, as
// the existing application's middleware stamps the post it answers
// (docs/migration/65). A handed-on save is stamped by the existing
// application.
func (s *Service) WithPresence(stamper *presence.Stamper, logger *slog.Logger) *Service {
	s.presence, s.logger = stamper, logger
	return s
}

// stamp writes the beat for the post Go answered (a refusal included). A
// failure is logged and never changes the answer, as touch_presence
// swallows database errors.
func (s *Service) stamp(ctx context.Context, p auth.Principal, path, page string, outcome error) {
	if s.presence == nil || errors.Is(outcome, ErrHandOn) {
		return
	}
	_, err := s.presence.Stamp(ctx, p.UserID, presence.Request{
		Method: http.MethodPost, Path: path, HTMX: true, CurrentURL: page,
	})
	if err != nil && s.logger != nil {
		s.logger.ErrorContext(ctx, "the presence stamp failed", slog.String("error", err.Error()))
	}
}

// NewService returns the save over the gateway's pool.
func NewService(db *pgxpool.Pool, now func() time.Time) (*Service, error) {
	loc, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		return nil, fmt.Errorf("todosnooze: loading the time zone: %w", err)
	}
	if now == nil {
		now = time.Now
	}
	return &Service{db: db, now: now, kampala: loc}, nil
}

// Takes reports whether Go makes this reader's snooze. Everyone else is the
// existing application's: a role the Today page refuses (its refusal writes
// an audit row and draws the Access Denied page), a partner role (its page
// map is asked per person), anyone working in or holding an acting
// appointment (apps.core.acting.page_withheld), an account that must change
// its password or is not active, and a person without a role.
func Takes(p auth.Principal) bool {
	door, known := rules.Doors[p.ActiveRole]
	switch {
	case p.UserID == "" || p.ActiveRole == "" || !known:
		return false
	case !door.Today || door.PerPerson:
		return false
	case p.InActingAppointment || p.Acting != nil:
		return false
	case p.MustChangePassword || p.Status != "active":
		return false
	}
	return true
}

// Plan is the snooze decided before anything is written.
type Plan struct {
	UserID, TodoID, Title string
	Until                 time.Time
	Answer                Answer
}

// Decide plays today_snooze and today_actions.snooze up to the write: the
// refusal, the day, the stored values and the answer. today is the local
// day (timezone.localdate()).
func Decide(p auth.Principal, r Request, today time.Time) (Plan, error) {
	if !Takes(p) {
		return Plan{}, ErrHandOn
	}
	// Postgres refuses a NUL in a text column; the existing save then fails
	// with a server error, which Go does not imitate.
	if strings.ContainsRune(r.TodoID+r.Choice+r.Title, 0) {
		return Plan{}, ErrHandOn
	}
	days, known := rules.SnoozeDays[r.Choice]
	if r.TodoID == "" || !known {
		return Plan{}, &Refusal{Message: rules.Refusal, Slug: RowSlug(r.TodoID)}
	}
	until := time.Date(today.Year(), today.Month(), today.Day()+days, 0, 0, 0, 0, time.UTC)
	todoID := cut(r.TodoID, rules.Lengths.TodoID)
	return Plan{
		UserID: p.UserID,
		TodoID: todoID,
		Title:  cut(r.Title, rules.Lengths.Title),
		Until:  until,
		Answer: Answer{
			Title:   cut(r.Title, doneTitleLength),
			Message: "snoozed until " + until.Format("Mon 2 Jan"),
			Until:   until,
			// The Undo names the posted id, as the view does (undo_todo).
			TodoID: r.TodoID,
			Slug:   RowSlug(r.TodoID),
		},
	}, nil
}

// Snooze makes the save: TodoSnooze.objects.update_or_create(user_id,
// todo_id, defaults={until, title}) in one read-write transaction. A new
// row gets a fresh id and both stamps; an existing one keeps its id and
// created_at and takes the new until, title and updated_at.
func (s *Service) Snooze(ctx context.Context, p auth.Principal, r Request) (Answer, error) {
	answer, err := s.snooze(ctx, p, r)
	s.stamp(ctx, p, rules.Posts.Snooze, r.Page, err)
	return answer, err
}

func (s *Service) snooze(ctx context.Context, p auth.Principal, r Request) (Answer, error) {
	now := s.now()
	plan, err := Decide(p, r, now.In(s.kampala))
	if err != nil {
		return Answer{}, err
	}
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return Answer{}, fmt.Errorf("todosnooze: opening the save: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := write(ctx, tx, plan, now.UTC()); err != nil {
		return Answer{}, err
	}
	if err := tx.Commit(ctx); err != nil {
		return Answer{}, fmt.Errorf("todosnooze: committing the snooze: %w", err)
	}
	return plan.Answer, nil
}

// write is update_or_create as Django makes it: the person's row for the
// item locked (select_for_update().get()), then updated; or, when there is
// none, created, and should a concurrent save create it first (the unique
// constraint todo_snooze_one_per_item), locked and updated after all.
func write(ctx context.Context, tx pgx.Tx, plan Plan, stamp time.Time) error {
	until := plan.Until.Format(time.DateOnly)
	update := func() (bool, error) {
		var id string
		err := tx.QueryRow(ctx, `
SELECT id FROM command_center_todo_snooze WHERE user_id = $1 AND todo_id = $2 FOR UPDATE`,
			plan.UserID, plan.TodoID).Scan(&id)
		if errors.Is(err, pgx.ErrNoRows) {
			return false, nil
		}
		if err != nil {
			return false, fmt.Errorf("todosnooze: reading the snooze: %w", err)
		}
		if _, err := tx.Exec(ctx, `
UPDATE command_center_todo_snooze SET until = $2, title = $3, updated_at = $4 WHERE id = $1`,
			id, until, plan.Title, stamp); err != nil {
			return false, fmt.Errorf("todosnooze: updating the snooze: %w", err)
		}
		return true, nil
	}
	if done, err := update(); done || err != nil {
		return err
	}
	if _, err := tx.Exec(ctx, "SAVEPOINT todo_snooze_create"); err != nil {
		return fmt.Errorf("todosnooze: %w", err)
	}
	_, err := tx.Exec(ctx, `
INSERT INTO command_center_todo_snooze (id, created_at, updated_at, user_id, todo_id, title, until)
VALUES ($1, $2, $2, $3, $4, $5, $6)`, cuid.New(), stamp, plan.UserID, plan.TodoID, plan.Title, until)
	var pgErr *pgconn.PgError
	if errors.As(err, &pgErr) && pgErr.Code == uniqueViolation {
		if _, err := tx.Exec(ctx, "ROLLBACK TO SAVEPOINT todo_snooze_create"); err != nil {
			return fmt.Errorf("todosnooze: %w", err)
		}
		if done, err := update(); done || err != nil {
			return err
		}
		return fmt.Errorf("todosnooze: the snooze was made and is gone again")
	}
	if err != nil {
		return fmt.Errorf("todosnooze: writing the snooze: %w", err)
	}
	return nil
}

const uniqueViolation = "23505"

// RowSlug is today_actions.row_slug: "today-" and the first 12 hex digits
// of the posted id's SHA-1 (an element id, not a secret).
func RowSlug(todoID string) string {
	sum := sha1.Sum([]byte(todoID)) // #nosec G401 -- an element id, as the existing row_slug
	return "today-" + hex.EncodeToString(sum[:])[:12]
}

// cut is Python's s[:n]: n characters, not bytes.
func cut(s string, n int) string {
	runes := []rune(s)
	if len(runes) <= n {
		return s
	}
	return string(runes[:n])
}
