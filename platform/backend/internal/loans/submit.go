package loans

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// ConsentVersion names the declaration and privacy notice the applicant
// agreed to; a change to their wording gets a new version.
const ConsentVersion = "2026-11-11"

// receiptLifetime is how long a receipt link shows the application's status.
const receiptLifetime = 24 * time.Hour

// duplicateWindow: a second application for the same school, from the same
// phone, to the same lender within this window is the first one again.
const duplicateWindow = 24 * time.Hour

// NewApplication is a validated submission ready to store.
type NewApplication struct {
	Input      Input
	Place      ResolvedPlace
	Match      Match
	Invitation *Invitation
	// ShareLinkID is the lender's or sharer's link it came through, if any.
	ShareLinkID string
	Now         time.Time
}

// Submitted is what the applicant is told after submitting.
type Submitted struct {
	ID           string
	Reference    string
	ReceiptToken string
	// Replayed is true when this submission was already stored (the same
	// form sent twice); nothing new was written.
	Replayed bool
}

// DuplicateError is a second application for the same school already
// received from the same phone for the same lender.
type DuplicateError struct {
	Reference   string
	SubmittedAt time.Time
}

func (e *DuplicateError) Error() string {
	return fmt.Sprintf("loans: already received as %s", e.Reference)
}

// Submit stores a submission, its first timeline event and its delivery
// task in one transaction (a transactional outbox: an accepted application
// is never lost between storage and the lender's notification), and returns
// its receipt. The same idempotency key twice returns the first result.
func (s *Store) Submit(ctx context.Context, keys Keys, app NewApplication) (Submitted, error) {
	var out Submitted
	for attempt := 0; attempt < 3; attempt++ {
		err := s.inWrite(ctx, func(tx pgx.Tx) error {
			var err error
			out, err = submitIn(ctx, tx, keys, app)
			return err
		})
		switch {
		case err == nil:
			return out, nil
		case isUniqueViolation(err, "idempotency_key"):
			// A simultaneous submit of the same form won the race: answer
			// with its receipt.
			continue
		case isUniqueViolation(err, "reference"):
			continue // a new random reference on the next attempt
		default:
			return Submitted{}, err
		}
	}
	return Submitted{}, errors.New("loans: could not store the application after three attempts")
}

