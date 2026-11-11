package loans

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sort"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"connectrpc.com/connect"

	loansv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1/loansv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

var _ loansv1connect.LoanFollowUpServiceHandler = (*FollowUpService)(nil)

// FollowUpService serves edify.loans.v1.LoanFollowUpService.
type FollowUpService struct {
	*Lending
	isReady atomic.Bool
}

// NewFollowUpService returns the service.
func NewFollowUpService(l *Lending) *FollowUpService { return &FollowUpService{Lending: l} }

// portfolioPageSize is how many rows a page holds.
const portfolioPageSize = 25

// follower is who is following loans, and what they may see and do.
type follower struct {
	principal    auth.Principal
	kind         string // "cceo", "pl", "edify" or "lender"
	edify        *access
	lender       *LenderIdentity
	sender       Sender
	showsAmounts bool
	seesOfficer  bool
}

func (f follower) viewer() viewer {
	if f.lender != nil {
		return viewer{principal: f.principal, lender: f.lender}
	}
	return viewer{principal: f.principal, edify: f.edify}
}

func (s *FollowUpService) fail(ctx context.Context, err error) error {
	var field *FieldError
	switch {
	case errors.As(err, &field):
		return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, field.Message)
	case errors.Is(err, ErrNotFound):
		return apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "That application is not in your schools.")
	case errors.Is(err, ErrNoteDuplicate):
		return apierr.New(ctx, connect.CodeAlreadyExists, apierr.ReasonInvalidArgument, "That notification was already sent today.")
	}
	s.logger.Error("loan follow-up request failed", slog.String("error", err.Error()))
	return apierr.New(ctx, connect.CodeInternal, apierr.ReasonInternal, "Something went wrong. Try again.")
}

func (s *FollowUpService) caller(ctx context.Context) (follower, error) {
	principal, err := principalOf(ctx)
	if err != nil {
		return follower{}, err
	}
	if s.ready != nil && !s.isReady.Load() {
		if err := s.ready(ctx); err != nil {
			return follower{}, apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable,
				"School loans are not set up on this server yet.")
		}
		s.isReady.Store(true)
	}
	f := follower{principal: principal, sender: Sender{ID: principal.UserID, Name: principal.Name, Role: principal.ActiveRole,
		Organisation: "Edify"}}
	switch {
	case principal.ActiveRole == roleCCEO || principal.ActiveRole == roleProgramLead:
		if principal.StaffProfileID == "" {
			return f, denied(ctx, "Your account has no staff profile, so it has no school portfolio.")
		}
		f.kind = "cceo"
		if principal.ActiveRole == roleProgramLead {
			f.kind = "pl"
		}
	case IsLenderRole(principal.ActiveRole):
		identity, err := s.store.LenderIdentityOf(ctx, principal.UserID, principal.ActiveRole, principal.Name)
		if errors.Is(err, ErrNotLenderStaff) {
			return f, denied(ctx, "Your account is not an active member of a lending partner's team.")
		}
		if err != nil {
			return f, s.fail(ctx, err)
		}
		f.kind, f.lender, f.showsAmounts, f.seesOfficer = "lender", &identity, true, true
		f.sender = lenderSender(viewer{lender: &identity})
	default:
		granted, ok := staffAccess[principal.ActiveRole]
		if !ok {
			return f, denied(ctx, "Your role does not follow school loans.")
		}
		f.kind, f.edify = "edify", &granted
		f.showsAmounts, f.seesOfficer = !granted.summaryOnly, !granted.summaryOnly
		f.sender.CanOverride = granted.followsUp || granted.managesLender
	}
	return f, nil
}

// scopes are the portfolios the caller may choose between.
func (f follower) scopes() []Option {
	switch f.kind {
	case "cceo":
		return []Option{{ScopeMine, "My schools"}}
	case "pl":
		return []Option{{ScopeMine, "My schools"}, {ScopeTeam, "My team's schools"}}
	case "lender":
		return []Option{{ScopeAll, "Our applications"}}
	}
	return []Option{{ScopeAll, "All schools"}}
}

