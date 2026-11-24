// Package clusterfacilitation is the partner a cluster is assigned to
// facilitate (apps.clusters.facilitation, cluster_views.
// cluster_facilitator_drawer_view and cluster_facilitator_action): a
// standing choice with no date, no cost and no school handed over.
package clusterfacilitation

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/coreforms"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ErrHandOn says the existing application keeps this request.
var ErrHandOn = errors.New("clusterfacilitation: handed on")

const (
	notActivePartner = "Cluster not assigned: Select an active Partner organisation to facilitate."
	whatItAssigns    = "What this assigns The partner facilitates this cluster's group trainings and cluster meetings. Each one you plan from now on names them as its facilitator, and its costs are worked out then: Edify staff carry the meals, venue, materials and transport; the partner is paid the facilitation fee only. The cluster's schools are not assigned to the partner. Assign a school to a partner separately for visits and in-school support."
)

// editableStatuses are activities.editing.EDITABLE_STATUSES.
var editableStatuses = []string{"planned", "scheduled", "rescheduled"}

// Cluster is the cluster as the drawer and save read it.
type Cluster struct {
	ID, Name, Lead, DistrictID, FacilitatorID string
}

// Partner is an active partner organisation.
type Partner struct{ ID, Name string }

// Service draws and saves the facilitator.
type Service struct {
	db     *pgxpool.Pool
	push   activities.NoticePush
	live   activities.NoticePublisher
	logger *slog.Logger
	now    func() time.Time
}

// New makes the service.
func New(db *pgxpool.Pool, push activities.NoticePush, live activities.NoticePublisher, logger *slog.Logger, now func() time.Time) *Service {
	return &Service{db: db, push: push, live: live, logger: logger, now: now}
}

func assignedMessage() string { return "Saved. Press Refresh to see it on the page." }

// cluster is _facilitator_cluster: a role that may assign to a partner, then
// get_operational_cluster_or_404 for a field reader's own cluster. A country
// reader and a supervisor opening a CCEO's cluster are handed on.
func (s *Service) cluster(ctx context.Context, p auth.Principal, id string) (*Cluster, string, error) {
	if !coreforms.MayAssign(p.ActiveRole) {
		return nil, coreforms.AssignPartnerRefused, nil
	}
	if p.InActingAppointment || p.StaffProfileID == "" {
		return nil, "", ErrHandOn
	}
	var c Cluster
	var lead, district, fac *string
	err := s.db.QueryRow(ctx, `SELECT id, name, responsible_staff_id, district_id, facilitating_partner_id
FROM cluster WHERE id = $1 AND deleted_at IS NULL`, strings.TrimSpace(id)).Scan(&c.ID, &c.Name, &lead, &district, &fac)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, "", ErrHandOn
	}
	if err != nil {
		return nil, "", fmt.Errorf("clusterfacilitation: reading the cluster: %w", err)
	}
	for dst, src := range map[*string]*string{&c.Lead: lead, &c.DistrictID: district, &c.FacilitatorID: fac} {
		if src != nil {
			*dst = strings.TrimSpace(*src)
		}
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil || scope.CountryScope || scope.SummaryOnly {
		return nil, "", ErrHandOn
	}
	direct := slices.Contains(scope.OwnClusterIDs, c.ID) ||
		(c.Lead != "" && (c.Lead == p.UserID || c.Lead == p.StaffProfileID)) ||
		(c.Lead == "" && c.DistrictID != "" && slices.Contains(scope.OwnDistrictIDs, c.DistrictID))
	if !direct {
		return nil, "", ErrHandOn
	}
	return &c, "", nil
}

func (s *Service) partners(ctx context.Context) ([]Partner, error) {
	rows, err := s.db.Query(ctx, `SELECT id, name FROM partner WHERE deleted_at IS NULL AND active_status ORDER BY name`)
	if err != nil {
		return nil, fmt.Errorf("clusterfacilitation: reading the partners: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (Partner, error) {
		var p Partner
		err := r.Scan(&p.ID, &p.Name)
		return p, err
	})
}

// Drawer is cluster_facilitator_drawer_view; a refusal is the view's 403.
func (s *Service) Drawer(ctx context.Context, p auth.Principal, clusterID string) (*screensv1.PageDrawer, string, error) {
	c, refusal, err := s.cluster(ctx, p, clusterID)
	if err != nil || refusal != "" {
		return nil, refusal, err
	}
	partners, err := s.partners(ctx)
	if err != nil {
		return nil, "", err
	}
	current := ""
	for _, partner := range partners {
		if partner.ID == c.FacilitatorID {
			current = partner.ID
		}
	}
	var sessions int
	if err := s.db.QueryRow(ctx, `SELECT count(*) FROM activity WHERE cluster_id = $1 AND school_id IS NULL
  AND deleted_at IS NULL AND status = ANY($2)`, c.ID, editableStatuses).Scan(&sessions); err != nil {
		return nil, "", fmt.Errorf("clusterfacilitation: counting the planned sessions: %w", err)
	}
	return drawerFor(*c, current, partners, sessions), "", nil
}

