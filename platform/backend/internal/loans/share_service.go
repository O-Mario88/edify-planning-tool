package loans

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/url"
	"sort"
	"strings"
	"sync/atomic"
	"time"

	"connectrpc.com/connect"

	loansv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1/loansv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
)

var _ loansv1connect.LoanShareServiceHandler = (*ShareService)(nil)

// roleClusterLeader is the Cluster Leader Portal's role. A Cluster Leader
// shares only while leading a cluster today, invites only that cluster's
// member schools, and never sees an application.
const roleClusterLeader = "ClusterLeader"

// ShareService serves edify.loans.v1.LoanShareService.
type ShareService struct {
	store   *Store
	ledger  *LedgerClient
	base    string
	logger  *slog.Logger
	now     func() time.Time
	ready   func(context.Context) error
	isReady atomic.Bool
}

// NewShareService returns the service; base is the public address.
func NewShareService(store *Store, ledgerClient *LedgerClient, base string, ready func(context.Context) error, logger *slog.Logger, now func() time.Time) *ShareService {
	if now == nil {
		now = time.Now
	}
	return &ShareService{store: store, ledger: ledgerClient, base: base, ready: ready, logger: logger, now: now}
}

// sharer is who is sharing, and what they may do.
type sharer struct {
	actor          LinkActor
	edify          *access
	lender         *LenderIdentity
	clusters       []ShareCluster
	inviteAny      bool // any directory school (BTO)
	editTemplates  bool
	seeMetrics     bool
	setLenderLinks bool // any lender's link policy (Country Director)
}

func (s *ShareService) fail(ctx context.Context, err error) error {
	var field *FieldError
	switch {
	case errors.As(err, &field):
		return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, field.Message)
	case errors.Is(err, ErrNotFound):
		return apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "That link or invitation was not found.")
	case errors.Is(err, errNoPublicAddress):
		return apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonScreenUnavailable,
			"This server has no HTTPS public address set, so it cannot make application links.")
	}
	s.logger.Error("loan sharing request failed", slog.String("error", err.Error()))
	return apierr.New(ctx, connect.CodeInternal, apierr.ReasonInternal, "Something went wrong. Try again.")
}

func (s *ShareService) caller(ctx context.Context) (sharer, error) {
	principal, err := principalOf(ctx)
	if err != nil {
		return sharer{}, err
	}
	if s.ready != nil && !s.isReady.Load() {
		if err := s.ready(ctx); err != nil {
			return sharer{}, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable,
				"School loan sharing is not set up on this server yet.")
		}
		s.isReady.Store(true)
	}
	who := sharer{actor: LinkActor{ID: principal.UserID, Name: principal.Name, Role: principal.ActiveRole}}
	switch {
	case IsLenderRole(principal.ActiveRole):
		identity, err := s.store.LenderIdentityOf(ctx, principal.UserID, principal.ActiveRole, principal.Name)
		if errors.Is(err, ErrNotLenderStaff) {
			return who, denied(ctx, "Your account is not an active member of a lending partner's team.")
		}
		if err != nil {
			return who, s.fail(ctx, err)
		}
		who.lender = &identity
	case principal.ActiveRole == roleClusterLeader:
		clusters, err := s.store.LeaderClusters(ctx, principal.UserID, dayOf(s.now()))
		if err != nil {
			return who, s.fail(ctx, err)
		}
		if len(clusters) == 0 {
			return who, denied(ctx, "You can share the loan application while you lead a cluster.")
		}
		who.clusters = clusters
	default:
		granted, ok := staffAccess[principal.ActiveRole]
		if !ok {
			return who, denied(ctx, "Your role does not share the school loan application.")
		}
		who.edify = &granted
		who.inviteAny = granted.followsUp
		who.editTemplates = granted.followsUp || granted.managesLender
		who.seeMetrics = true
		who.setLenderLinks = granted.managesLender
	}
	return who, nil
}

// messages renders the approved texts for a link.
func (s *ShareService) messages(ctx context.Context, link, lender string, fixedLender bool) ([]*loansv1.ShareMessage, error) {
	saved, err := s.store.ShareTemplates(ctx)
	if err != nil {
		return nil, err
	}
	var out []*loansv1.ShareMessage
	for _, channel := range []string{"whatsapp", "sms", "email"} {
		t := saved[channel]
		if fixedLender {
			t = lenderTemplates[channel]
		}
		rendered := renderShare(t, link, lender)
		message := &loansv1.ShareMessage{Channel: channel, Subject: rendered.Subject, Body: rendered.Body}
		if channel == "sms" {
			message.SmsParts = int32(smsParts(rendered.Body))
		}
		out = append(out, message)
	}
	return out, nil
}

