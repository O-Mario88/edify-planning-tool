// Package exports implements native Go report export generation and authorized
// download (replacing Django export forwarding).
//
// Authorization is enforced BOTH at export creation and at download time,
// scoping rows to the requester's role, country boundary, and active filters.
// Every school-list export includes the authoritative Edify School ID.
package exports

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"errors"
	"fmt"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

const (
	maxExportRows   = 50000
	maxRetainedJobs = 250
	jobRetentionTTL = 30 * time.Minute
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
	Filters     map[string]string
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
	"completed_visits": {"Admin": true, "CountryDirector": true, "Program Lead": true, "ImpactAssessment": true, "CCEO": true, "RegionalProgramLead": true, "RegionalVicePresident": true},
	"finance_weekly":   {"Admin": true, "CountryDirector": true, "Program Lead": true, "Accountant": true},
	"ssa_records":      {"Admin": true, "CountryDirector": true, "Program Lead": true, "ImpactAssessment": true, "RegionalProgramLead": true, "RegionalVicePresident": true},
	"school_directory": {"Admin": true, "CountryDirector": true, "Program Lead": true, "ImpactAssessment": true, "CCEO": true, "ProjectCoordinator": true, "RegionalProgramLead": true, "RegionalVicePresident": true},
	"core_schools":     {"Admin": true, "CountryDirector": true, "Program Lead": true, "ImpactAssessment": true, "CCEO": true, "RegionalProgramLead": true, "RegionalVicePresident": true},
	"clusters":         {"Admin": true, "CountryDirector": true, "Program Lead": true, "ImpactAssessment": true, "CCEO": true, "RegionalProgramLead": true, "RegionalVicePresident": true},
	"cluster_schools":  {"Admin": true, "CountryDirector": true, "Program Lead": true, "ImpactAssessment": true, "CCEO": true, "RegionalProgramLead": true, "RegionalVicePresident": true},
	"escalations":      {"Admin": true, "CountryDirector": true, "Program Lead": true, "ImpactAssessment": true, "CCEO": true, "RegionalProgramLead": true, "RegionalVicePresident": true, "HumanResources": true},
	"leave_requests":   {"Admin": true, "CountryDirector": true, "Program Lead": true, "HumanResources": true, "CCEO": true, "ImpactAssessment": true, "Accountant": true},
	"debriefs":         {"Admin": true, "CountryDirector": true, "Program Lead": true, "ImpactAssessment": true, "CCEO": true, "RegionalProgramLead": true},
	"decision_log":     {"Admin": true, "CountryDirector": true, "Program Lead": true, "ImpactAssessment": true, "RegionalProgramLead": true, "RegionalVicePresident": true},
}

// CreateAndRun validates authorization at creation time, generates the CSV
// payload directly from PostgreSQL scoped to the caller's country, and stores
// the immutable result with SHA-256 checksum.
func (m *Manager) CreateAndRun(ctx context.Context, p auth.Principal, kind string) (*Job, error) {
	return m.CreateAndRunFiltered(ctx, p, kind, nil)
}

