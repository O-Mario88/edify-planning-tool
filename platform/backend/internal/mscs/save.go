// Package mscs is a Most Significant Change Story submitted from My Targets
// in Go with Django absent (staff_views.mscs_submit_view): the story, filed
// as submitted.
package mscs

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/mytargets"
)

// ErrHandOn says the existing application keeps this request.
var ErrHandOn = errors.New("mscs: handed on")

// FormKey is the My Targets dialog's form.
const FormKey = "/my-targets/mscs"

const (
	required  = "Title, story date and narrative are required."
	submitted = "MSCS submitted for review — it counts once approved."
	// badDate is a story date the model's field would not take; the view
	// fails on it, so it is handed on.
	badDate = "a story date in another form"
)

// Story is what the dialog posts.
type Story struct {
	Title, Narrative, School string
	Date                     time.Time
}

func readStory(v map[string]string) (Story, string) {
	st := Story{Title: strings.TrimSpace(v["title"]), Narrative: strings.TrimSpace(v["narrative"]), School: strings.TrimSpace(v["school_id"])}
	day := strings.TrimSpace(v["story_date"])
	if st.Title == "" || st.Narrative == "" || day == "" {
		return st, required
	}
	d, err := time.Parse(time.DateOnly, day)
	if err != nil {
		return st, badDate
	}
	st.Date = d
	return st, ""
}

// Service saves stories.
type Service struct {
	db  *pgxpool.Pool
	now func() time.Time
}

// New makes the service.
func New(db *pgxpool.Pool, now func() time.Time) *Service { return &Service{db: db, now: now} }

// Submit is the dialog's POST: the answer's message, or the refusal.
func (s *Service) Submit(ctx context.Context, p auth.Principal, values map[string]string) (string, string, error) {
	if p.InActingAppointment || !mytargets.MayOpen(p.ActiveRole) || p.UserID == "" {
		return "", "", ErrHandOn
	}
	st, refusal := readStory(values)
	switch refusal {
	case "":
	case badDate:
		return "", "", ErrHandOn
	default:
		return "", refusal, nil
	}
	var school *string
	if st.School != "" {
		var id string
		err := s.db.QueryRow(ctx, `SELECT id FROM school WHERE (id = $1 OR school_id = $1) AND deleted_at IS NULL
ORDER BY created_at DESC LIMIT 1`, st.School).Scan(&id)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return "", "", fmt.Errorf("mscs: reading the school: %w", err)
		}
		if err == nil {
			school = &id
		}
	}
	now := s.now()
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return "", "", fmt.Errorf("mscs: opening the save: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if _, err := tx.Exec(ctx, `INSERT INTO mscs_story (created_at, updated_at, id, user_id, cluster_id, title, narrative, evidence_uri,
  story_date, status, reviewed_by, reviewed_at, return_reason, school_id, country, intervention, outcome_area)
VALUES ($1, $1, $2, $3, NULL, $4, $5, NULL, $6, 'submitted', NULL, NULL, NULL, $7, '', '', '')`,
		now, cuid.New(), p.UserID, st.Title, st.Narrative, st.Date, school); err != nil {
		return "", "", fmt.Errorf("mscs: saving the story: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return "", "", fmt.Errorf("mscs: committing the story: %w", err)
	}
	// No ledger mark: the view creates the story with its date still a
	// string, so the model's signal finds no year to mark, and a submitted
	// story counts for nothing until it is approved, whose save marks it.
	return submitted, "", nil
}
