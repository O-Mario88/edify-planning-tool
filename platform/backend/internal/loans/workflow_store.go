package loans

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

// Assignment is who works a case, and since when.
type Assignment struct {
	ID, OfficerUserID, OfficerName, AssignedByName, EndReason string
	AssignedAt                                                time.Time
	EndedAt                                                   *time.Time
}

// Contact is one recorded contact attempt.
type Contact struct {
	ID, OfficerName, Method, Outcome, Notes string
	ContactedOn                             time.Time
	VisitOn, NextActionOn                   *time.Time
	CreatedAt                               time.Time
}

// Assessment is the officer's school assessment.
type Assessment struct {
	ID, Status                                                 string
	VisitOn                                                    *time.Time
	Facts                                                      map[string]string
	Observations, Strengths, Risks, DocumentsReviewed, Outcome string
	UpdatedAt                                                  time.Time
	SubmittedAt                                                *time.Time
}

// Recommendation is one version of the officer's credit recommendation.
type Recommendation struct {
	ID                                   string
	Version                              int
	Amount                               ledger.Money
	Capacity                             *ledger.Money
	RatePercent, Method                  string
	Fee                                  ledger.Money
	DueDates                             []time.Time
	CollateralSummary, Rationale         string
	Affordability                        map[string]string
	Status, SubmittedBy, SubmittedByName string
	SubmittedAt                          *time.Time
}

// Terms builds the recommendation's ledger terms.
func (r Recommendation) Terms() (ledger.Terms, error) {
	rate, err := ledger.ParseRate(r.RatePercent)
	if err != nil {
		return ledger.Terms{}, err
	}
	return ledger.Terms{Principal: r.Amount, Rate: rate, Method: ledger.Method(r.Method), FeePerInstallment: r.Fee, DueDates: r.DueDates}, nil
}

// AgreementTerms is the frozen copy of what a school is asked to agree to.
type AgreementTerms struct {
	Reference, School, Lender, Purpose     string
	Principal, TotalInterest, TotalFees    string
	TotalRepayable                         string
	RatePercent, Method, MethodDescription string
	Installments                           []TermInstallment
	Collateral                             string
	Conditions                             []string
	IssuedOn                               string
}

// TermInstallment is one installment of the proposed schedule.
type TermInstallment struct {
	Number                                   int
	DueDate, Principal, Interest, Fee, Total string
}

// Agreement is one issued version of the proposed terms.
type Agreement struct {
	ID, RecommendationID string
	Version              int
	Terms                AgreementTerms
	Hash, Status         string
	IssuedByName         string
	IssuedAt             time.Time
	RespondedAt          *time.Time
	ResponseNote         string
	Verification         map[string]string
}

// Decision is a credit approver's decision.
type Decision struct {
	ID, RecommendationID, Decision, Rationale, DecidedBy, DecidedByName string
	ApprovedAmount                                                      *ledger.Money
	ConditionsConfirmed                                                 bool
	DecidedAt                                                           time.Time
}

// Collateral is one security item with its history.
type Collateral struct {
	ID, ItemType, Description, DeclaredOwner, Identification, ValueSource, DocumentType string
	Custodian, Status, ReleaseConditions, ReleasedTo                                    string
	EstimatedValue                                                                      *ledger.Money
	ValueDate, ReleasedOn                                                               *time.Time
	Events                                                                              []CollateralEvent
}

// CollateralEvent is one change of a collateral item's status.
type CollateralEvent struct {
	FromStatus, ToStatus, Note, ActorName, DocumentID, Acknowledgment string
	At                                                                time.Time
}

// Evidence is a payment as reported, before and after verification.
type Evidence struct {
	ID, MFILoanID, Method, Reference, ReceivedBy, Notes, DocumentID, Source, Status string
	SubmittedByName, VerifiedByName, RejectionReason, LedgerTransactionID           string
	Amount, Excess                                                                  ledger.Money
	Applied                                                                         *ledger.Money
	PaidOn, SubmittedAt                                                             time.Time
	VerifiedAt                                                                      *time.Time
	SubmittedBy                                                                     string
}

// DocumentMeta is a stored document without its bytes.
type DocumentMeta struct {
	ID, Kind, FileName, ContentType, UploadedByKind string
	Size                                            int
	CreatedAt                                       time.Time
}

// SchoolRequest is a request a school sent from its statement.
type SchoolRequest struct {
	ID, Kind, Message, Status, Answer string
	CreatedAt                         time.Time
}

