// Package countryconfig answers CountryService (edify.countries.v1): the
// countries the platform serves, their versioned settings and which accounts
// belong to which country, read from and recorded in the Go-owned
// country_registry schema (internal/country). It writes no table of the
// existing application; it reads only whether an account exists and which
// country its profile names.
package countryconfig

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"

	countriesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// DB is what the service reads and writes through; *pgxpool.Pool satisfies it.
type DB interface {
	country.Querier
	BeginTx(ctx context.Context, opts pgx.TxOptions) (pgx.Tx, error)
}

const (
	roleAdmin = "Admin"
	// lockClass keys the advisory lock one country's settings change holds.
	lockClass = 7_425_032
)

// Service answers CountryService.
type Service struct {
	db     DB
	ready  func(context.Context) error
	logger *slog.Logger
}

// NewService serves the registry through db; ready reports whether
// country_registry is migrated to this build's version.
func NewService(db DB, ready func(context.Context) error, logger *slog.Logger) *Service {
	return &Service{db: db, ready: ready, logger: logger}
}

func (s *Service) reader(ctx context.Context) (auth.Principal, error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return p, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing, "sign in first")
	}
	if err := s.ready(ctx); err != nil {
		s.logger.WarnContext(ctx, "country registry not ready", "error", err)
		return p, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable,
			"The country registry is not set up on this database yet.")
	}
	return p, nil
}

// visible are the countries p may see: every one for an Admin, otherwise
// the Active countries the account works in.
func (s *Service) visible(ctx context.Context, p auth.Principal) ([]country.Country, error) {
	if p.ActiveRole == roleAdmin {
		rows, err := s.db.Query(ctx, `SELECT id::text, code, name, state FROM country_registry.country ORDER BY code`)
		if err != nil {
			return nil, fmt.Errorf("countryconfig: reading the countries: %w", err)
		}
		return pgx.CollectRows(rows, func(row pgx.CollectableRow) (country.Country, error) {
			var c country.Country
			return c, row.Scan(&c.ID, &c.Code, &c.Name, &c.State)
		})
	}
	var profile string
	if p.StaffProfileID != "" {
		var name *string
		err := s.db.QueryRow(ctx, `SELECT country FROM staff_profile WHERE id = $1`, p.StaffProfileID).Scan(&name)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return nil, fmt.Errorf("countryconfig: reading the profile's country: %w", err)
		}
		if name != nil {
			profile = strings.TrimSpace(*name)
		}
	}
	return country.Readable(ctx, s.db, p.UserID, profile)
}

// ListCountries is the countries the reader may see, each with its settings
// in force today.
func (s *Service) ListCountries(ctx context.Context, _ *connect.Request[countriesv1.ListCountriesRequest]) (*connect.Response[countriesv1.ListCountriesResponse], error) {
	p, err := s.reader(ctx)
	if err != nil {
		return nil, err
	}
	seen, err := s.visible(ctx, p)
	if err != nil {
		return nil, apierr.Internal(ctx, s.logger, err)
	}
	out := make([]*countriesv1.Country, 0, len(seen))
	for _, c := range seen {
		answer, err := s.country(ctx, s.db, c.ID)
		if err != nil {
			return nil, apierr.Internal(ctx, s.logger, err)
		}
		out = append(out, answer)
	}
	return connect.NewResponse(&countriesv1.ListCountriesResponse{Countries: out}), nil
}