// scopeIDs are the applications in a scope, with the portfolio's size.
func (s *FollowUpService) scopeIDs(ctx context.Context, f follower, scope, cceo string) ([]string, int, int, error) {
	switch f.kind {
	case "cceo", "pl":
		profiles := []string{f.principal.StaffProfileID}
		if scope == ScopeTeam {
			team, err := s.store.Supervisees(ctx, f.principal.StaffProfileID)
			if err != nil {
				return nil, 0, 0, err
			}
			profiles = nil
			for _, member := range team {
				if cceo == "" || member.Value == cceo {
					profiles = append(profiles, member.Value)
				}
			}
		}
		return s.store.PortfolioIDs(ctx, profiles)
	case "lender":
		officer := ""
		if !(viewer{lender: f.lender}).seesAllLenderCases() {
			officer = f.lender.UserID
		}
		ids, err := s.store.CaseIDs(ctx, f.lender.PartnerID, officer, portfolioCaseLimit)
		return ids, 0, 0, err
	}
	ids, err := s.store.CaseIDs(ctx, "", "", portfolioCaseLimit)
	return ids, 0, 0, err
}

// mayFollow says whether an application is in any of the caller's scopes.
func (s *FollowUpService) mayFollow(ctx context.Context, f follower, applicationID string) error {
	if f.kind == "edify" || f.kind == "lender" {
		return nil // the case load itself confines a lender to its own
	}
	for _, scope := range f.scopes() {
		ids, _, _, err := s.scopeIDs(ctx, f, scope.Value, "")
		if err != nil {
			return err
		}
		for _, id := range ids {
			if id == applicationID {
				return nil
			}
		}
	}
	return ErrNotFound
}

func (s *FollowUpService) loadFor(ctx context.Context, f follower, applicationID string) (*caseData, error) {
	if err := s.mayFollow(ctx, f, applicationID); err != nil {
		return nil, err
	}
	return s.load(ctx, applicationID, f.viewer())
}

// rowFor words a case for a list or a progress page.
func (s *FollowUpService) rowFor(ctx context.Context, f follower, c *caseData, staff map[string]string) (*loansv1.PortfolioLoanRow, bool, error) {
	r := c.record.Referral
	status, tone := c.displayStatus()
	follow, followTone, due := c.followUp(r.NextFollowUp)
	last, err := s.store.LastNotification(ctx, r.ID)
	if err != nil {
		return nil, false, err
	}
	row := &loansv1.PortfolioLoanRow{ApplicationId: r.ID, SchoolName: r.SchoolName, EdifySchoolId: r.EdifySchoolID,
		SchoolId: r.SchoolDirectoryID, District: r.District, ResponsibleStaff: staff[r.SchoolDirectoryID], LenderName: r.LenderName,
		Reference: r.Reference, AppliedOn: day(r.SubmittedAt.In(kampala)), StatusLabel: status, StatusTone: tone,
		DisbursementLabel: c.disbursementLabel(), FollowUpLabel: follow, FollowUpTone: followTone,
		LastLenderUpdate: day(r.UpdatedAt.In(kampala)), LastNotification: last, NeedsAttention: due,
		CanNotify: len(c.eligibleNotes(f.sender)) > 0, CanFollowUp: c.stage() != StageClosed}
	if r.NextFollowUp != nil {
		row.NextFollowUpOn = day(*r.NextFollowUp)
	}
	if c.disbursed() && c.position.NextDue != nil && c.position.Status != ledger.StatusSettled {
		row.NextPaymentOn = day(c.position.NextDue.DueDate)
	}
	if f.showsAmounts {
		row.Requested = FormatUGX(r.Requested)
		if c.disbursed() {
			row.Disbursed = ugx(c.position.NetDisbursed)
		}
	}
	return row, due, nil
}

