// Package fieldops implements native Go operational writes for Field Evidence
// (M8), IA Verification (M9), SSA Entry/Import/Confirmation (M7), and Partner
// Handovers (M10) through least-privilege SECURITY DEFINER SQL functions.
package fieldops

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

func withRW(ctx context.Context, pool *pgxpool.Pool, fn func(pgx.Tx) error) error {
	tx, err := pool.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := fn(tx); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

var (
	ErrForbidden    = errors.New("fieldops: actor is not permitted")
	ErrInvalidInput = errors.New("fieldops: invalid input")
	ErrQuarantined  = errors.New("fieldops: evidence file is quarantined")
)

type Service struct {
	pool *pgxpool.Pool
}

func NewService(pool *pgxpool.Pool) *Service {
	return &Service{pool: pool}
}

// ── M8: Evidence upload & authorized download ───────────────────────────────

type EvidenceUpload struct {
	ActivityID   string
	Kind         string
	URI          string
	OriginalName string
	MimeType     string
	Extension    string
	FileSize     int
	Provider     string
	Notes        string
}

// RecordUpload validates completeness (preventing interrupted uploads from
// publishing broken evidence) and writes idempotently via gateway_field_ops.
func (s *Service) RecordUpload(ctx context.Context, p auth.Principal, u EvidenceUpload) (string, error) {
	if strings.TrimSpace(u.ActivityID) == "" || strings.TrimSpace(u.URI) == "" {
		return "", fmt.Errorf("%w: activity_id and uri are required", ErrInvalidInput)
	}
	if u.FileSize <= 0 {
		return "", fmt.Errorf("%w: interrupted or empty upload (file_size must be > 0)", ErrInvalidInput)
	}
	kind := strings.TrimSpace(u.Kind)
	if kind == "" {
		kind = "visit_form"
	}
	var id string
	err := withRW(ctx, s.pool, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx,
			`SELECT gateway_field_ops.record_evidence($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`,
			u.ActivityID, kind, strings.TrimSpace(u.URI), u.OriginalName, u.MimeType, u.Extension,
			u.FileSize, u.Provider, p.UserID, p.ActiveRole, u.Notes).Scan(&id)
	})
	return id, err
}

// AuthorizeEvidenceRead checks whether principal p may view/download evidenceID
// (blocking quarantined records and unrelated officers).
func (s *Service) AuthorizeEvidenceRead(ctx context.Context, p auth.Principal, evidenceID string) (uri string, err error) {
	var ownerStaff, monitorStaff string
	var quarantined bool
	err = s.pool.QueryRow(ctx,
		`SELECT uri, quarantined, responsible_staff_id, monitored_by_staff_id FROM gateway_field_ops.read_evidence_uri($1)`,
		evidenceID).Scan(&uri, &quarantined, &ownerStaff, &monitorStaff)
	if err != nil {
		return "", err
	}
	if quarantined {
		return "", ErrQuarantined
	}
	switch p.ActiveRole {
	case "Admin", "CountryDirector", "ImpactAssessment", "RegionalVicePresident":
		return uri, nil
	case "Program Lead":
		// Permitted for own or supervised staff.
		if ownerStaff == p.StaffProfileID || ownerStaff == p.UserID || monitorStaff == p.StaffProfileID {
			return uri, nil
		}
		var supervised bool
		_ = s.pool.QueryRow(ctx, `SELECT EXISTS(
			SELECT 1 FROM staff_supervisor_assignment
			WHERE supervisor_id = $1 AND supervisee_id = $2)`, p.StaffProfileID, ownerStaff).Scan(&supervised)
		if supervised {
			return uri, nil
		}
		return "", ErrForbidden
	default:
		if ownerStaff == p.StaffProfileID || ownerStaff == p.UserID || monitorStaff == p.StaffProfileID || monitorStaff == p.UserID {
			return uri, nil
		}
		return "", ErrForbidden
	}
}

// ── M9: IA Verification & Return ────────────────────────────────────────────