// GetCountryConfig is one country the reader may see and every settings
// version recorded for it, newest first.
func (s *Service) GetCountryConfig(ctx context.Context, req *connect.Request[countriesv1.GetCountryConfigRequest]) (*connect.Response[countriesv1.GetCountryConfigResponse], error) {
	p, err := s.reader(ctx)
	if err != nil {
		return nil, err
	}
	seen, err := s.visible(ctx, p)
	if err != nil {
		return nil, apierr.Internal(ctx, s.logger, err)
	}
	for _, c := range seen {
		if c.Code != req.Msg.GetCountryCode() {
			continue
		}
		answer, err := s.country(ctx, s.db, c.ID)
		if err != nil {
			return nil, apierr.Internal(ctx, s.logger, err)
		}
		versions, err := s.configs(ctx, s.db, `v.country_id = $1::uuid ORDER BY v.version DESC`, c.ID)
		if err != nil {
			return nil, apierr.Internal(ctx, s.logger, err)
		}
		return connect.NewResponse(&countriesv1.GetCountryConfigResponse{Country: answer, Versions: versions}), nil
	}
	// A country the reader may not see is not told apart from one that
	// does not exist.
	return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "country not found")
}

// RecordCountryConfig records a new settings version for a country that is
// not yet Active, from a date no earlier than today and later than every
// version already recorded; the version open until then ends that day.
func (s *Service) RecordCountryConfig(ctx context.Context, req *connect.Request[countriesv1.RecordCountryConfigRequest]) (*connect.Response[countriesv1.RecordCountryConfigResponse], error) {
	p, err := s.reader(ctx)
	if err != nil {
		return nil, err
	}
	if p.ActiveRole != roleAdmin {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: only an Admin records a country's settings.")
	}
	want, err := settingsOf(req.Msg)
	if err != nil {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, err.Error())
	}
	countryID, version, err := s.record(ctx, p, want)
	var refused refusal
	switch {
	case errors.As(err, &refused):
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument, refused.Error())
	case errors.Is(err, pgx.ErrNoRows):
		return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "country not found")
	case err != nil:
		return nil, apierr.Internal(ctx, s.logger, err)
	}
	answer, err := s.country(ctx, s.db, countryID)
	if err != nil {
		return nil, apierr.Internal(ctx, s.logger, err)
	}
	recorded, err := s.configs(ctx, s.db, `v.country_id = $1::uuid AND v.version = $2`, countryID, version)
	if err != nil || len(recorded) != 1 {
		return nil, apierr.Internal(ctx, s.logger, fmt.Errorf("countryconfig: reading the version recorded: %w", err))
	}
	return connect.NewResponse(&countriesv1.RecordCountryConfigResponse{Country: answer, Recorded: recorded[0]}), nil
}

// record writes the version in one transaction declared for that country
// alone, so the registry's row-level security refuses any other row.
func (s *Service) record(ctx context.Context, p auth.Principal, want settings) (string, int, error) {
	// The gateway's sessions are read-only unless a write asks otherwise.
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return "", 0, err
	}
	defer func() { _ = tx.Rollback(context.Background()) }()

	var id, name, state string
	if err := tx.QueryRow(ctx, `SELECT id::text, name, state FROM country_registry.country WHERE code = $1`,
		want.code).Scan(&id, &name, &state); err != nil {
		return "", 0, err
	}
	switch state {
	case country.StateActive, country.StateSuspended, country.StateArchived:
		return "", 0, refusal(fmt.Sprintf("%s is %s: its settings change only through an approved change, which is not built yet.",
			name, strings.ReplaceAll(state, "_", " ")))
	}
	if err := country.WriteFor(ctx, tx, false, id); err != nil {
		return "", 0, err
	}
	if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock($1, hashtext($2))`, lockClass, id); err != nil {
		return "", 0, fmt.Errorf("countryconfig: locking the country's settings: %w", err)
	}
	var asked any
	if want.from != "" {
		asked = want.from
	}
	var (
		from, latest string
		inPast       bool
		version      int
	)
	if err := tx.QueryRow(ctx, `SELECT COALESCE($2::date, current_date)::text, COALESCE($2::date, current_date) < current_date,
  COALESCE((SELECT max(effective_from) FROM country_registry.country_config_version WHERE country_id = $1::uuid)::text, ''),
  COALESCE((SELECT max(version) FROM country_registry.country_config_version WHERE country_id = $1::uuid), 0) + 1`,
		id, asked).Scan(&from, &inPast, &latest, &version); err != nil {
		return "", 0, fmt.Errorf("countryconfig: reading the versions recorded: %w", err)
	}
	if inPast {
		return "", 0, refusal("effective_from may not be in the past")
	}
	if latest != "" && from <= latest {
		return "", 0, refusal(fmt.Sprintf("effective_from must be after %s, when the latest version takes effect", latest))
	}
	if _, err := tx.Exec(ctx, `UPDATE country_registry.country_config_version SET effective_until = $2::date