// CaseRecord is everything the workflow holds for one application.
type CaseRecord struct {
	Referral        Referral
	LedgerReferral  string
	ClosureStatus   string
	ClosureNote     string
	Assignment      *Assignment
	Assignments     []Assignment
	Contacts        []Contact
	Assessment      *Assessment
	Recommendations []Recommendation
	Agreements      []Agreement
	Decisions       []Decision
	Collateral      []Collateral
	Evidence        []Evidence
	Documents       []DocumentMeta
	Requests        []SchoolRequest
}

// LatestRecommendation is the newest version, or nil.
func (c CaseRecord) LatestRecommendation() *Recommendation {
	if len(c.Recommendations) == 0 {
		return nil
	}
	return &c.Recommendations[len(c.Recommendations)-1]
}

// LatestAgreement is the newest version, or nil.
func (c CaseRecord) LatestAgreement() *Agreement {
	if len(c.Agreements) == 0 {
		return nil
	}
	return &c.Agreements[len(c.Agreements)-1]
}

// LatestDecision is the newest decision, or nil.
func (c CaseRecord) LatestDecision() *Decision {
	if len(c.Decisions) == 0 {
		return nil
	}
	return &c.Decisions[len(c.Decisions)-1]
}

func dates(raw []time.Time) []time.Time {
	out := make([]time.Time, len(raw))
	for index, d := range raw {
		out[index] = ledger.DayOf(d)
	}
	return out
}