// ListPortfolioLoans is the caller's schools' loans.
func (s *FollowUpService) ListPortfolioLoans(ctx context.Context, request *connect.Request[loansv1.ListPortfolioLoansRequest]) (*connect.Response[loansv1.ListPortfolioLoansResponse], error) {
	f, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	msg := request.Msg
	scopes := f.scopes()
	scope := scopes[0].Value
	for _, option := range scopes {
		if option.Value == msg.GetScope() {
			scope = option.Value
		}
	}
	if msg.GetCceoStaffId() != "" && scope != ScopeTeam {
		return nil, invalid(ctx, "Filter by CCEO in your team's schools.")
	}
	ids, schools, without, err := s.scopeIDs(ctx, f, scope, msg.GetCceoStaffId())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	cases := make([]*caseData, 0, len(ids))
	schoolIDs := []string{}
	for _, id := range ids {
		c, err := s.load(ctx, id, f.viewer())
		if errors.Is(err, ErrNotFound) {
			continue
		}
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		cases = append(cases, c)
		if school := c.record.Referral.SchoolDirectoryID; school != "" {
			schoolIDs = append(schoolIDs, school)
		}
	}
	staff, err := s.store.ResponsibleStaff(ctx, schoolIDs)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	type counted struct {
		schools map[string]bool
		records int
	}
	counts := map[string]*counted{}
	for _, rule := range counterRules {
		counts[rule.key] = &counted{schools: map[string]bool{}}
	}
	lenders := map[string]string{}
	search := strings.ToLower(strings.TrimSpace(msg.GetSearch()))
	var rows []*loansv1.PortfolioLoanRow
	for _, c := range cases {
		row, due, err := s.rowFor(ctx, f, c, staff)
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		school := c.record.Referral.SchoolDirectoryID
		if school == "" {
			school = "application:" + c.record.Referral.ID
		}
		in := c.counters(due)
		for key, yes := range in {
			if yes {
				counts[key].records++
				counts[key].schools[school] = true
			}
		}
		lenders[c.record.Referral.PartnerID] = c.record.Referral.LenderName
		switch {
		case msg.GetCounter() != "" && !in[msg.GetCounter()]:
			continue
		case msg.GetLenderPartnerId() != "" && c.record.Referral.PartnerID != msg.GetLenderPartnerId():
			continue
		case search != "" && !strings.Contains(c.searchable(), search):
			continue
		}
		rows = append(rows, row)
	}
	sort.SliceStable(rows, func(i, j int) bool { return rows[i].NeedsAttention && !rows[j].NeedsAttention })
	response := &loansv1.ListPortfolioLoansResponse{Scope: scope, PortfolioSchools: int32(schools),
		SchoolsWithoutApplication: int32(without), ShowsAmounts: f.showsAmounts, Total: int32(len(rows)), PageSize: portfolioPageSize}
	for _, option := range scopes {
		response.Scopes = append(response.Scopes, &loansv1.Choice{Value: option.Value, Label: option.Label})
		if option.Value == scope {
			response.ScopeLabel = option.Label
		}
	}
	for _, rule := range counterRules {
		response.Counters = append(response.Counters, &loansv1.PortfolioCounter{Key: rule.key, Label: rule.label,
			Schools: int32(len(counts[rule.key].schools)), Records: int32(counts[rule.key].records), Rule: rule.rule})
	}
	for id, name := range lenders {
		response.Lenders = append(response.Lenders, &loansv1.Choice{Value: id, Label: name})
	}
	sort.Slice(response.Lenders, func(i, j int) bool { return response.Lenders[i].Label < response.Lenders[j].Label })
	if f.kind == "pl" {
		team, err := s.store.Supervisees(ctx, f.principal.StaffProfileID)
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		for _, member := range team {
			response.Cceos = append(response.Cceos, &loansv1.Choice{Value: member.Value, Label: member.Label})
		}
	}
	page := max(int(msg.GetPage()), 1)
	start := min((page-1)*portfolioPageSize, len(rows))
	response.Rows, response.Page = rows[start:min(start+portfolioPageSize, len(rows))], int32(page)
	return connect.NewResponse(response), nil
}