func (s *Service) IADecideActivity(ctx context.Context, p auth.Principal, activityID, decision, note string) (string, error) {
	if p.ActiveRole != "ImpactAssessment" && p.ActiveRole != "Admin" {
		return "", fmt.Errorf("%w: ImpactAssessment or Admin role required", ErrForbidden)
	}
	decision = strings.ToLower(strings.TrimSpace(decision))
	if decision != "verified" && decision != "returned" {
		return "", fmt.Errorf("%w: decision must be verified or returned", ErrInvalidInput)
	}
	if decision == "returned" && strings.TrimSpace(note) == "" {
		return "", fmt.Errorf("%w: return note is required", ErrInvalidInput)
	}
	var newStatus string
	err := withRW(ctx, s.pool, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx,
			`SELECT gateway_field_ops.ia_decide_activity($1,$2,$3,$4,$5)`,
			activityID, decision, p.UserID, p.ActiveRole, strings.TrimSpace(note)).Scan(&newStatus)
	})
	return newStatus, err
}

// ── M7: SSA Entry, CSV Preview/Commit, & Confirmation ───────────────────────

type SSAScoreInput struct {
	Intervention string  `json:"intervention"`
	Score        float64 `json:"score"`
}

type SSAEntryRequest struct {
	SchoolID      string
	FY            string
	Quarter       string
	Date          time.Time
	NewEnrollment int
	Scores        []SSAScoreInput
	CollectorType string
	ActivityID    string
}

func (s *Service) EnterSSA(ctx context.Context, p auth.Principal, req SSAEntryRequest) (string, error) {
	if strings.TrimSpace(req.SchoolID) == "" || strings.TrimSpace(req.FY) == "" || len(req.Scores) == 0 {
		return "", fmt.Errorf("%w: school_id, fy, and at least one score are required", ErrInvalidInput)
	}
	sum := 0.0
	for _, sc := range req.Scores {
		if strings.TrimSpace(sc.Intervention) == "" || sc.Score < 0 || sc.Score > 5 {
			return "", fmt.Errorf("%w: invalid SSA score %+v (must be 0..5)", ErrInvalidInput, sc)
		}
		sum += sc.Score
	}
	avg := math.Round((sum/float64(len(req.Scores)))*100) / 100
	quarter := strings.TrimSpace(req.Quarter)
	if quarter == "" {
		quarter = "Q1"
	}
	payload, err := json.Marshal(req.Scores)
	if err != nil {
		return "", err
	}
	var id string
	err = withRW(ctx, s.pool, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx,
			`SELECT gateway_field_ops.enter_ssa($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10)`,
			req.SchoolID, req.FY, quarter, req.Date.UTC(), req.NewEnrollment, avg,
			string(payload), req.CollectorType, p.UserID, req.ActivityID).Scan(&id)
	})
	return id, err
}

func (s *Service) DecideSSA(ctx context.Context, p auth.Principal, ssaID, decision, reason string) (string, error) {
	if p.ActiveRole != "Program Lead" && p.ActiveRole != "ImpactAssessment" && p.ActiveRole != "Admin" && p.ActiveRole != "CountryDirector" {
		return "", fmt.Errorf("%w: supervisor or IA role required", ErrForbidden)
	}
	if decision != "confirmed" && decision != "returned" {
		return "", fmt.Errorf("%w: decision must be confirmed or returned", ErrInvalidInput)
	}
	var out string
	err := withRW(ctx, s.pool, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx, `SELECT gateway_field_ops.decide_ssa($1,$2,$3,$4)`,
			ssaID, decision, p.UserID, strings.TrimSpace(reason)).Scan(&out)
	})
	return out, err
}

// SSACSVPreview summarizes a bulk SSA CSV upload with exact reconciliation of
// valid, duplicate, and rejected rows before commit.
type SSACSVPreview struct {
	Valid     []SSAEntryRequest
	Duplicate []int
	Rejected  map[int]string
}

