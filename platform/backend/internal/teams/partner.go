package teams

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/accounts"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
)

// The existing status sets the school split reads.
var (
	// releasedAssignment: a school handed back is no longer held
	// (PartnerAssignment.RELEASED_STATUSES).
	releasedAssignment = []string{"cancelled", "returned", "returned_to_staff"}
	// finishedWork keeps the name it was delivered under
	// (COMPLETED_WORK_STATUSES, NOT_IN_PLAN_ACTIVITY_STATUSES).
	finishedWork = []string{"accountant_confirmed", "closed", "completed", "ia_verified",
		"cancelled", "deferred", "not_planned", "rejected"}
)

const msgOnlyLeads = "Only the organisation's Partner Admin or an Edify Admin manages its team's logins, schools and activities."

// Member is a roster entry with its login and school count.
type Member struct {
	ID, Name, Role, Title, Phone, Email string
	Login                               *MemberLogin
	Schools                             int
}

// MemberLogin is a member's own sign-in.
type MemberLogin struct {
	UserID, Email, Status string
	IsActive              bool
}

// HeldSchool is a school the organisation holds, and who looks after it.
type HeldSchool struct {
	ID, Name, District, MemberID string
}

// PartnerTeam is an organisation's team as its leader sees it.
type PartnerTeam struct {
	PartnerID, PartnerName string
	LeadsTeam, Roster      bool
	Members                []Member
	Schools                []HeldSchool
}

// PartnerService is a partner organisation's own team.
type PartnerService struct {
	store    *Store
	accounts *accounts.Service
	now      func() time.Time
}

// NewPartnerService returns the service. Member logins are accounts, made
// and changed through the accounts service so they follow its rules.
func NewPartnerService(store *Store, accountService *accounts.Service, now func() time.Time) *PartnerService {
	return &PartnerService{store: store, accounts: accountService, now: now}
}

type partnerRow struct {
	ID, Name, UserID string
}

func (s *PartnerService) partner(ctx context.Context, q pgx.Row) (partnerRow, error) {
	var p partnerRow
	err := q.Scan(&p.ID, &p.Name, &p.UserID)
	if errors.Is(err, pgx.ErrNoRows) {
		return partnerRow{}, notFound("Partner organisation not found.")
	}
	return p, err
}

// ownPartner is resolve_partner_ids: the organisation a partner login signs
// in as — its own login, or a member's login of its team.
func (s *PartnerService) ownPartner(ctx context.Context, principal auth.Principal) (string, error) {
	var id string
	err := s.store.db.QueryRow(ctx, `
SELECT id FROM partner WHERE user_id = $1 AND active_status ORDER BY created_at LIMIT 1`, principal.UserID).Scan(&id)
	if err == nil || !errors.Is(err, pgx.ErrNoRows) {
		return id, err
	}
	if principal.ActiveRole != rolePartnerAdm && principal.ActiveRole != rolePartnerFO {
		return "", nil
	}
	err = s.store.db.QueryRow(ctx, `
SELECT m.partner_id FROM partner_member m JOIN partner p ON p.id = m.partner_id
WHERE m.user_id = $1 AND m.active AND p.active_status LIMIT 1`, principal.UserID).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	return id, err
}

// leadsTeam is leads_team: the Admin, the organisation's own login, or a
// login of the organisation working as Partner Admin. A member's Field
// Officer login does not lead.
func (s *PartnerService) leadsTeam(ctx context.Context, principal auth.Principal, p partnerRow) (bool, error) {
	if principal.ActiveRole == rbac.Admin || (p.UserID != "" && p.UserID == principal.UserID) {
		return true, nil
	}
	if principal.ActiveRole != rolePartnerAdm {
		return false, nil
	}
	own, err := s.ownPartner(ctx, principal)
	return own == p.ID, err
}