// CaseRecord reads a case. partnerID, when set, confines it to that lender.
func (s *Store) CaseRecord(ctx context.Context, applicationID, partnerID string) (CaseRecord, error) {
	var record CaseRecord
	referral, err := s.Referral(ctx, applicationID, partnerID)
	if err != nil {
		return record, err
	}
	record.Referral = referral
	if err := s.db.QueryRow(ctx, `SELECT ledger_referral_id, closure_status, closure_note FROM school_loans.application WHERE id = $1`,
		applicationID).Scan(&record.LedgerReferral, &record.ClosureStatus, &record.ClosureNote); err != nil {
		return record, err
	}
	queries := []func() error{
		func() error {
			rows, err := s.db.Query(ctx, `
SELECT id, officer_user_id, officer_name, assigned_by_name, end_reason, assigned_at, ended_at
FROM school_loans.assignment WHERE application_id = $1 ORDER BY assigned_at`, applicationID)
			if err != nil {
				return err
			}
			defer rows.Close()
			for rows.Next() {
				var a Assignment
				if err := rows.Scan(&a.ID, &a.OfficerUserID, &a.OfficerName, &a.AssignedByName, &a.EndReason, &a.AssignedAt, &a.EndedAt); err != nil {
					return err
				}
				record.Assignments = append(record.Assignments, a)
				if a.EndedAt == nil {
					current := a
					record.Assignment = &current
				}
			}
			return rows.Err()
		},
		func() error {
			rows, err := s.db.Query(ctx, `
SELECT id, officer_name, method, outcome, notes, contacted_on, visit_on, next_action_on, created_at
FROM school_loans.contact_log WHERE application_id = $1 ORDER BY created_at`, applicationID)
			if err != nil {
				return err
			}
			defer rows.Close()
			for rows.Next() {
				var c Contact
				if err := rows.Scan(&c.ID, &c.OfficerName, &c.Method, &c.Outcome, &c.Notes, &c.ContactedOn, &c.VisitOn,
					&c.NextActionOn, &c.CreatedAt); err != nil {
					return err
				}
				record.Contacts = append(record.Contacts, c)
			}
			return rows.Err()
		},
		func() error {
			var a Assessment
			var facts []byte
			err := s.db.QueryRow(ctx, `
SELECT id, status, visit_on, facts, observations, strengths, risks, documents_reviewed, outcome, updated_at, submitted_at
FROM school_loans.assessment WHERE application_id = $1`, applicationID).Scan(&a.ID, &a.Status, &a.VisitOn, &facts,
				&a.Observations, &a.Strengths, &a.Risks, &a.DocumentsReviewed, &a.Outcome, &a.UpdatedAt, &a.SubmittedAt)
			if errors.Is(err, pgx.ErrNoRows) {
				return nil
			}
			if err != nil {
				return err
			}
			_ = json.Unmarshal(facts, &a.Facts)
			record.Assessment = &a
			return nil
		},
		func() error {
			rows, err := s.db.Query(ctx, `
SELECT id, version, recommended_amount::text, repayment_capacity_per_term::text, rate_percent, interest_method,
  fee_per_installment::text, due_dates, collateral_summary, rationale, affordability, status, submitted_by,
  submitted_by_name, submitted_at
FROM school_loans.recommendation WHERE application_id = $1 ORDER BY version`, applicationID)
			if err != nil {
				return err
			}
			defer rows.Close()
			for rows.Next() {
				var r Recommendation
				var amount, fee string
				var capacity *string
				var affordability []byte
				if err := rows.Scan(&r.ID, &r.Version, &amount, &capacity, &r.RatePercent, &r.Method, &fee, &r.DueDates,
					&r.CollateralSummary, &r.Rationale, &affordability, &r.Status, &r.SubmittedBy, &r.SubmittedByName,
					&r.SubmittedAt); err != nil {
					return err
				}
				r.Amount, r.Fee = money(&amount), money(&fee)
				if capacity != nil {
					c := money(capacity)
					r.Capacity = &c
				}
				r.DueDates = dates(r.DueDates)
				_ = json.Unmarshal(affordability, &r.Affordability)
				record.Recommendations = append(record.Recommendations, r)
			}
			return rows.Err()
		},
		func() error {
			rows, err := s.db.Query(ctx, `
SELECT id, recommendation_id, version, terms, terms_hash, status, issued_by_name, issued_at, responded_at,
  response_note, verification
FROM school_loans.agreement_version WHERE application_id = $1 ORDER BY version`, applicationID)
			if err != nil {
				return err
			}
			defer rows.Close()
			for rows.Next() {
				var a Agreement
				var terms, verification []byte
				if err := rows.Scan(&a.ID, &a.RecommendationID, &a.Version, &terms, &a.Hash, &a.Status, &a.IssuedByName,
					&a.IssuedAt, &a.RespondedAt, &a.ResponseNote, &verification); err != nil {
					return err
				}
				_ = json.Unmarshal(terms, &a.Terms)
				_ = json.Unmarshal(verification, &a.Verification)
				record.Agreements = append(record.Agreements, a)
			}
			return rows.Err()
		},
		func() error {
			rows, err := s.db.Query(ctx, `
SELECT id, recommendation_id, decision, rationale, decided_by, decided_by_name, approved_amount::text, conditions_confirmed, decided_at
FROM school_loans.approval_decision WHERE application_id = $1 ORDER BY decided_at`, applicationID)
			if err != nil {
				return err
			}
			defer rows.Close()
			for rows.Next() {
				var d Decision
				var approved *string
				if err := rows.Scan(&d.ID, &d.RecommendationID, &d.Decision, &d.Rationale, &d.DecidedBy, &d.DecidedByName, &approved,
					&d.ConditionsConfirmed, &d.DecidedAt); err != nil {
					return err
				}
				if approved != nil {
					m := money(approved)
					d.ApprovedAmount = &m
				}
				record.Decisions = append(record.Decisions, d)
			}
			return rows.Err()
		},
		func() error { return s.readCollateral(ctx, applicationID, &record) },
		func() error {
			rows, err := s.db.Query(ctx, `
SELECT id, mfi_loan_id, method, transaction_reference, received_by, notes, COALESCE(document_id::text, ''), source,
  status, submitted_by, submitted_by_name, verified_by_name, rejection_reason, ledger_transaction_id, amount::text,
  excess_amount::text, applied_amount::text, paid_on, submitted_at, verified_at
FROM school_loans.payment_evidence WHERE application_id = $1 ORDER BY submitted_at`, applicationID)
			if err != nil {
				return err
			}
			defer rows.Close()
			for rows.Next() {
				var e Evidence
				var amount, excess string
				var applied *string
				if err := rows.Scan(&e.ID, &e.MFILoanID, &e.Method, &e.Reference, &e.ReceivedBy, &e.Notes, &e.DocumentID,
					&e.Source, &e.Status, &e.SubmittedBy, &e.SubmittedByName, &e.VerifiedByName, &e.RejectionReason,
					&e.LedgerTransactionID, &amount, &excess, &applied, &e.PaidOn, &e.SubmittedAt, &e.VerifiedAt); err != nil {
					return err
				}
				e.Amount, e.Excess = money(&amount), money(&excess)
				if applied != nil {
					m := money(applied)
					e.Applied = &m
				}
				record.Evidence = append(record.Evidence, e)
			}
			return rows.Err()
		},
		func() error {
			rows, err := s.db.Query(ctx, `
SELECT id, kind, file_name, content_type, uploaded_by_kind, size_bytes, created_at
FROM school_loans.document WHERE application_id = $1 ORDER BY created_at`, applicationID)
			if err != nil {
				return err
			}
			defer rows.Close()
			for rows.Next() {
				var d DocumentMeta
				if err := rows.Scan(&d.ID, &d.Kind, &d.FileName, &d.ContentType, &d.UploadedByKind, &d.Size, &d.CreatedAt); err != nil {
					return err
				}
				record.Documents = append(record.Documents, d)
			}
			return rows.Err()
		},
		func() error {
			rows, err := s.db.Query(ctx, `
SELECT id, kind, message, status, answer, created_at FROM school_loans.school_request
WHERE application_id = $1 ORDER BY created_at`, applicationID)
			if err != nil {
				return err
			}
			defer rows.Close()
			for rows.Next() {
				var r SchoolRequest
				if err := rows.Scan(&r.ID, &r.Kind, &r.Message, &r.Status, &r.Answer, &r.CreatedAt); err != nil {
					return err
				}
				record.Requests = append(record.Requests, r)
			}
			return rows.Err()
		},
	}
	for _, query := range queries {
		if err := query(); err != nil {
			return record, fmt.Errorf("loans: reading a case: %w", err)
		}
	}
	return record, nil
}

