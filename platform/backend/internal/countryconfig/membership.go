package countryconfig

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"

	countriesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

const (
	// membershipLock keys the advisory lock one account's membership change
	// holds, so two grants for the same account cannot both pass the checks.
	membershipLock = 7_425_033
	// maxUserID is the existing account id's width.
	maxUserID = 30
)

var membershipID = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

// notFound is a record the request names that does not exist; its text is
// shown.
type notFound string

func (n notFound) Error() string { return string(n) }

// grantAsked is a checked GrantMembershipRequest.
type grantAsked struct {
	// from and until are YYYY-MM-DD; from empty for today, until empty for
	// open-ended.
	userID, code, from, until, reason string
}

func grantOf(r *countriesv1.GrantMembershipRequest) (grantAsked, error) {
	g := grantAsked{
		userID: strings.TrimSpace(r.GetUserId()), code: r.GetCountryCode(),
		from: strings.TrimSpace(r.GetEffectiveFrom()), until: strings.TrimSpace(r.GetEffectiveUntil()),
		reason: strings.TrimSpace(r.GetReason()),
	}
	checks := []error{
		check(g.userID != "" && len(g.userID) <= maxUserID, "user_id is required"),
		check(countryCode.MatchString(g.code), "country_code must be a two-letter code such as KE"),
		day("effective_from", g.from),
		day("effective_until", g.until),
		reasonOf("reason", g.reason),
	}
	if g.from != "" && g.until != "" {
		// YYYY-MM-DD orders as text.
		checks = append(checks, check(g.until > g.from, "effective_until must be after effective_from"))
	}
	return g, errors.Join(checks...)
}

func reasonOf(field, reason string) error {
	return errors.Join(check(reason != "", field+" is required"),
		check(utf8.RuneCountInString(reason) <= maxReason, fmt.Sprintf("%s must be at most %d characters", field, maxReason)))
}

// nullable is a date argument: NULL when empty.
func nullable(day string) any {
	if day == "" {
		return nil
	}
	return day
}

// manager is the Admin who may change memberships; nobody else may.
func (s *Service) manager(ctx context.Context) (auth.Principal, error) {
	p, err := s.reader(ctx)
	if err != nil {
		return p, err
	}
	if p.ActiveRole != roleAdmin {
		return p, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: only an Admin grants or revokes a country.")
	}
	return p, nil
}

// refused answers a write that did not happen.
func (s *Service) refused(ctx context.Context, err error) error {
	var (
		cannot  refusal
		missing notFound
	)
	switch {
	case errors.As(err, &cannot):
		return apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument, cannot.Error())
	case errors.As(err, &missing):
		return apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, missing.Error())
	}
	return apierr.Internal(ctx, s.logger, err)
}

// ListMemberships is an account's memberships, newest first: the reader's
// own, or, for an Admin, anyone's.
func (s *Service) ListMemberships(ctx context.Context, req *connect.Request[countriesv1.ListMembershipsRequest]) (*connect.Response[countriesv1.ListMembershipsResponse], error) {
	p, err := s.reader(ctx)
	if err != nil {
		return nil, err
	}
	whose := strings.TrimSpace(req.Msg.GetUserId())
	if whose == "" {
		whose = p.UserID
	}
	if whose != p.UserID && p.ActiveRole != roleAdmin {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: only an Admin reads another account's countries.")
	}
	out, err := memberships(ctx, s.db, `m.user_id = $1`, whose)
	if err != nil {
		return nil, apierr.Internal(ctx, s.logger, err)
	}
	return connect.NewResponse(&countriesv1.ListMembershipsResponse{Memberships: out}), nil
}

// GrantMembership records that an account works in a country from a date.
func (s *Service) GrantMembership(ctx context.Context, req *connect.Request[countriesv1.GrantMembershipRequest]) (*connect.Response[countriesv1.GrantMembershipResponse], error) {
	p, err := s.manager(ctx)
	if err != nil {
		return nil, err
	}
	asked, err := grantOf(req.Msg)
	if err != nil {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, err.Error())
	}
	id, err := s.grant(ctx, p, asked)
	if err != nil {
		return nil, s.refused(ctx, err)
	}
	granted, err := memberships(ctx, s.db, `m.id = $1::uuid`, id)
	if err != nil || len(granted) != 1 {
		return nil, apierr.Internal(ctx, s.logger, fmt.Errorf("countryconfig: reading the membership granted: %w", err))
	}
	return connect.NewResponse(&countriesv1.GrantMembershipResponse{Granted: granted[0]}), nil
}

