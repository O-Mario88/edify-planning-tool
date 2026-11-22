// Package uploads implements native Go Bulk Upload Center templates and
// transactional CSV re-imports (official SSA score sheets and planned-activity
// completion sheets), enforcing RBAC, country boundaries, input validation,
// separation-of-duties (pending verification), audit logging, and real-time SSE.
package uploads

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/realtime"
)

const maxUploadBytes = 5 << 20 // 5 MiB

// Authenticator authenticates a Bearer Authorization header.
type Authenticator interface {
	Authenticate(ctx context.Context, header string) (auth.Principal, error)
}

var (
	ssaUploadRoles = map[string]bool{
		"Admin":            true,
		"ImpactAssessment": true,
		"CountryDirector":  true,
		"Program Lead":     true,
	}
	activityUploadRoles = map[string]bool{
		"Admin":           true,
		"CountryDirector": true,
		"Program Lead":    true,
		"CCEO":            true,
	}
)

// ssaInterventions matches the 8 official Edify SSA intervention codes and labels.
var ssaInterventions = [][2]string{
	{"christ_centered_education", "Christ-Centered Education"},
	{"school_leadership", "School Leadership"},
	{"teaching_and_learning", "Teaching & Learning"},
	{"financial_sustainability", "Financial Sustainability"},
	{"education_technology", "Education Technology"},
	{"enrolment", "Enrolment"},
	{"community_engagement", "Community Engagement"},
	{"safeguarding", "Safeguarding"},
}

// Service owns native Go bulk CSV template downloads and validated imports.
type Service struct {
	pool     *pgxpool.Pool
	now      func() time.Time
	realtime *realtime.Broker
}

// NewService constructs a Bulk Upload Center service over pool.
func NewService(pool *pgxpool.Pool, now func() time.Time) *Service {
	if now == nil {
		now = time.Now
	}
	return &Service{pool: pool, now: now}
}

// WithRealtime attaches the SSE broker for post-commit import notifications.
func (s *Service) WithRealtime(b *realtime.Broker) *Service {
	s.realtime = b
	return s
}

// SSATemplateCSV renders the official SSA upload CSV template headers & sample.
func SSATemplateCSV(now time.Time) []byte {
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	headers := []string{"School ID", "Assessment Date", "SSA Year"}
	for _, iv := range ssaInterventions {
		headers = append(headers, iv[1]+" (0-10)")
	}
	_ = w.Write(headers)
	sample := []string{"UG-0001", now.UTC().Format("2006-01-02"), operationalFY(now.UTC())}
	for range ssaInterventions {
		sample = append(sample, "7.5")
	}
	_ = w.Write(sample)
	w.Flush()
	return buf.Bytes()
}

// RowError identifies a validation error on a specific 1-based CSV row.
type RowError struct {
	Row     int    `json:"row"`
	Message string `json:"message"`
}

// ImportResult summarizes a bulk CSV import execution.
type ImportResult struct {
	ImportedCount int        `json:"imported_count"`
	SkippedCount  int        `json:"skipped_count"`
	RecordIDs     []string   `json:"record_ids"`
	Errors        []RowError `json:"errors,omitempty"`
}

type parsedSSARow struct {
	rowNum     int
	schoolCode string
	assessDate time.Time
	fy         string
	scores     map[string]float64
	avg        float64
}