// managesRoster is manages_roster: country staff who run the directory, and
// whoever leads the team. Country staff manage the partners of the country
// they work in (docs/migration/80, §17): the Admin and the regional roles
// every partner, anyone else none while they work in no Active country.
func (s *PartnerService) managesRoster(ctx context.Context, principal auth.Principal, p partnerRow) (bool, error) {
	if slices.Contains(countryRoles, principal.ActiveRole) {
		if principal.ActiveRole == rbac.Admin || registry.IsRegional(principal.ActiveRole) {
			return true, nil
		}
		if principal.Country == nil {
			return false, nil
		}
		var inCountry bool
		if err := s.store.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM partner p WHERE p.id = $1 AND `+registry.PartnerIn("p", "$2")+`)`,
			p.ID, []string{principal.Country.ID}).Scan(&inCountry); err != nil {
			return false, fmt.Errorf("teams: reading the partner's country: %w", err)
		}
		if inCountry {
			return true, nil
		}
	}
	return s.leadsTeam(ctx, principal, p)
}

const partnerSelect = `SELECT id, name, COALESCE(user_id, '') FROM partner WHERE id = $1 AND deleted_at IS NULL`

// Team reads an organisation's team: partnerID, or the caller's own.
func (s *PartnerService) Team(ctx context.Context, principal auth.Principal, partnerID string) (PartnerTeam, error) {
	if partnerID == "" {
		own, err := s.ownPartner(ctx, principal)
		if err != nil {
			return PartnerTeam{}, err
		}
		if own == "" {
			return PartnerTeam{}, notFound("Your account is not linked to a partner organisation.")
		}
		partnerID = own
	}
	p, err := s.partner(ctx, s.store.db.QueryRow(ctx, partnerSelect, partnerID))
	if err != nil {
		return PartnerTeam{}, err
	}
	leads, err := s.leadsTeam(ctx, principal, p)
	if err != nil {
		return PartnerTeam{}, err
	}
	roster, err := s.managesRoster(ctx, principal, p)
	if err != nil {
		return PartnerTeam{}, err
	}
	if !leads && !roster {
		return PartnerTeam{}, forbidden("You may only manage the roster of a partner in your scope.")
	}
	team := PartnerTeam{PartnerID: p.ID, PartnerName: p.Name, LeadsTeam: leads, Roster: roster}
	if team.Schools, err = s.heldSchools(ctx, p.ID); err != nil {
		return PartnerTeam{}, err
	}
	counts := map[string]int{}
	for _, school := range team.Schools {
		if school.MemberID != "" {
			counts[school.MemberID]++
		}
	}
	rows, err := s.store.db.Query(ctx, `
SELECT m.id, m.name, m.role, m.title, m.phone, m.email,
       COALESCE(u.id, ''), COALESCE(u.email, ''), COALESCE(u.status, ''), COALESCE(u.is_active, false)
FROM partner_member m
LEFT JOIN "user" u ON u.id = m.user_id AND u.deleted_at IS NULL
WHERE m.partner_id = $1 AND m.active
ORDER BY m.role, m.name`, p.ID)
	if err != nil {
		return PartnerTeam{}, fmt.Errorf("teams: reading the roster: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var m Member
		var login MemberLogin
		if err := rows.Scan(&m.ID, &m.Name, &m.Role, &m.Title, &m.Phone, &m.Email,
			&login.UserID, &login.Email, &login.Status, &login.IsActive); err != nil {
			return PartnerTeam{}, err
		}
		if login.UserID != "" {
			m.Login = &login
		}
		m.Schools = counts[m.ID]
		team.Members = append(team.Members, m)
	}
	return team, rows.Err()
}

// heldSchools is held_schools with members_by_school: every school the
// organisation holds, by name, and its active member.
func (s *PartnerService) heldSchools(ctx context.Context, partnerID string) ([]HeldSchool, error) {
	rows, err := s.store.db.Query(ctx, `
SELECT sc.id, sc.name, COALESCE(d.name, ''), COALESCE(psm.member_id, '')
FROM school sc
LEFT JOIN district d ON d.id = sc.district_id
LEFT JOIN partner_school_member psm ON psm.partner_id = $1 AND psm.school_id = sc.id
     AND EXISTS (SELECT 1 FROM partner_member m WHERE m.id = psm.member_id AND m.active)
WHERE sc.id IN (SELECT DISTINCT school_id FROM partner_assignment
                WHERE partner_id = $1 AND school_id IS NOT NULL AND NOT (status = ANY($2)))
ORDER BY sc.name, sc.id`, partnerID, releasedAssignment)
	if err != nil {
		return nil, fmt.Errorf("teams: reading the held schools: %w", err)
	}
	defer rows.Close()
	var out []HeldSchool
	for rows.Next() {
		var h HeldSchool
		if err := rows.Scan(&h.ID, &h.Name, &h.District, &h.MemberID); err != nil {
			return nil, err
		}
		out = append(out, h)
	}
	return out, rows.Err()
}

// NewMember is a roster entry to add.
type NewMember struct {
	Name, Role, Title, Phone, Email string
}

// AddMember is add_member: a person on the roster, staff or volunteer.
func (s *PartnerService) AddMember(ctx context.Context, principal auth.Principal, partnerID string, in NewMember) (Member, error) {
	p, err := s.partner(ctx, s.store.db.QueryRow(ctx, `SELECT id, name, COALESCE(user_id, '') FROM partner WHERE id = $1`, partnerID))
	if err != nil {
		return Member{}, err
	}
	if ok, err := s.managesRoster(ctx, principal, p); err != nil || !ok {
		if err != nil {
			return Member{}, err
		}
		return Member{}, forbidden("You may only manage the roster of a partner in your scope.")
	}
	m := Member{ID: cuid.New(), Name: strings.TrimSpace(in.Name), Role: strings.TrimSpace(in.Role),
		Title: strings.TrimSpace(in.Title), Phone: strings.TrimSpace(in.Phone),
		Email: strings.ToLower(strings.TrimSpace(in.Email))}
	if m.Name == "" {
		return Member{}, refuse("A name is required.")
	}
	if m.Role == "" {
		m.Role = "staff"
	}
	if m.Role != "staff" && m.Role != "volunteer" {
		return Member{}, refuse("Role must be staff or volunteer.")
	}
	now := s.now()
	err = s.store.write(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `
INSERT INTO partner_member (id, partner_id, name, role, title, phone, email, active, added_by_user_id, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, true, $8, $9, $9)`,
			m.ID, p.ID, m.Name, m.Role, m.Title, m.Phone, m.Email, principal.UserID, now)
		return err
	})
	return m, err
}

// memberRow is a roster entry and its login.
type memberRow struct {
	ID, Name, Email, Phone, UserID string
	Active, LoginLive, LoginActive bool
}

func (s *PartnerService) member(ctx context.Context, q pgx.Row) (memberRow, error) {
	var m memberRow
	err := q.Scan(&m.ID, &m.Name, &m.Email, &m.Phone, &m.Active, &m.UserID, &m.LoginLive, &m.LoginActive)
	if errors.Is(err, pgx.ErrNoRows) {
		return memberRow{}, notFound("This person is not on the organisation's team.")
	}
	return m, err
}

const memberSelect = `
SELECT m.id, m.name, m.email, m.phone, m.active, COALESCE(m.user_id, ''),
       u.id IS NOT NULL AND u.deleted_at IS NULL, COALESCE(u.is_active, false)
FROM partner_member m LEFT JOIN "user" u ON u.id = m.user_id
WHERE m.id = $1 AND m.partner_id = $2`

// RemoveMember is remove_member: a login of their own stops signing in, and
// their schools go back to nobody.
func (s *PartnerService) RemoveMember(ctx context.Context, principal auth.Principal, partnerID, memberID string) error {
	p, err := s.partner(ctx, s.store.db.QueryRow(ctx, `SELECT id, name, COALESCE(user_id, '') FROM partner WHERE id = $1`, partnerID))
	if err != nil {
		return err
	}
	m, err := s.member(ctx, s.store.db.QueryRow(ctx, memberSelect, memberID, p.ID))
	if err != nil {
		return notFound("Roster entry not found.")
	}
	if ok, err := s.managesRoster(ctx, principal, p); err != nil || !ok {
		if err != nil {
			return err
		}
		return forbidden("You may only manage the roster of a partner in your scope.")
	}
	if m.LoginLive && m.LoginActive {
		if _, err := s.accounts.SetStatus(ctx, principal, m.UserID, "disabled"); err != nil {
			return err
		}
	}
	return s.store.write(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `DELETE FROM partner_school_member WHERE member_id = $1`, m.ID); err != nil {
			return err
		}
		_, err := tx.Exec(ctx, `DELETE FROM partner_member WHERE id = $1`, m.ID)
		return err
	})
}

// led is a partner and member the caller leads the team of.
func (s *PartnerService) led(ctx context.Context, principal auth.Principal, partnerID, memberID string) (partnerRow, memberRow, error) {
	p, err := s.partner(ctx, s.store.db.QueryRow(ctx, partnerSelect, partnerID))
	if err != nil {
		return partnerRow{}, memberRow{}, err
	}
	if ok, err := s.leadsTeam(ctx, principal, p); err != nil || !ok {
		if err != nil {
			return partnerRow{}, memberRow{}, err
		}
		return partnerRow{}, memberRow{}, forbidden(msgOnlyLeads)
	}
	m, err := s.member(ctx, s.store.db.QueryRow(ctx, memberSelect, memberID, p.ID))
	return p, m, err
}

func (s *PartnerService) auditMember(ctx context.Context, tx pgx.Tx, action string, p partnerRow, m memberRow,
	principal auth.Principal, extra map[string]any, now time.Time) error {
	payload := map[string]any{"memberId": m.ID, "memberName": m.Name}
	for key, value := range extra {
		payload[key] = value
	}
	_, err := audit.Append(ctx, tx, audit.Entry{
		Action: action, SubjectKind: audit.Text("partner"), SubjectID: audit.Text(p.ID),
		ActorID: audit.Text(principal.UserID), ActorRole: audit.Text(principal.ActiveRole), Success: true,
		Payload: payload,
	}, now)
	return err
}

func (s *PartnerService) auditAlone(ctx context.Context, action string, p partnerRow, m memberRow, principal auth.Principal, extra map[string]any) error {
	return s.store.write(ctx, func(tx pgx.Tx) error {
		return s.auditMember(ctx, tx, action, p, m, principal, extra, s.now())
	})
}

// LoginCreated says how the member was given a login.
type LoginCreated struct {
	Invited        bool
	InvitationLink string
}

// CreateLogin is create_login: a Partner Field Officer login for a team
// member, made and linked in one transaction.
func (s *PartnerService) CreateLogin(ctx context.Context, principal auth.Principal, partnerID, memberID, email, password string) (LoginCreated, error) {
	p, _, err := s.led(ctx, principal, partnerID, memberID)
	if err != nil {
		return LoginCreated{}, err
	}
	now := s.now()
	var m memberRow
	var address, invitation string
	err = s.store.write(ctx, func(tx pgx.Tx) error {
		found, err := s.member(ctx, tx.QueryRow(ctx, memberSelect+` FOR UPDATE OF m`, memberID, p.ID))
		if err != nil {
			return err
		}
		m = found
		if !m.Active {
			return refuse("This person is no longer on the team.")
		}
		if m.LoginLive {
			return &Refused{Message: m.Name + " already has a login.", Conflict: true}
		}
		address = strings.ToLower(strings.TrimSpace(email))
		if address == "" {
			address = strings.ToLower(strings.TrimSpace(m.Email))
		}
		if address == "" {
			return refuse("Enter the email address this person will sign in with.")
		}
		userID, raw, err := s.accounts.CreateInTx(ctx, tx, principal, accounts.NewAccount{
			Name: m.Name, Email: address, Phone: m.Phone, Role: rolePartnerFO,
			Password: strings.TrimSpace(password), ForPartnerMember: true,
		})
		var refused *accounts.Refused
		if errors.As(err, &refused) && refused.Conflict {
			return &Refused{Message: "An account already uses " + address + ".", Conflict: true}
		}
		if err != nil {
			return err
		}
		invitation = raw
		if _, err := tx.Exec(ctx, `
UPDATE partner_member SET user_id = $2, email = CASE WHEN email = '' THEN $3 ELSE email END, updated_at = $4 WHERE id = $1`,
			m.ID, userID, address, now); err != nil {
			return err
		}
		return s.auditMember(ctx, tx, "partner.member_login_created", p, m, principal,
			map[string]any{"userId": userID, "email": address, "invited": raw != ""}, now)
	})
	if err != nil {
		return LoginCreated{}, err
	}
	link := s.accounts.NotifyCreated(principal, m.Name, address, invitation)
	return LoginCreated{Invited: invitation != "", InvitationLink: link}, nil
}

// ResetPassword is member_logins.reset_password: a new one-time password.
func (s *PartnerService) ResetPassword(ctx context.Context, principal auth.Principal, partnerID, memberID, password string) error {
	p, m, err := s.led(ctx, principal, partnerID, memberID)
	if err != nil {
		return err
	}
	if !m.LoginLive {
		return refuse(m.Name + " has no login yet.")
	}
	if strings.TrimSpace(password) == "" {
		return refuse("Enter the new password.")
	}
	if err := s.accounts.SetTemporaryPassword(ctx, principal, m.UserID, strings.TrimSpace(password)); err != nil {
		return err
	}
	return s.auditAlone(ctx, "partner.member_login_password_reset", p, m, principal, nil)
}

// SetLoginActive is member_logins.set_active: stop a member's login signing
// in, or let it again; never the login the caller is using.
func (s *PartnerService) SetLoginActive(ctx context.Context, principal auth.Principal, partnerID, memberID string, active bool) error {
	p, m, err := s.led(ctx, principal, partnerID, memberID)
	if err != nil {
		return err
	}
	if !m.LoginLive {
		return refuse(m.Name + " has no login yet.")
	}
	if m.UserID == principal.UserID {
		return refuse("You cannot deactivate the login you are signed in with.")
	}
	status, action := "disabled", "partner.member_login_deactivated"
	if active {
		status, action = "active", "partner.member_login_activated"
	}
	if _, err := s.accounts.SetStatus(ctx, principal, m.UserID, status); err != nil {
		return err
	}
	return s.auditAlone(ctx, action, p, m, principal, nil)
}

// SchoolsSet is a member's schools replaced.
type SchoolsSet struct {
	Given, Moved, Cleared, Named int
}

// SetSchools is set_member_schools: the member's schools become schoolIDs.
// A school another member had moves, with its unfinished work that names
// nobody or that member; one no longer ticked goes back to nobody. Only
// schools the organisation holds can be given.
func (s *PartnerService) SetSchools(ctx context.Context, principal auth.Principal, partnerID, memberID string, schoolIDs []string) (SchoolsSet, error) {
	p, m, err := s.led(ctx, principal, partnerID, memberID)
	if err != nil {
		return SchoolsSet{}, err
	}
	if !m.Active {
		return SchoolsSet{}, notFound("This person is not on the organisation's team.")
	}
	wanted := dedupe(schoolIDs)
	held, err := s.heldSchools(ctx, p.ID)
	if err != nil {
		return SchoolsSet{}, err
	}
	heldIDs := map[string]bool{}
	for _, school := range held {
		heldIDs[school.ID] = true
	}
	strangers := 0
	for _, id := range wanted {
		if !heldIDs[id] {
			strangers++
		}
	}
	if strangers > 0 {
		verb := "are"
		if strangers == 1 {
			verb = "is"
		}
		return SchoolsSet{}, refuse(fmt.Sprintf("%d of the schools chosen %s not assigned to %s. Reload the list and choose again.",
			strangers, verb, p.Name))
	}
	now := s.now()
	var result SchoolsSet
	err = s.store.write(ctx, func(tx pgx.Tx) error {
		rows, err := tx.Query(ctx, `
SELECT psm.id, psm.school_id, psm.member_id, COALESCE(pm.name, '')
FROM partner_school_member psm LEFT JOIN partner_member pm ON pm.id = psm.member_id
WHERE psm.partner_id = $1 FOR UPDATE OF psm`, p.ID)
		if err != nil {
			return err
		}
		type row struct{ id, member, memberName string }
		current := map[string]row{}
		var before []string
		for rows.Next() {
			var r row
			var school string
			if err := rows.Scan(&r.id, &school, &r.member, &r.memberName); err != nil {
				rows.Close()
				return err
			}
			current[school] = r
			if r.member == m.ID {
				before = append(before, school)
			}
		}
		rows.Close()
		var given, moved, cleared []string
		for _, school := range sortedCopy(wanted) {
			r, ok := current[school]
			switch {
			case !ok:
				if _, err := tx.Exec(ctx, `
INSERT INTO partner_school_member (id, partner_id, school_id, member_id, assigned_by_user_id, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, $6, $6)`, cuid.New(), p.ID, school, m.ID, principal.UserID, now); err != nil {
					return err
				}
				given = append(given, school)
			case r.member != m.ID:
				named, err := nameOpenWork(ctx, tx, p.ID, []string{school}, m.Name, []string{"", r.memberName})
				if err != nil {
					return err
				}
				result.Named += named
				if _, err := tx.Exec(ctx, `
UPDATE partner_school_member SET member_id = $2, assigned_by_user_id = $3, updated_at = $4 WHERE id = $1`,
					r.id, m.ID, principal.UserID, now); err != nil {
					return err
				}
				moved = append(moved, school)
			}
		}
		for _, school := range before {
			if !slices.Contains(wanted, school) {
				if _, err := tx.Exec(ctx, `DELETE FROM partner_school_member WHERE id = $1`, current[school].id); err != nil {
					return err
				}
				cleared = append(cleared, school)
			}
		}
		named, err := nameOpenWork(ctx, tx, p.ID, given, m.Name, []string{""})
		if err != nil {
			return err
		}
		result.Named += named
		result.Given, result.Moved, result.Cleared = len(given), len(moved), len(cleared)
		if len(given)+len(moved)+len(cleared) == 0 {
			return nil
		}
		_, err = audit.Append(ctx, tx, audit.Entry{
			Action: "partner.school_team_member_set", SubjectKind: audit.Text("partner"), SubjectID: audit.Text(p.ID),
			ActorID: audit.Text(principal.UserID), ActorRole: audit.Text(principal.ActiveRole), Success: true,
			Payload: map[string]any{"memberId": m.ID, "memberName": m.Name, "given": toAny(given),
				"movedFromAnother": toAny(moved), "cleared": toAny(cleared), "activitiesNamed": result.Named},
		}, now)
		return err
	})
	return result, err
}

// nameOpenWork is _name_open_work: the organisation's unfinished work at
// these schools that names nobody yet, or the member the school is moving
// from, takes the member's name. A name chosen on purpose stays; finished
// work keeps the name it was delivered under.
func nameOpenWork(ctx context.Context, tx pgx.Tx, partnerID string, schoolIDs []string, name string, was []string) (int, error) {
	if len(schoolIDs) == 0 {
		return 0, nil
	}
	tag, err := tx.Exec(ctx, `
UPDATE activity SET delivery_contact_name = $4
WHERE deleted_at IS NULL AND assigned_partner_id = $1 AND school_id = ANY($2)
  AND delivery_contact_name = ANY($3) AND NOT (status = ANY($5))`,
		partnerID, schoolIDs, was, name, finishedWork)
	if err != nil {
		return 0, fmt.Errorf("teams: naming open work: %w", err)
	}
	return int(tag.RowsAffected()), nil
}

func sortedCopy(items []string) []string {
	out := slices.Clone(items)
	slices.Sort(out)
	return out
}