func staffFollowUpMessage(f StaffFollowUpRecord) *loansv1.StaffFollowUp {
	out := &loansv1.StaffFollowUp{Id: f.ID, FollowedUpOn: day(f.FollowedUpOn), StaffName: f.StaffName, StaffRole: f.StaffRole,
		Method: labelOf(followUpMethods, f.Method), Reason: followUpReasonLabel(f.Reason), Summary: f.Summary,
		SchoolFeedback: f.SchoolFeedback, NextAction: f.NextAction, PaymentReported: f.PaymentReported}
	if f.NextFollowUpOn != nil {
		out.NextFollowUpOn = day(*f.NextFollowUpOn)
	}
	if f.PaymentReported {
		note := "Payment reported by the school"
		if f.ReportedAmount != nil {
			note += ": " + ugx(*f.ReportedAmount)
		}
		if f.ReportedPaidOn != nil {
			note += " on " + day(*f.ReportedPaidOn)
		}
		out.PaymentNote = note + " — awaiting the lender's verification."
	}
	return out
}

func noteMessage(n NoteRecord) *loansv1.NotificationEntry {
	by := n.TriggeredByName
	if n.SenderRole == "system" {
		by = "Weekly reminder"
	}
	return &loansv1.NotificationEntry{Id: n.ID, TypeLabel: NoteLabels[n.Type], SentBy: by, SendingOrganisation: n.Organisation,
		Recipient: maskPhone(n.Recipient), StatusLabel: deliveryStatusLabels[n.Status], StatusTone: deliveryTones[n.Status],
		CreatedAt: n.CreatedAt.In(kampala).Format("2 Jan 2006 15:04"), Failure: failureLabels[n.Failure], Body: n.Body}
}

// GetLoanProgress is one application's progress for the caller.
func (s *FollowUpService) GetLoanProgress(ctx context.Context, request *connect.Request[loansv1.GetLoanProgressRequest]) (*connect.Response[loansv1.GetLoanProgressResponse], error) {
	f, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	c, err := s.loadFor(ctx, f, request.Msg.GetApplicationId())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	staff, err := s.store.ResponsibleStaff(ctx, []string{c.record.Referral.SchoolDirectoryID})
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	row, _, err := s.rowFor(ctx, f, c, staff)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	response := &loansv1.GetLoanProgressResponse{Row: row}
	for _, step := range c.progress() {
		response.Stages = append(response.Stages, &loansv1.ProgressStage{Key: step.Key, Label: step.Label, State: step.State,
			UpdatedOn: step.UpdatedOn, Responsible: step.Responsible, NextAction: step.NextAction, Note: step.Note})
	}
	followUps, err := s.store.StaffFollowUps(ctx, c.record.Referral.ID)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	for _, entry := range followUps {
		response.FollowUps = append(response.FollowUps, staffFollowUpMessage(entry))
	}
	notes, err := s.store.Notifications(ctx, c.record.Referral.ID, 50)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	for _, n := range notes {
		response.Notifications = append(response.Notifications, noteMessage(n))
	}
	if f.seesOfficer && c.record.Assignment != nil {
		response.AssignedOfficer = c.record.Assignment.OfficerName
	}
	if f.kind != "lender" {
		if contact, err := s.store.LenderContact(ctx, c.record.Referral.PartnerID); err == nil {
			response.LenderContact = contact
		}
	}
	response.Facts = []*loansv1.CaseLine{line("Reference", c.record.Referral.Reference), line("Lender", c.record.Referral.LenderName),
		line("Applied", row.AppliedOn), line("Purpose", c.record.Referral.PurposeLabel)}
	if f.showsAmounts {
		response.Facts = append(response.Facts, line("Requested", row.Requested))
	}
	return connect.NewResponse(response), nil
}