func (s *Store) readCollateral(ctx context.Context, applicationID string, record *CaseRecord) error {
	rows, err := s.db.Query(ctx, `
SELECT id, item_type, description, declared_owner, identification, value_source, document_type, custodian, status,
  release_conditions, released_to, estimated_value::text, value_date, released_on
FROM school_loans.collateral WHERE application_id = $1 ORDER BY created_at`, applicationID)
	if err != nil {
		return err
	}
	var items []Collateral
	for rows.Next() {
		var c Collateral
		var value *string
		if err := rows.Scan(&c.ID, &c.ItemType, &c.Description, &c.DeclaredOwner, &c.Identification, &c.ValueSource,
			&c.DocumentType, &c.Custodian, &c.Status, &c.ReleaseConditions, &c.ReleasedTo, &value, &c.ValueDate,
			&c.ReleasedOn); err != nil {
			rows.Close()
			return err
		}
		if value != nil {
			m := money(value)
			c.EstimatedValue = &m
		}
		items = append(items, c)
	}
	rows.Close()
	for index := range items {
		events, err := s.db.Query(ctx, `
SELECT from_status, to_status, note, actor_name, COALESCE(document_id::text, ''), recipient_acknowledgment, created_at
FROM school_loans.collateral_event WHERE collateral_id = $1 ORDER BY created_at`, items[index].ID)
		if err != nil {
			return err
		}
		for events.Next() {
			var e CollateralEvent
			if err := events.Scan(&e.FromStatus, &e.ToStatus, &e.Note, &e.ActorName, &e.DocumentID, &e.Acknowledgment, &e.At); err != nil {
				events.Close()
				return err
			}
			items[index].Events = append(items[index].Events, e)
		}
		events.Close()
	}
	record.Collateral = items
	return nil
}

// Assign makes officer the case's officer, ending the current assignment.
func (s *Store) Assign(ctx context.Context, applicationID, officerID, officerName, byID, byName, reason string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `
UPDATE school_loans.assignment SET ended_at = $2, end_reason = $3 WHERE application_id = $1 AND ended_at IS NULL`,
			applicationID, now, reason); err != nil {
			return err
		}
		id, err := NewID()
		if err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
INSERT INTO school_loans.assignment (id, application_id, officer_user_id, officer_name, assigned_by, assigned_by_name, assigned_at)
VALUES ($1, $2, $3, $4, $5, $6, $7)`, id, applicationID, officerID, officerName, byID, byName, now); err != nil {
			return err
		}
		return appendEvent(ctx, tx, Event{ApplicationID: applicationID, Kind: "assigned", ActorKind: "lender",
			ActorID: byID, ActorName: byName, Note: "Assigned to " + officerName + ". " + reason})
	})
}

// AddContact records a contact attempt.
func (s *Store) AddContact(ctx context.Context, applicationID string, c Contact, officerID string) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		id, err := NewID()
		if err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `
INSERT INTO school_loans.contact_log (id, application_id, officer_user_id, officer_name, contacted_on, method, outcome,
  notes, visit_on, next_action_on, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)`, id, applicationID, officerID, c.OfficerName, c.ContactedOn,
			c.Method, c.Outcome, c.Notes, c.VisitOn, c.NextActionOn, c.CreatedAt)
		return err
	})
}

// SaveAssessment stores the assessment and its history entry.
func (s *Store) SaveAssessment(ctx context.Context, applicationID string, a Assessment, actorID, actorName, note string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		facts, _ := json.Marshal(a.Facts)
		var from string
		err := tx.QueryRow(ctx, `SELECT status FROM school_loans.assessment WHERE application_id = $1 FOR UPDATE`, applicationID).Scan(&from)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		var submitted *time.Time
		if a.Status == "submitted" {
			submitted = &now
		}
		id := a.ID
		if errors.Is(err, pgx.ErrNoRows) {
			if id, err = NewID(); err != nil {
				return err
			}
			if _, err := tx.Exec(ctx, `
