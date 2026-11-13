package presence

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// Stamper writes beats through gateway_presence.beat.
type Stamper struct {
	db *pgxpool.Pool
}

// NewStamper returns a Stamper over the gateway's pool (whose role is a
// member of edify_presence_rw).
func NewStamper(db *pgxpool.Pool) *Stamper { return &Stamper{db: db} }

// previous is the person's last beat as the request read it.
type previous struct {
	seen   *time.Time
	path   string
	action string
	login  string
}

// Beat is the function call one request makes: what is written and what the
// beat before it is credited to. It is decided before anything is written.
type Beat struct {
	UserID string
	// HasFootprint: the page and action are written (else left as they are).
	HasFootprint bool
	Page, Action string
	LoginID      string
	// Guard is the beat the request read; nil when there is none to credit
	// (none read, a bearer's person, or its page empty or untracked).
	Guard            *time.Time
	PreviousLogin    string
	Section, Working string
}

// Plan is touch_presence and _next_beat up to the write.
func plan(userID string, r Request, prev previous) Beat {
	b := Beat{UserID: userID}
	if page, action, ok := Footprint(r); ok {
		b.HasFootprint, b.Page, b.Action = true, page, action
	}
	if r.LoginID != "" {
		b.LoginID = cut(r.LoginID, rules.Lengths.LoginID)
	}
	// A bearer's person is an AuthPrincipal: no beat is read, so the
	// UPDATE is not guarded and nothing is credited.
	if r.Bearer {
		return b
	}
	path := prev.path
	if Untracked(path) {
		path = ""
	}
	if prev.seen == nil || path == "" {
		return b
	}
	b.Guard, b.PreviousLogin = prev.seen, prev.login
	b.Section, b.Working = Describe(path, prev.action)
	b.Section, b.Working = cut(b.Section, rules.Lengths.Section), cut(b.Working, rules.Lengths.WorkingOn)
	return b
}

// Stamp writes the beat the middleware would have written for r, after the
// request Go answered: nothing when the middleware would not touch. It
// returns the seconds credited to the beat before. A failure is the
// caller's to log; it never undoes the answer (touch_presence swallows
// database errors).
func (s *Stamper) Stamp(ctx context.Context, userID string, r Request) (int, error) {
	if s == nil || s.db == nil || userID == "" || !Touches(r) {
		return 0, nil
	}
	var prev previous
	if !r.Bearer {
		var path, action, login *string
		err := s.db.QueryRow(ctx,
			`SELECT last_seen_at, last_seen_path, last_seen_action, last_seen_login_id FROM "user" WHERE id = $1`,
			userID).Scan(&prev.seen, &path, &action, &login)
		if errors.Is(err, pgx.ErrNoRows) {
			return 0, nil
		}
		if err != nil {
			return 0, fmt.Errorf("presence: reading the last beat: %w", err)
		}
		prev.path, prev.action, prev.login = deref(path), deref(action), deref(login)
	}
	return s.write(ctx, plan(userID, r, prev))
}

func (s *Stamper) write(ctx context.Context, b Beat) (int, error) {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return 0, fmt.Errorf("presence: opening the beat: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var credited int
	err = tx.QueryRow(ctx,
		`SELECT gateway_presence.beat($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)`,
		b.UserID, text(b.HasFootprint, b.Page), text(b.HasFootprint, b.Action), text(b.LoginID != "", b.LoginID),
		b.Guard, text(b.Guard != nil && b.PreviousLogin != "", b.PreviousLogin),
		text(b.Guard != nil, b.Section), text(b.Guard != nil, b.Working), text(b.Guard != nil, cuid.New()),
		rules.IdleSeconds, rules.FinalBeatSeconds, rules.OnlineWindowSeconds, rules.TimeZone,
	).Scan(&credited)
	if err != nil {
		return 0, fmt.Errorf("presence: writing the beat: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return 0, fmt.Errorf("presence: committing the beat: %w", err)
	}
	return credited, nil
}

// text is a nullable text parameter.
func text(present bool, value string) *string {
	if !present {
		return nil
	}
	return &value
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}
