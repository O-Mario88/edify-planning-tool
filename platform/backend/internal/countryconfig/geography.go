package countryconfig

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"unicode/utf8"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"

	countriesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// The geographic registry (country_registry 0007; docs/migration/80 §25,
// §26). Every country the reader may see has its levels and units read
// here. Only an Admin defines a level or adds a unit, and only for a
// country that is not yet Active: Uganda's geography is its existing
// application's, mapped in by id, and changes there.
//
// A unit's parent is always at a higher level (a lower level number) in
// the same country, so no chain of parents can loop.

const (
	unitsPage     = 50
	mostLevel     = 12
	mostQuery     = 100
	mostLabel     = 80
	mostUnitName  = 200
	mostUnitCode  = 40
	mostTypeWord  = 40
	uniqueKeyCode = "23505"
)

var canonicalWord = regexp.MustCompile(`^[a-z][a-z_]*$`)

// levelAsked is a level an Admin asked to define, checked.
type levelAsked struct {
	code, canonical, label string
	level                  int32
	required               bool
}

func levelOf(r *countriesv1.DefineAdminUnitLevelRequest) (levelAsked, error) {
	l := levelAsked{
		code: strings.TrimSpace(r.GetCountryCode()), canonical: strings.TrimSpace(r.GetCanonicalType()),
		label: strings.TrimSpace(r.GetLocalLabel()), level: r.GetLevel(), required: r.GetIsRequired(),
	}
	return l, errors.Join(
		check(l.code != "", "country_code is required"),
		check(canonicalWord.MatchString(l.canonical) && len(l.canonical) <= mostTypeWord,
			fmt.Sprintf("canonical_type must be lower-case letters and underscores, at most %d", mostTypeWord)),
		check(l.label != "" && utf8.RuneCountInString(l.label) <= mostLabel,
			fmt.Sprintf("local_label is required, at most %d characters", mostLabel)),
		check(l.level >= 1 && l.level <= mostLevel, fmt.Sprintf("level must be 1 to %d", mostLevel)),
	)
}

// unitAsked is a unit an Admin asked to add, checked.
type unitAsked struct {
	code, levelID, parentID, name, officialCode string
}

func unitOf(r *countriesv1.AddAdminUnitRequest) (unitAsked, error) {
	u := unitAsked{
		code: strings.TrimSpace(r.GetCountryCode()), levelID: strings.TrimSpace(r.GetLevelId()),
		parentID: strings.TrimSpace(r.GetParentId()), name: strings.TrimSpace(r.GetOfficialName()),
		officialCode: strings.TrimSpace(r.GetOfficialCode()),
	}
	return u, errors.Join(
		check(u.code != "", "country_code is required"),
		check(membershipID.MatchString(u.levelID), "level_id must be a level's id"),
		check(u.parentID == "" || membershipID.MatchString(u.parentID), "parent_id must be a unit's id"),
		check(u.name != "" && utf8.RuneCountInString(u.name) <= mostUnitName,
			fmt.Sprintf("official_name is required, at most %d characters", mostUnitName)),
		check(utf8.RuneCountInString(u.officialCode) <= mostUnitCode,
			fmt.Sprintf("official_code may be at most %d characters", mostUnitCode)),
	)
}

// listAsked is the page of units asked for, checked.
type listAsked struct {
	code, parentID, query string
	page                  int32
}

func listOf(r *countriesv1.ListAdminUnitsRequest) (listAsked, error) {
	l := listAsked{
		code: strings.TrimSpace(r.GetCountryCode()), parentID: strings.TrimSpace(r.GetParentId()),
		query: strings.TrimSpace(r.GetQuery()), page: r.GetPage(),
	}
	if l.page < 1 {
		l.page = 1
	}
	return l, errors.Join(
		check(l.code != "", "country_code is required"),
		check(l.parentID == "" || membershipID.MatchString(l.parentID), "parent_id must be a unit's id"),
		check(utf8.RuneCountInString(l.query) <= mostQuery, fmt.Sprintf("query may be at most %d characters", mostQuery)),
	)
}

// seen is the country with code if the reader may see it.
func (s *Service) seen(ctx context.Context, p auth.Principal, code string) (country.Country, error) {
	countries, err := s.visible(ctx, p)
	if err != nil {
		return country.Country{}, apierr.Internal(ctx, s.logger, err)
	}
	for _, c := range countries {
		if c.Code == code {
			return c, nil
		}
	}
	// A country the reader may not see is not told apart from one that
	// does not exist.
	return country.Country{}, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "country not found")
}