func (s *ShareService) linkMessage(ctx context.Context, kind, id, path, title, description, lender string, lock bool) (*loansv1.ShareLink, error) {
	link, err := publicLink(s.base, path)
	if err != nil {
		return nil, err
	}
	messages, err := s.messages(ctx, link, lender, kind == LinkPartner && lock)
	if err != nil {
		return nil, err
	}
	out := &loansv1.ShareLink{Kind: kind, Id: id, Title: title, Description: description, Url: link, Messages: messages,
		LenderName: lender, LockPartner: lock}
	if kind != "invitation" {
		out.QrUrl, _ = publicLink(s.base, path+"/qr.png")
		out.PosterUrl, _ = publicLink(s.base, path+"/poster")
		if kind == "universal" {
			out.QrUrl, _ = publicLink(s.base, applyPath+"/qr.png")
			out.PosterUrl, _ = publicLink(s.base, applyPath+"/poster")
		}
	}
	return out, nil
}

func (s *ShareService) partnerLinkMessage(ctx context.Context, link ShareLink, canManage bool) (*loansv1.ShareLink, error) {
	description := "Opens the application with " + link.LenderName + " already chosen."
	if link.LockPartner {
		description = "Opens the application for " + link.LenderName + " only: the school cannot choose another lender."
	}
	out, err := s.linkMessage(ctx, LinkPartner, link.ID, partnerPath+link.ID, link.LenderName+"'s application link",
		description, link.LenderName, link.LockPartner)
	if err != nil {
		return nil, err
	}
	out.CanSetPolicy, out.CanReplace = canManage, canManage
	return out, nil
}

// GetShareKit is the links and messages the caller may share.
func (s *ShareService) GetShareKit(ctx context.Context, _ *connect.Request[loansv1.GetShareKitRequest]) (*connect.Response[loansv1.GetShareKitResponse], error) {
	who, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	response := &loansv1.GetShareKitResponse{CanInviteSchools: who.inviteAny || len(who.clusters) > 0,
		CanEditTemplates: who.editTemplates, CanSeeMetrics: who.seeMetrics,
		Note: "Sharing opens your phone's own WhatsApp, SMS or email: nothing is sent until you send it. The link opens the public form only; it shows nobody's application."}
	now := s.now()
	switch {
	case who.lender != nil:
		link, err := s.store.PartnerLink(ctx, who.lender.PartnerID, who.actor, now)
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		message, err := s.partnerLinkMessage(ctx, link, who.lender.Has(RoleAdministrator))
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		response.Links = append(response.Links, message)
	case len(who.clusters) > 0:
		link, err := s.store.ReferralLink(ctx, who.clusters[0].ID, who.actor, now)
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		message, err := s.linkMessage(ctx, LinkReferral, link.ID, referralPath+link.ID, "School loan application link",
			"For any school in "+who.clusters[0].Name+": the public form, where the school chooses its lender. "+
				"Applications are counted for your cluster; you will not see them.", "", false)
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		message.CanReplace = true
		response.Links = append(response.Links, message)
		for _, c := range who.clusters {
			response.Clusters = append(response.Clusters, &loansv1.ShareCluster{ClusterId: c.ID, Name: c.Name,
				MemberSchools: int32(c.MemberSchools)})
		}
	default:
		message, err := s.linkMessage(ctx, "universal", "", applyPath, "School loan application link",
			"The public form: the school fills it in and chooses its lender. No account needed.", "", false)
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		response.Links = append(response.Links, message)
	}
	return connect.NewResponse(response), nil
}

var shareChannels = map[string]bool{"whatsapp": true, "sms": true, "email": true, "copy": true, "native": true, "qr": true}

