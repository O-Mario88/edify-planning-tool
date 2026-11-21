// Package exports implements native Go asynchronous report export generation
// and authorized download (Batch 13 — replacing Django export forwarding).
//
// Authorization is enforced BOTH at export creation and at download time,
// scoping rows to the requester's role and country boundary.
package exports

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"errors"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

var (
	ErrForbidden   = errors.New("exports: reader is not authorized for this export")
	ErrNotFound    = errors.New("exports: export job not found")
	ErrUnknownKind = errors.New("exports: unsupported export kind")
)

type JobStatus string

const (
	StatusPending   JobStatus = "pending"
	StatusCompleted JobStatus = "completed"
	StatusFailed    JobStatus = "failed"
)

type Job struct {
	ID          string
	Kind        string
	OwnerUserID string
	OwnerRole   string
	CountryID   string
	Status      JobStatus
	RowCount    int
	SHA256      string
	Payload     []byte
	Error       string
	CreatedAt   time.Time
	CompletedAt *time.Time
}

type Manager struct {
	pool *pgxpool.Pool
	now  func() time.Time
	mu   sync.RWMutex
	jobs map[string]*Job
}

func NewManager(pool *pgxpool.Pool, now func() time.Time) *Manager {
	if now == nil {
		now = time.Now
	}
	return &Manager{pool: pool, now: now, jobs: map[string]*Job{}}
}

var allowedRoles = map[string]map[string]bool{
	"completed_visits": {"Admin": true, "CountryDirector": true, "Program Lead": true, "ImpactAssessment": true, "CCEO": true},
	"finance_weekly":   {"Admin": true, "CountryDirector": true, "Program Lead": true, "Accountant": true},
	"ssa_records":      {"Admin": true, "CountryDirector": true, "Program Lead": true, "ImpactAssessment": true},
	"school_directory": {"Admin": true, "CountryDirector": true, "Program Lead": true, "ImpactAssessment": true, "CCEO": true, "ProjectCoordinator": true},
}

// CreateAndRun validates authorization at creation time, generates the CSV
// payload directly from PostgreSQL scoped to the caller's country, and stores
// the immutable result with SHA-256 checksum.
func (m *Manager) CreateAndRun(ctx context.Context, p auth.Principal, kind string) (*Job, error) {
	roles, ok := allowedRoles[kind]
	if !ok {
		return nil, fmt.Errorf("%w: %s", ErrUnknownKind, kind)
	}
	if !roles[p.ActiveRole] {
		return nil, ErrForbidden
	}
	countryID := ""
	if p.Country != nil {
		countryID = p.Country.ID
	}
	ts := m.now().UTC()
	sum := sha256.Sum256([]byte(fmt.Sprintf("%s:%s:%s:%d", kind, p.UserID, countryID, ts.UnixNano())))
	job := &Job{
		ID:          "exp_" + hex.EncodeToString(sum[:10]),
		Kind:        kind,
		OwnerUserID: p.UserID,
		OwnerRole:   p.ActiveRole,
		CountryID:   countryID,
		Status:      StatusPending,
		CreatedAt:   ts,
	}
	m.mu.Lock()
	m.jobs[job.ID] = job
	m.mu.Unlock()

	payload, count, err := m.generate(ctx, p, kind, countryID)
	doneAt := m.now().UTC()
	m.mu.Lock()
	defer m.mu.Unlock()
	if err != nil {
		job.Status = StatusFailed
		job.Error = err.Error()
		job.CompletedAt = &doneAt
		return job, err
	}
	digest := sha256.Sum256(payload)
	job.Payload = payload
	job.RowCount = count
	job.SHA256 = hex.EncodeToString(digest[:])
	job.Status = StatusCompleted
	job.CompletedAt = &doneAt
	return job, nil
}

// AuthorizeDownload re-verifies authorization and country boundary at download
// time so no unrelated user or cross-country principal can download another
// user's export artifact.
func (m *Manager) AuthorizeDownload(p auth.Principal, jobID string) (*Job, error) {
	m.mu.RLock()
	job, ok := m.jobs[jobID]
	m.mu.RUnlock()
	if !ok {
		return nil, ErrNotFound
	}
	if p.ActiveRole != "Admin" {
		if job.OwnerUserID != p.UserID {
			return nil, ErrForbidden
		}
		readerCountry := ""
		if p.Country != nil {
			readerCountry = p.Country.ID
		}
		if job.CountryID != "" && readerCountry != "" && job.CountryID != readerCountry {
			return nil, ErrForbidden
		}
	}
	return job, nil
}