// ListAdminUnitLevels is a country's live levels, top first, with how many
// units each holds.
func (s *Service) ListAdminUnitLevels(ctx context.Context, req *connect.Request[countriesv1.ListAdminUnitLevelsRequest]) (*connect.Response[countriesv1.ListAdminUnitLevelsResponse], error) {
	p, err := s.reader(ctx)
	if err != nil {
		return nil, err
	}
	c, err := s.seen(ctx, p, strings.TrimSpace(req.Msg.GetCountryCode()))
	if err != nil {
		return nil, err
	}
	levels, err := s.levels(ctx, s.db, `t.country_id = $1::uuid`, c.ID)
	if err != nil {
		return nil, apierr.Internal(ctx, s.logger, err)
	}
	return connect.NewResponse(&countriesv1.ListAdminUnitLevelsResponse{Levels: levels}), nil
}

// levels are the live levels where holds (the alias is t), top first.
func (s *Service) levels(ctx context.Context, q country.Querier, where string, args ...any) ([]*countriesv1.AdminUnitLevel, error) {
	rows, err := q.Query(ctx, `SELECT t.id::text, t.canonical_type, t.local_label, t.level, t.is_required,
  (SELECT count(*) FROM country_registry.admin_unit u WHERE u.type_id = t.id AND u.valid_to IS NULL),
  (SELECT count(*) FROM country_registry.admin_unit u WHERE u.type_id = t.id AND u.valid_to IS NULL
     AND u.verification_status = 'verified')
FROM country_registry.admin_unit_type t WHERE t.effective_to IS NULL AND `+where+` ORDER BY t.level`, args...)
	if err != nil {
		return nil, fmt.Errorf("countryconfig: reading the levels: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (*countriesv1.AdminUnitLevel, error) {
		l := &countriesv1.AdminUnitLevel{}
		var level int16
		err := row.Scan(&l.Id, &l.CanonicalType, &l.LocalLabel, &level, &l.IsRequired, &l.UnitCount, &l.VerifiedCount)
		l.Level = int32(level)
		return l, err
	})
}

// unitColumns read one unit aliased u, with its level aliased t.
const unitColumns = `u.id::text, u.official_name, COALESCE(u.official_code, ''), t.id::text, t.local_label,
  COALESCE(u.parent_id::text, ''), u.verification_status, u.source,
  (SELECT count(*) FROM country_registry.admin_unit c WHERE c.parent_id = u.id AND c.valid_to IS NULL)`

func scanUnit(row pgx.CollectableRow) (*countriesv1.AdminUnit, error) {
	u := &countriesv1.AdminUnit{}
	return u, row.Scan(&u.Id, &u.OfficialName, &u.OfficialCode, &u.LevelId, &u.LevelLabel, &u.ParentId,
		&u.VerificationStatus, &u.Source, &u.ChildCount)
}

