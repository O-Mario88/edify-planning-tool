package loans

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

var (
	// ErrNotFound: no such record, or not one the caller may see.
	ErrNotFound = errors.New("loans: not found")
	// ErrLenderUnavailable: the chosen lender cannot receive referrals now.
	ErrLenderUnavailable = errors.New("loans: lender not available")
	// ErrConflict: the record changed since it was read.
	ErrConflict = errors.New("loans: changed meanwhile")
)

// Store reads the existing records the portal needs (read only, through the
// gateway's read-only grants) and reads and writes the portal's own records
// in school_loans, inside explicit read-write transactions.
type Store struct {
	db *pgxpool.Pool
}

// NewStore returns a Store over pool.
func NewStore(pool *pgxpool.Pool) *Store { return &Store{db: pool} }

// Lender is a Loan Partner of the Partner Directory that may receive
// referrals now.
type Lender struct {
	PartnerID      string
	LenderID       string // its bt_mfi_organization record in the loan workflow
	Name           string
	Description    string
	DeliveryEmail  string
	HasPortalUsers bool
}

// eligibleLenders is the brief's four conditions (§4): a Loan Partner of the
// Partner Directory, active; its lender active and under a data-sharing
// agreement; switched on for referrals; and with a receiving address the
// lender itself confirmed.
const eligibleLenders = `
SELECT p.id, m.id, p.name, c.description, c.confirmed_email,
  EXISTS (SELECT 1 FROM bt_mfi_membership mm WHERE mm.mfi_id = m.id AND mm.active)
FROM partner p
JOIN bt_mfi_organization m ON m.id = p.loan_lender_id
JOIN school_loans.lender_channel c ON c.partner_id = p.id
WHERE p.partner_role = 'loan' AND p.active_status AND p.deleted_at IS NULL
  AND m.active AND m.deleted_at IS NULL AND m.data_sharing_agreement_active
  AND c.referrals_enabled AND c.confirmed_at IS NOT NULL
  AND c.confirmed_email <> '' AND c.confirmed_email = c.delivery_email`

type querier interface {
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// Lenders are the lenders the public form offers, by name.
func (s *Store) Lenders(ctx context.Context) ([]Lender, error) {
	return lenders(ctx, s.db, eligibleLenders+` ORDER BY p.name`)
}

func lenders(ctx context.Context, q querier, sql string, args ...any) ([]Lender, error) {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("loans: reading lenders: %w", err)
	}
	defer rows.Close()
	var out []Lender
	for rows.Next() {
		var lender Lender
		if err := rows.Scan(&lender.PartnerID, &lender.LenderID, &lender.Name, &lender.Description,
			&lender.DeliveryEmail, &lender.HasPortalUsers); err != nil {
			return nil, fmt.Errorf("loans: reading a lender: %w", err)
		}
		out = append(out, lender)
	}
	return out, rows.Err()
}

func eligibleLender(ctx context.Context, q querier, partnerID string) (Lender, error) {
	found, err := lenders(ctx, q, eligibleLenders+` AND p.id = $1`, partnerID)
	if err != nil {
		return Lender{}, err
	}
	if len(found) == 0 {
		return Lender{}, ErrLenderUnavailable
	}
	return found[0], nil
}

// Place is one entry of the location lists.
type Place struct {
	ID   string
	Name string
}

// Districts are the School Directory's districts, by name.
func (s *Store) Districts(ctx context.Context) ([]Place, error) {
	return places(ctx, s.db, `SELECT id, name FROM district ORDER BY name`)
}

// SubCounties are the sub-counties recorded under the named district.
func (s *Store) SubCounties(ctx context.Context, district string) ([]Place, error) {
	return places(ctx, s.db, `
SELECT sc.id, sc.name FROM sub_county sc JOIN district d ON d.id = sc.district_id
WHERE lower(d.name) = lower($1) ORDER BY sc.name`, district)
}

// Parishes are the parishes recorded under the named sub-county.
func (s *Store) Parishes(ctx context.Context, district, subCounty string) ([]Place, error) {
	return places(ctx, s.db, `
SELECT pa.id, pa.name FROM parish pa
JOIN sub_county sc ON sc.id = pa.sub_county_id JOIN district d ON d.id = sc.district_id
WHERE lower(d.name) = lower($1) AND lower(sc.name) = lower($2) ORDER BY pa.name`, district, subCounty)
}

func places(ctx context.Context, q querier, sql string, args ...any) ([]Place, error) {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("loans: reading places: %w", err)
	}
	defer rows.Close()
	var out []Place
	for rows.Next() {
		var place Place
		if err := rows.Scan(&place.ID, &place.Name); err != nil {
			return nil, fmt.Errorf("loans: reading a place: %w", err)
		}
		out = append(out, place)
	}
	return out, rows.Err()
}

// ResolvedPlace is a submitted location with the directory's ids where the
// names were the directory's own; a typed name keeps an empty id.
type ResolvedPlace struct {
	DistrictID, SubCountyID, ParishID string
}

// one returns the id of the only place sql finds, or "" for none or several:
// an ambiguous name is never given an id (brief: "Do not ... silently assign
// incorrect geographic identifiers").
func one(ctx context.Context, q querier, sql string, args ...any) (string, error) {
	found, err := places(ctx, q, sql, args...)
	if err != nil || len(found) != 1 {
		return "", err
	}
	return found[0].ID, nil
}

