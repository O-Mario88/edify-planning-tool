package countryconfig

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"

	countriesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/peopledirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Role and scope per country (docs/migration/80-multi-country-phase-0.md
// §12): in a country whose roles come from the registry, an account works
// only in the roles assigned to it there, each with the scope its kind of
// role has. Uganda's roles stay the existing profile's and are never
// recorded here.

// maxRegionID is the existing region id's width.
const maxRegionID = 30

// roleAsked is a checked AssignCountryRoleRequest.
type roleAsked struct {
	membershipID, role, scopeType, reason string
	regionIDs                             []string
}

func roleOf(r *countriesv1.AssignCountryRoleRequest) (roleAsked, error) {
	a := roleAsked{
		membershipID: strings.TrimSpace(r.GetMembershipId()), role: strings.TrimSpace(r.GetRole()),
		reason: strings.TrimSpace(r.GetReason()), regionIDs: []string{},
	}
	a.scopeType = schooldirectory.ScopeTypeOf(a.role)
	regionsWellFormed := true
	for _, id := range r.GetRegionIds() {
		id = strings.TrimSpace(id)
		regionsWellFormed = regionsWellFormed && id != "" && len(id) <= maxRegionID
		if id != "" && !slices.Contains(a.regionIDs, id) {
			a.regionIDs = append(a.regionIDs, id)
		}
	}
	checks := []error{
		check(membershipID.MatchString(a.membershipID), "membership_id must be a membership's id"),
		check(rbac.IsRole(a.role), "role must be one of the roles the platform defines"),
		check(a.role != roleAdmin, "Admin is the platform's own role: it is not held in one country"),
		check(regionsWellFormed, "region_ids must be region ids"),
		reasonOf("reason", a.reason),
	}
	if a.scopeType == country.ScopeRegions {
		checks = append(checks, check(len(a.regionIDs) > 0, a.role+" covers regions: name at least one"))
	} else {
		checks = append(checks, check(len(a.regionIDs) == 0, "region_ids are only for a role that covers regions"))
	}
	return a, errors.Join(checks...)
}

// assignableRoles are the roles an Admin may assign in a country, in the
// platform's order, each with its kind of scope.
func assignableRoles() []*countriesv1.AssignableRole {
	out := []*countriesv1.AssignableRole{}
	for _, role := range rbac.Roles() {
		if role != roleAdmin {
			out = append(out, &countriesv1.AssignableRole{Role: role, ScopeType: schooldirectory.ScopeTypeOf(role),
				Label: peopledirectory.RoleLabel(role)})
		}
	}
	return out
}

// regionsFor are the existing regions of the countries userID belongs to
// whose roles come from the registry, by country then name.
func regionsFor(ctx context.Context, q country.Querier, userID string) ([]*countriesv1.Region, error) {
	rows, err := q.Query(ctx, `SELECT g.id, g.name, c.code FROM region g
JOIN country_registry.country_alias a ON a.alias = btrim(g.country)
JOIN country_registry.country c ON c.id = a.country_id
WHERE c.roles_source = $2 AND c.id IN (SELECT m.country_id FROM country_registry.country_membership m WHERE m.user_id = $1)
ORDER BY c.code, g.name, g.id`, userID, country.RolesFromRegistry)
	if err != nil {
		return nil, fmt.Errorf("countryconfig: reading the regions: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (*countriesv1.Region, error) {
		r := &countriesv1.Region{}
		return r, row.Scan(&r.Id, &r.Name, &r.CountryCode)
	})
}

// withRoles fills each membership's roles, newest first.
func withRoles(ctx context.Context, q country.Querier, ms []*countriesv1.Membership) ([]*countriesv1.Membership, error) {
	if len(ms) == 0 {
		return ms, nil
	}
	byID := map[string]*countriesv1.Membership{}
	ids := []string{}
	for _, m := range ms {
		byID[m.GetId()] = m
		ids = append(ids, m.GetId())
	}
	rows, err := q.Query(ctx, `SELECT r.id::text, r.membership_id::text, r.role_name, r.scope_type, r.region_ids,
  ARRAY(SELECT COALESCE(g.name, u.id) FROM unnest(r.region_ids) WITH ORDINALITY AS u(id, n)
        LEFT JOIN region g ON g.id = u.id ORDER BY u.n),
  r.granted_by, r.grant_reason, r.granted_at, COALESCE(r.revoked_by, ''), r.revoked_at, COALESCE(r.revoke_reason, '')
FROM country_registry.country_role_assignment r WHERE r.membership_id::text = ANY($1)
ORDER BY r.granted_at DESC, r.id`, ids)
	if err != nil {
		return nil, fmt.Errorf("countryconfig: reading the roles: %w", err)
	}
	roles, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (*countriesv1.CountryRole, error) {
		r := &countriesv1.CountryRole{}
		var (
			granted time.Time
			revoked *time.Time
		)
		err := row.Scan(&r.Id, &r.MembershipId, &r.Role, &r.ScopeType, &r.RegionIds, &r.RegionNames, &r.GrantedBy,
			&r.GrantReason, &granted, &r.RevokedBy, &revoked, &r.RevokeReason)
		r.GrantedAt, r.RoleLabel = granted.UTC().Format(time.RFC3339), peopledirectory.RoleLabel(r.Role)
		if revoked != nil {
			r.RevokedAt = revoked.UTC().Format(time.RFC3339)
		}
		return r, err
	})
	if err != nil {
		return nil, fmt.Errorf("countryconfig: reading the roles: %w", err)
	}
	for _, r := range roles {
		if m := byID[r.GetMembershipId()]; m != nil {
			m.Roles = append(m.Roles, r)
		}
	}
	return ms, nil
}

