package loans

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"regexp"
	"time"

	"github.com/jackc/pgx/v5"
)

// Share links: opaque ids for lender links and personal referral links,
// school invitations, share counts and the approved message texts.

// ShareLink is a lender's link or a person's referral link.
type ShareLink struct {
	ID, Kind, PartnerID, LenderName, ClusterID, Label string
	CreatedBy, CreatedByName, CreatedRole             string
	LockPartner                                       bool
	CreatedAt                                         time.Time
}

// Share link kinds, as stored.
const (
	LinkPartner  = "partner"
	LinkReferral = "referral"
)

// newLinkID is 128 random bits, URL-safe: not guessable, not a sequence.
func newLinkID() (string, error) {
	raw := make([]byte, 16)
	if _, err := rand.Read(raw); err != nil {
		return "", fmt.Errorf("loans: reading randomness: %w", err)
	}
	return base64.RawURLEncoding.EncodeToString(raw), nil
}

const shareLinkColumns = `
l.id, l.kind, COALESCE(l.partner_id, ''), COALESCE(p.name, ''), COALESCE(l.cluster_id, ''), l.label,
l.created_by, l.created_by_name, l.created_role, l.lock_partner, l.created_at`

func scanShareLink(row pgx.Row) (ShareLink, error) {
	var l ShareLink
	err := row.Scan(&l.ID, &l.Kind, &l.PartnerID, &l.LenderName, &l.ClusterID, &l.Label, &l.CreatedBy, &l.CreatedByName,
		&l.CreatedRole, &l.LockPartner, &l.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return l, ErrNotFound
	}
	return l, err
}

// LiveShareLink is a link that still works.
func (s *Store) LiveShareLink(ctx context.Context, id string) (ShareLink, error) {
	return scanShareLink(s.db.QueryRow(ctx, `
SELECT`+shareLinkColumns+`
FROM school_loans.share_link l LEFT JOIN partner p ON p.id = l.partner_id
WHERE l.id = $1 AND l.revoked_at IS NULL`, id))
}

// LinkActor is who makes or replaces a link.
type LinkActor struct{ ID, Name, Role string }

type rowQuerier interface {
	QueryRow(context.Context, string, ...any) pgx.Row
}

// liveLink finds the one live link of a kind for a lender or a person,
// making it when there is none. Two people asking at once get the same one.
func (s *Store) liveLink(ctx context.Context, kind, partnerID, clusterID string, actor LinkActor, now time.Time) (ShareLink, error) {
	find := func(q rowQuerier) (ShareLink, error) {
		if kind == LinkPartner {
			return scanShareLink(q.QueryRow(ctx, `SELECT`+shareLinkColumns+`
FROM school_loans.share_link l LEFT JOIN partner p ON p.id = l.partner_id
WHERE l.kind = 'partner' AND l.partner_id = $1 AND l.revoked_at IS NULL`, partnerID))
		}
		return scanShareLink(q.QueryRow(ctx, `SELECT`+shareLinkColumns+`
FROM school_loans.share_link l LEFT JOIN partner p ON p.id = l.partner_id
WHERE l.kind = 'referral' AND l.created_by = $1 AND l.revoked_at IS NULL`, actor.ID))
	}
	link, found := find(s.db)
	if found == nil && (kind == LinkPartner || link.ClusterID == clusterID) {
		return link, nil
	}
	if found != nil && !errors.Is(found, ErrNotFound) {
		return link, found
	}
	err := s.inWrite(ctx, func(tx pgx.Tx) error {
		if found == nil {
			// A Cluster Leader now leads another cluster: their link follows it,
			// so applications are counted where they were shared.
			if _, err := tx.Exec(ctx, `UPDATE school_loans.share_link SET revoked_at = $2, revoked_by = $3 WHERE id = $1`,
				link.ID, now, actor.ID); err != nil {
				return err
			}
		}
		id, err := newLinkID()
		if err != nil {
			return err
		}
		var partner, cluster *string
		if partnerID != "" {
			partner = &partnerID
		}
		if clusterID != "" {
			cluster = &clusterID
		}
		tag, err := tx.Exec(ctx, `
INSERT INTO school_loans.share_link (id, kind, partner_id, cluster_id, created_by, created_by_name, created_role, created_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8) ON CONFLICT DO NOTHING`, id, kind, partner, cluster, actor.ID, actor.Name, actor.Role, now)
		if err != nil || tag.RowsAffected() == 0 {
			return err
		}
		return shareEvent(ctx, tx, "generated", "", kind, id, "", actor)
	})
	if err != nil {
		return ShareLink{}, err
	}
	return find(s.db)
}

