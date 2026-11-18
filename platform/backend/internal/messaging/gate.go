package messaging

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ErrHandOn is a thread whose record Go does not yet decide on (an activity
// outside a country lens, a partner hand-over for a partner, officer or
// lead): the inbox is the existing application's to answer.
var ErrHandOn = errors.New("messaging: the inbox is handed on to the existing application")

// record kinds a context resolves to (resolve_context_record).
type recordKind int

const (
	kindNone recordKind = iota
	kindSchool
	kindCluster
	kindActivity
	kindFundRequest
	kindLeave
	kindProject
	kindPartnerAssignment
)

// record is what the gate reads of a resolved record.
type record struct {
	kind  recordKind
	id    string
	owner string // a fund request's responsible user; a leave's staff profile
	// A cluster's lead, district and region.
	clusterLead, districtID, regionID string
}

// gate is can_access_context for one reader, remembering each answer and the
// reader's scope for the request.
type gate struct {
	db      schooldirectory.Querier
	p       auth.Principal
	now     time.Time
	scope   *schooldirectory.Scope
	team    []string // _team_staff_ids
	teamUse []string // _team_user_ids
	answers map[[2]string]bool
}

func newGate(db schooldirectory.Querier, p auth.Principal, now time.Time) *gate {
	return &gate{db: db, p: p, now: now, answers: map[[2]string]bool{}}
}

// allows is can_access_context(user, contextType, contextID).
func (g *gate) allows(ctx context.Context, contextType, contextID string) (bool, error) {
	key := [2]string{contextType, contextID}
	if answer, ok := g.answers[key]; ok {
		return answer, nil
	}
	answer, err := g.decide(ctx, contextType, contextID)
	if err != nil {
		return false, err
	}
	g.answers[key] = answer
	return answer, nil
}

func (g *gate) decide(ctx context.Context, contextType, contextID string) (bool, error) {
	if contextType == "" || contextID == "" {
		return false, nil
	}
	role := slug(g.p.ActiveRole)
	if allowed, decided := roleGate(role, contextType); decided {
		return allowed, nil
	}
	rec, err := resolve(ctx, g.db, contextType, contextID)
	if err != nil {
		return false, err
	}
	switch rec.kind {
	case kindNone:
		return unresolved(role, contextType), nil
	case kindSchool, kindCluster, kindActivity:
		return g.canViewRecord(ctx, rec)
	case kindFundRequest:
		if in(rules.FundRequestReaders, role) || rec.owner == g.p.UserID {
			return true, nil
		}
		if role != slugPL {
			return false, nil
		}
		users, err := g.teamUserIDs(ctx)
		return in(users, rec.owner), err
	case kindLeave:
		if in(rules.LeaveReaders, role) {
			return true, nil
		}
		if role == slugPL {
			staff, err := g.teamStaffIDs(ctx)
			return in(staff, rec.owner), err
		}
		return g.p.StaffProfileID != "" && rec.owner == g.p.StaffProfileID, nil
	case kindPartnerAssignment:
		if role == slugPartner || in(rules.PartnerAssignmentScoped, role) {
			return false, ErrHandOn
		}
		return in(rules.PartnerAssignmentReaders, role), nil
	}
	// A project, once found.
	return true, nil
}

// roleGate is can_access_context's answers before any record is read: the
// Admin opens everything, an Accountant only money and leave, a partner no
// money but disbursements, and a key nobody defined is no context.
func roleGate(role, contextType string) (allowed, decided bool) {
	finance := in(rules.FinanceContexts, contextType)
	switch {
	case role == slugAdmin:
		return true, true
	case role == slugAccountant && !finance && contextType != "leave":
		return false, true
	case role == slugPartner && finance && contextType != "accountant_disbursement":
		return false, true
	}
	if contextLabel(contextType) == "" {
		return false, true
	}
	return false, false
}

// unresolved is the answer for a context that resolves to no record: the IA
// contexts by role, the workflow stages by their participants, nothing else.
func unresolved(role, contextType string) bool {
	if in(rules.IAContexts, contextType) {
		return in(rules.IAUnresolvedRoles, role)
	}
	if roles, stage := rules.StageContexts[contextType]; stage {
		return in(roles, role)
	}
	return false
}

// resolve is resolve_context_record's record, through the same managers:
// soft-deleted schools, clusters, activities and projects are not found.
func resolve(ctx context.Context, db schooldirectory.Querier, contextType, contextID string) (record, error) {
	switch contextType {
	case "schedule":
		contextType = "school"
	case "field_debrief":
		contextType = "activity"
	}
	rec := record{}
	var statement string
	switch {
	case contextType == "school":
		// .first() on an unordered queryset orders by the primary key.
		rec.kind, statement = kindSchool, `SELECT id, '', '', '', '' FROM school WHERE deleted_at IS NULL AND (id = $1 OR school_id = $1) ORDER BY id ASC LIMIT 1`
	case contextType == "cluster":
		rec.kind, statement = kindCluster, `SELECT id, '', COALESCE(responsible_staff_id, ''), COALESCE(district_id, ''), COALESCE(region_id, '') FROM cluster WHERE deleted_at IS NULL AND id = $1 ORDER BY id ASC LIMIT 1`
	case in(rules.ActivityContexts, contextType):
		rec.kind, statement = kindActivity, `SELECT id, '', '', '', '' FROM activity WHERE deleted_at IS NULL AND id = $1 ORDER BY id ASC LIMIT 1`
	case contextType == "fund_request" || contextType == "accountant_disbursement":
		rec.kind, statement = kindFundRequest, `SELECT id, COALESCE(responsible_user, ''), '', '', '' FROM weekly_fund_request WHERE id = $1 ORDER BY id ASC LIMIT 1`
	case contextType == "leave":
		// The label reads the leave's staff member's name; a leave whose
		// person cannot be read resolves to nothing.
		rec.kind, statement = kindLeave, `SELECT l.id, l.staff_id, '', '', '' FROM leave l
JOIN staff_profile sp ON sp.id = l.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE l.id = $1 ORDER BY l.id ASC LIMIT 1`
	case contextType == "project":
		rec.kind, statement = kindProject, `SELECT id, '', '', '', '' FROM project WHERE deleted_at IS NULL AND id = $1 ORDER BY id ASC LIMIT 1`
	case contextType == "partner_assignment":
		rec.kind, statement = kindPartnerAssignment, `SELECT id, '', '', '', '' FROM partner_assignment WHERE id = $1 ORDER BY id ASC LIMIT 1`
	default:
		return record{}, nil
	}
	err := db.QueryRow(ctx, statement, contextID).Scan(&rec.id, &rec.owner, &rec.clusterLead, &rec.districtID, &rec.regionID)
	if errors.Is(err, pgx.ErrNoRows) {
		return record{}, nil
	}
	if err != nil {
		return record{}, fmt.Errorf("messaging: reading the thread's record: %w", err)
	}
	return rec, nil
}

// canViewRecord is RolePermissionService.can_view_record for a school, a
// cluster or an activity.
func (g *gate) canViewRecord(ctx context.Context, rec record) (bool, error) {
	switch g.p.ActiveRole {
	case roleCountryDirector:
		if !rules.AllowCDOperational {
			return false, nil
		}
	case roleRVP:
		return false, nil
	}
	scope, err := g.readerScope(ctx)
	if err != nil {
		return false, err
	}
	switch rec.kind {
	case kindSchool:
		if in(scope.SchoolIDs, rec.id) {
			return true, nil
		}
		if scope.CountryScope {
			// A country reader's own country's schools (docs/migration/80,
			// §21); an unbounded one (the Admin, a regional role) every school.
			return g.inCountry(ctx, scope, `SELECT EXISTS (SELECT 1 FROM school s WHERE s.id = $1 AND `+registry.SchoolHeldIn("s", "$2")+`)`, rec.id)
		}
		return g.openTo(ctx, rec.id)
	case kindCluster:
		return clusterpage.ClusterReadable(ctx, g.db, scope, rec.id, rec.clusterLead, rec.districtID, rec.regionID)
	}
	if scope.CountryScope {
		return g.inCountry(ctx, scope, `SELECT EXISTS (SELECT 1 FROM activity a LEFT JOIN school s ON s.id = a.school_id
  LEFT JOIN cluster cl ON cl.id = a.cluster_id WHERE a.id = $1 AND `+registry.ActivityHeldIn("a", "s", "cl", "$2")+`)`, rec.id)
	}
	return false, ErrHandOn
}

// inCountry runs check (its $1 the record's id, $2 the scope's country) for
// a country reader bounded to a country; one unbounded reads every record.
// Records the registry places in no country are Uganda's, as the existing
// application, which served Uganda alone, let every country reader open
// them.
func (g *gate) inCountry(ctx context.Context, scope schooldirectory.Scope, check, id string) (bool, error) {
	if scope.Country == "" {
		return true, nil
	}
	var ok bool
	if err := g.db.QueryRow(ctx, check, id, scope.CountryIDs()).Scan(&ok); err != nil {
		return false, fmt.Errorf("messaging: reading the record's country: %w", err)
	}
	return ok, nil
}

// openTo is data_gaps.open_to: field staff may open a school nobody holds in
// their country.
func (g *gate) openTo(ctx context.Context, schoolID string) (bool, error) {
	if !in(rules.FieldRoles, g.p.ActiveRole) || g.p.StaffProfileID == "" {
		return false, nil
	}
	country, err := schooldirectory.OfficerCountry(ctx, g.db, g.p.UserID)
	if err != nil {
		return false, err
	}
	if g.p.Country.FromRegistry() {
		// The country they work in, not their profile's (docs/migration/80,
		// §21).
		country = g.p.Country.Name
	}
	return schooldirectory.UnheldInCountry(ctx, g.db, country, schoolID)
}

func (g *gate) readerScope(ctx context.Context) (schooldirectory.Scope, error) {
	if g.scope == nil {
		scope, err := schooldirectory.ResolveScope(ctx, g.db, g.p, g.now)
		if err != nil {
			return schooldirectory.Scope{}, fmt.Errorf("messaging: reading the reader's scope: %w", err)
		}
		g.scope = &scope
	}
	return *g.scope, nil
}

// teamStaffIDs is _team_staff_ids: the reader's supervisees and their own
// staff profile.
func (g *gate) teamStaffIDs(ctx context.Context) ([]string, error) {
	if g.team == nil {
		scope, err := g.readerScope(ctx)
		if err != nil {
			return nil, err
		}
		team := append([]string{}, scope.SupervisedStaffIDs...)
		if g.p.StaffProfileID != "" {
			team = append(team, g.p.StaffProfileID)
		}
		g.team = team
	}
	return g.team, nil
}

// teamUserIDs is _team_user_ids: the accounts behind teamStaffIDs (live
// staff profiles only) and the reader's own.
func (g *gate) teamUserIDs(ctx context.Context) ([]string, error) {
	if g.teamUse != nil {
		return g.teamUse, nil
	}
	staff, err := g.teamStaffIDs(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := g.db.Query(ctx, `SELECT user_id FROM staff_profile WHERE deleted_at IS NULL AND id = ANY($1) AND user_id IS NOT NULL AND user_id <> ''`, staff)
	if err != nil {
		return nil, fmt.Errorf("messaging: reading the team's accounts: %w", err)
	}
	users, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, fmt.Errorf("messaging: reading the team's accounts: %w", err)
	}
	g.teamUse = append(users, g.p.UserID)
	return g.teamUse, nil
}

// fixedContextLabels are labels the existing page lacks for contexts it
// lists: an "evidence" thread had none, so the page refused it to everyone
// but the Admin; Go labels it as its list's Impact Assessment context
// (owner, 2026-11-13: "Can you fix those from the go side").
var fixedContextLabels = map[string]string{"evidence": "Evidence"}

// contextLabel is a context's label: the existing page's, else Go's fix.
func contextLabel(contextType string) string {
	if label, ok := rules.ContextLabels[contextType]; ok {
		return label
	}
	return fixedContextLabels[contextType]
}