// RecordShare counts a share the caller made from their own phone.
func (s *ShareService) RecordShare(ctx context.Context, request *connect.Request[loansv1.RecordShareRequest]) (*connect.Response[loansv1.RecordShareResponse], error) {
	who, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	msg := request.Msg
	if !shareChannels[msg.GetChannel()] {
		return nil, invalid(ctx, "Unknown share channel.")
	}
	linkID, invitationID := "", ""
	switch msg.GetLinkKind() {
	case "universal":
	case LinkPartner, LinkReferral:
		link, err := s.store.LiveShareLink(ctx, msg.GetLinkId())
		if err != nil || link.Kind != msg.GetLinkKind() {
			return nil, invalid(ctx, "That link is not live.")
		}
		linkID = link.ID
	case "invitation":
		invitationID = msg.GetLinkId()
		if !uuidPattern.MatchString(invitationID) {
			return nil, invalid(ctx, "That invitation is not known.")
		}
	default:
		return nil, invalid(ctx, "Unknown link kind.")
	}
	if err := s.store.RecordShare(ctx, msg.GetChannel(), msg.GetLinkKind(), linkID, invitationID, who.actor); err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&loansv1.RecordShareResponse{}), nil
}

// SetPartnerLinkPolicy fixes or frees the lender on a lender's link.
func (s *ShareService) SetPartnerLinkPolicy(ctx context.Context, request *connect.Request[loansv1.SetPartnerLinkPolicyRequest]) (*connect.Response[loansv1.SetPartnerLinkPolicyResponse], error) {
	who, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	partnerID := request.Msg.GetPartnerId()
	switch {
	case who.lender != nil && who.lender.Has(RoleAdministrator) && (partnerID == "" || partnerID == who.lender.PartnerID):
		partnerID = who.lender.PartnerID
	case who.setLenderLinks && partnerID != "":
	default:
		return nil, denied(ctx, "Only the lender's administrator or the Country Director sets this.")
	}
	link, err := s.store.PartnerLink(ctx, partnerID, who.actor, s.now())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	if err := s.store.SetPartnerLock(ctx, link.ID, request.Msg.GetLockPartner()); err != nil {
		return nil, s.fail(ctx, err)
	}
	link.LockPartner = request.Msg.GetLockPartner()
	message, err := s.partnerLinkMessage(ctx, link, true)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&loansv1.SetPartnerLinkPolicyResponse{Link: message}), nil
}

// ReplaceShareLink retires a link (a lender's, by its administrator; one's
// own referral link) and returns its replacement.
func (s *ShareService) ReplaceShareLink(ctx context.Context, request *connect.Request[loansv1.ReplaceShareLinkRequest]) (*connect.Response[loansv1.ReplaceShareLinkResponse], error) {
	who, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	link, err := s.store.LiveShareLink(ctx, request.Msg.GetLinkId())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	allowed := (link.Kind == LinkReferral && link.CreatedBy == who.actor.ID) ||
		(link.Kind == LinkPartner && who.lender != nil && who.lender.Has(RoleAdministrator) && who.lender.PartnerID == link.PartnerID) ||
		(link.Kind == LinkPartner && who.setLenderLinks)
	if !allowed {
		return nil, denied(ctx, "You cannot replace that link.")
	}
	if err := s.store.ReplaceShareLink(ctx, link, who.actor, s.now()); err != nil {
		return nil, s.fail(ctx, err)
	}
	var message *loansv1.ShareLink
	if link.Kind == LinkPartner {
		fresh, err := s.store.PartnerLink(ctx, link.PartnerID, who.actor, s.now())
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		if err := s.store.SetPartnerLock(ctx, fresh.ID, link.LockPartner); err != nil {
			return nil, s.fail(ctx, err)
		}
		fresh.LockPartner = link.LockPartner
		message, err = s.partnerLinkMessage(ctx, fresh, true)
		if err != nil {
			return nil, s.fail(ctx, err)
		}
	} else {
		fresh, err := s.store.ReferralLink(ctx, link.ClusterID, who.actor, s.now())
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		message, err = s.linkMessage(ctx, LinkReferral, fresh.ID, referralPath+fresh.ID, "School loan application link", "", "", false)
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		message.CanReplace = true
	}
	return connect.NewResponse(&loansv1.ReplaceShareLinkResponse{Link: message}), nil
}