// ListAdminUnits is a page of a country's live units under one parent, or
// at its top, by name, with the parent's chain up to the top.
func (s *Service) ListAdminUnits(ctx context.Context, req *connect.Request[countriesv1.ListAdminUnitsRequest]) (*connect.Response[countriesv1.ListAdminUnitsResponse], error) {
	p, err := s.reader(ctx)
	if err != nil {
		return nil, err
	}
	asked, err := listOf(req.Msg)
	if err != nil {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, err.Error())
	}
	c, err := s.seen(ctx, p, asked.code)
	if err != nil {
		return nil, err
	}
	out := &countriesv1.ListAdminUnitsResponse{Page: asked.page, Units: []*countriesv1.AdminUnit{}, Trail: []*countriesv1.AdminUnit{}}
	if asked.parentID != "" {
		rows, err := s.db.Query(ctx, `WITH RECURSIVE up AS (
  SELECT u.id, u.parent_id, 1 AS depth FROM country_registry.admin_unit u WHERE u.id = $1::uuid AND u.country_id = $2::uuid
  UNION ALL
  SELECT u.id, u.parent_id, up.depth + 1 FROM country_registry.admin_unit u JOIN up ON u.id = up.parent_id
  WHERE up.depth < $3
)
SELECT `+unitColumns+` FROM up JOIN country_registry.admin_unit u ON u.id = up.id
JOIN country_registry.admin_unit_type t ON t.id = u.type_id ORDER BY up.depth DESC`, asked.parentID, c.ID, mostLevel)
		if err != nil {
			return nil, apierr.Internal(ctx, s.logger, fmt.Errorf("countryconfig: reading the unit's chain: %w", err))
		}
		if out.Trail, err = pgx.CollectRows(rows, scanUnit); err != nil {
			return nil, apierr.Internal(ctx, s.logger, fmt.Errorf("countryconfig: reading the unit's chain: %w", err))
		}
		if len(out.Trail) == 0 {
			return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "unit not found")
		}
	}
	const under = `u.country_id = $1::uuid AND u.valid_to IS NULL
  AND (($2 = '' AND u.parent_id IS NULL) OR u.parent_id = NULLIF($2, '')::uuid)
  AND ($3 = '' OR u.official_name ILIKE '%' || replace(replace(replace($3, '\', '\\'), '%', '\%'), '_', '\_') || '%')`
	if err := s.db.QueryRow(ctx, `SELECT count(*) FROM country_registry.admin_unit u WHERE `+under,
		c.ID, asked.parentID, asked.query).Scan(&out.Total); err != nil {
		return nil, apierr.Internal(ctx, s.logger, fmt.Errorf("countryconfig: counting the units: %w", err))
	}
	rows, err := s.db.Query(ctx, `SELECT `+unitColumns+` FROM country_registry.admin_unit u
JOIN country_registry.admin_unit_type t ON t.id = u.type_id
WHERE `+under+` ORDER BY u.official_name, u.id LIMIT $4 OFFSET $5`,
		c.ID, asked.parentID, asked.query, unitsPage, (asked.page-1)*unitsPage)
	if err != nil {
		return nil, apierr.Internal(ctx, s.logger, fmt.Errorf("countryconfig: reading the units: %w", err))
	}
	if out.Units, err = pgx.CollectRows(rows, scanUnit); err != nil {
		return nil, apierr.Internal(ctx, s.logger, fmt.Errorf("countryconfig: reading the units: %w", err))
	}
	return connect.NewResponse(out), nil
}

// DefineAdminUnitLevel defines a level for a country that is not yet
// Active.
func (s *Service) DefineAdminUnitLevel(ctx context.Context, req *connect.Request[countriesv1.DefineAdminUnitLevelRequest]) (*connect.Response[countriesv1.DefineAdminUnitLevelResponse], error) {
	p, err := s.geographyWriter(ctx)
	if err != nil {
		return nil, err
	}
	asked, err := levelOf(req.Msg)
	if err != nil {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, err.Error())
	}
	var id string
	err = s.inGeography(ctx, asked.code, func(tx pgx.Tx, countryID string) error {
		return tx.QueryRow(ctx, `INSERT INTO country_registry.admin_unit_type
  (id, country_id, canonical_type, local_label, level, is_required, effective_from, created_by)
VALUES (gen_random_uuid(), $1::uuid, $2, $3, $4, $5, current_date, $6) RETURNING id::text`,
			countryID, asked.canonical, asked.label, asked.level, asked.required, p.UserID).Scan(&id)
	})
	if isUnique(err) {
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
			"The country already has a live level with that name or number.")
	}
	if err != nil {
		return nil, s.geographyError(ctx, err)
	}
	s.logger.InfoContext(ctx, "admin unit level defined", "country", asked.code, "level", asked.level, "by", p.UserID)
	defined, err := s.levels(ctx, s.db, `t.id = $1::uuid`, id)
	if err != nil || len(defined) != 1 {
		return nil, apierr.Internal(ctx, s.logger, fmt.Errorf("countryconfig: reading the level defined: %w", err))
	}
	return connect.NewResponse(&countriesv1.DefineAdminUnitLevelResponse{Level: defined[0]}), nil
}