// ParseSSACSV validates and normalizes an uploaded SSA CSV sheet prior to DB write.
func ParseSSACSV(r io.Reader, now time.Time) ([]parsedSSARow, []RowError, error) {
	records, err := csv.NewReader(r).ReadAll()
	if err != nil {
		return nil, nil, fmt.Errorf("uploads: invalid CSV: %w", err)
	}
	if len(records) < 2 {
		return nil, nil, errors.New("uploads: CSV must contain a header row and at least one data row")
	}
	headerIdx := map[string]int{}
	for i, raw := range records[0] {
		key := normalizeHeader(raw)
		headerIdx[key] = i
	}
	colSchool, okSchool := findHeader(headerIdx, "school id", "edify school id", "school_id", "edify_school_id")
	colDate, okDate := findHeader(headerIdx, "assessment date", "date of ssa", "date_of_ssa", "date")
	colFY, okFY := findHeader(headerIdx, "ssa year", "fy", "fiscal year")
	if !okSchool || !okDate || !okFY {
		return nil, nil, errors.New("uploads: missing required columns (School ID, Assessment Date, SSA Year)")
	}

	ivCols := map[string]int{}
	for _, iv := range ssaInterventions {
		if idx, ok := findHeader(headerIdx,
			normalizeHeader(iv[1]+" (0-10)"),
			normalizeHeader(iv[1]),
			normalizeHeader(iv[0]),
		); ok {
			ivCols[iv[0]] = idx
		}
	}
	if len(ivCols) == 0 {
		return nil, nil, errors.New("uploads: CSV must include at least one intervention score column")
	}

	seen := map[string]bool{}
	var valid []parsedSSARow
	var rowErrs []RowError
	curFY := operationalFY(now.UTC())
	curFYInt, _ := strconv.Atoi(curFY)

	for i := 1; i < len(records); i++ {
		rec := records[i]
		rowNum := i + 1
		if isBlankRow(rec) {
			continue
		}
		schoolCode := cell(rec, colSchool)
		rawDate := cell(rec, colDate)
		rawFY := cell(rec, colFY)
		if schoolCode == "" {
			rowErrs = append(rowErrs, RowError{Row: rowNum, Message: "School ID is required"})
			continue
		}
		dt, err := time.Parse("2006-01-02", rawDate)
		if err != nil {
			rowErrs = append(rowErrs, RowError{Row: rowNum, Message: fmt.Sprintf("invalid Assessment Date %q (expected YYYY-MM-DD)", rawDate)})
			continue
		}
		fy, err := resolveFY(rawFY, curFYInt)
		if err != nil {
			rowErrs = append(rowErrs, RowError{Row: rowNum, Message: err.Error()})
			continue
		}
		dedupKey := strings.ToUpper(schoolCode) + "|" + dt.Format("2006-01-02")
		if seen[dedupKey] {
			rowErrs = append(rowErrs, RowError{Row: rowNum, Message: fmt.Sprintf("duplicate School ID %q and Assessment Date %q in file", schoolCode, rawDate)})
			continue
		}
		seen[dedupKey] = true

		scores := map[string]float64{}
		var sum float64
		badScore := false
		for code, ci := range ivCols {
			rawVal := cell(rec, ci)
			if rawVal == "" {
				continue
			}
			v, err := strconv.ParseFloat(rawVal, 64)
			if err != nil || math.IsNaN(v) || math.IsInf(v, 0) || v < 0 || v > 10 {
				rowErrs = append(rowErrs, RowError{Row: rowNum, Message: fmt.Sprintf("invalid score %q for %s (must be 0-10)", rawVal, code)})
				badScore = true
				break
			}
			scores[code] = v
			sum += v
		}
		if badScore {
			continue
		}
		if len(scores) == 0 {
			rowErrs = append(rowErrs, RowError{Row: rowNum, Message: "at least one intervention score (0-10) is required"})
			continue
		}
		avg := math.Round((sum/float64(len(scores)))*100) / 100
		valid = append(valid, parsedSSARow{
			rowNum:     rowNum,
			schoolCode: schoolCode,
			assessDate: dt.UTC(),
			fy:         fy,
			scores:     scores,
			avg:        avg,
		})
	}
	return valid, rowErrs, nil
}