INSERT INTO school_loans.assessment (id, application_id, status, visit_on, facts, observations, strengths, risks,
  documents_reviewed, outcome, updated_by, updated_at, submitted_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)`, id, applicationID, a.Status, a.VisitOn, facts,
				a.Observations, a.Strengths, a.Risks, a.DocumentsReviewed, a.Outcome, actorID, now, submitted); err != nil {
				return err
			}
		} else {
			if err := tx.QueryRow(ctx, `
UPDATE school_loans.assessment SET status = $2, visit_on = $3, facts = $4, observations = $5, strengths = $6,
  risks = $7, documents_reviewed = $8, outcome = $9, updated_by = $10, updated_at = $11,
  submitted_at = COALESCE($12, submitted_at)
WHERE application_id = $1 RETURNING id`, applicationID, a.Status, a.VisitOn, facts, a.Observations, a.Strengths,
				a.Risks, a.DocumentsReviewed, a.Outcome, actorID, now, submitted).Scan(&id); err != nil {
				return err
			}
		}
		snapshot, _ := json.Marshal(a)
		eventID, err := NewID()
		if err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `
INSERT INTO school_loans.assessment_event (id, assessment_id, from_status, to_status, snapshot, actor_id, actor_name, note)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`, eventID, id, from, a.Status, snapshot, actorID, actorName, note)
		return err
	})
}

// AddRecommendation stores a new version; earlier draft or returned
// versions are superseded, never edited.
func (s *Store) AddRecommendation(ctx context.Context, applicationID string, r Recommendation, now time.Time) (Recommendation, error) {
	err := s.inWrite(ctx, func(tx pgx.Tx) error {
		if err := tx.QueryRow(ctx, `SELECT COALESCE(max(version), 0) + 1 FROM school_loans.recommendation WHERE application_id = $1`,
			applicationID).Scan(&r.Version); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
UPDATE school_loans.recommendation SET status = 'superseded'
WHERE application_id = $1 AND status IN ('draft', 'returned', 'submitted')`, applicationID); err != nil {
			return err
		}
		var err error
		if r.ID, err = NewID(); err != nil {
			return err
		}
		affordability, _ := json.Marshal(r.Affordability)
		var capacity *string
		if r.Capacity != nil {
			text := r.Capacity.String()
			capacity = &text
		}
		if r.Status == "submitted" {
			r.SubmittedAt = &now
		}
		_, err = tx.Exec(ctx, `
INSERT INTO school_loans.recommendation (id, application_id, version, recommended_amount, repayment_capacity_per_term,
  rate_percent, interest_method, fee_per_installment, due_dates, collateral_summary, rationale, affordability, status,
  submitted_by, submitted_by_name, submitted_at, created_at)
VALUES ($1, $2, $3, $4::numeric, $5::numeric, $6, $7, $8::numeric, $9, $10, $11, $12, $13, $14, $15, $16, $17)`,
			r.ID, applicationID, r.Version, r.Amount.String(), capacity, r.RatePercent, r.Method, r.Fee.String(), r.DueDates,
			r.CollateralSummary, r.Rationale, affordability, r.Status, r.SubmittedBy, r.SubmittedByName, r.SubmittedAt, now)
		if err != nil {
			return err
		}
		return appendEvent(ctx, tx, Event{ApplicationID: applicationID, Kind: "recommendation_" + r.Status, ActorKind: "lender",
			ActorID: r.SubmittedBy, ActorName: r.SubmittedByName,
			Note: fmt.Sprintf("Recommendation version %d: %s.", r.Version, ledger.FormatUGX(r.Amount))})
	})
	return r, err
}

// IssueAgreement freezes the recommendation's terms as a new agreement
// version, superseding any earlier version still awaiting the school.
func (s *Store) IssueAgreement(ctx context.Context, applicationID, recommendationID string, terms AgreementTerms, byID, byName string, now time.Time) (Agreement, error) {
	a := Agreement{RecommendationID: recommendationID, Terms: terms, Status: "issued", IssuedByName: byName, IssuedAt: now}
	raw, err := json.Marshal(terms)
	if err != nil {
		return a, err
	}
	sum := sha256.Sum256(raw)
	a.Hash = hex.EncodeToString(sum[:])
	err = s.inWrite(ctx, func(tx pgx.Tx) error {
		if err := tx.QueryRow(ctx, `SELECT COALESCE(max(version), 0) + 1 FROM school_loans.agreement_version WHERE application_id = $1`,
			applicationID).Scan(&a.Version); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
UPDATE school_loans.agreement_version SET status = 'superseded'
WHERE application_id = $1 AND status IN ('issued', 'clarification_requested')`, applicationID); err != nil {
			return err
		}
		var err error
		if a.ID, err = NewID(); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
INSERT INTO school_loans.agreement_version (id, application_id, recommendation_id, version, terms, terms_hash, status,
  issued_by, issued_by_name, issued_at)
VALUES ($1, $2, $3, $4, $5, $6, 'issued', $7, $8, $9)`, a.ID, applicationID, recommendationID, a.Version, raw, a.Hash,
			byID, byName, now); err != nil {
			return err
		}
		return appendEvent(ctx, tx, Event{ApplicationID: applicationID, Kind: "agreement_issued", ActorKind: "lender",
			ActorID: byID, ActorName: byName, Note: fmt.Sprintf("Proposed terms version %d sent to the school.", a.Version)})
	})
	return a, err
}