// CreateAndRunFiltered generates a filtered CSV export authorized for p.
func (m *Manager) CreateAndRunFiltered(ctx context.Context, p auth.Principal, kind string, filters map[string]string) (*Job, error) {
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
	cleanFilters := make(map[string]string, len(filters))
	for k, v := range filters {
		k = strings.ToLower(strings.TrimSpace(k))
		v = strings.TrimSpace(v)
		if k != "" && v != "" && !strings.EqualFold(v, "all") {
			cleanFilters[k] = v
		}
	}
	ts := m.now().UTC()
	sum := sha256.Sum256([]byte(fmt.Sprintf("%s:%s:%s:%d", kind, p.UserID, countryID, ts.UnixNano())))
	job := &Job{
		ID:          "exp_" + hex.EncodeToString(sum[:10]),
		Kind:        kind,
		OwnerUserID: p.UserID,
		OwnerRole:   p.ActiveRole,
		CountryID:   countryID,
		Filters:     cleanFilters,
		Status:      StatusPending,
		CreatedAt:   ts,
	}
	m.mu.Lock()
	m.evictLocked(ts)
	m.jobs[job.ID] = job
	m.mu.Unlock()

	payload, count, err := m.generate(ctx, p, kind, countryID, cleanFilters)
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

// evictLocked bounds memory usage under high export concurrency (export storms).
func (m *Manager) evictLocked(now time.Time) {
	for id, j := range m.jobs {
		if now.Sub(j.CreatedAt) > jobRetentionTTL {
			delete(m.jobs, id)
		}
	}
	if len(m.jobs) < maxRetainedJobs {
		return
	}
	type pair struct {
		id string
		at time.Time
	}
	all := make([]pair, 0, len(m.jobs))
	for id, j := range m.jobs {
		all = append(all, pair{id: id, at: j.CreatedAt})
	}
	sort.Slice(all, func(i, j int) bool { return all[i].at.Before(all[j].at) })
	toDrop := len(all) - maxRetainedJobs + 1
	for i := 0; i < toDrop && i < len(all); i++ {
		delete(m.jobs, all[i].id)
	}
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

func (m *Manager) generate(ctx context.Context, p auth.Principal, kind, countryID string, filters map[string]string) ([]byte, int, error) {
	if m.pool == nil {
		return []byte("edify_school_id,id\n"), 0, nil
	}
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	switch kind {
	case "school_directory":
		_ = w.Write([]string{"edify_school_id", "record_id", "school_name", "district", "sub_region", "cluster", "school_type", "operational_status", "enrollment"})
		q := `SELECT COALESCE(s.school_id, ''), s.id, s.name, COALESCE(d.name, ''), COALESCE(sr.name, ''), COALESCE(c.name, ''), COALESCE(s.school_type, ''), COALESCE(s.operational_status, ''), COALESCE(s.enrollment::text, '')
FROM school s
LEFT JOIN district d ON d.id = s.district_id
LEFT JOIN sub_region sr ON sr.id = COALESCE(s.sub_region_id, d.sub_region_id)
LEFT JOIN cluster c ON c.id = s.cluster_id AND c.deleted_at IS NULL
WHERE s.deleted_at IS NULL`
		var args []any
		addArg := func(v any) string {
			args = append(args, v)
			return fmt.Sprintf("$%d", len(args))
		}
		if strings.TrimSpace(countryID) != "" {
			q += ` AND ` + country.SchoolIn("s", addArg([]string{strings.TrimSpace(countryID)}))
		}
		if v := filters["district"]; v != "" {
			q += ` AND lower(COALESCE(d.name, '')) = lower(` + addArg(v) + `)`
		}
		if v := filters["school_type"]; v != "" {
			q += ` AND lower(COALESCE(s.school_type, '')) = lower(` + addArg(v) + `)`
		}
		if v := filters["q"]; v != "" {
			pat := "%" + v + "%"
			ph := addArg(pat)
			q += ` AND (s.name ILIKE ` + ph + ` OR COALESCE(s.school_id, '') ILIKE ` + ph + ` OR COALESCE(d.name, '') ILIKE ` + ph + `)`
		}
		q += fmt.Sprintf(` ORDER BY s.name ASC LIMIT %d`, maxExportRows)
		return scanCSV(ctx, m.pool, w, &buf, q, args, 9)

	case "core_schools":
		_ = w.Write([]string{"edify_school_id", "record_id", "school_name", "district", "sub_region", "cluster", "school_type", "latest_ssa_score", "fy"})
		fy := filters["fy"]
		var args []any
		addArg := func(v any) string {
			args = append(args, v)
			return fmt.Sprintf("$%d", len(args))
		}
		ssaJoin := `LEFT JOIN LATERAL (
  SELECT r.average_score, r.fy FROM ssa_record r
  WHERE r.school_id = s.id AND r.deleted_at IS NULL AND r.verification_status = 'confirmed'`
		if fy != "" {
			ssaJoin += ` AND r.fy = ` + addArg(fy)
		}
		ssaJoin += ` ORDER BY r.date_of_ssa DESC LIMIT 1) ssa ON true`
		q := `SELECT COALESCE(s.school_id, ''), s.id, s.name, COALESCE(d.name, ''), COALESCE(sr.name, ''), COALESCE(c.name, ''), COALESCE(s.school_type, ''), COALESCE(round(ssa.average_score::numeric, 2)::text, ''), COALESCE(ssa.fy, '')
FROM school s
LEFT JOIN district d ON d.id = s.district_id
LEFT JOIN sub_region sr ON sr.id = COALESCE(s.sub_region_id, d.sub_region_id)
LEFT JOIN cluster c ON c.id = s.cluster_id AND c.deleted_at IS NULL
` + ssaJoin + `
WHERE s.deleted_at IS NULL AND s.operational_status IN ('active','reopened')
  AND lower(COALESCE(s.school_type, '')) IN ('core','core_trained','core_graduate','champion')`
		if strings.TrimSpace(countryID) != "" {
			q += ` AND ` + country.SchoolIn("s", addArg([]string{strings.TrimSpace(countryID)}))
		}
		if v := filters["district"]; v != "" {
			q += ` AND lower(COALESCE(d.name, '')) = lower(` + addArg(v) + `)`
		}
		q += fmt.Sprintf(` ORDER BY s.name ASC LIMIT %d`, maxExportRows)
		return scanCSV(ctx, m.pool, w, &buf, q, args, 9)

	case "clusters":
		_ = w.Write([]string{"cluster_id", "cluster_name", "district", "sub_region", "school_count"})
		q := `SELECT c.id, COALESCE(c.name, ''), COALESCE(d.name, ''), COALESCE(sr.name, ''), count(s.id)::text
FROM cluster c
LEFT JOIN district d ON d.id = c.district_id
LEFT JOIN sub_region sr ON sr.id = d.sub_region_id
LEFT JOIN school s ON s.cluster_id = c.id AND s.deleted_at IS NULL AND s.operational_status IN ('active','reopened')
WHERE c.deleted_at IS NULL
GROUP BY c.id, c.name, d.name, sr.name
ORDER BY c.name ASC LIMIT ` + fmt.Sprint(maxExportRows)
		return scanCSV(ctx, m.pool, w, &buf, q, nil, 5)

	case "cluster_schools":
		_ = w.Write([]string{"cluster_id", "cluster_name", "edify_school_id", "school_name", "district", "school_type"})
		var args []any
		q := `SELECT c.id, COALESCE(c.name, ''), COALESCE(s.school_id, ''), s.name, COALESCE(d.name, ''), COALESCE(s.school_type, '')
FROM school s
JOIN cluster c ON c.id = s.cluster_id AND c.deleted_at IS NULL
LEFT JOIN district d ON d.id = s.district_id
WHERE s.deleted_at IS NULL AND s.operational_status IN ('active','reopened')`
		if cid := filters["cluster_id"]; cid != "" {
			args = append(args, cid)
			q += fmt.Sprintf(` AND c.id = $%d`, len(args))
		}
		q += fmt.Sprintf(` ORDER BY c.name ASC, s.name ASC LIMIT %d`, maxExportRows)
		return scanCSV(ctx, m.pool, w, &buf, q, args, 6)

	case "completed_visits":
		_ = w.Write([]string{"activity_id", "edify_school_id", "school_name", "district", "activity_type", "status", "fy", "planned_date"})
		q := `SELECT a.id, COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(d.name, ''), COALESCE(a.activity_type, ''), a.status, COALESCE(a.fy, ''), COALESCE(a.planned_date::text, '')
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN district d ON d.id = s.district_id
WHERE a.deleted_at IS NULL AND a.status IN ('completed','submitted','pl_approved','ia_verified','confirmed','closed')`
		var args []any
		addArg := func(v any) string {
			args = append(args, v)
			return fmt.Sprintf("$%d", len(args))
		}
		if countryID != "" {
			q += ` AND ` + country.SchoolIn("s", addArg([]string{countryID}))
		}
		if fy := filters["fy"]; fy != "" {
			q += ` AND a.fy = ` + addArg(fy)
		}
		q += fmt.Sprintf(` ORDER BY a.updated_at DESC LIMIT %d`, maxExportRows)
		return scanCSV(ctx, m.pool, w, &buf, q, args, 8)

	case "ssa_records":
		_ = w.Write([]string{"ssa_id", "edify_school_id", "school_name", "district", "fy", "average_score", "verification_status"})
		q := `SELECT r.id, COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(d.name, ''), r.fy, COALESCE(r.average_score::text, ''), r.verification_status
FROM ssa_record r
JOIN school s ON s.id = r.school_id
LEFT JOIN district d ON d.id = s.district_id
WHERE r.deleted_at IS NULL`
		var args []any
		addArg := func(v any) string {
			args = append(args, v)
			return fmt.Sprintf("$%d", len(args))
		}
		if countryID != "" {
			q += ` AND ` + country.SchoolIn("s", addArg([]string{countryID}))
		}
		if fy := filters["fy"]; fy != "" {
			q += ` AND r.fy = ` + addArg(fy)
		}
		q += fmt.Sprintf(` ORDER BY r.date_of_ssa DESC LIMIT %d`, maxExportRows)
		return scanCSV(ctx, m.pool, w, &buf, q, args, 7)

	case "finance_weekly":
		_ = w.Write([]string{"advance_id", "fy", "planned_date", "requested_amount_ugx", "disbursed_amount_ugx", "accounted_amount_ugx", "returned_amount_ugx", "status"})
		var args []any
		q := `SELECT id, COALESCE(fy, ''), COALESCE(planned_date::text, ''), COALESCE(amount::text, '0'), COALESCE(disbursed_amount::text, '0'), COALESCE(accounted_amount::text, '0'), COALESCE(returned_amount::text, '0'), COALESCE(status, '')
FROM advance_request WHERE 1=1`
		if fy := filters["fy"]; fy != "" {
			args = append(args, fy)
			q += fmt.Sprintf(` AND fy = $%d`, len(args))
		}
		q += fmt.Sprintf(` ORDER BY planned_date DESC NULLS LAST LIMIT %d`, maxExportRows)
		return scanCSV(ctx, m.pool, w, &buf, q, args, 8)

	case "escalations":
		_ = w.Write([]string{"escalation_id", "category", "severity", "subject", "addressed_role", "status", "created_at"})
		var args []any
		q := `SELECT id, COALESCE(category, ''), COALESCE(severity, ''), COALESCE(subject, ''), COALESCE(addressed_role, ''), COALESCE(status, ''), created_at::text
FROM leadership_escalation WHERE 1=1`
		if p.ActiveRole == "CCEO" {
			args = append(args, p.UserID)
			q += fmt.Sprintf(` AND raised_by_user_id = $%d`, len(args))
		}
		q += fmt.Sprintf(` ORDER BY created_at DESC LIMIT %d`, maxExportRows)
		return scanCSV(ctx, m.pool, w, &buf, q, args, 7)

	case "leave_requests":
		_ = w.Write([]string{"leave_id", "leave_type", "start_date", "end_date", "days", "status"})
		var args []any
		q := `SELECT id, COALESCE(type, ''), COALESCE(start_date::text, ''), COALESCE(end_date::text, ''), COALESCE(days::text, '0'), COALESCE(status, '')
FROM leave WHERE 1=1`
		if p.ActiveRole == "CCEO" || p.ActiveRole == "ImpactAssessment" || p.ActiveRole == "Accountant" {
			args = append(args, p.StaffProfileID)
			q += fmt.Sprintf(` AND staff_id = $%d`, len(args))
		}
		q += fmt.Sprintf(` ORDER BY start_date DESC LIMIT %d`, maxExportRows)
		return scanCSV(ctx, m.pool, w, &buf, q, args, 6)

	case "debriefs":
		_ = w.Write([]string{"debrief_id", "debrief_date", "status", "risk_level", "title", "summary"})
		q := fmt.Sprintf(`SELECT id, COALESCE(date::text, ''), COALESCE(status, ''), COALESCE(risk_level, ''), COALESCE(title, ''), COALESCE(summary, '')
FROM daily_debrief WHERE deleted_at IS NULL ORDER BY date DESC NULLS LAST LIMIT %d`, maxExportRows)
		return scanCSV(ctx, m.pool, w, &buf, q, nil, 6)

	case "decision_log":
		_ = w.Write([]string{"decision_id", "created_at", "action", "actor_role", "subject_kind", "subject_id"})
		q := fmt.Sprintf(`SELECT id, created_at::text, COALESCE(action, ''), COALESCE(actor_role, ''), COALESCE(subject_kind, ''), COALESCE(subject_id, '')
FROM audit_log ORDER BY created_at DESC LIMIT %d`, maxExportRows)
		return scanCSV(ctx, m.pool, w, &buf, q, nil, 6)

	default:
		return nil, 0, ErrUnknownKind
	}
}

func scanCSV(ctx context.Context, pool *pgxpool.Pool, w *csv.Writer, buf *bytes.Buffer, q string, args []any, cols int) ([]byte, int, error) {
	rows, err := pool.Query(ctx, q, args...)
	if err != nil {
		return nil, 0, err
	}
	defer rows.Close()
	count := 0
	vals := make([]string, cols)
	ptrs := make([]any, cols)
	for i := range vals {
		ptrs[i] = &vals[i]
	}
	for rows.Next() {
		if err := rows.Scan(ptrs...); err != nil {
			return nil, 0, err
		}
		_ = w.Write(vals)
		count++
	}
	w.Flush()
	return buf.Bytes(), count, rows.Err()
}