// membership answers with the one membership id names, roles included.
func (s *Service) membership(ctx context.Context, id string) (*countriesv1.Membership, error) {
	found, err := memberships(ctx, s.db, `m.id = $1::uuid`, id)
	if err != nil || len(found) != 1 {
		return nil, fmt.Errorf("countryconfig: reading membership %s: %w", id, err)
	}
	return found[0], nil
}

// AssignCountryRole records a role an account holds in a country.
func (s *Service) AssignCountryRole(ctx context.Context, req *connect.Request[countriesv1.AssignCountryRoleRequest]) (*connect.Response[countriesv1.AssignCountryRoleResponse], error) {
	p, err := s.manager(ctx)
	if err != nil {
		return nil, err
	}
	asked, err := roleOf(req.Msg)
	if err != nil {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, err.Error())
	}
	if err := s.assign(ctx, p, asked); err != nil {
		return nil, s.refused(ctx, err)
	}
	m, err := s.membership(ctx, asked.membershipID)
	if err != nil {
		return nil, apierr.Internal(ctx, s.logger, err)
	}
	return connect.NewResponse(&countriesv1.AssignCountryRoleResponse{Membership: m}), nil
}

// RevokeCountryRole revokes a role held in a country, keeping its record.
func (s *Service) RevokeCountryRole(ctx context.Context, req *connect.Request[countriesv1.RevokeCountryRoleRequest]) (*connect.Response[countriesv1.RevokeCountryRoleResponse], error) {
	p, err := s.manager(ctx)
	if err != nil {
		return nil, err
	}
	id, reason := strings.TrimSpace(req.Msg.GetRoleId()), strings.TrimSpace(req.Msg.GetReason())
	if err := errors.Join(check(membershipID.MatchString(id), "role_id must be a country role's id"),
		reasonOf("reason", reason)); err != nil {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, err.Error())
	}
	membershipOf, err := s.revokeRole(ctx, p, id, reason)
	if err != nil {
		return nil, s.refused(ctx, err)
	}
	m, err := s.membership(ctx, membershipOf)
	if err != nil {
		return nil, apierr.Internal(ctx, s.logger, err)
	}
	return connect.NewResponse(&countriesv1.RevokeCountryRoleResponse{Membership: m}), nil
}