// ImportSSACSV validates and atomically persists SSA records (pending verification).
func (s *Service) ImportSSACSV(ctx context.Context, p auth.Principal, r io.Reader) (*ImportResult, error) {
	if !ssaUploadRoles[p.ActiveRole] {
		return nil, errors.New("uploads: forbidden")
	}
	rows, errs, err := ParseSSACSV(r, s.now())
	if err != nil {
		return nil, err
	}
	res := &ImportResult{Errors: errs}
	if len(rows) == 0 {
		res.SkippedCount = len(errs)
		return res, nil
	}

	countryID := ""
	countryCode := ""
	if p.Country != nil {
		countryID = strings.TrimSpace(p.Country.ID)
		countryCode = strings.ToUpper(strings.TrimSpace(p.Country.Code))
	}

	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	now := s.now().UTC()
	for _, row := range rows {
		var schoolUUID string
		q := `SELECT s.id FROM school s WHERE s.deleted_at IS NULL AND (lower(COALESCE(s.school_id, '')) = lower($1) OR s.id = $1)`
		args := []any{row.schoolCode}
		if countryID != "" {
			args = append(args, []string{countryID})
			q += ` AND ` + country.SchoolIn("s", "$2")
		}
		q += ` LIMIT 1`
		if err := tx.QueryRow(ctx, q, args...).Scan(&schoolUUID); err != nil {
			res.Errors = append(res.Errors, RowError{Row: row.rowNum, Message: fmt.Sprintf("school %q not found in your country", row.schoolCode)})
			res.SkippedCount++
			continue
		}
		var existing int
		_ = tx.QueryRow(ctx, `SELECT count(*) FROM ssa_record WHERE school_id = $1 AND date_of_ssa::date = $2::date AND deleted_at IS NULL`,
			schoolUUID, row.assessDate.Format("2006-01-02")).Scan(&existing)
		if existing > 0 {
			res.Errors = append(res.Errors, RowError{Row: row.rowNum, Message: fmt.Sprintf("SSA record already exists for %s on %s", row.schoolCode, row.assessDate.Format("2006-01-02"))})
			res.SkippedCount++
			continue
		}

		recID := newID("ssa_")
		_, err := tx.Exec(ctx, `
INSERT INTO ssa_record (
  id, created_at, date_of_ssa, fy, average_score, verification_status,
  collector_type, collected_by_user_id, uploaded_by, school_id, return_reason
) VALUES ($1, $2, $3, $4, $5, 'pending', 'bulk_upload', $6, $7, $8, '')`,
			recID, now, row.assessDate, row.fy, row.avg, p.UserID, p.UserID, schoolUUID)
		if err != nil {
			return nil, fmt.Errorf("uploads: insert ssa_record: %w", err)
		}
		for iv, score := range row.scores {
			if _, err := tx.Exec(ctx, `INSERT INTO ssa_score (id, ssa_record_id, intervention, score) VALUES ($1, $2, $3, $4)`,
				newID("ssas_"), recID, iv, score); err != nil {
				return nil, fmt.Errorf("uploads: insert ssa_score: %w", err)
			}
		}
		res.ImportedCount++
		res.RecordIDs = append(res.RecordIDs, recID)
	}
	res.SkippedCount = len(res.Errors)

	if res.ImportedCount > 0 {
		_, _ = tx.Exec(ctx, `
INSERT INTO audit_log (id, created_at, actor_user_id, actor_role, action, subject_kind, subject_id, metadata)
VALUES ($1, $2, $3, $4, 'ssa.bulk_uploaded', 'ssa_record', $5, $6)`,
			newID("aud_"), now, p.UserID, p.ActiveRole, res.RecordIDs[0],
			fmt.Sprintf(`{"imported_count":%d,"skipped_count":%d}`, res.ImportedCount, res.SkippedCount))
	}

	if err := tx.Commit(ctx); err != nil {
		return nil, err
	}

	if res.ImportedCount > 0 && s.realtime != nil {
		s.realtime.Publish(realtime.Event{
			Type:        "ssa.bulk_uploaded",
			EntityType:  "ssa_record",
			EntityID:    res.RecordIDs[0],
			CountryCode: countryCode,
			TargetRoles: []string{"Admin", "ImpactAssessment", "CountryDirector", "Program Lead"},
			ActorUserID: p.UserID,
			Summary:     fmt.Sprintf("%d SSA record(s) uploaded and queued for independent verification", res.ImportedCount),
		})
	}
	return res, nil
}

