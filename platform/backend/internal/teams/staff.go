// Package teams is staff and partner team management, owned by Go (owner
// brief, 2026-11-11: "Staff and partner team management"): who supervises
// whom, the people a manager manages, and a partner organisation's own team.
// The rules are the existing application's (apps/accounts/supervisor_service.py,
// apps/partners/services.py, member_logins.py, school_team.py), on the
// existing records.
package teams

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
)

// Roles the existing team rules name (EdifyRole values).
const (
	roleCCEO        = "CCEO"
	roleProgramLead = "Program Lead"
	roleCD          = "CountryDirector"
	roleIA          = "ImpactAssessment"
	roleRVP         = "RegionalVicePresident"
	roleAccountant  = "Accountant"
	roleBTO         = "BusinessTransformationOfficer"
	rolePartnerAdm  = "PartnerAdmin"
	rolePartnerFO   = "PartnerFieldOfficer"
)

// Permission keys.
const (
	permStaffView   = "staffPerformance.view"
	permStaffManage = "staff.manage"
)

// supervisorRole is _SUPERVISOR_ROLE: the role that should supervise a role.
var supervisorRole = map[string]string{roleCCEO: roleProgramLead, roleProgramLead: roleCD}

// managerRoles are the roles that manage people (_MANAGER_ROLES).
var managerRoles = []string{roleProgramLead, roleCD, roleIA, roleRVP}

// cdTeamRoles are the roles a Country Director's country team holds.
var cdTeamRoles = []string{roleProgramLead, roleIA, roleAccountant, roleCCEO}

// countryRoles see the whole country (apps/core/scoping.py COUNTRY_ROLES).
var countryRoles = []string{roleCD, roleIA, roleAccountant, roleBTO, rbac.Admin}

// internalRoles is _INTERNAL_MANAGED_ROLES: every role but the Admin and
// the partner roles.
func internalRoles() []string {
	var out []string
	for _, role := range rbac.Roles() {
		if role != rbac.Admin && role != rolePartnerAdm && role != rolePartnerFO {
			out = append(out, role)
		}
	}
	return out
}

// Refused is a request the rules do not allow, in words for the person.
type Refused struct {
	Message   string
	NotFound  bool
	Forbidden bool
	Conflict  bool
}

func (r *Refused) Error() string { return r.Message }

func refuse(message string) error    { return &Refused{Message: message} }
func notFound(message string) error  { return &Refused{Message: message, NotFound: true} }
func forbidden(message string) error { return &Refused{Message: message, Forbidden: true} }

// Store reads and writes teams.
type Store struct{ db *pgxpool.Pool }

// NewStore returns a Store on pool.
func NewStore(pool *pgxpool.Pool) *Store { return &Store{db: pool} }

func (s *Store) write(ctx context.Context, fn func(pgx.Tx) error) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("teams: opening a transaction: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if err := fn(tx); err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("teams: committing: %w", err)
	}
	return nil
}

type querier interface {
	Query(context.Context, string, ...any) (pgx.Rows, error)
}

// person is a staff profile with its account.
type person struct {
	StaffID, UserID, Name, Email, ActiveRole, Status string
	Roles                                            []string
	Title, Onboarding, Country                       string
}

func (p person) holds(role string) bool {
	return p.ActiveRole == role || slices.Contains(p.Roles, role)
}

func (p person) holdsAny(roles []string) bool {
	return slices.ContainsFunc(roles, p.holds)
}

// managementRole is _management_role: the active role when it manages
// people, otherwise the first held role that does.
func (p person) managementRole() string {
	if slices.Contains(managerRoles, p.ActiveRole) {
		return p.ActiveRole
	}
	for _, role := range p.Roles {
		if slices.Contains(managerRoles, role) {
			return role
		}
	}
	return ""
}

const personSelect = `
SELECT sp.id, u.id, u.name, u.email, u.active_role, u.status, u.roles, COALESCE(sp.title, ''),
       sp.onboarding_state, sp.country
FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND u.deleted_at IS NULL`

func scanPerson(row pgx.Row) (person, error) {
	var p person
	err := row.Scan(&p.StaffID, &p.UserID, &p.Name, &p.Email, &p.ActiveRole, &p.Status, &p.Roles, &p.Title,
		&p.Onboarding, &p.Country)
	return p, err
}