// RevokeMembership revokes a membership, keeping its record.
func (s *Service) RevokeMembership(ctx context.Context, req *connect.Request[countriesv1.RevokeMembershipRequest]) (*connect.Response[countriesv1.RevokeMembershipResponse], error) {
	p, err := s.manager(ctx)
	if err != nil {
		return nil, err
	}
	id, reason := strings.TrimSpace(req.Msg.GetMembershipId()), strings.TrimSpace(req.Msg.GetReason())
	if err := errors.Join(check(membershipID.MatchString(id), "membership_id must be a membership's id"),
		reasonOf("reason", reason)); err != nil {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, err.Error())
	}
	if err := s.revoke(ctx, p, id, reason); err != nil {
		return nil, s.refused(ctx, err)
	}
	revoked, err := memberships(ctx, s.db, `m.id = $1::uuid`, id)
	if err != nil || len(revoked) != 1 {
		return nil, apierr.Internal(ctx, s.logger, fmt.Errorf("countryconfig: reading the membership revoked: %w", err))
	}
	return connect.NewResponse(&countriesv1.RevokeMembershipResponse{Revoked: revoked[0]}), nil
}

// writing opens a read-write transaction (the gateway's sessions are
// read-only unless a write asks otherwise) holding the account's lock.
func (s *Service) writing(ctx context.Context, userID string) (pgx.Tx, error) {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return nil, err
	}
	if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock($1, hashtext($2))`, membershipLock, userID); err != nil {
		_ = tx.Rollback(context.Background())
		return nil, fmt.Errorf("countryconfig: locking the account's memberships: %w", err)
	}
	return tx, nil
}

// grant writes the membership in one transaction declared for its country
// alone, after every check that would refuse it.
func (s *Service) grant(ctx context.Context, p auth.Principal, g grantAsked) (string, error) {
	if g.userID == p.UserID {
		return "", refusal("An Admin's own countries are granted by another Admin.")
	}
	tx, err := s.writing(ctx, g.userID)
	if err != nil {
		return "", err
	}
	defer func() { _ = tx.Rollback(context.Background()) }()

	var exists bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM "user" WHERE id = $1 AND deleted_at IS NULL)`, g.userID).Scan(&exists); err != nil {
		return "", fmt.Errorf("countryconfig: reading the account: %w", err)
	}
	if !exists {
		return "", notFound("account not found")
	}
	var countryID, name, state string
	err = tx.QueryRow(ctx, `SELECT id::text, name, state FROM country_registry.country WHERE code = $1`, g.code).Scan(&countryID, &name, &state)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", notFound("country not found")
	}
	if err != nil {
		return "", fmt.Errorf("countryconfig: reading the country: %w", err)
	}
	if state == country.StateArchived {
		return "", refusal(name + " is archived: nobody is granted it.")
	}
	from, err := s.grantable(ctx, tx, g, countryID, name)
	if err != nil {
		return "", err
	}
	if err := country.WriteFor(ctx, tx, false, countryID); err != nil {
		return "", err
	}
	var id string
	if err := tx.QueryRow(ctx, `INSERT INTO country_registry.country_membership
  (id, user_id, country_id, is_default, effective_from, effective_until, granted_by, grant_reason)
VALUES (gen_random_uuid(), $1::text, $2::uuid,
  NOT EXISTS (SELECT 1 FROM country_registry.country_membership x WHERE x.user_id = $1::text AND x.revoked_at IS NULL
    AND (x.effective_until IS NULL OR x.effective_until > current_date)),
  $3::date, $4::date, $5, $6)
RETURNING id::text`, g.userID, countryID, from, nullable(g.until), p.UserID, g.reason).Scan(&id); err != nil {
		return "", fmt.Errorf("countryconfig: granting the membership: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return "", err
	}
	s.logger.InfoContext(ctx, "country membership granted", "user", g.userID, "country", g.code, "from", from, "by", p.UserID)
	return id, nil
}