// PrepareNotification lists what the caller may send now, with previews.
func (s *FollowUpService) PrepareNotification(ctx context.Context, request *connect.Request[loansv1.PrepareNotificationRequest]) (*connect.Response[loansv1.PrepareNotificationResponse], error) {
	f, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	c, err := s.loadFor(ctx, f, request.Msg.GetApplicationId())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	r := c.record.Referral
	verified, err := s.store.PhoneVerified(ctx, r.ID)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	last, err := s.store.LastNotification(ctx, r.ID)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	response := &loansv1.PrepareNotificationResponse{SchoolName: r.SchoolName, RecipientName: r.DirectorName,
		RecipientPhone: maskPhone(r.DirectorPhone), RecipientVerified: verified, Reference: r.Reference, LastNotification: last,
		Note: "Messages go only to the director's phone on the application, from approved texts. A reminder of the same kind waits " +
			strconv.Itoa(s.cooldownDays()) + " days whoever sent the last one; a school gets at most 2 messages a day and 5 a week."}
	eligible := c.eligibleNotes(f.sender)
	for _, kind := range noteOrder {
		facts, ok := eligible[kind]
		if !ok {
			continue
		}
		link := ""
		if _, linked := linkedNotes[kind]; linked {
			link = "[secure link]"
		}
		preview := renderNote(kind, c, facts, link)
		sameKind, limit, err := s.store.cooldown(ctx, s.store.db, r.ID, kind, s.cooldownDays(), s.now())
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		if transactionalNotes[kind] {
			sameKind = ""
		}
		option := &loansv1.NotificationOption{Type: kind, Label: NoteLabels[kind], Preview: preview, SmsParts: int32(smsParts(preview)),
			InCooldown: sameKind != "" || limit != "", CanOverride: f.sender.CanOverride && limit == ""}
		option.CooldownNote = strings.TrimSpace(limit + " " + sameKind)
		response.Options = append(response.Options, option)
	}
	return connect.NewResponse(response), nil
}

// SendNotification queues one notification to the school.
func (s *FollowUpService) SendNotification(ctx context.Context, request *connect.Request[loansv1.SendNotificationRequest]) (*connect.Response[loansv1.SendNotificationResponse], error) {
	f, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	reason := strings.TrimSpace(request.Msg.GetExceptionReason())
	if len([]rune(reason)) > 500 {
		return nil, invalid(ctx, "Keep the reason to 500 characters.")
	}
	c, err := s.loadFor(ctx, f, request.Msg.GetApplicationId())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	id, status, err := s.sendSchoolNote(ctx, c, request.Msg.GetType(), f.sender, reason, "")
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	s.logger.Info("loan notification", slog.String("application", c.record.Referral.ID), slog.String("type", request.Msg.GetType()),
		slog.String("user", f.principal.UserID), slog.Bool("exception", reason != ""))
	notes, err := s.store.Notifications(ctx, c.record.Referral.ID, 5)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	response := &loansv1.SendNotificationResponse{Message: "Queued. It shows as delivered only when the SMS provider confirms it."}
	if status == "suppressed" {
		response.Message = "Not sent: the school's number has opted out of text messages."
	}
	for _, n := range notes {
		if n.ID == id {
			response.Notification = noteMessage(n)
		}
	}
	return connect.NewResponse(response), nil
}

func isoDay(raw string) (*time.Time, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return nil, nil
	}
	parsed, err := time.Parse("2006-01-02", raw)
	if err != nil {
		return nil, err
	}
	day := ledger.DayOf(parsed)
	return &day, nil
}