// ResolvePlace looks the submitted names up in the directory.
func (s *Store) ResolvePlace(ctx context.Context, input Input) (ResolvedPlace, error) {
	var place ResolvedPlace
	var err error
	if place.DistrictID, err = one(ctx, s.db, `SELECT id, name FROM district WHERE lower(name) = lower($1)`,
		input.District); err != nil || place.DistrictID == "" {
		return place, err
	}
	if place.SubCountyID, err = one(ctx, s.db, `SELECT id, name FROM sub_county WHERE district_id = $1 AND lower(name) = lower($2)`,
		place.DistrictID, input.SubCounty); err != nil || place.SubCountyID == "" {
		return place, err
	}
	place.ParishID, err = one(ctx, s.db, `SELECT id, name FROM parish WHERE sub_county_id = $1 AND lower(name) = lower($2)`,
		place.SubCountyID, input.Parish)
	return place, err
}

// SchoolsInDistrict are the directory's open schools in a district, for
// matching.
func (s *Store) SchoolsInDistrict(ctx context.Context, districtID string) ([]SchoolCandidate, error) {
	return candidates(ctx, s.db, `
SELECT id, COALESCE(school_id, ''), name, COALESCE(district_id, ''), COALESCE(sub_county_id, '')
FROM school WHERE deleted_at IS NULL AND district_id = $1`, districtID)
}

// SchoolsNamed are directory schools anywhere whose name holds word, for a
// submission whose district was typed in. They only ever become candidates.
func (s *Store) SchoolsNamed(ctx context.Context, word string) ([]SchoolCandidate, error) {
	return candidates(ctx, s.db, `
SELECT id, COALESCE(school_id, ''), name, COALESCE(district_id, ''), COALESCE(sub_county_id, '')
FROM school WHERE deleted_at IS NULL AND name ILIKE '%' || $1 || '%' ORDER BY name LIMIT 50`, word)
}

// School is one directory school by its internal id.
func (s *Store) School(ctx context.Context, id string) (SchoolCandidate, error) {
	found, err := candidates(ctx, s.db, `
SELECT id, COALESCE(school_id, ''), name, COALESCE(district_id, ''), COALESCE(sub_county_id, '')
FROM school WHERE deleted_at IS NULL AND id = $1`, id)
	if err != nil {
		return SchoolCandidate{}, err
	}
	if len(found) == 0 {
		return SchoolCandidate{}, ErrNotFound
	}
	return found[0], nil
}

func candidates(ctx context.Context, q querier, sql string, args ...any) ([]SchoolCandidate, error) {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("loans: reading schools: %w", err)
	}
	defer rows.Close()
	var out []SchoolCandidate
	for rows.Next() {
		var school SchoolCandidate
		if err := rows.Scan(&school.ID, &school.SchoolID, &school.Name, &school.DistrictID, &school.SubCountyID); err != nil {
			return nil, fmt.Errorf("loans: reading a school: %w", err)
		}
		out = append(out, school)
	}
	return out, rows.Err()
}

// Invitation is a live school-specific link.
type Invitation struct {
	ID     string
	School SchoolCandidate
}

// InvitationByToken is the live invitation whose token hashes to hash.
func (s *Store) InvitationByToken(ctx context.Context, hash string, now time.Time) (Invitation, error) {
	var invitation Invitation
	var schoolID string
	err := s.db.QueryRow(ctx, `
SELECT id, school_id FROM school_loans.invitation
WHERE token_hash = $1 AND revoked_at IS NULL AND expires_at > $2`, hash, now).Scan(&invitation.ID, &schoolID)
	if errors.Is(err, pgx.ErrNoRows) {
		return Invitation{}, ErrNotFound
	}
	if err != nil {
		return Invitation{}, fmt.Errorf("loans: reading an invitation: %w", err)
	}
	if invitation.School, err = s.School(ctx, schoolID); err != nil {
		return Invitation{}, err
	}
	return invitation, nil
}

// inWrite runs work in a read-write transaction: the gateway's role is read
// only by default, and the transaction reaches only edify_loans_rw's tables.
func (s *Store) inWrite(ctx context.Context, work func(pgx.Tx) error) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("loans: beginning a write: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := work(tx); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("loans: committing a write: %w", err)
	}
	return nil
}

// isUniqueViolation says whether err broke the named unique constraint.
func isUniqueViolation(err error, constraint string) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == "23505" &&
		(constraint == "" || strings.Contains(pgErr.ConstraintName, constraint))
}

func appendEvent(ctx context.Context, tx pgx.Tx, event Event) error {
	id, err := NewID()
	if err != nil {
		return err
	}
	_, err = tx.Exec(ctx, `
INSERT INTO school_loans.application_event
  (id, application_id, kind, actor_kind, actor_id, actor_name, from_status, to_status, note, evidence)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`,
		id, event.ApplicationID, event.Kind, event.ActorKind, event.ActorID, event.ActorName,
		event.FromStatus, event.ToStatus, event.Note, event.Evidence)
	if err != nil {
		return fmt.Errorf("loans: recording a %s event: %w", event.Kind, err)
	}
	return nil
}

// Event is one entry of an application's timeline.
type Event struct {
	ApplicationID string
	Kind          string
	ActorKind     string // applicant, staff, lender, system
	ActorID       string
	ActorName     string
	FromStatus    string
	ToStatus      string
	Note          string
	Evidence      string
	At            time.Time
}