func text(t string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: t}}
}

// drawerFor is facilitator_drawer.html as the feed reads it.
func drawerFor(c Cluster, current string, partners []Partner, sessions int) *screensv1.PageDrawer {
	now := "Staff"
	field := &screensv1.DrawerField{Name: "facilitating_partner_id", Label: "Facilitated by", Kind: "select", Value: current,
		Options: []*screensv1.DrawerOption{{Value: "", Label: "Staff"}}}
	for _, partner := range partners {
		field.Options = append(field.Options, &screensv1.DrawerOption{Value: partner.ID, Label: partner.Name})
		if partner.ID == current {
			now = partner.Name
		}
	}
	items := []*screensv1.DrawerItem{
		text("Now facilitated by " + now + "."),
		{Kind: &screensv1.DrawerItem_Field{Field: field}},
		{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: whatItAssigns, Tone: "info"}}},
	}
	switch {
	case sessions == 1:
		items = append(items, text("1 session already planned for this cluster keeps the facilitator it has. Change one from its own Edit."))
	case sessions > 1:
		items = append(items, text(fmt.Sprintf("%d sessions already planned for this cluster keep the facilitator they have. Change one from its own Edit.", sessions)))
	}
	return &screensv1.PageDrawer{Title: "Partner to facilitate " + c.Name, HasRequired: true, Items: items,
		SubmitLabel: "Save", CancelLabel: "Cancel", CanSubmit: true}
}

// Assign is cluster_facilitator_action and assign_facilitator: the answer's
// message, or a refusal in the existing words, or ErrHandOn.
func (s *Service) Assign(ctx context.Context, p auth.Principal, clusterID, partnerID string, origin activities.Origin) (string, string, error) {
	c, refusal, err := s.cluster(ctx, p, clusterID)
	if err != nil || refusal != "" {
		return "", refusal, err
	}
	partnerID = strings.TrimSpace(partnerID)
	var partnerUser string
	if partnerID != "" {
		var user *string
		err := s.db.QueryRow(ctx, `SELECT user_id FROM partner WHERE id = $1 AND deleted_at IS NULL AND active_status`, partnerID).Scan(&user)
		if errors.Is(err, pgx.ErrNoRows) {
			return "", notActivePartner, nil
		}
		if err != nil {
			return "", "", fmt.Errorf("clusterfacilitation: reading the partner: %w", err)
		}
		if user != nil {
			partnerUser = *user
		}
	}
	now := s.now()
	assignedBy := p.StaffProfileID
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		return "", "", fmt.Errorf("clusterfacilitation: opening the save: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var answer string
	if err := tx.QueryRow(ctx, `SELECT gateway_cluster_facilitation.assign($1, $2, $3, $4)`, c.ID, partnerID, assignedBy, now).Scan(&answer); err != nil {
		return "", "", fmt.Errorf("clusterfacilitation: saving the facilitator: %w", err)
	}
	previous, changed := strings.CutPrefix(answer, "changed:")
	if !changed {
		return assignedMessage(), "", tx.Commit(ctx)
	}
	cover, err := audit.CoverageStamp(ctx, tx, p.UserID, now)
	if err != nil {
		return "", "", err
	}
	if _, err := audit.Append(ctx, tx, audit.Entry{
		Action: "cluster.facilitator_changed", SubjectKind: audit.Text("Cluster"), SubjectID: audit.Text(c.ID),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true,
		Payload:   audit.WithStamps(map[string]any{"from": previous, "to": partnerID}, cover),
		IPAddress: textOrNil(origin.IP), UserAgent: textOrNil(origin.UserAgent), CorrelationID: textOrNil(origin.CorrelationID),
	}, now); err != nil {
		return "", "", fmt.Errorf("clusterfacilitation: writing the audit row: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return "", "", fmt.Errorf("clusterfacilitation: committing the facilitator: %w", err)
	}
	if partnerID != "" && partnerUser != "" {
		if err := activities.SendNotices(ctx, s.db, s.push, s.live, s.logger, now, partnerID, p.UserID, origin, activities.Notice{
			Title: "You are assigned a cluster to facilitate",
			Body:  fmt.Sprintf("Edify assigned %s to your organisation to facilitate. Its trainings and meetings appear on your plan as Edify staff schedule them, each with its facilitation fee.", c.Name),
			Event: "partner_cluster_facilitation_assigned", Category: "partner", ContextType: "Partner", Priority: "normal",
		}, []activities.NoticeTo{{UserID: partnerUser, Route: "/partner/my-plan", Label: "Open My Plan"}}); err != nil && s.logger != nil {
			s.logger.Warn("clusterfacilitation: the partner was not told", "cluster", c.ID, "err", err)
		}
	}
	return assignedMessage(), "", nil
}

func textOrNil(v string) *string {
	if v == "" {
		return nil
	}
	return &v
}