// AddAdminUnit adds a unit to a country that is not yet Active, under a
// parent of a higher level in that country; only a unit of the country's
// top level has none.
func (s *Service) AddAdminUnit(ctx context.Context, req *connect.Request[countriesv1.AddAdminUnitRequest]) (*connect.Response[countriesv1.AddAdminUnitResponse], error) {
	p, err := s.geographyWriter(ctx)
	if err != nil {
		return nil, err
	}
	asked, err := unitOf(req.Msg)
	if err != nil {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, err.Error())
	}
	var id string
	err = s.inGeography(ctx, asked.code, func(tx pgx.Tx, countryID string) error {
		var level, top int16
		err := tx.QueryRow(ctx, `SELECT t.level, (SELECT min(x.level) FROM country_registry.admin_unit_type x
  WHERE x.country_id = t.country_id AND x.effective_to IS NULL)
FROM country_registry.admin_unit_type t WHERE t.id = $1::uuid AND t.country_id = $2::uuid AND t.effective_to IS NULL`,
			asked.levelID, countryID).Scan(&level, &top)
		if errors.Is(err, pgx.ErrNoRows) {
			return refusal("That level is not one of the country's live levels.")
		}
		if err != nil {
			return fmt.Errorf("countryconfig: reading the level: %w", err)
		}
		if asked.parentID == "" && level != top {
			return refusal("A unit below the country's top level needs a parent.")
		}
		if asked.parentID != "" {
			var parentLevel int16
			err := tx.QueryRow(ctx, `SELECT t.level FROM country_registry.admin_unit u
JOIN country_registry.admin_unit_type t ON t.id = u.type_id
WHERE u.id = $1::uuid AND u.country_id = $2::uuid AND u.valid_to IS NULL`, asked.parentID, countryID).Scan(&parentLevel)
			if errors.Is(err, pgx.ErrNoRows) {
				return refusal("The parent is not a live unit of the country.")
			}
			if err != nil {
				return fmt.Errorf("countryconfig: reading the parent: %w", err)
			}
			if parentLevel >= level {
				return refusal("The parent must be at a higher level than the unit.")
			}
		}
		var parent, code any
		if asked.parentID != "" {
			parent = asked.parentID
		}
		if asked.officialCode != "" {
			code = asked.officialCode
		}
		return tx.QueryRow(ctx, `INSERT INTO country_registry.admin_unit
  (id, country_id, type_id, official_name, official_code, parent_id, valid_from, source, verification_status, created_by)
VALUES (gen_random_uuid(), $1::uuid, $2::uuid, $3, $4, $5::uuid, current_date, 'manual', 'unverified', $6) RETURNING id::text`,
			countryID, asked.levelID, asked.name, code, parent, p.UserID).Scan(&id)
	})
	if isUnique(err) {
		return nil, apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
			"Another unit at that level already has that official code.")
	}
	if err != nil {
		return nil, s.geographyError(ctx, err)
	}
	s.logger.InfoContext(ctx, "admin unit added", "country", asked.code, "unit", id, "by", p.UserID)
	rows, err := s.db.Query(ctx, `SELECT `+unitColumns+` FROM country_registry.admin_unit u
JOIN country_registry.admin_unit_type t ON t.id = u.type_id WHERE u.id = $1::uuid`, id)
	if err != nil {
		return nil, apierr.Internal(ctx, s.logger, fmt.Errorf("countryconfig: reading the unit added: %w", err))
	}
	added, err := pgx.CollectRows(rows, scanUnit)
	if err != nil || len(added) != 1 {
		return nil, apierr.Internal(ctx, s.logger, fmt.Errorf("countryconfig: reading the unit added: %w", err))
	}
	return connect.NewResponse(&countriesv1.AddAdminUnitResponse{Unit: added[0]}), nil
}

func (s *Service) geographyWriter(ctx context.Context) (auth.Principal, error) {
	p, err := s.reader(ctx)
	if err != nil {
		return p, err
	}
	if p.ActiveRole != roleAdmin {
		return p, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: only an Admin changes a country's geography.")
	}
	return p, nil
}

// inGeography runs write in one transaction declared for the country with
// code alone, once the country is found and is not yet Active.
func (s *Service) inGeography(ctx context.Context, code string, write func(pgx.Tx, string) error) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
	var id, name, state string
	if err := tx.QueryRow(ctx, `SELECT id::text, name, state FROM country_registry.country WHERE code = $1`, code).
		Scan(&id, &name, &state); err != nil {
		return err
	}
	switch state {
	case country.StateActive, country.StateSuspended, country.StateArchived:
		return refusal(fmt.Sprintf("%s is %s: its geography is its existing application's and changes there.",
			name, strings.ReplaceAll(state, "_", " ")))
	}
	if err := country.WriteFor(ctx, tx, false, id); err != nil {
		return err
	}
	if err := write(tx, id); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func (s *Service) geographyError(ctx context.Context, err error) error {
	var refused refusal
	switch {
	case errors.As(err, &refused):
		return apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument, refused.Error())
	case errors.Is(err, pgx.ErrNoRows):
		return apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "country not found")
	}
	return apierr.Internal(ctx, s.logger, err)
}

func isUnique(err error) bool {
	var pgErr *pgconn.PgError
	return errors.As(err, &pgErr) && pgErr.Code == uniqueKeyCode
}