// RespondToAgreement records the school's answer to an agreement version.
// It must still be the version awaiting an answer, and the terms hash the
// school saw must be that version's.
func (s *Store) RespondToAgreement(ctx context.Context, applicationID, agreementID, hash, response, note string, verification map[string]string, now time.Time) error {
	raw, _ := json.Marshal(verification)
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `
UPDATE school_loans.agreement_version SET status = $4, response_note = $5, responded_at = $6, verification = $7
WHERE id = $1 AND application_id = $2 AND terms_hash = $3 AND status = 'issued'`,
			agreementID, applicationID, hash, response, note, now, raw)
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			return need("agreement", "These terms are no longer the ones awaiting your answer. Open the newest link from your lender.")
		}
		labels := map[string]string{"accepted": "accepted", "declined": "declined", "clarification_requested": "asked for clarification on"}
		return appendEvent(ctx, tx, Event{ApplicationID: applicationID, Kind: "agreement_" + response, ActorKind: "applicant",
			ActorName: "The school (verified)", Note: "The school " + labels[response] + " the proposed terms. " + note})
	})
}

// RecordDecision stores the credit approver's decision and marks the
// recommendation with it.
func (s *Store) RecordDecision(ctx context.Context, applicationID string, d Decision, agreementID, byID string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		id, err := NewID()
		if err != nil {
			return err
		}
		var approved *string
		if d.ApprovedAmount != nil {
			text := d.ApprovedAmount.String()
			approved = &text
		}
		var agreement *string
		if agreementID != "" {
			agreement = &agreementID
		}
		if _, err := tx.Exec(ctx, `
INSERT INTO school_loans.approval_decision (id, application_id, recommendation_id, agreement_version_id, decision,
  approved_amount, rationale, conditions_confirmed, decided_by, decided_by_name, decided_at)
VALUES ($1, $2, $3, $4, $5, $6::numeric, $7, $8, $9, $10, $11)`, id, applicationID, d.RecommendationID, agreement,
			d.Decision, approved, d.Rationale, d.ConditionsConfirmed, byID, d.DecidedByName, now); err != nil {
			return err
		}
		status := map[string]string{"approved": "approved", "declined": "declined", "returned": "returned"}[d.Decision]
		if _, err := tx.Exec(ctx, `UPDATE school_loans.recommendation SET status = $2 WHERE id = $1`, d.RecommendationID, status); err != nil {
			return err
		}
		return appendEvent(ctx, tx, Event{ApplicationID: applicationID, Kind: "credit_" + d.Decision, ActorKind: "lender",
			ActorID: byID, ActorName: d.DecidedByName, Note: d.Rationale})
	})
}

// AddCollateral records a proposed collateral item.
func (s *Store) AddCollateral(ctx context.Context, applicationID string, c Collateral, byID, byName string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		id, err := NewID()
		if err != nil {
			return err
		}
		var value *string
		if c.EstimatedValue != nil {
			text := c.EstimatedValue.String()
			value = &text
		}
		if _, err := tx.Exec(ctx, `
INSERT INTO school_loans.collateral (id, application_id, item_type, description, declared_owner, identification,
  estimated_value, value_date, value_source, document_type, custodian, status, release_conditions, created_by, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7::numeric, $8, $9, $10, $11, 'proposed', $12, $13, $14, $14)`, id, applicationID,
			c.ItemType, c.Description, c.DeclaredOwner, c.Identification, value, c.ValueDate, c.ValueSource, c.DocumentType,
			c.Custodian, c.ReleaseConditions, byID, now); err != nil {
			return err
		}
		return collateralEvent(ctx, tx, id, "", "proposed", "Recorded.", "", "", byID, byName)
	})
}