// InviteSchool makes a school's invitation link: a BTO for any directory
// school, a Cluster Leader for a member school of a cluster they lead.
func (s *ShareService) InviteSchool(ctx context.Context, request *connect.Request[loansv1.InviteSchoolRequest]) (*connect.Response[loansv1.InviteSchoolResponse], error) {
	who, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	if _, err := publicLink(s.base, ""); err != nil {
		return nil, s.fail(ctx, err)
	}
	source, campaign := "bto", strings.TrimSpace(request.Msg.GetCampaign())
	if len([]rune(campaign)) > 80 {
		return nil, invalid(ctx, "Keep the campaign name to 80 characters.")
	}
	switch {
	case who.inviteAny:
	case len(who.clusters) > 0:
		ids := make([]string, len(who.clusters))
		for index, c := range who.clusters {
			ids[index] = c.ID
		}
		member, err := s.store.IsMemberSchool(ctx, request.Msg.GetSchoolId(), ids)
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		if !member {
			return nil, denied(ctx, "You can invite the member schools of the clusters you lead.")
		}
		source = "cluster_leader"
	default:
		return nil, denied(ctx, "Your role does not invite schools.")
	}
	school, err := s.store.School(ctx, request.Msg.GetSchoolId())
	if errors.Is(err, ErrNotFound) {
		return nil, invalid(ctx, "That school is not in the School Directory.")
	}
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	token, invitation, err := s.store.InviteSchool(ctx, school, who.actor, source, campaign, s.now())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	message, err := s.linkMessage(ctx, "invitation", invitation.ID, invitationPath+url.PathEscape(token),
		"Invitation for "+school.Name, "Opens the public form with the school's name filled in. It shows nothing else about the school, "+
			"and replaces any earlier invitation for it.", "", false)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	message.SchoolName, message.ExpiresOn = school.Name, invitation.ExpiresAt.In(kampala).Format("2006-01-02")
	return connect.NewResponse(&loansv1.InviteSchoolResponse{Link: message}), nil
}

func (s *ShareService) invitationMessage(i SchoolInvitation, showApplications bool) *loansv1.SchoolInvitation {
	out := &loansv1.SchoolInvitation{Id: i.ID, SchoolName: i.SchoolName, CreatedByName: i.CreatedByName,
		CreatedAt: i.CreatedAt.In(kampala).Format("2006-01-02 15:04"), ExpiresOn: i.ExpiresAt.In(kampala).Format("2006-01-02"),
		Status: i.Status(s.now()), Source: i.Source, Campaign: i.Campaign}
	if showApplications {
		out.Applications = int32(i.Applications)
	}
	return out
}

// ListSchoolInvitations is a school's invitations. Edify's loan staff see
// all with what they led to; a Cluster Leader sees only their own, and
// never whether the school applied.
func (s *ShareService) ListSchoolInvitations(ctx context.Context, request *connect.Request[loansv1.ListSchoolInvitationsRequest]) (*connect.Response[loansv1.ListSchoolInvitationsResponse], error) {
	who, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	if who.edify == nil && len(who.clusters) == 0 {
		return nil, denied(ctx, "Your role does not see school invitations.")
	}
	invitations, err := s.store.SchoolInvitations(ctx, request.Msg.GetSchoolId())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	response := &loansv1.ListSchoolInvitationsResponse{}
	for _, i := range invitations {
		if who.edify == nil && i.CreatedBy != who.actor.ID {
			continue
		}
		response.Invitations = append(response.Invitations, s.invitationMessage(i, who.edify != nil))
	}
	return connect.NewResponse(response), nil
}

// RevokeSchoolInvitation stops an invitation: its maker, or a BTO.
func (s *ShareService) RevokeSchoolInvitation(ctx context.Context, request *connect.Request[loansv1.RevokeSchoolInvitationRequest]) (*connect.Response[loansv1.RevokeSchoolInvitationResponse], error) {
	who, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	id := request.Msg.GetInvitationId()
	if !uuidPattern.MatchString(id) {
		return nil, invalid(ctx, "That invitation is not known.")
	}
	if !who.inviteAny {
		mine, err := s.store.InvitationMadeBy(ctx, id, who.actor.ID)
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		if !mine {
			return nil, denied(ctx, "You can revoke the invitations you made.")
		}
	}
	reason := strings.TrimSpace(request.Msg.GetReason())
	if reason == "" || len([]rune(reason)) > 500 {
		return nil, invalid(ctx, "Give a short reason.")
	}
	invitation, err := s.store.RevokeInvitation(ctx, id, reason, who.actor, s.now())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&loansv1.RevokeSchoolInvitationResponse{Invitation: s.invitationMessage(invitation, who.edify != nil)}), nil
}

func templateMessage(t ShareTemplate) *loansv1.ShareTemplate {
	out := &loansv1.ShareTemplate{Channel: t.Channel, Subject: t.Subject, Body: t.Body, IsDefault: t.IsDefault,
		UpdatedByName: t.UpdatedByName}
	if !t.UpdatedAt.IsZero() {
		out.UpdatedAt = t.UpdatedAt.In(kampala).Format("2006-01-02 15:04")
	}
	return out
}