func PreviewSSACSV(r io.Reader, fy string) (SSACSVPreview, error) {
	cr := csv.NewReader(r)
	header, err := cr.Read()
	if err != nil {
		return SSACSVPreview{}, fmt.Errorf("%w: reading CSV header: %v", ErrInvalidInput, err)
	}
	cols := map[string]int{}
	for i, h := range header {
		cols[strings.ToLower(strings.TrimSpace(h))] = i
	}
	if _, ok := cols["school_id"]; !ok {
		return SSACSVPreview{}, fmt.Errorf("%w: missing required school_id column", ErrInvalidInput)
	}
	out := SSACSVPreview{Rejected: map[int]string{}}
	seen := map[string]bool{}
	rowNum := 1
	for {
		rec, err := cr.Read()
		if errors.Is(err, io.EOF) {
			break
		}
		rowNum++
		if err != nil {
			out.Rejected[rowNum] = err.Error()
			continue
		}
		schoolID := strings.TrimSpace(rec[cols["school_id"]])
		if schoolID == "" {
			out.Rejected[rowNum] = "missing school_id"
			continue
		}
		if seen[schoolID] {
			out.Duplicate = append(out.Duplicate, rowNum)
			continue
		}
		seen[schoolID] = true
		var scores []SSAScoreInput
		bad := ""
		for name, idx := range cols {
			if !strings.HasPrefix(name, "score_") || idx >= len(rec) {
				continue
			}
			raw := strings.TrimSpace(rec[idx])
			if raw == "" {
				continue
			}
			v, perr := strconv.ParseFloat(raw, 64)
			if perr != nil || v < 0 || v > 5 {
				bad = fmt.Sprintf("invalid %s=%q", name, raw)
				break
			}
			scores = append(scores, SSAScoreInput{Intervention: strings.TrimPrefix(name, "score_"), Score: v})
		}
		if bad != "" {
			out.Rejected[rowNum] = bad
			continue
		}
		if len(scores) == 0 {
			out.Rejected[rowNum] = "no score_* columns present"
			continue
		}
		out.Valid = append(out.Valid, SSAEntryRequest{
			SchoolID: schoolID, FY: fy, Quarter: "Q1", Date: time.Now().UTC(),
			Scores: scores, CollectorType: "staff",
		})
	}
	return out, nil
}

// ── M10: Partner Handover, Dating, and Return ───────────────────────────────

func (s *Service) HandOverToPartner(ctx context.Context, p auth.Principal, partnerID, schoolID, purpose, intervention, activityType, notes string) (string, error) {
	if p.ActiveRole != "CCEO" && p.ActiveRole != "Program Lead" && p.ActiveRole != "Admin" {
		return "", fmt.Errorf("%w: staff planning role required", ErrForbidden)
	}
	if strings.TrimSpace(partnerID) == "" || strings.TrimSpace(schoolID) == "" {
		return "", fmt.Errorf("%w: partner_id and school_id are required", ErrInvalidInput)
	}
	staffID := p.StaffProfileID
	if staffID == "" {
		staffID = p.UserID
	}
	var id string
	err := withRW(ctx, s.pool, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx,
			`SELECT gateway_field_ops.create_partner_assignment($1,$2,$3,$4,$5,$6,$7)`,
			partnerID, schoolID, staffID, purpose, intervention, activityType, notes).Scan(&id)
	})
	return id, err
}

func (s *Service) DatePartnerAssignment(ctx context.Context, p auth.Principal, assignmentID string, date time.Time) (string, error) {
	if strings.TrimSpace(assignmentID) == "" || date.IsZero() {
		return "", fmt.Errorf("%w: assignment_id and date are required", ErrInvalidInput)
	}
	var status string
	err := withRW(ctx, s.pool, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx,
			`SELECT gateway_field_ops.update_partner_assignment($1,'date',$2::date,$3,'')`,
			assignmentID, date.Format("2006-01-02"), p.UserID).Scan(&status)
	})
	return status, err
}

func (s *Service) ReturnPartnerAssignment(ctx context.Context, p auth.Principal, assignmentID, reason string) (string, error) {
	if strings.TrimSpace(assignmentID) == "" || strings.TrimSpace(reason) == "" {
		return "", fmt.Errorf("%w: assignment_id and return reason are required", ErrInvalidInput)
	}
	var status string
	err := withRW(ctx, s.pool, func(tx pgx.Tx) error {
		return tx.QueryRow(ctx,
			`SELECT gateway_field_ops.update_partner_assignment($1,'return',NULL,$2,$3)`,
			assignmentID, p.UserID, strings.TrimSpace(reason)).Scan(&status)
	})
	return status, err
}