// RegisterHTTP mounts native Go Bulk Upload Center endpoints:
//   - GET  /api/v1/uploads/ssa/template
//   - POST /api/v1/uploads/ssa/import
//   - GET  /api/v1/uploads/planned-activities/template
//   - POST /api/v1/uploads/planned-activities/import
func (s *Service) RegisterHTTP(mux *http.ServeMux, auther Authenticator) {
	mux.HandleFunc("GET /api/v1/uploads/ssa/template", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in first."})
			return
		}
		if !ssaUploadRoles[p.ActiveRole] {
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "Your role cannot download SSA upload templates."})
			return
		}
		payload := SSATemplateCSV(s.now())
		w.Header().Set("Content-Type", "text/csv; charset=utf-8")
		w.Header().Set("Content-Disposition", `attachment; filename="edify-ssa-upload-template.csv"`)
		w.Header().Set("Cache-Control", "no-store")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(payload)
	})

	mux.HandleFunc("POST /api/v1/uploads/ssa/import", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in first."})
			return
		}
		if !ssaUploadRoles[p.ActiveRole] {
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "Your role cannot upload official SSA scores."})
			return
		}
		reader, cleanup, err := extractCSVReader(w, r)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		defer cleanup()

		res, err := s.ImportSSACSV(r.Context(), p, reader)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, res)
	})

	mux.HandleFunc("GET /api/v1/uploads/planned-activities/template", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in first."})
			return
		}
		if !activityUploadRoles[p.ActiveRole] {
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "Your role cannot download planned-activity templates."})
			return
		}
		var buf bytes.Buffer
		cw := csv.NewWriter(&buf)
		_ = cw.Write([]string{"activity_id", "edify_school_id", "school_name", "activity_type", "planned_date", "current_status", "completion_status", "completion_notes"})
		if s.pool != nil {
			q := `SELECT a.id, COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(a.activity_type, ''), COALESCE(a.planned_date::text, ''), COALESCE(a.status, '')
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
WHERE a.deleted_at IS NULL AND a.status IN ('planned','scheduled','in_progress','returned_by_pl','returned_by_ia')`
			var args []any
			if p.ActiveRole == "CCEO" && p.StaffProfileID != "" {
				args = append(args, p.StaffProfileID)
				q += fmt.Sprintf(` AND a.responsible_staff_id = $%d`, len(args))
			}
			q += ` ORDER BY a.planned_date ASC NULLS LAST LIMIT 500`
			if rows, qerr := s.pool.Query(r.Context(), q, args...); qerr == nil {
				defer rows.Close()
				for rows.Next() {
					var id, code, school, kind, dt, status string
					if scanErr := rows.Scan(&id, &code, &school, &kind, &dt, &status); scanErr == nil {
						_ = cw.Write([]string{id, code, school, kind, dt, status, "", ""})
					}
				}
			}
		}
		cw.Flush()
		w.Header().Set("Content-Type", "text/csv; charset=utf-8")
		w.Header().Set("Content-Disposition", `attachment; filename="edify-planned-activities-template.csv"`)
		w.Header().Set("Cache-Control", "no-store")
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write(buf.Bytes())
	})

	mux.HandleFunc("POST /api/v1/uploads/planned-activities/import", func(w http.ResponseWriter, r *http.Request) {
		p, err := auther.Authenticate(r.Context(), r.Header.Get("Authorization"))
		if err != nil {
			writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "Sign in first."})
			return
		}
		if !activityUploadRoles[p.ActiveRole] {
			writeJSON(w, http.StatusForbidden, map[string]string{"error": "Your role cannot bulk-update planned activities."})
			return
		}
		reader, cleanup, err := extractCSVReader(w, r)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		defer cleanup()

		res, err := s.importPlannedActivities(r.Context(), p, reader)
		if err != nil {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, res)
	})
}