// GetShareTemplates are the approved texts.
func (s *ShareService) GetShareTemplates(ctx context.Context, _ *connect.Request[loansv1.GetShareTemplatesRequest]) (*connect.Response[loansv1.GetShareTemplatesResponse], error) {
	who, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	saved, err := s.store.ShareTemplates(ctx)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	response := &loansv1.GetShareTemplatesResponse{CanEdit: who.editTemplates, Placeholders: []string{placeholderLink, placeholderLender}}
	for _, channel := range []string{"whatsapp", "sms", "email"} {
		response.Templates = append(response.Templates, templateMessage(saved[channel]))
	}
	return connect.NewResponse(response), nil
}

// SaveShareTemplate replaces a channel's text (BTO, Country Director).
func (s *ShareService) SaveShareTemplate(ctx context.Context, request *connect.Request[loansv1.SaveShareTemplateRequest]) (*connect.Response[loansv1.SaveShareTemplateResponse], error) {
	who, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	if !who.editTemplates {
		return nil, denied(ctx, "Only the BTO or the Country Director edits the share messages.")
	}
	t := ShareTemplate{Channel: request.Msg.GetChannel(), Subject: strings.TrimSpace(request.Msg.GetSubject()),
		Body: strings.TrimSpace(request.Msg.GetBody())}
	if err := checkTemplate(t); err != nil {
		return nil, s.fail(ctx, err)
	}
	if err := s.store.SaveShareTemplate(ctx, t, who.actor, s.now()); err != nil {
		return nil, s.fail(ctx, err)
	}
	t.UpdatedByName, t.UpdatedAt = who.actor.Name, s.now()
	return connect.NewResponse(&loansv1.SaveShareTemplateResponse{Template: templateMessage(t)}), nil
}

func metricRows(counts []ShareCount) []*loansv1.ShareMetricRow {
	out := make([]*loansv1.ShareMetricRow, len(counts))
	for index, c := range counts {
		out[index] = &loansv1.ShareMetricRow{Label: c.Label, Shares: int32(c.Shares), Applications: int32(c.Applications),
			Delivered: int32(c.Delivered), InAssessment: int32(c.Assessment), Approved: int32(c.Approved), Disbursed: int32(c.Disbursed)}
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Applications+out[i].Shares > out[j].Applications+out[j].Shares })
	return out
}

// GetShareMetrics is what sharing led to (Edify's loan staff only).
func (s *ShareService) GetShareMetrics(ctx context.Context, request *connect.Request[loansv1.GetShareMetricsRequest]) (*connect.Response[loansv1.GetShareMetricsResponse], error) {
	who, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	if !who.seeMetrics {
		return nil, denied(ctx, "Sharing results are for Edify's loan oversight.")
	}
	to := dayOf(s.now())
	from := to.AddDate(0, 0, -90)
	if raw := request.Msg.GetFromDate(); raw != "" {
		if from, err = isoDate(raw); err != nil {
			return nil, invalid(ctx, "The from date must look like 2026-11-01.")
		}
	}
	if raw := request.Msg.GetToDate(); raw != "" {
		if to, err = isoDate(raw); err != nil {
			return nil, invalid(ctx, "The to date must look like 2026-11-30.")
		}
	}
	if to.Before(from) {
		return nil, invalid(ctx, "The to date is before the from date.")
	}
	m, err := s.store.SharingResults(ctx, from, to)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&loansv1.GetShareMetricsResponse{FromDate: from.Format("2006-01-02"), ToDate: to.Format("2006-01-02"),
		LinksGenerated: int32(m.LinksGenerated), InvitationsIssued: int32(m.InvitationsIssued), Shares: int32(m.Shares),
		BySource: metricRows(m.BySource), ByLender: metricRows(m.ByLender), ByCluster: metricRows(m.ByCluster),
		ByChannel: metricRows(m.ByChannel),
		Note: fmt.Sprintf("Shares count taps on a share option, not messages delivered or schools reached. "+
			"Applications are counted by how they arrived; cluster figures only where a Cluster Leader's link carried them. "+
			"Approved and disbursed are what lenders recorded (%s to %s).", from.Format("2 Jan 2006"), to.Format("2 Jan 2006")),
	}), nil
}