func (s *Store) people(ctx context.Context, q querier, where string, args ...any) ([]person, error) {
	rows, err := q.Query(ctx, personSelect+where+` ORDER BY u.name, sp.id`, args...)
	if err != nil {
		return nil, fmt.Errorf("teams: reading staff: %w", err)
	}
	defer rows.Close()
	var out []person
	for rows.Next() {
		p, err := scanPerson(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

func personFound(row pgx.Row) (person, error) {
	p, err := scanPerson(row)
	if errors.Is(err, pgx.ErrNoRows) {
		return person{}, notFound("Staff member not found.")
	}
	return p, err
}

// link is a staff_supervisor_assignment row with its supervisor.
type link struct {
	ID, SuperviseeID string
	Supervisor       person
}

func (s *Store) linksOf(ctx context.Context, q querier, superviseeIDs []string) ([]link, error) {
	rows, err := q.Query(ctx, `
SELECT a.id, a.supervisee_id, sp.id, u.id, u.name, u.email, u.active_role, u.status, u.roles,
       COALESCE(sp.title, ''), sp.onboarding_state, sp.country
FROM staff_supervisor_assignment a
JOIN staff_profile sp ON sp.id = a.supervisor_id
JOIN "user" u ON u.id = sp.user_id
WHERE a.supervisee_id = ANY($1)
ORDER BY a.created_at, a.id`, superviseeIDs)
	if err != nil {
		return nil, fmt.Errorf("teams: reading reporting lines: %w", err)
	}
	defer rows.Close()
	var out []link
	for rows.Next() {
		var l link
		p := &l.Supervisor
		if err := rows.Scan(&l.ID, &l.SuperviseeID, &p.StaffID, &p.UserID, &p.Name, &p.Email, &p.ActiveRole, &p.Status,
			&p.Roles, &p.Title, &p.Onboarding, &p.Country); err != nil {
			return nil, err
		}
		out = append(out, l)
	}
	return out, rows.Err()
}

// directLine is the person's reporting line: the first link whose
// supervisor holds the role that should supervise them, or, when their role
// names none, the first link.
func directLine(links []link, superviseeRole string) (link, bool) {
	expected := supervisorRole[superviseeRole]
	for _, l := range links {
		if expected == "" || l.Supervisor.holds(expected) {
			return l, true
		}
	}
	return link{}, false
}

// ── Service ──────────────────────────────────────────────────────────────

// StaffMember is a roster row.
type StaffMember struct {
	person
	SupervisorStaffID, SupervisorName string
	AssignedSchools                   int
}

// StaffService is staff teams.
type StaffService struct {
	store *Store
	now   func() time.Time
	// changed tells the existing application a staff or team change was
	// made, so its cached analytics are filed afresh.
	changed func()
}

// NewStaffService returns the service.
func NewStaffService(store *Store, now func() time.Time, changed func()) *StaffService {
	if changed == nil {
		changed = func() {}
	}
	return &StaffService{store: store, now: now, changed: changed}
}

// List is list_staff: everyone for the Admin and the country roles; the
// people a manager supervises, and themselves, for everyone else.
func (s *StaffService) List(ctx context.Context, principal auth.Principal, search string) ([]StaffMember, error) {
	if !rbac.Grants(principal.ActiveRole, permStaffView) {
		return nil, forbidden("You do not have access to the staff roster.")
	}
	where, args := "", []any{}
	if !slices.Contains(countryRoles, principal.ActiveRole) {
		where = ` AND (sp.id = $1 OR sp.id IN (SELECT a.supervisee_id FROM staff_supervisor_assignment a WHERE a.supervisor_id = $1))`
		args = append(args, principal.StaffProfileID)
	}
	if search = strings.TrimSpace(search); search != "" {
		args = append(args, search)
		n := len(args)
		where += fmt.Sprintf(` AND (u.name ILIKE '%%' || $%d || '%%' OR u.email ILIKE '%%' || $%d || '%%')`, n, n)
	}
	people, err := s.store.people(ctx, s.store.db, where, args...)
	if err != nil {
		return nil, err
	}
	return s.rows(ctx, people)
}

func (s *StaffService) rows(ctx context.Context, people []person) ([]StaffMember, error) {
	ids := make([]string, len(people))
	for i, p := range people {
		ids[i] = p.StaffID
	}
	links, err := s.store.linksOf(ctx, s.store.db, ids)
	if err != nil {
		return nil, err
	}
	bySupervisee := map[string][]link{}
	for _, l := range links {
		bySupervisee[l.SuperviseeID] = append(bySupervisee[l.SuperviseeID], l)
	}
	counts := map[string]int{}
	rows, err := s.store.db.Query(ctx,
		`SELECT staff_id, count(*) FROM staff_school_assignment WHERE staff_id = ANY($1) GROUP BY staff_id`, ids)
	if err != nil {
		return nil, fmt.Errorf("teams: counting schools: %w", err)
	}
	for rows.Next() {
		var id string
		var n int
		if err := rows.Scan(&id, &n); err != nil {
			rows.Close()
			return nil, err
		}
		counts[id] = n
	}
	rows.Close()
	out := make([]StaffMember, len(people))
	for i, p := range people {
		out[i] = StaffMember{person: p, AssignedSchools: counts[p.StaffID]}
		if line, ok := directLine(bySupervisee[p.StaffID], p.ActiveRole); ok {
			out[i].SupervisorStaffID, out[i].SupervisorName = line.Supervisor.StaffID, line.Supervisor.Name
		}
	}
	return out, nil
}

// SupervisorChoices is who supervises a person now, and who may.
type SupervisorChoices struct {
	Staff        StaffMember
	ExpectedRole string
	Choices      []person
}

// Supervisor reads a person's reporting line and the people who could hold
// it: those of the role that should, or any manager when no role is set.
func (s *StaffService) Supervisor(ctx context.Context, principal auth.Principal, userID string) (SupervisorChoices, error) {
	if !rbac.Grants(principal.ActiveRole, permStaffManage) {
		return SupervisorChoices{}, forbidden("You do not have permission to assign supervisors.")
	}
	supervisee, err := personFound(s.store.db.QueryRow(ctx, personSelect+` AND u.id = $1`, userID))
	if err != nil {
		return SupervisorChoices{}, err
	}
	rows, err := s.rows(ctx, []person{supervisee})
	if err != nil {
		return SupervisorChoices{}, err
	}
	expected := supervisorRole[supervisee.ActiveRole]
	wanted := managerRoles
	if expected != "" {
		wanted = []string{expected}
	}
	everyone, err := s.store.people(ctx, s.store.db, ` AND sp.id <> $1`, supervisee.StaffID)
	if err != nil {
		return SupervisorChoices{}, err
	}
	var choices []person
	for _, p := range everyone {
		if p.holdsAny(wanted) {
			choices = append(choices, p)
		}
	}
	return SupervisorChoices{Staff: rows[0], ExpectedRole: expected, Choices: choices}, nil
}

// Reassigned is a reporting line changed.
type Reassigned struct {
	OldSupervisorStaffID, NewSupervisorStaffID, NewSupervisorName string
}

// AssignSupervisor is assign_supervisor: the supervisor must work in the
// role that should supervise the person (an Admin may decide otherwise); only
// the direct reporting line is replaced, oversight links stay.
func (s *StaffService) AssignSupervisor(ctx context.Context, principal auth.Principal, userID, supervisorStaffID string) (Reassigned, error) {
	var result Reassigned
	err := s.store.write(ctx, func(tx pgx.Tx) error {
		var err error
		result, err = s.AssignSupervisorInTx(ctx, tx, principal, userID, supervisorStaffID, s.now())
		return err
	})
	if err == nil {
		s.changed()
	}
	return result, err
}

// AssignSupervisorInTx is AssignSupervisor inside the caller's transaction
// (an account created with its supervisor, as create() does); the caller
// commits and tells the existing application the staff changed.
func (s *StaffService) AssignSupervisorInTx(ctx context.Context, tx pgx.Tx, principal auth.Principal, userID, supervisorStaffID string,
	now time.Time) (Reassigned, error) {
	if !rbac.Grants(principal.ActiveRole, permStaffManage) {
		return Reassigned{}, forbidden("You do not have permission to assign supervisors.")
	}
	supervisorStaffID = strings.TrimSpace(supervisorStaffID)
	if supervisorStaffID == "" {
		return Reassigned{}, refuse("A supervisorId is required.")
	}
	var result Reassigned
	err := func() error {
		supervisee, err := personFound(tx.QueryRow(ctx, personSelect+` AND u.id = $1 FOR UPDATE OF sp`, userID))
		if err != nil {
			return err
		}
		supervisor, err := scanPerson(tx.QueryRow(ctx, personSelect+` AND sp.id = $1`, supervisorStaffID))
		if errors.Is(err, pgx.ErrNoRows) {
			return notFound("Supervisor not found.")
		}
		if err != nil {
			return err
		}
		if supervisor.StaffID == supervisee.StaffID {
			return refuse("A staff member cannot supervise themselves.")
		}
		expected := supervisorRole[supervisee.ActiveRole]
		if expected != "" && supervisor.ActiveRole != expected && principal.ActiveRole != rbac.Admin {
			return refuse(fmt.Sprintf("A %s should be supervised by a %s, not a %s.",
				supervisee.ActiveRole, expected, supervisor.ActiveRole))
		}
		links, err := s.store.linksOf(ctx, tx, []string{supervisee.StaffID})
		if err != nil {
			return err
		}
		old, hasOld := directLine(links, supervisee.ActiveRole)
		if hasOld {
			result.OldSupervisorStaffID = old.Supervisor.StaffID
		}
		if hasOld && old.Supervisor.StaffID != supervisor.StaffID {
			if _, err := tx.Exec(ctx, `DELETE FROM staff_supervisor_assignment WHERE id = $1`, old.ID); err != nil {
				return err
			}
			hasOld = false
		}
		if !hasOld {
			if err := ensureLink(ctx, tx, supervisee.StaffID, supervisor.StaffID, now); err != nil {
				return err
			}
		}
		result.NewSupervisorStaffID, result.NewSupervisorName = supervisor.StaffID, supervisor.Name
		_, err = audit.Append(ctx, tx, audit.Entry{
			Action: "admin.supervisor_reassigned", SubjectKind: audit.Text("staff_profile"),
			SubjectID: audit.Text(supervisee.StaffID), ActorID: audit.Text(principal.UserID),
			ActorRole: audit.Text(principal.ActiveRole), Success: true,
			Payload: map[string]any{"oldSupervisorId": nilIfEmpty(result.OldSupervisorStaffID),
				"newSupervisorId": supervisor.StaffID},
		}, now)
		return err
	}()
	return result, err
}

// ensureLink is get_or_create on (supervisee, supervisor).
func ensureLink(ctx context.Context, tx pgx.Tx, supervisee, supervisor string, now time.Time) error {
	var exists bool
	if err := tx.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM staff_supervisor_assignment WHERE supervisee_id = $1 AND supervisor_id = $2)`,
		supervisee, supervisor).Scan(&exists); err != nil || exists {
		return err
	}
	_, err := tx.Exec(ctx, `
INSERT INTO staff_supervisor_assignment (id, supervisee_id, supervisor_id, created_at, updated_at)
VALUES ($1, $2, $3, $4, $4)`, cuid.New(), supervisee, supervisor, now)
	return err
}

// ManagedTeam is managed_people_team.
type ManagedTeam struct {
	Role, Country string
	Automatic     bool
	People        []ManagedPerson
}

// ManagedPerson is one person a manager could manage.
type ManagedPerson struct {
	person
	Assigned     bool
	OtherManager string
}

// eligibleFor is _eligible_managed_people: same-country staff a manager may
// manage — CCEOs for a Program Lead, the country team's roles for a Country
// Director, any Edify staff role otherwise.
func eligibleFor(manager person, managerRole string, candidates []person) []person {
	allowed := internalRoles()
	switch managerRole {
	case roleProgramLead:
		allowed = []string{roleCCEO}
	case roleCD:
		allowed = cdTeamRoles
	}
	var out []person
	for _, p := range candidates {
		if p.StaffID != manager.StaffID && p.Country == manager.Country && p.holdsAny(allowed) {
			out = append(out, p)
		}
	}
	return out
}

// Team is managed_people_team, for the Admin.
func (s *StaffService) Team(ctx context.Context, principal auth.Principal, userID string) (ManagedTeam, error) {
	if principal.ActiveRole != rbac.Admin {
		return ManagedTeam{}, forbidden("Only an Admin can configure managed people.")
	}
	manager, err := personFound(s.store.db.QueryRow(ctx, personSelect+` AND u.id = $1`, userID))
	if err != nil {
		return ManagedTeam{}, err
	}
	role := manager.managementRole()
	if role == "" {
		return ManagedTeam{}, nil
	}
	candidates, err := s.store.people(ctx, s.store.db, ` AND sp.country = $1`, manager.Country)
	if err != nil {
		return ManagedTeam{}, err
	}
	people := eligibleFor(manager, role, candidates)
	ids := make([]string, len(people))
	for i, p := range people {
		ids[i] = p.StaffID
	}
	links, err := s.store.linksOf(ctx, s.store.db, ids)
	if err != nil {
		return ManagedTeam{}, err
	}
	assigned, others := map[string]bool{}, map[string][]string{}
	for _, l := range links {
		switch {
		case l.Supervisor.StaffID == manager.StaffID:
			assigned[l.SuperviseeID] = true
		case role == roleProgramLead && l.Supervisor.holds(roleProgramLead):
			others[l.SuperviseeID] = append(others[l.SuperviseeID], l.Supervisor.Name)
		}
	}
	team := ManagedTeam{Role: role, Country: manager.Country, Automatic: role == roleCD}
	for _, p := range people {
		team.People = append(team.People, ManagedPerson{person: p, Assigned: team.Automatic || assigned[p.StaffID],
			OtherManager: strings.Join(others[p.StaffID], ", ")})
	}
	return team, nil
}

// Configured is a managed team replaced.
type Configured struct {
	Assigned, Added, Removed int
}

// ConfigureTeam is configure_managed_people (and, for a Program Lead,
// configure_program_lead_team): the Admin replaces the list; a CCEO keeps
// one Program Lead, so choosing one moves them; a Country Director's team is
// automatic and cannot be listed.
func (s *StaffService) ConfigureTeam(ctx context.Context, principal auth.Principal, userID string, staffIDs []string) (Configured, error) {
	var result Configured
	err := s.store.write(ctx, func(tx pgx.Tx) error {
		var err error
		result, err = s.ConfigureTeamInTx(ctx, tx, principal, userID, staffIDs, s.now())
		return err
	})
	if err == nil {
		s.changed()
	}
	return result, err
}

// ConfigureTeamInTx is ConfigureTeam inside the caller's transaction.
func (s *StaffService) ConfigureTeamInTx(ctx context.Context, tx pgx.Tx, principal auth.Principal, userID string, staffIDs []string,
	now time.Time) (Configured, error) {
	if principal.ActiveRole != rbac.Admin {
		return Configured{}, forbidden("Only an Admin can configure managed people.")
	}
	selected := dedupe(staffIDs)
	var result Configured
	err := func() error {
		manager, err := personFound(tx.QueryRow(ctx, personSelect+` AND u.id = $1 FOR UPDATE OF sp`, userID))
		if err != nil {
			return err
		}
		role := manager.managementRole()
		switch role {
		case "":
			return refuse("Managed people can only be configured for PL, CD, IA, or RVP roles.")
		case roleCD:
			return refuse("Country Directors automatically manage every PL, IA, Accountant, and CCEO in their country.")
		}
		candidates, err := s.store.people(ctx, tx, ` AND sp.country = $1`, manager.Country)
		if err != nil {
			return err
		}
		eligible := map[string]bool{}
		for _, p := range eligibleFor(manager, role, candidates) {
			eligible[p.StaffID] = true
		}
		for _, id := range selected {
			if !eligible[id] {
				if role == roleProgramLead {
					return refuse("A Program Lead can only manage CCEOs in the same country.")
				}
				return refuse(fmt.Sprintf("A %s can only manage eligible staff in the same country.", role))
			}
		}
		var moved Configured
		if role == roleProgramLead {
			if moved, err = moveCCEOs(ctx, tx, principal, manager, selected, now); err != nil {
				return err
			}
		}
		result, err = replaceTeam(ctx, tx, principal, manager, role, selected, now)
		if role == roleProgramLead {
			// The Program Lead step made the change; its counts are the answer.
			result.Added, result.Removed = moved.Added, moved.Removed
		}
		return err
	}()
	return result, err
}

// moveCCEOs is configure_program_lead_team's move: each chosen CCEO's link
// to any other Program Lead goes, so a CCEO has one Program Lead; audited as
// the existing code audits it.
func moveCCEOs(ctx context.Context, tx pgx.Tx, principal auth.Principal, lead person, selected []string, now time.Time) (Configured, error) {
	rows, err := tx.Query(ctx, `
SELECT a.id, a.supervisee_id, a.supervisor_id = $1
FROM staff_supervisor_assignment a
JOIN staff_profile sp ON sp.id = a.supervisor_id JOIN "user" u ON u.id = sp.user_id
WHERE a.supervisor_id = $1
   OR (a.supervisee_id = ANY($2) AND (u.active_role = $3 OR u.roles @> ARRAY[$3]::varchar[]))
FOR UPDATE OF a`, lead.StaffID, selected, roleProgramLead)
	if err != nil {
		return Configured{}, err
	}
	current, previous := map[string]bool{}, map[string]bool{}
	var competing []string
	for rows.Next() {
		var id, supervisee string
		var mine bool
		if err := rows.Scan(&id, &supervisee, &mine); err != nil {
			rows.Close()
			return Configured{}, err
		}
		if mine {
			current[supervisee] = true
		} else {
			previous[supervisee] = true
			competing = append(competing, id)
		}
	}
	rows.Close()
	if len(competing) > 0 {
		if _, err := tx.Exec(ctx, `DELETE FROM staff_supervisor_assignment WHERE id = ANY($1)`, competing); err != nil {
			return Configured{}, err
		}
	}
	// configure_program_lead_team writes the lead's own links too, before
	// the generic step reads them: that step then audits no change.
	if _, err := tx.Exec(ctx, `DELETE FROM staff_supervisor_assignment WHERE supervisor_id = $1 AND NOT (supervisee_id = ANY($2))`,
		lead.StaffID, selected); err != nil {
		return Configured{}, err
	}
	for _, id := range selected {
		if err := ensureLink(ctx, tx, id, lead.StaffID, now); err != nil {
			return Configured{}, err
		}
	}
	added, removed, reassigned := diff(selected, current, previous)
	_, err = audit.Append(ctx, tx, audit.Entry{
		Action: "admin.program_lead_team_configured", SubjectKind: audit.Text("staff_profile"),
		SubjectID: audit.Text(lead.StaffID), ActorID: audit.Text(principal.UserID),
		ActorRole: audit.Text(principal.ActiveRole), Success: true,
		Payload: map[string]any{"programLeadId": lead.StaffID, "cceoIds": toAny(selected), "addedCceoIds": toAny(added),
			"removedCceoIds": toAny(removed), "reassignedCceoIds": toAny(reassigned)},
	}, now)
	return Configured{Assigned: len(selected), Added: len(added), Removed: len(removed)}, err
}

// diff sorts a new selection against the current members and those moving
// from elsewhere.
func diff(selected []string, current, elsewhere map[string]bool) (added, removed, moved []string) {
	added, removed, moved = []string{}, []string{}, []string{}
	chosen := map[string]bool{}
	for _, id := range selected {
		chosen[id] = true
		if !current[id] {
			added = append(added, id)
		}
		if elsewhere[id] {
			moved = append(moved, id)
		}
	}
	for id := range current {
		if !chosen[id] {
			removed = append(removed, id)
		}
	}
	sort.Strings(added)
	sort.Strings(removed)
	sort.Strings(moved)
	return added, removed, moved
}

// replaceTeam makes selected the manager's links, and audits the change.
func replaceTeam(ctx context.Context, tx pgx.Tx, principal auth.Principal, manager person, role string, selected []string, now time.Time) (Configured, error) {
	current := map[string]bool{}
	rows, err := tx.Query(ctx, `SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = $1 FOR UPDATE`,
		manager.StaffID)
	if err != nil {
		return Configured{}, err
	}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return Configured{}, err
		}
		current[id] = true
	}
	rows.Close()
	if _, err := tx.Exec(ctx, `DELETE FROM staff_supervisor_assignment WHERE supervisor_id = $1 AND NOT (supervisee_id = ANY($2))`,
		manager.StaffID, selected); err != nil {
		return Configured{}, err
	}
	for _, id := range selected {
		if err := ensureLink(ctx, tx, id, manager.StaffID, now); err != nil {
			return Configured{}, err
		}
	}
	added, removed, _ := diff(selected, current, nil)
	_, err = audit.Append(ctx, tx, audit.Entry{
		Action: "admin.managed_people_configured", SubjectKind: audit.Text("staff_profile"),
		SubjectID: audit.Text(manager.StaffID), ActorID: audit.Text(principal.UserID),
		ActorRole: audit.Text(principal.ActiveRole), Success: true,
		Payload: map[string]any{"managerRole": role, "managedStaffIds": toAny(selected),
			"addedStaffIds": toAny(added), "removedStaffIds": toAny(removed)},
	}, now)
	return Configured{Assigned: len(selected), Added: len(added), Removed: len(removed)}, err
}

func dedupe(ids []string) []string {
	out := []string{}
	for _, id := range ids {
		if id = strings.TrimSpace(id); id != "" && !slices.Contains(out, id) {
			out = append(out, id)
		}
	}
	return out
}

func toAny(items []string) []any {
	out := make([]any, len(items))
	for i, item := range items {
		out[i] = item
	}
	return out
}

func nilIfEmpty(s string) any {
	if s == "" {
		return nil
	}
	return s
}