func (s *Service) importPlannedActivities(ctx context.Context, p auth.Principal, r io.Reader) (*ImportResult, error) {
	records, err := csv.NewReader(r).ReadAll()
	if err != nil {
		return nil, fmt.Errorf("uploads: invalid CSV: %w", err)
	}
	if len(records) < 2 {
		return nil, errors.New("uploads: CSV must contain a header row and at least one data row")
	}
	hdr := map[string]int{}
	for i, h := range records[0] {
		hdr[normalizeHeader(h)] = i
	}
	colID, okID := findHeader(hdr, "activity_id", "activity id")
	colStatus, okStatus := findHeader(hdr, "completion_status", "completion status", "status")
	colNotes, _ := findHeader(hdr, "completion_notes", "completion notes", "notes")
	if !okID || !okStatus {
		return nil, errors.New("uploads: missing required columns (activity_id, completion_status)")
	}

	allowedTargets := map[string]bool{"completed": true, "submitted_to_pl": true, "cancelled": true}
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	res := &ImportResult{}
	now := s.now().UTC()
	for i := 1; i < len(records); i++ {
		rec := records[i]
		rowNum := i + 1
		if isBlankRow(rec) {
			continue
		}
		actID := cell(rec, colID)
		target := strings.ToLower(cell(rec, colStatus))
		if target == "" {
			continue // untouched template row
		}
		if actID == "" {
			res.Errors = append(res.Errors, RowError{Row: rowNum, Message: "activity_id is required"})
			continue
		}
		if !allowedTargets[target] {
			res.Errors = append(res.Errors, RowError{Row: rowNum, Message: fmt.Sprintf("unsupported completion_status %q (use completed, submitted_to_pl, or cancelled)", target)})
			continue
		}
		notes := cell(rec, colNotes)
		q := `UPDATE activity SET status = $1, updated_at = $2, completion_notes = CASE WHEN $3 <> '' THEN $3 ELSE completion_notes END WHERE id = $4 AND deleted_at IS NULL`
		args := []any{target, now, notes, actID}
		if p.ActiveRole == "CCEO" && p.StaffProfileID != "" {
			args = append(args, p.StaffProfileID)
			q += ` AND responsible_staff_id = $5`
		}
		tag, err := tx.Exec(ctx, q, args...)
		if err != nil {
			return nil, fmt.Errorf("uploads: update activity: %w", err)
		}
		if tag.RowsAffected() == 0 {
			res.Errors = append(res.Errors, RowError{Row: rowNum, Message: fmt.Sprintf("activity %q not found or not owned by you", actID)})
			continue
		}
		res.ImportedCount++
		res.RecordIDs = append(res.RecordIDs, actID)
	}
	res.SkippedCount = len(res.Errors)

	if err := tx.Commit(ctx); err != nil {
		return nil, err
	}
	if res.ImportedCount > 0 && s.realtime != nil {
		cc := ""
		if p.Country != nil {
			cc = p.Country.Code
		}
		s.realtime.Publish(realtime.Event{
			Type:        "activities.bulk_updated",
			EntityType:  "activity",
			EntityID:    res.RecordIDs[0],
			CountryCode: cc,
			TargetRoles: []string{"Admin", "CountryDirector", "Program Lead", "CCEO"},
			ActorUserID: p.UserID,
			Summary:     fmt.Sprintf("%d planned activity record(s) updated via bulk CSV upload", res.ImportedCount),
		})
	}
	return res, nil
}

func extractCSVReader(w http.ResponseWriter, r *http.Request) (io.Reader, func(), error) {
	r.Body = http.MaxBytesReader(w, r.Body, maxUploadBytes)
	ct := strings.ToLower(r.Header.Get("Content-Type"))
	if strings.HasPrefix(ct, "multipart/form-data") {
		if err := r.ParseMultipartForm(maxUploadBytes); err != nil {
			return nil, func() {}, errors.New("Could not read uploaded multipart form.")
		}
		file, _, err := r.FormFile("file")
		if err != nil {
			return nil, func() {}, errors.New("Attach a CSV file in the 'file' field.")
		}
		return file, func() { _ = file.Close() }, nil
	}
	data, err := io.ReadAll(r.Body)
	if err != nil {
		return nil, func() {}, errors.New("Could not read CSV request body.")
	}
	return bytes.NewReader(data), func() {}, nil
}

func normalizeHeader(raw string) string {
	raw = strings.TrimPrefix(raw, "\ufeff")
	raw = strings.ToLower(strings.TrimSpace(raw))
	return strings.Join(strings.Fields(raw), " ")
}

func findHeader(idx map[string]int, names ...string) (int, bool) {
	for _, n := range names {
		if i, ok := idx[n]; ok {
			return i, true
		}
	}
	return -1, false
}

func cell(rec []string, idx int) string {
	if idx < 0 || idx >= len(rec) {
		return ""
	}
	return strings.TrimSpace(rec[idx])
}

func isBlankRow(rec []string) bool {
	for _, c := range rec {
		if strings.TrimSpace(c) != "" {
			return false
		}
	}
	return true
}

func operationalFY(now time.Time) string {
	if now.Month() >= time.October {
		return strconv.Itoa(now.Year() + 1)
	}
	return strconv.Itoa(now.Year())
}

func resolveFY(raw string, curFY int) (string, error) {
	s := strings.ToLower(strings.TrimSpace(raw))
	s = strings.TrimPrefix(s, "fy")
	s = strings.TrimSpace(s)
	switch s {
	case "current":
		return strconv.Itoa(curFY), nil
	case "last":
		return strconv.Itoa(curFY - 1), nil
	default:
		n, err := strconv.Atoi(s)
		if err != nil || n < 2015 || n > 2100 {
			return "", fmt.Errorf("invalid SSA Year %q (use last, current, or 4-digit FY)", raw)
		}
		return strconv.Itoa(n), nil
	}
}

func newID(prefix string) string {
	var b [8]byte
	_, _ = rand.Read(b[:])
	return prefix + hex.EncodeToString(b[:])
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