func submitIn(ctx context.Context, tx pgx.Tx, keys Keys, app NewApplication) (Submitted, error) {
	input := app.Input
	var existing Submitted
	err := tx.QueryRow(ctx, `SELECT id, reference FROM school_loans.application WHERE idempotency_key = $1`,
		input.IdempotencyKey).Scan(&existing.ID, &existing.Reference)
	if err == nil {
		existing.ReceiptToken = keys.ReceiptToken(existing.ID, input.IdempotencyKey)
		existing.Replayed = true
		return existing, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return Submitted{}, fmt.Errorf("loans: checking for a repeated submission: %w", err)
	}

	// Checked again inside the transaction: the form's list may be stale.
	lender, err := eligibleLender(ctx, tx, input.PartnerID)
	if err != nil {
		return Submitted{}, err
	}

	var duplicate DuplicateError
	err = tx.QueryRow(ctx, `
SELECT reference, submitted_at FROM school_loans.application
WHERE director_phone = $1 AND partner_id = $2 AND lower(school_name) = lower($3)
  AND submitted_at > $4 AND status NOT IN ('declined', 'closed', 'withdrawn')
ORDER BY submitted_at DESC LIMIT 1`,
		input.DirectorPhone, input.PartnerID, input.SchoolName, app.Now.Add(-duplicateWindow)).
		Scan(&duplicate.Reference, &duplicate.SubmittedAt)
	if err == nil {
		return Submitted{}, &duplicate
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return Submitted{}, fmt.Errorf("loans: checking for a duplicate: %w", err)
	}

	id, err := NewID()
	if err != nil {
		return Submitted{}, err
	}
	reference, err := NewReference()
	if err != nil {
		return Submitted{}, err
	}
	receipt := keys.ReceiptToken(id, input.IdempotencyKey)
	source, invitationID := "public_link", (*string)(nil)
	if app.Invitation != nil {
		source, invitationID = "invitation", &app.Invitation.ID
	}
	var schoolID *string
	if app.Match.Status == MatchMatched {
		schoolID = &app.Match.School.ID
	}
	var term *int
	if input.TermMonths > 0 {
		term = &input.TermMonths
	}

	_, err = tx.Exec(ctx, `
INSERT INTO school_loans.application (
  id, reference, idempotency_key, receipt_token_hash, receipt_expires_at, source, invitation_id,
  school_name, director_name, director_phone, director_email, director_religion,
  district_id, district_name, sub_county_id, sub_county_name, parish_id, parish_name, village_name,
  boys, girls, average_fees_collected_ugx,
  purpose_code, purpose_label, purpose_other, purpose_details, requested_amount_ugx, preferred_term_months,
  partner_id, lender_id, lender_name, consent_version, consent_recorded_at,
  school_match_status, school_id, match_method, matched_by, matched_at,
  status, delivery_status, next_follow_up_on, submitted_at, updated_at, share_link_id, country_code
) VALUES (
  $1, $2, $3, $4, $5, $6, $7,
  $8, $9, $10, $11, $12,
  $13, $14, $15, $16, $17, $18, $19,
  $20, $21, $22,
  $23, $24, $25, $26, $27, $28,
  $29, $30, $31, $32, $33,
  $34, $35, $36, $37, $38,
  'submitted', 'queued', $39, $33, $33, $40,
  `+registry.SchoolCountryCode("$35::text")+`
)`,
		id, reference, input.IdempotencyKey, HashToken(receipt), app.Now.Add(receiptLifetime), source, invitationID,
		input.SchoolName, input.DirectorName, input.DirectorPhone, input.DirectorEmail, input.Religion,
		app.Place.DistrictID, input.District, app.Place.SubCountyID, input.SubCounty, app.Place.ParishID, input.Parish, input.Village,
		input.Boys, input.Girls, input.FeesCollected,
		input.Purpose.Code, input.Purpose.Label, input.PurposeOther, input.PurposeDetails, input.Requested, term,
		lender.PartnerID, lender.LenderID, lender.Name, ConsentVersion, app.Now,
		app.Match.Status, schoolID, app.Match.Method, matchedBy(app.Match), matchedAt(app.Match, app.Now),
		firstFollowUp(app.Now), shareLink(app.ShareLinkID),
	)
	if err != nil {
		return Submitted{}, fmt.Errorf("loans: storing the application: %w", err)
	}
	note := "Submitted through the public application link."
	if app.Invitation != nil {
		note = "Submitted through a school invitation link for " + app.Invitation.School.Name + "."
	}
	if err := appendEvent(ctx, tx, Event{
		ApplicationID: id, Kind: "submitted", ActorKind: "applicant", ActorName: input.DirectorName,
		ToStatus: StatusSubmitted, Note: note,
	}); err != nil {
		return Submitted{}, err
	}
	if app.Match.Status == MatchMatched {
		if err := appendEvent(ctx, tx, Event{
			ApplicationID: id, Kind: "school_matched", ActorKind: "system",
			Note: "Linked to " + app.Match.School.Name + " (" + app.Match.School.SchoolID + ") by " +
				map[string]string{"invitation": "its invitation link", "name_and_place": "its name and location"}[app.Match.Method] + ".",
		}); err != nil {
			return Submitted{}, err
		}
	}
	if err := enqueue(ctx, tx, task{
		Kind: TaskLenderReferral, DedupeKey: "referral:" + id, ApplicationID: id,
		PartnerID: lender.PartnerID, Recipient: lender.DeliveryEmail, At: app.Now,
	}); err != nil {
		return Submitted{}, err
	}
	return Submitted{ID: id, Reference: reference, ReceiptToken: receipt}, nil
}