// PartnerLink is the lender's one live link, made on first use.
func (s *Store) PartnerLink(ctx context.Context, partnerID string, actor LinkActor, now time.Time) (ShareLink, error) {
	return s.liveLink(ctx, LinkPartner, partnerID, "", actor, now)
}

// ReferralLink is the person's one live referral link, made on first use;
// clusterID attributes it to the cluster a Cluster Leader leads.
func (s *Store) ReferralLink(ctx context.Context, clusterID string, actor LinkActor, now time.Time) (ShareLink, error) {
	return s.liveLink(ctx, LinkReferral, "", clusterID, actor, now)
}

// SetPartnerLock sets whether a lender's link fixes the lender.
func (s *Store) SetPartnerLock(ctx context.Context, linkID string, lock bool) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `UPDATE school_loans.share_link SET lock_partner = $2 WHERE id = $1 AND revoked_at IS NULL`, linkID, lock)
		if err == nil && tag.RowsAffected() == 0 {
			return ErrNotFound
		}
		return err
	})
}

// ReplaceShareLink stops a link; the next request makes a new one.
func (s *Store) ReplaceShareLink(ctx context.Context, link ShareLink, actor LinkActor, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `UPDATE school_loans.share_link SET revoked_at = $2, revoked_by = $3 WHERE id = $1 AND revoked_at IS NULL`,
			link.ID, now, actor.ID)
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			return ErrNotFound
		}
		return shareEvent(ctx, tx, "revoked", "", link.Kind, link.ID, "", actor)
	})
}

func shareEvent(ctx context.Context, tx pgx.Tx, kind, channel, linkKind, linkID, invitationID string, actor LinkActor) error {
	id, err := NewID()
	if err != nil {
		return err
	}
	var link, invitation *string
	if linkID != "" {
		link = &linkID
	}
	if invitationID != "" {
		invitation = &invitationID
	}
	_, err = tx.Exec(ctx, `
INSERT INTO school_loans.share_event (id, kind, channel, link_kind, share_link_id, invitation_id, actor_id, actor_role)
VALUES ($1, $2, $3, $4, $5, $6::uuid, $7, $8)`, id, kind, channel, linkKind, link, invitation, actor.ID, actor.Role)
	return err
}

// RecordShare counts that someone shared a link through a channel.
func (s *Store) RecordShare(ctx context.Context, channel, linkKind, linkID, invitationID string, actor LinkActor) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		return shareEvent(ctx, tx, "shared", channel, linkKind, linkID, invitationID, actor)
	})
}

// SchoolInvitation is an invitation as staff see it.
type SchoolInvitation struct {
	ID, SchoolID, SchoolName, CreatedBy, CreatedByName, Source, Campaign string
	CreatedAt, ExpiresAt                                                 time.Time
	RevokedAt                                                            *time.Time
	Applications                                                         int
}

// Status is active, expired or revoked.
func (i SchoolInvitation) Status(now time.Time) string {
	switch {
	case i.RevokedAt != nil:
		return "revoked"
	case !i.ExpiresAt.After(now):
		return "expired"
	}
	return "active"
}