// grantable is the grant's first day, or why it may not be made: a past
// date, an end before the start, dates that overlap a membership of the same
// country not revoked, a revoked one from the same day, or a first
// membership that would end the country the account works in through its
// profile.
func (s *Service) grantable(ctx context.Context, tx pgx.Tx, g grantAsked, countryID, name string) (string, error) {
	var (
		from                                 string
		inPast, endsTooSoon, overlaps, reuse bool
		hasAny                               bool
		profileID, profileName               string
	)
	if err := tx.QueryRow(ctx, `WITH asked AS (SELECT COALESCE($3::date, current_date) AS from_day, $4::date AS until_day)
SELECT a.from_day::text, a.from_day < current_date, a.until_day IS NOT NULL AND a.until_day <= a.from_day,
  EXISTS (SELECT 1 FROM country_registry.country_membership m WHERE m.user_id = $1 AND m.country_id = $2::uuid
    AND m.revoked_at IS NULL AND m.effective_from < COALESCE(a.until_day, 'infinity'::date)
    AND COALESCE(m.effective_until, 'infinity'::date) > a.from_day),
  EXISTS (SELECT 1 FROM country_registry.country_membership m WHERE m.user_id = $1 AND m.country_id = $2::uuid
    AND m.effective_from = a.from_day),
  EXISTS (SELECT 1 FROM country_registry.country_membership m WHERE m.user_id = $1),
  COALESCE(home.id, ''), COALESCE(home.name, '')
FROM asked a LEFT JOIN LATERAL (
  SELECT c.id::text, c.name FROM staff_profile sp
  JOIN country_registry.country_alias al ON al.alias = btrim(sp.country)
  JOIN country_registry.country c ON c.id = al.country_id AND c.state = 'active'
  WHERE sp.user_id = $1 AND sp.deleted_at IS NULL ORDER BY sp.id LIMIT 1) home ON true`, g.userID, countryID, nullable(g.from), nullable(g.until)).Scan(
		&from, &inPast, &endsTooSoon, &overlaps, &reuse, &hasAny, &profileID, &profileName); err != nil {
		return "", fmt.Errorf("countryconfig: reading the account's memberships: %w", err)
	}
	switch {
	case inPast:
		return "", refusal("effective_from may not be in the past")
	case endsTooSoon:
		return "", refusal("effective_until must be after effective_from")
	case overlaps:
		return "", refusal(fmt.Sprintf("This account already belongs to %s for some of those dates.", name))
	case reuse:
		return "", refusal(fmt.Sprintf("A membership of %s from %s is already recorded (it was revoked or has ended); grant it from another day.", name, from))
	case !hasAny && profileID != "" && profileID != countryID:
		// An account with no membership works in its profile's country; its
		// first membership replaces that, so it would silently lose it.
		return "", refusal(fmt.Sprintf("This account has no country membership yet and works in %[1]s through its profile. Grant %[1]s first: %[2]s alone would take %[1]s away.",
			profileName, name))
	}
	return from, nil
}

// revoke marks the membership revoked in one transaction declared for its
// country alone.
func (s *Service) revoke(ctx context.Context, p auth.Principal, id, reason string) error {
	var userID, countryID string
	err := s.db.QueryRow(ctx, `SELECT user_id, country_id::text FROM country_registry.country_membership WHERE id = $1::uuid`,
		id).Scan(&userID, &countryID)
	if errors.Is(err, pgx.ErrNoRows) {
		return notFound("membership not found")
	}
	if err != nil {
		return fmt.Errorf("countryconfig: reading the membership: %w", err)
	}
	if userID == p.UserID {
		return refusal("An Admin's own countries are revoked by another Admin.")
	}
	tx, err := s.writing(ctx, userID)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
	if err := country.WriteFor(ctx, tx, false, countryID); err != nil {
		return err
	}
	tag, err := tx.Exec(ctx, `UPDATE country_registry.country_membership SET revoked_at = now(), revoked_by = $2, revoke_reason = $3
WHERE id = $1::uuid AND revoked_at IS NULL`, id, p.UserID, reason)
	if err != nil {
		return fmt.Errorf("countryconfig: revoking the membership: %w", err)
	}
	if tag.RowsAffected() != 1 {
		return refusal("This membership is already revoked.")
	}
	if err := tx.Commit(ctx); err != nil {
		return err
	}
	s.logger.InfoContext(ctx, "country membership revoked", "membership", id, "user", userID, "by", p.UserID)
	return nil
}

// memberships are the memberships where holds (the alias is m), newest
// first.
func memberships(ctx context.Context, q country.Querier, where string, args ...any) ([]*countriesv1.Membership, error) {
	rows, err := q.Query(ctx, `SELECT m.id::text, m.user_id, c.code, c.name, c.state, m.is_default, m.effective_from::text,
  COALESCE(m.effective_until::text, ''), m.granted_by, m.grant_reason, m.granted_at, COALESCE(m.revoked_by, ''),
  m.revoked_at, COALESCE(m.revoke_reason, ''),
  m.revoked_at IS NULL AND m.effective_from <= current_date AND (m.effective_until IS NULL OR m.effective_until > current_date)
    AND c.state = 'active'
FROM country_registry.country_membership m JOIN country_registry.country c ON c.id = m.country_id
WHERE `+where+` ORDER BY m.granted_at DESC, m.id`, args...)
	if err != nil {
		return nil, fmt.Errorf("countryconfig: reading the memberships: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (*countriesv1.Membership, error) {
		m := &countriesv1.Membership{}
		var (
			granted time.Time
			revoked *time.Time
		)
		err := row.Scan(&m.Id, &m.UserId, &m.CountryCode, &m.CountryName, &m.CountryState, &m.IsDefault, &m.EffectiveFrom,
			&m.EffectiveUntil, &m.GrantedBy, &m.GrantReason, &granted, &m.RevokedBy, &revoked, &m.RevokeReason, &m.InForce)
		m.GrantedAt = granted.UTC().Format(time.RFC3339)
		if revoked != nil {
			m.RevokedAt = revoked.UTC().Format(time.RFC3339)
		}
		return m, err
	})
}