WHERE country_id = $1::uuid AND effective_until IS NULL`, id, from); err != nil {
		return "", 0, fmt.Errorf("countryconfig: ending the version in force: %w", err)
	}
	if _, err := tx.Exec(ctx, `INSERT INTO country_registry.country_config_version
  (id, country_id, version, default_language, languages, currency_code, currency_minor_units, time_zone,
   date_format, calendars, fy_start_month, effective_from, changed_by, change_reason)
VALUES (gen_random_uuid(), $1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::date, $12, $13)`,
		id, version, want.defaultLanguage, want.languages, want.currency, want.minorUnits, want.timeZone,
		want.dateFormat, want.calendars, want.fyStartMonth, from, p.UserID, want.reason); err != nil {
		return "", 0, fmt.Errorf("countryconfig: recording the version: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return "", 0, err
	}
	s.logger.InfoContext(ctx, "country settings recorded", "country", want.code, "version", version, "from", from, "by", p.UserID)
	return id, version, nil
}

// country is one country with the settings in force today.
func (s *Service) country(ctx context.Context, q country.Querier, id string) (*countriesv1.Country, error) {
	out := &countriesv1.Country{}
	if err := q.QueryRow(ctx, `SELECT id::text, code, name, state, COALESCE(activated_on::text, ''), roles_source
FROM country_registry.country WHERE id = $1::uuid`, id).Scan(&out.Id, &out.Code, &out.Name, &out.State, &out.ActivatedOn,
		&out.RolesSource); err != nil {
		return nil, fmt.Errorf("countryconfig: reading the country: %w", err)
	}
	inForce, err := s.configs(ctx, q, `v.country_id = $1::uuid AND v.effective_from <= current_date
  AND (v.effective_until IS NULL OR v.effective_until > current_date)`, id)
	if err != nil {
		return nil, err
	}
	if len(inForce) > 0 {
		out.Config = inForce[0]
	}
	return out, nil
}

// configs are the settings versions where holds (the alias is v).
func (s *Service) configs(ctx context.Context, q country.Querier, where string, args ...any) ([]*countriesv1.CountryConfig, error) {
	rows, err := q.Query(ctx, `SELECT v.version, v.default_language, v.languages, v.currency_code, v.currency_minor_units,
  v.time_zone, v.date_format, v.calendars, v.fy_start_month, v.effective_from::text, COALESCE(v.effective_until::text, ''),
  v.changed_by, v.change_reason, COALESCE(v.approved_by, ''), v.created_at
FROM country_registry.country_config_version v WHERE `+where, args...)
	if err != nil {
		return nil, fmt.Errorf("countryconfig: reading the settings: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (*countriesv1.CountryConfig, error) {
		c := &countriesv1.CountryConfig{}
		var minor, month int16
		var created time.Time
		err := row.Scan(&c.Version, &c.DefaultLanguage, &c.Languages, &c.CurrencyCode, &minor, &c.TimeZone, &c.DateFormat,
			&c.Calendars, &month, &c.EffectiveFrom, &c.EffectiveUntil, &c.ChangedBy, &c.ChangeReason, &c.ApprovedBy, &created)
		c.CurrencyMinorUnits, c.FyStartMonth, c.CreatedAt = int32(minor), int32(month), created.UTC().Format(time.RFC3339)
		return c, err
	})
}