func collateralEvent(ctx context.Context, tx pgx.Tx, collateralID, from, to, note, documentID, ack, byID, byName string) error {
	id, err := NewID()
	if err != nil {
		return err
	}
	var document *string
	if documentID != "" {
		document = &documentID
	}
	_, err = tx.Exec(ctx, `
INSERT INTO school_loans.collateral_event (id, collateral_id, from_status, to_status, note, document_id,
  recipient_acknowledgment, actor_id, actor_name)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`, id, collateralID, from, to, note, document, ack, byID, byName)
	return err
}

// SetCollateralStatus moves an item on, with its history; a release
// records when and to whom.
func (s *Store) SetCollateralStatus(ctx context.Context, applicationID, collateralID, to, note, documentID, releasedTo, ack string, releasedOn *time.Time, byID, byName string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		var from string
		err := tx.QueryRow(ctx, `SELECT status FROM school_loans.collateral WHERE id = $1 AND application_id = $2 FOR UPDATE`,
			collateralID, applicationID).Scan(&from)
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrNotFound
		}
		if err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
UPDATE school_loans.collateral SET status = $2, updated_at = $3,
  released_on = CASE WHEN $2 = 'released' THEN $4 ELSE released_on END,
  released_to = CASE WHEN $2 = 'released' THEN $5 ELSE released_to END
WHERE id = $1`, collateralID, to, now, releasedOn, releasedTo); err != nil {
			return err
		}
		return collateralEvent(ctx, tx, collateralID, from, to, note, documentID, ack, byID, byName)
	})
}

// Document limits.
const maxDocumentBytes = 5 << 20

// StoreDocument keeps an uploaded file, checking it is what it claims to be.
func (s *Store) StoreDocument(ctx context.Context, applicationID, kind, fileName string, content []byte, byID, byKind string) (string, error) {
	contentType, err := sniffDocument(content)
	if err != nil {
		return "", err
	}
	if len(content) > maxDocumentBytes {
		return "", need("file", "The file is larger than 5 MB.")
	}
	sum := sha256.Sum256(content)
	id, err := NewID()
	if err != nil {
		return "", err
	}
	err = s.inWrite(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `
INSERT INTO school_loans.document (id, application_id, kind, file_name, content_type, size_bytes, sha256, content,
  uploaded_by, uploaded_by_kind)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`, id, applicationID, kind, cleanFileName(fileName), contentType,
			len(content), hex.EncodeToString(sum[:]), content, byID, byKind)
		return err
	})
	return id, err
}

// Document is one stored document with its bytes, confined to an application.
func (s *Store) Document(ctx context.Context, applicationID, documentID string) (DocumentMeta, []byte, error) {
	var d DocumentMeta
	var content []byte
	err := s.db.QueryRow(ctx, `
SELECT id, kind, file_name, content_type, uploaded_by_kind, size_bytes, created_at, content
FROM school_loans.document WHERE id = $1 AND application_id = $2`, documentID, applicationID).
		Scan(&d.ID, &d.Kind, &d.FileName, &d.ContentType, &d.UploadedByKind, &d.Size, &d.CreatedAt, &content)
	if errors.Is(err, pgx.ErrNoRows) {
		return d, nil, ErrNotFound
	}
	return d, content, err
}

// SubmitEvidence records a reported payment as pending verification. The
// same idempotency key twice is the same submission.
// SubmitEvidence records a reported payment as awaiting verification. The
// same submission sent twice is stored once; already says it was.
func (s *Store) SubmitEvidence(ctx context.Context, applicationID string, e Evidence, key string, now time.Time) (id string, already bool, err error) {
	err = s.inWrite(ctx, func(tx pgx.Tx) error {
		err := tx.QueryRow(ctx, `SELECT id FROM school_loans.payment_evidence WHERE idempotency_key = $1`, key).Scan(&id)
		if err == nil {
			already = true
			return nil
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		if id, err = NewID(); err != nil {
			return err
		}
		var document *string
		if e.DocumentID != "" {
			document = &e.DocumentID
		}
		_, err = tx.Exec(ctx, `
INSERT INTO school_loans.payment_evidence (id, application_id, mfi_loan_id, idempotency_key, amount, paid_on, method,
  transaction_reference, received_by, notes, document_id, source, submitted_by, submitted_by_name, submitted_at)