// InviteSchool records a school-specific link and returns its token. Earlier
// live invitations for the school are replaced, so one link is in use.
func (s *Store) InviteSchool(ctx context.Context, school SchoolCandidate, actor LinkActor, source, campaign string, now time.Time) (string, SchoolInvitation, error) {
	token, err := NewToken()
	if err != nil {
		return "", SchoolInvitation{}, err
	}
	id, err := NewID()
	if err != nil {
		return "", SchoolInvitation{}, err
	}
	invitation := SchoolInvitation{ID: id, SchoolID: school.ID, SchoolName: school.Name, CreatedBy: actor.ID,
		CreatedByName: actor.Name, Source: source, Campaign: campaign, CreatedAt: now, ExpiresAt: now.Add(invitationLifetime)}
	err = s.inWrite(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `
UPDATE school_loans.invitation SET revoked_at = $2, revoked_by = $3, revoke_reason = 'Replaced by a newer invitation.'
WHERE school_id = $1 AND revoked_at IS NULL AND expires_at > $2`, school.ID, now, actor.ID); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `
INSERT INTO school_loans.invitation (id, token_hash, school_id, school_name, created_by, created_by_name, created_at, expires_at,
  source, campaign)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`, id, HashToken(token), school.ID, school.Name, actor.ID, actor.Name, now,
			invitation.ExpiresAt, source, campaign); err != nil {
			return err
		}
		return shareEvent(ctx, tx, "generated", "", "invitation", "", id, actor)
	})
	return token, invitation, err
}

const invitationColumns = `
i.id::text, i.school_id, i.school_name, i.created_by, i.created_by_name, i.source, i.campaign, i.created_at, i.expires_at,
i.revoked_at, (SELECT count(*) FROM school_loans.application a WHERE a.invitation_id = i.id)`

func scanInvitation(row pgx.Row) (SchoolInvitation, error) {
	var i SchoolInvitation
	err := row.Scan(&i.ID, &i.SchoolID, &i.SchoolName, &i.CreatedBy, &i.CreatedByName, &i.Source, &i.Campaign, &i.CreatedAt,
		&i.ExpiresAt, &i.RevokedAt, &i.Applications)
	if errors.Is(err, pgx.ErrNoRows) {
		return i, ErrNotFound
	}
	return i, err
}

// SchoolInvitations are a school's invitations, newest first.
func (s *Store) SchoolInvitations(ctx context.Context, schoolID string) ([]SchoolInvitation, error) {
	rows, err := s.db.Query(ctx, `SELECT`+invitationColumns+`
FROM school_loans.invitation i WHERE i.school_id = $1 ORDER BY i.created_at DESC LIMIT 50`, schoolID)
	if err != nil {
		return nil, fmt.Errorf("loans: reading invitations: %w", err)
	}
	defer rows.Close()
	var out []SchoolInvitation
	for rows.Next() {
		i, err := scanInvitation(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, i)
	}
	return out, rows.Err()
}

// RevokeInvitation stops an invitation working.
func (s *Store) RevokeInvitation(ctx context.Context, id, reason string, actor LinkActor, now time.Time) (SchoolInvitation, error) {
	err := s.inWrite(ctx, func(tx pgx.Tx) error {
		tag, err := tx.Exec(ctx, `
UPDATE school_loans.invitation SET revoked_at = $2, revoked_by = $3, revoke_reason = $4 WHERE id = $1 AND revoked_at IS NULL`,
			id, now, actor.ID, reason)
		if err != nil {
			return err
		}
		if tag.RowsAffected() == 0 {
			return need("invitation_id", "That invitation is already revoked, or does not exist.")
		}
		return shareEvent(ctx, tx, "revoked", "", "invitation", "", id, actor)
	})
	if err != nil {
		return SchoolInvitation{}, err
	}
	return scanInvitation(s.db.QueryRow(ctx, `SELECT`+invitationColumns+` FROM school_loans.invitation i WHERE i.id = $1`, id))
}

// ShareCluster is a cluster a Cluster Leader leads today.
type ShareCluster struct {
	ID, Name      string
	MemberSchools int
}