func matchedBy(match Match) string {
	if match.Status == MatchMatched {
		return "system"
	}
	return ""
}

func matchedAt(match Match, now time.Time) *time.Time {
	if match.Status == MatchMatched {
		return &now
	}
	return nil
}

// firstFollowUp: Edify's existing intake asks for a first follow-up three
// days after submission (apps/business_transformation/loan_tracking.py).
func firstFollowUp(now time.Time) time.Time {
	return now.In(kampala).AddDate(0, 0, 3)
}

// Delivery task kinds.
const (
	TaskLenderReferral = "lender_referral"
	TaskStaffAlert     = "staff_alert"
	TaskFollowUpRemind = "follow_up_reminder"
)

type task struct {
	Kind            string
	DedupeKey       string
	ApplicationID   string
	PartnerID       string
	RecipientUserID string
	Recipient       string
	At              time.Time
}

// enqueue adds a delivery task once: a second task with the same dedupe key
// is the first one.
func enqueue(ctx context.Context, tx pgx.Tx, t task) error {
	id, err := NewID()
	if err != nil {
		return err
	}
	var applicationID *string
	if t.ApplicationID != "" {
		applicationID = &t.ApplicationID
	}
	_, err = tx.Exec(ctx, `
INSERT INTO school_loans.delivery_task
  (id, kind, dedupe_key, application_id, partner_id, recipient_user_id, recipient_email,
   next_attempt_at, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $8, $8)
ON CONFLICT (dedupe_key) DO NOTHING`,
		id, t.Kind, t.DedupeKey, applicationID, t.PartnerID, t.RecipientUserID, t.Recipient, t.At)
	if err != nil {
		return fmt.Errorf("loans: queueing a %s: %w", t.Kind, err)
	}
	return nil
}

// Receipt is what the applicant's receipt link shows: their own
// application's reference, school, lender and progress, and nothing else.
type Receipt struct {
	Reference      string
	SchoolName     string
	LenderName     string
	SubmittedAt    time.Time
	Status         string
	DeliveryStatus string
}

// ReceiptByToken is the application whose live receipt token hashes to hash.
func (s *Store) ReceiptByToken(ctx context.Context, hash string, now time.Time) (Receipt, error) {
	var receipt Receipt
	err := s.db.QueryRow(ctx, `
SELECT reference, school_name, lender_name, submitted_at, status, delivery_status
FROM school_loans.application WHERE receipt_token_hash = $1 AND receipt_expires_at > $2`, hash, now).
		Scan(&receipt.Reference, &receipt.SchoolName, &receipt.LenderName, &receipt.SubmittedAt,
			&receipt.Status, &receipt.DeliveryStatus)
	if errors.Is(err, pgx.ErrNoRows) {
		return Receipt{}, ErrNotFound
	}
	if err != nil {
		return Receipt{}, fmt.Errorf("loans: reading a receipt: %w", err)
	}
	return receipt, nil
}

var kampala = mustZone("Africa/Kampala")

func mustZone(name string) *time.Location {
	zone, err := time.LoadLocation(name)
	if err != nil {
		return time.FixedZone("EAT", 3*60*60)
	}
	return zone
}

func shareLink(id string) *string {
	if id == "" {
		return nil
	}
	return &id
}

// ReceiptOf is an application's receipt facts, for a verified tracking
// session.
func (s *Store) ReceiptOf(ctx context.Context, applicationID string) (Receipt, error) {
	var receipt Receipt
	err := s.db.QueryRow(ctx, `
SELECT reference, school_name, lender_name, submitted_at, status, delivery_status
FROM school_loans.application WHERE id = $1`, applicationID).
		Scan(&receipt.Reference, &receipt.SchoolName, &receipt.LenderName, &receipt.SubmittedAt,
			&receipt.Status, &receipt.DeliveryStatus)
	if errors.Is(err, pgx.ErrNoRows) {
		return Receipt{}, ErrNotFound
	}
	return receipt, err
}