VALUES ($1, $2, $3, $4, $5::numeric, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)`, id, applicationID, e.MFILoanID, key,
			e.Amount.String(), e.PaidOn, e.Method, e.Reference, e.ReceivedBy, e.Notes, document, e.Source, e.SubmittedBy,
			e.SubmittedByName, now)
		if isUniqueViolation(err, "payment_evidence_reference") {
			return need("reference", "A payment with this transaction reference is already recorded for this loan.")
		}
		if err != nil {
			return err
		}
		return evidenceEvent(ctx, tx, id, "verification_pending", "Payment recorded; awaiting the lender's verification.",
			e.SubmittedBy, e.SubmittedByName)
	})
	return id, already, err
}

func evidenceEvent(ctx context.Context, tx pgx.Tx, evidenceID, to, note, byID, byName string) error {
	id, err := NewID()
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `
INSERT INTO school_loans.payment_evidence_event (id, payment_evidence_id, to_status, note, actor_id, actor_name)
VALUES ($1, $2, $3, $4, $5, $6)`, id, evidenceID, to, note, byID, byName)
	return err
}

// MarkEvidenceVerified records that the payment was verified and posted to
// the ledger as transactionID, with what was applied and any excess.
func (s *Store) MarkEvidenceVerified(ctx context.Context, applicationID, evidenceID, transactionID string, applied, excess ledger.Money, byID, byName string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `
UPDATE school_loans.payment_evidence SET status = 'verified', verified_by = $3, verified_by_name = $4, verified_at = $5,
  ledger_transaction_id = $6, applied_amount = $7::numeric, excess_amount = $8::numeric
WHERE id = $1 AND application_id = $2 AND status = 'verification_pending'`, evidenceID, applicationID, byID, byName, now,
			transactionID, applied.String(), excess.String())
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			return need("payment", "This payment is no longer awaiting verification.")
		}
		note := "Verified and posted to the loan ledger (" + ledger.FormatUGX(applied) + ")."
		if excess > 0 {
			note += " " + ledger.FormatUGX(excess) + " was more than the loan owed and is held as an overpayment for the lender to settle."
		}
		return evidenceEvent(ctx, tx, evidenceID, "verified", note, byID, byName)
	})
}

// RejectEvidence records that the lender could not verify the payment.
func (s *Store) RejectEvidence(ctx context.Context, applicationID, evidenceID, reason, byID, byName string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `
UPDATE school_loans.payment_evidence SET status = 'rejected', verified_by = $3, verified_by_name = $4, verified_at = $5,
  rejection_reason = $6
WHERE id = $1 AND application_id = $2 AND status = 'verification_pending'`, evidenceID, applicationID, byID, byName, now, reason)
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			return need("payment", "This payment is no longer awaiting verification.")
		}
		return evidenceEvent(ctx, tx, evidenceID, "rejected", reason, byID, byName)
	})
}

// SetLedgerReferral records the referral the application became in the ledger.
func (s *Store) SetLedgerReferral(ctx context.Context, applicationID, referralID, byID, byName string) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `UPDATE school_loans.application SET ledger_referral_id = $2 WHERE id = $1`, applicationID, referralID); err != nil {
			return err
		}
		return appendEvent(ctx, tx, Event{ApplicationID: applicationID, Kind: "ledger_referral", ActorKind: "staff",
			ActorID: byID, ActorName: byName, Note: "Referred in the loan ledger (" + referralID + ")."})
	})
}

// SetLedgerLoan records the loan the lender registered for the application.
func (s *Store) SetLedgerLoan(ctx context.Context, applicationID, loanID, byID, byName string) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `UPDATE school_loans.application SET linked_mfi_loan_id = $2 WHERE id = $1`, applicationID, loanID); err != nil {
			return err
		}
		return appendEvent(ctx, tx, Event{ApplicationID: applicationID, Kind: "loan_linked", ActorKind: "lender",
			ActorID: byID, ActorName: byName, Note: "Registered in the loan ledger (" + loanID + ")."})
	})
}

// Close records the loan's closure; it never deletes anything.
func (s *Store) Close(ctx context.Context, applicationID, status, note, byID, byName string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `
UPDATE school_loans.application SET closure_status = $2, closure_note = $3, closed_at = $4, updated_at = $4 WHERE id = $1`,
			applicationID, status, note, now); err != nil {
			return err
		}
		return appendEvent(ctx, tx, Event{ApplicationID: applicationID, Kind: "loan_" + status, ActorKind: "lender",
			ActorID: byID, ActorName: byName, Note: note})
	})
}

// AnswerSchoolRequest records the lender's answer to a school's request.
func (s *Store) AnswerSchoolRequest(ctx context.Context, applicationID, requestID, answer, byName string, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `
UPDATE school_loans.school_request SET status = 'answered', answer = $3, answered_by = $4, answered_at = $5
WHERE id = $1 AND application_id = $2 AND status = 'open'`, requestID, applicationID, answer, byName, now)
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			return ErrNotFound
		}
		return nil
	})
}