// assign writes the role in one transaction declared for the membership's
// country alone, holding the account's lock, after every check that would
// refuse it.
func (s *Service) assign(ctx context.Context, p auth.Principal, a roleAsked) error {
	var (
		userID, countryID, name, source string
		revoked, ended                  bool
	)
	err := s.db.QueryRow(ctx, `SELECT m.user_id, c.id::text, c.name, c.roles_source, m.revoked_at IS NOT NULL,
  m.effective_until IS NOT NULL AND m.effective_until <= current_date
FROM country_registry.country_membership m JOIN country_registry.country c ON c.id = m.country_id
WHERE m.id = $1::uuid`, a.membershipID).Scan(&userID, &countryID, &name, &source, &revoked, &ended)
	if errors.Is(err, pgx.ErrNoRows) {
		return notFound("membership not found")
	}
	if err != nil {
		return fmt.Errorf("countryconfig: reading the membership: %w", err)
	}
	switch {
	case userID == p.UserID:
		return refusal("An Admin's own roles are assigned by another Admin.")
	case source != country.RolesFromRegistry:
		return refusal(fmt.Sprintf("%s's roles come from each account's profile in the existing application; change them there.", name))
	case revoked:
		return refusal(fmt.Sprintf("This membership of %s is revoked: grant the country again before assigning a role.", name))
	case ended:
		return refusal(fmt.Sprintf("This membership of %s has ended: grant the country again before assigning a role.", name))
	}

	tx, err := s.writing(ctx, userID)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
	var regionsOfCountry int
	var held bool
	if err := tx.QueryRow(ctx, `SELECT
  (SELECT count(DISTINCT g.id) FROM region g JOIN country_registry.country_alias al ON al.alias = btrim(g.country)
   WHERE g.id = ANY($3) AND al.country_id = $2::uuid),
  EXISTS (SELECT 1 FROM country_registry.country_role_assignment r
   WHERE r.membership_id = $1::uuid AND r.role_name = $4 AND r.revoked_at IS NULL)`,
		a.membershipID, countryID, a.regionIDs, a.role).Scan(&regionsOfCountry, &held); err != nil {
		return fmt.Errorf("countryconfig: reading the role's regions: %w", err)
	}
	if held {
		return refusal(fmt.Sprintf("This account already holds %s in %s.", a.role, name))
	}
	if regionsOfCountry != len(a.regionIDs) {
		return refusal(fmt.Sprintf("Every region must be one of %s's.", name))
	}
	if err := country.WriteFor(ctx, tx, false, countryID); err != nil {
		return err
	}
	if _, err := tx.Exec(ctx, `INSERT INTO country_registry.country_role_assignment
  (id, membership_id, country_id, user_id, role_name, scope_type, region_ids, granted_by, grant_reason)
VALUES (gen_random_uuid(), $1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8)`,
		a.membershipID, countryID, userID, a.role, a.scopeType, a.regionIDs, p.UserID, a.reason); err != nil {
		return fmt.Errorf("countryconfig: assigning the role: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return err
	}
	s.logger.InfoContext(ctx, "country role assigned", "membership", a.membershipID, "user", userID, "role", a.role, "by", p.UserID)
	return nil
}

// revokeRole marks the role revoked in one transaction declared for its
// country alone, and names the membership it was held under.
func (s *Service) revokeRole(ctx context.Context, p auth.Principal, id, reason string) (string, error) {
	var userID, countryID, membershipOf string
	err := s.db.QueryRow(ctx, `SELECT user_id, country_id::text, membership_id::text
FROM country_registry.country_role_assignment WHERE id = $1::uuid`, id).Scan(&userID, &countryID, &membershipOf)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", notFound("country role not found")
	}
	if err != nil {
		return "", fmt.Errorf("countryconfig: reading the role: %w", err)
	}
	if userID == p.UserID {
		return "", refusal("An Admin's own roles are revoked by another Admin.")
	}
	tx, err := s.writing(ctx, userID)
	if err != nil {
		return "", err
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
	if err := country.WriteFor(ctx, tx, false, countryID); err != nil {
		return "", err
	}
	tag, err := tx.Exec(ctx, `UPDATE country_registry.country_role_assignment
SET revoked_at = now(), revoked_by = $2, revoke_reason = $3 WHERE id = $1::uuid AND revoked_at IS NULL`, id, p.UserID, reason)
	if err != nil {
		return "", fmt.Errorf("countryconfig: revoking the role: %w", err)
	}
	if tag.RowsAffected() != 1 {
		return "", refusal("This role is already revoked.")
	}
	if err := tx.Commit(ctx); err != nil {
		return "", err
	}
	s.logger.InfoContext(ctx, "country role revoked", "role", id, "user", userID, "by", p.UserID)
	return membershipOf, nil
}