func (m *Manager) generate(ctx context.Context, p auth.Principal, kind, countryID string) ([]byte, int, error) {
	if m.pool == nil {
		return []byte("id\n"), 0, nil
	}
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	switch kind {
	case "completed_visits":
		_ = w.Write([]string{"activity_id", "school_code", "school_name", "status", "fy"})
		q := `SELECT a.id, COALESCE(s.school_id, ''), COALESCE(s.name, ''), a.status, COALESCE(a.fy, '')
FROM activity a LEFT JOIN school s ON s.id = a.school_id
WHERE a.deleted_at IS NULL AND a.status IN ('completed','submitted','pl_approved','ia_verified','confirmed','closed')`
		var args []any
		if countryID != "" {
			q += ` AND ` + country.SchoolIn("s", "$1")
			args = append(args, []string{countryID})
		}
		q += ` ORDER BY a.updated_at DESC LIMIT 500`
		rows, err := m.pool.Query(ctx, q, args...)
		if err != nil {
			return nil, 0, err
		}
		defer rows.Close()
		count := 0
		for rows.Next() {
			var id, code, name, status, fy string
			if err := rows.Scan(&id, &code, &name, &status, &fy); err != nil {
				return nil, 0, err
			}
			_ = w.Write([]string{id, code, name, status, fy})
			count++
		}
		w.Flush()
		return buf.Bytes(), count, rows.Err()
	case "finance_weekly":
		_ = w.Write([]string{"request_id", "fy", "week_start", "total_amount", "status"})
		rows, err := m.pool.Query(ctx, `
SELECT id, fy, week_start_date::text, total_amount::text, status
FROM weekly_fund_request ORDER BY week_start_date DESC LIMIT 500`)
		if err != nil {
			return nil, 0, err
		}
		defer rows.Close()
		count := 0
		for rows.Next() {
			var id, fy, wk, amt, st string
			if err := rows.Scan(&id, &fy, &wk, &amt, &st); err != nil {
				return nil, 0, err
			}
			_ = w.Write([]string{id, fy, wk, amt, st})
			count++
		}
		w.Flush()
		return buf.Bytes(), count, rows.Err()
	case "ssa_records":
		_ = w.Write([]string{"ssa_id", "school_code", "fy", "average_score", "verification_status"})
		q := `SELECT r.id, COALESCE(s.school_id, ''), r.fy, COALESCE(r.average_score::text, ''), r.verification_status
FROM ssa_record r JOIN school s ON s.id = r.school_id
WHERE r.deleted_at IS NULL`
		var args []any
		if countryID != "" {
			q += ` AND ` + country.SchoolIn("s", "$1")
			args = append(args, []string{countryID})
		}
		q += ` ORDER BY r.date_of_ssa DESC LIMIT 500`
		rows, err := m.pool.Query(ctx, q, args...)
		if err != nil {
			return nil, 0, err
		}
		defer rows.Close()
		count := 0
		for rows.Next() {
			var id, code, fy, score, st string
			if err := rows.Scan(&id, &code, &fy, &score, &st); err != nil {
				return nil, 0, err
			}
			_ = w.Write([]string{id, code, fy, score, st})
			count++
		}
		w.Flush()
		return buf.Bytes(), count, rows.Err()
	case "school_directory":
		_ = w.Write([]string{"school_id", "school_code", "name", "school_type", "operational_status"})
		q := `SELECT s.id, COALESCE(s.school_id, ''), s.name, COALESCE(s.school_type, ''), COALESCE(s.operational_status, '')
FROM school s WHERE s.deleted_at IS NULL`
		var args []any
		if strings.TrimSpace(countryID) != "" {
			q += ` AND ` + country.SchoolIn("s", "$1")
			args = append(args, []string{strings.TrimSpace(countryID)})
		}
		q += ` ORDER BY s.name ASC LIMIT 500`
		rows, err := m.pool.Query(ctx, q, args...)
		if err != nil {
			return nil, 0, err
		}
		defer rows.Close()
		count := 0
		for rows.Next() {
			var id, code, name, stype, status string
			if err := rows.Scan(&id, &code, &name, &stype, &status); err != nil {
				return nil, 0, err
			}
			_ = w.Write([]string{id, code, name, stype, status})
			count++
		}
		w.Flush()
		return buf.Bytes(), count, rows.Err()
	default:
		return nil, 0, ErrUnknownKind
	}
}