// LeaderClusters are the clusters userID leads on day, with their
// operating member schools.
func (s *Store) LeaderClusters(ctx context.Context, userID string, day time.Time) ([]ShareCluster, error) {
	rows, err := s.db.Query(ctx, `
SELECT c.id, c.name,
  (SELECT count(*) FROM school s WHERE s.cluster_id = c.id AND s.deleted_at IS NULL
     AND s.operational_status IN ('active', 'reopened'))
FROM cluster_leadership.leader_assignment a
JOIN cluster c ON c.id = a.cluster_id AND c.deleted_at IS NULL
WHERE a.user_id = $1 AND a.status = 'active' AND a.starts_on <= $2 AND (a.ends_on IS NULL OR a.ends_on >= $2)
ORDER BY a.starts_on, c.id`, userID, day)
	if err != nil {
		return nil, fmt.Errorf("loans: reading a leader's clusters: %w", err)
	}
	defer rows.Close()
	var out []ShareCluster
	for rows.Next() {
		var c ShareCluster
		if err := rows.Scan(&c.ID, &c.Name, &c.MemberSchools); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// IsMemberSchool says whether a directory school is an operating member of
// one of the clusters.
func (s *Store) IsMemberSchool(ctx context.Context, schoolID string, clusterIDs []string) (bool, error) {
	var member bool
	err := s.db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM school s WHERE s.id = $1 AND s.cluster_id = ANY($2) AND s.deleted_at IS NULL
  AND s.operational_status IN ('active', 'reopened'))`, schoolID, clusterIDs).Scan(&member)
	return member, err
}

// ShareTemplate is an approved message text.
type ShareTemplate struct {
	Channel, Subject, Body, UpdatedByName string
	UpdatedAt                             time.Time
	IsDefault                             bool
}

// ShareTemplates are the saved texts, by channel; channels never saved
// use the defaults.
func (s *Store) ShareTemplates(ctx context.Context) (map[string]ShareTemplate, error) {
	out := map[string]ShareTemplate{}
	for channel, t := range defaultTemplates {
		t.Channel, t.IsDefault = channel, true
		out[channel] = t
	}
	rows, err := s.db.Query(ctx, `SELECT channel, subject, body, updated_by_name, updated_at FROM school_loans.share_template`)
	if err != nil {
		return nil, fmt.Errorf("loans: reading share templates: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var t ShareTemplate
		if err := rows.Scan(&t.Channel, &t.Subject, &t.Body, &t.UpdatedByName, &t.UpdatedAt); err != nil {
			return nil, err
		}
		out[t.Channel] = t
	}
	return out, rows.Err()
}

// SaveShareTemplate replaces a channel's text.
func (s *Store) SaveShareTemplate(ctx context.Context, t ShareTemplate, actor LinkActor, now time.Time) error {
	return s.inWrite(ctx, func(tx pgx.Tx) error {
		_, err := tx.Exec(ctx, `
INSERT INTO school_loans.share_template (channel, subject, body, updated_by, updated_by_name, updated_at)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (channel) DO UPDATE SET subject = EXCLUDED.subject, body = EXCLUDED.body, updated_by = EXCLUDED.updated_by,
  updated_by_name = EXCLUDED.updated_by_name, updated_at = EXCLUDED.updated_at`,
			t.Channel, t.Subject, t.Body, actor.ID, actor.Name, now)
		return err
	})
}

// ShareCount is one row of the sharing figures.
type ShareCount struct {
	Label                                                            string
	Shares, Applications, Delivered, Assessment, Approved, Disbursed int
}

// stageCounts counts applications by the furthest stage each reached.
const stageCounts = `
count(a.id),
count(a.id) FILTER (WHERE a.delivery_status IN ('sent', 'opened_by_lender')),
count(a.id) FILTER (WHERE a.status IN ('under_review', 'information_requested', 'approved', 'disbursed', 'closed')
  OR EXISTS (SELECT 1 FROM school_loans.assessment x WHERE x.application_id = a.id)),
count(a.id) FILTER (WHERE a.status IN ('approved', 'disbursed', 'closed')),
count(a.id) FILTER (WHERE a.status = 'disbursed' OR a.disbursed_amount_ugx IS NOT NULL)`

func (s *Store) shareCounts(ctx context.Context, sql string, args ...any) ([]ShareCount, error) {
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("loans: counting shares: %w", err)
	}
	defer rows.Close()
	var out []ShareCount
	for rows.Next() {
		var c ShareCount
		if err := rows.Scan(&c.Label, &c.Applications, &c.Delivered, &c.Assessment, &c.Approved, &c.Disbursed); err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, rows.Err()
}

// ShareMetrics are sharing's results between two dates.
type ShareMetrics struct {
	LinksGenerated, InvitationsIssued, Shares int
	BySource, ByLender, ByCluster, ByChannel  []ShareCount
}

// SharingResults counts links, shares and the applications they led to,
// from and to inclusive. Applications are counted by how they arrived; no
// applicant is named.
func (s *Store) SharingResults(ctx context.Context, from, to time.Time) (ShareMetrics, error) {
	var m ShareMetrics
	end := to.AddDate(0, 0, 1)
	if err := s.db.QueryRow(ctx, `
SELECT count(*) FILTER (WHERE kind = 'generated' AND link_kind <> 'invitation'),
  count(*) FILTER (WHERE kind = 'generated' AND link_kind = 'invitation'),
  count(*) FILTER (WHERE kind = 'shared')
FROM school_loans.share_event WHERE created_at >= $1 AND created_at < $2`, from, end).
		Scan(&m.LinksGenerated, &m.InvitationsIssued, &m.Shares); err != nil {
		return m, fmt.Errorf("loans: counting share events: %w", err)
	}
	var err error
	if m.BySource, err = s.shareCounts(ctx, `
SELECT CASE WHEN a.invitation_id IS NOT NULL THEN 'School invitation'
  WHEN l.kind = 'partner' THEN 'Lender link'
  WHEN l.kind = 'referral' AND l.cluster_id IS NOT NULL THEN 'Cluster Leader link'
  WHEN l.kind = 'referral' THEN 'Staff personal link'
  ELSE 'Universal link' END,`+stageCounts+`
FROM school_loans.application a LEFT JOIN school_loans.share_link l ON l.id = a.share_link_id
WHERE a.submitted_at >= $1 AND a.submitted_at < $2 GROUP BY 1 ORDER BY 2 DESC`, from, end); err != nil {
		return m, err
	}
	if m.ByLender, err = s.shareCounts(ctx, `
SELECT a.lender_name,`+stageCounts+`
FROM school_loans.application a WHERE a.submitted_at >= $1 AND a.submitted_at < $2 GROUP BY 1 ORDER BY 2 DESC`, from, end); err != nil {
		return m, err
	}
	if m.ByCluster, err = s.shareCounts(ctx, `
SELECT COALESCE(c.name, l.cluster_id),`+stageCounts+`
FROM school_loans.application a JOIN school_loans.share_link l ON l.id = a.share_link_id AND l.cluster_id IS NOT NULL
LEFT JOIN cluster c ON c.id = l.cluster_id
WHERE a.submitted_at >= $1 AND a.submitted_at < $2 GROUP BY 1 ORDER BY 2 DESC`, from, end); err != nil {
		return m, err
	}
	rows, err := s.db.Query(ctx, `
SELECT channel, count(*) FROM school_loans.share_event
WHERE kind = 'shared' AND created_at >= $1 AND created_at < $2 GROUP BY 1 ORDER BY 2 DESC`, from, end)
	if err != nil {
		return m, fmt.Errorf("loans: counting shares by channel: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var c ShareCount
		if err := rows.Scan(&c.Label, &c.Shares); err != nil {
			return m, err
		}
		m.ByChannel = append(m.ByChannel, c)
	}
	return m, rows.Err()
}

// uuidPattern is the shape of the portal's record ids.
var uuidPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

// InvitationMadeBy says whether userID made the invitation.
func (s *Store) InvitationMadeBy(ctx context.Context, id, userID string) (bool, error) {
	var mine bool
	err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM school_loans.invitation WHERE id = $1 AND created_by = $2)`,
		id, userID).Scan(&mine)
	return mine, err
}

// InPortfolio says whether an operating school is assigned to the staff profile.
func (s *Store) InPortfolio(ctx context.Context, schoolID, staffProfile string) (bool, error) {
	var mine bool
	err := s.db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM school s JOIN staff_school_assignment a ON a.school_id = s.id
  WHERE s.id = $1 AND a.staff_id = $2 AND s.deleted_at IS NULL AND s.operational_status IN ('active', 'reopened'))`,
		schoolID, staffProfile).Scan(&mine)
	return mine, err
}