// RecordStaffFollowUp records what the caller did about a school's loan.
func (s *FollowUpService) RecordStaffFollowUp(ctx context.Context, request *connect.Request[loansv1.RecordStaffFollowUpRequest]) (*connect.Response[loansv1.RecordStaffFollowUpResponse], error) {
	f, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	msg := request.Msg
	c, err := s.loadFor(ctx, f, msg.GetApplicationId())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	today := ledger.DayOf(s.now().In(kampala))
	in := actionInput{values: map[string]string{"method": msg.GetMethod(), "reason": msg.GetReason()}, today: today}
	method, err := in.choice("method", "how you followed up", followUpMethods)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	reasonCode, err := in.choice("reason", "the reason", followUpReasons)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	on, err := isoDay(msg.GetFollowedUpOn())
	switch {
	case err != nil:
		return nil, invalid(ctx, "The follow-up date must look like 2026-11-11.")
	case on == nil:
		on = &today
	case on.After(today):
		return nil, invalid(ctx, "A follow-up cannot be dated in the future.")
	}
	next, err := isoDay(msg.GetNextFollowUpOn())
	if err != nil || (next != nil && next.Before(today)) {
		return nil, invalid(ctx, "The next follow-up date must be today or later, like 2026-11-18.")
	}
	summary := strings.TrimSpace(msg.GetSummary())
	if summary == "" || len([]rune(summary)) > 4000 {
		return nil, invalid(ctx, "Write a short summary of the discussion (up to 4,000 characters).")
	}
	record := StaffFollowUpRecord{ApplicationID: c.record.Referral.ID, StaffID: f.principal.UserID, StaffName: f.principal.Name,
		StaffRole: f.principal.ActiveRole, Method: method, ContactedPerson: clip(msg.GetContactedPerson(), 200),
		Reason: reasonCode, Summary: summary, SchoolFeedback: clip(msg.GetSchoolFeedback(), 2000),
		ReportedIssue: clip(msg.GetReportedIssue(), 2000), NextAction: clip(msg.GetNextAction(), 1000),
		EscalationTarget: clip(msg.GetEscalationTarget(), 200), ResponsibleUserID: f.principal.UserID,
		FollowedUpOn: *on, NextFollowUpOn: next, PaymentReported: msg.GetPaymentReported(), CreatedAt: s.now()}
	if record.PaymentReported {
		if amount := msg.GetReportedAmountUgx(); amount > 0 {
			m := ledger.Shillings(amount)
			record.ReportedAmount = &m
		} else if amount < 0 {
			return nil, invalid(ctx, "The reported amount cannot be below zero.")
		}
		paid, err := isoDay(msg.GetReportedPaidOn())
		if err != nil || (paid != nil && paid.After(today)) {
			return nil, invalid(ctx, "The reported payment date must be today or earlier.")
		}
		record.ReportedPaidOn = paid
	}
	id, err := s.store.AddStaffFollowUp(ctx, record)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	record.ID = id
	return connect.NewResponse(&loansv1.RecordStaffFollowUpResponse{FollowUp: staffFollowUpMessage(record)}), nil
}

func clip(text string, limit int) string {
	text = strings.TrimSpace(text)
	if runes := []rune(text); len(runes) > limit {
		return string(runes[:limit])
	}
	return text
}

// GetLoanChanges says whether school loans changed since a cursor.
func (s *FollowUpService) GetLoanChanges(ctx context.Context, request *connect.Request[loansv1.GetLoanChangesRequest]) (*connect.Response[loansv1.GetLoanChangesResponse], error) {
	if _, err := s.caller(ctx); err != nil {
		return nil, err
	}
	at, err := s.store.ChangeCursor(ctx)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	cursor := fmt.Sprint(at.UnixNano())
	return connect.NewResponse(&loansv1.GetLoanChangesResponse{Cursor: cursor,
		Changed: request.Msg.GetSince() != "" && request.Msg.GetSince() != cursor}), nil
}
