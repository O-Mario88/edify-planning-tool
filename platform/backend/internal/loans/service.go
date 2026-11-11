package loans

import (
	"bytes"
	"context"
	"encoding/csv"
	"errors"
	"log/slog"
	"net/url"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"connectrpc.com/connect"

	loansv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1/loansv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
)

var _ loansv1connect.LoanReferralServiceHandler = (*Service)(nil)

// Service serves edify.loans.v1.LoanReferralService.
type Service struct {
	store   *Store
	cfg     config.Loans
	mailer  Mailer
	logger  *slog.Logger
	now     func() time.Time
	ready   func(context.Context) error
	isReady atomic.Bool
}

// NewService returns the service. ready says whether school_loans is at the
// version this build needs; mailer may be nil.
func NewService(store *Store, cfg config.Loans, mailer Mailer, ready func(context.Context) error, logger *slog.Logger, now func() time.Time) *Service {
	if now == nil {
		now = time.Now
	}
	return &Service{store: store, cfg: cfg, mailer: mailer, ready: ready, logger: logger, now: now}
}

func (s *Service) checkReady(ctx context.Context) error {
	if s.ready == nil || s.isReady.Load() {
		return nil
	}
	if err := s.ready(ctx); err != nil {
		s.logger.Warn("school loans schema not ready", slog.String("error", err.Error()))
		return apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable,
			"School loan referrals are not set up on this server yet.")
	}
	s.isReady.Store(true)
	return nil
}

func (s *Service) internal(ctx context.Context, err error) error {
	s.logger.Error("loan referral request failed", slog.String("error", err.Error()))
	return apierr.New(ctx, connect.CodeInternal, apierr.ReasonInternal, "Something went wrong. Try again.")
}

// fail turns a store error into the answer the caller sees.
func (s *Service) fail(ctx context.Context, err error) error {
	var field *FieldError
	switch {
	case errors.As(err, &field):
		return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, field.Message)
	case errors.Is(err, ErrNotFound):
		return apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "That application was not found.")
	case errors.Is(err, ErrAlreadyQueued):
		return apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
			"A notification for this application is already waiting to be sent.")
	}
	return s.internal(ctx, err)
}

func invalid(ctx context.Context, message string) error {
	return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, message)
}

// staffCall is the start of every staff RPC: the caller's role and the
// schema's readiness.
func (s *Service) staffCall(ctx context.Context) (auth.Principal, access, error) {
	principal, granted, err := staff(ctx)
	if err != nil {
		return principal, granted, err
	}
	return principal, granted, s.checkReady(ctx)
}

func (s *Service) today() time.Time { return dayOf(s.now()) }

func isoDate(raw string) (time.Time, error) {
	if strings.TrimSpace(raw) == "" {
		return time.Time{}, nil
	}
	return time.ParseInLocation("2006-01-02", strings.TrimSpace(raw), kampala)
}

func filterFrom(ctx context.Context, f *loansv1.LoanFilter) (Filter, error) {
	if f == nil {
		return Filter{}, nil
	}
	from, err := isoDate(f.GetFromDate())
	if err != nil {
		return Filter{}, invalid(ctx, "The from date must look like 2026-11-01.")
	}
	to, err := isoDate(f.GetToDate())
	if err != nil {
		return Filter{}, invalid(ctx, "The to date must look like 2026-11-30.")
	}
	return Filter{
		Search: f.GetSearch(), PartnerID: f.GetPartnerId(), District: f.GetDistrict(), Status: f.GetStatus(),
		DeliveryStatus: f.GetDeliveryStatus(), From: from, To: to, MinRequested: f.GetMinRequestedUgx(),
		MaxRequested: f.GetMaxRequestedUgx(), NeedsFollowUp: f.GetNeedsFollowUp(), MatchStatus: f.GetMatchStatus(),
		PurposeCode: f.GetPurposeCode(),
	}, nil
}

func stamp(at *time.Time) string {
	if at == nil || at.IsZero() {
		return ""
	}
	return at.UTC().Format(time.RFC3339)
}

func dateText(at *time.Time) string {
	if at == nil || at.IsZero() {
		return ""
	}
	return at.Format("2006-01-02")
}

func amountOf(value *int64) int64 {
	if value == nil {
		return 0
	}
	return *value
}

// rowMessage is a list row as the caller's role may see it.
func (s *Service) rowMessage(r Row, granted access) *loansv1.LoanApplicationRow {
	row := &loansv1.LoanApplicationRow{
		Id: r.ID, Reference: r.Reference, SchoolName: r.SchoolName, EdifySchoolId: r.EdifySchoolID,
		District: r.District, DirectorName: r.DirectorName, DirectorPhone: r.DirectorPhone,
		TotalEnrollment: int32(r.Total), FeesCollectedUgx: r.FeesCollected, PurposeLabel: r.PurposeLabel,
		RequestedUgx: r.Requested, PartnerId: r.PartnerID, LenderName: r.LenderName,
		SubmittedAt: r.SubmittedAt.UTC().Format(time.RFC3339), Status: r.Status, StatusLabel: StatusLabel(r.Status),
		DeliveryStatus: r.DeliveryStatus, DeliveryLabel: DeliveryLabel(r.DeliveryStatus),
		LastFollowUpAt: stamp(r.LastFollowUp), NextFollowUpOn: dateText(r.NextFollowUp),
		ResponsibleBtoName: r.ResponsibleBTOName, MatchStatus: r.MatchStatus,
		ApprovedUgx: amountOf(r.Approved), DisbursedUgx: amountOf(r.Disbursed),
		IsOverdue: IsOpen(r.Status) && (r.NextFollowUp == nil || r.NextFollowUp.Before(s.today())),
	}
	if granted.summaryOnly {
		row.DirectorName, row.DirectorPhone, row.FeesCollectedUgx = "", "", 0
	}
	return row
}

func choices() (statuses, deliveries, purposes []*loansv1.Choice) {
	for _, status := range Statuses {
		statuses = append(statuses, &loansv1.Choice{Value: status, Label: StatusLabel(status)})
	}
	for _, status := range []string{DeliveryQueued, DeliverySent, DeliveryFailed, DeliveryOpened} {
		deliveries = append(deliveries, &loansv1.Choice{Value: status, Label: DeliveryLabel(status)})
	}
	for _, purpose := range Purposes {
		purposes = append(purposes, &loansv1.Choice{Value: purpose.Code, Label: purpose.Label})
	}
	return statuses, deliveries, purposes
}

// ListLoanApplications is one page of the filtered applications.
func (s *Service) ListLoanApplications(ctx context.Context, request *connect.Request[loansv1.ListLoanApplicationsRequest]) (*connect.Response[loansv1.ListLoanApplicationsResponse], error) {
	_, granted, err := s.staffCall(ctx)
	if err != nil {
		return nil, err
	}
	filter, err := filterFrom(ctx, request.Msg.GetFilter())
	if err != nil {
		return nil, err
	}
	filter.SummaryOnly = granted.summaryOnly
	page := int(request.Msg.GetPage())
	if page < 1 {
		page = 1
	}
	rows, total, err := s.store.Applications(ctx, filter, page, s.today())
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	channels, err := s.store.Channels(ctx, s.now())
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	statuses, deliveries, purposes := choices()
	response := &loansv1.ListLoanApplicationsResponse{
		Total: int32(total), Page: int32(page), PageSize: pageSize, ContactDetailsHidden: granted.summaryOnly,
		CanFollowUp: granted.followsUp, CanManageLenders: granted.managesLender, CanRecordOversight: granted.oversight,
		Statuses: statuses, DeliveryStatuses: deliveries, Purposes: purposes,
	}
	for _, row := range rows {
		response.Rows = append(response.Rows, s.rowMessage(row, granted))
	}
	for _, channel := range channels {
		response.Lenders = append(response.Lenders, &loansv1.LenderOption{PartnerId: channel.PartnerID, Name: channel.LenderName})
	}
	return connect.NewResponse(response), nil
}

// GetLoanApplication is one application in full, for the caller's role.
func (s *Service) GetLoanApplication(ctx context.Context, request *connect.Request[loansv1.GetLoanApplicationRequest]) (*connect.Response[loansv1.GetLoanApplicationResponse], error) {
	_, granted, err := s.staffCall(ctx)
	if err != nil {
		return nil, err
	}
	referral, err := s.store.Referral(ctx, request.Msg.GetId(), "")
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	timeline, err := s.store.Timeline(ctx, referral.ID, false)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	followUps, err := s.store.FollowUps(ctx, referral.ID)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	deliveries, err := s.store.Deliveries(ctx, referral.ID)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	response := &loansv1.GetLoanApplicationResponse{
		Application: s.detailMessage(referral, granted), CanFollowUp: granted.followsUp,
		CanRecordOversight: granted.oversight, ContactDetailsHidden: granted.summaryOnly,
	}
	for _, event := range timeline {
		response.Timeline = append(response.Timeline, timelineMessage(event, granted))
	}
	for _, f := range followUps {
		response.FollowUps = append(response.FollowUps, followUpMessage(f))
	}
	for _, d := range deliveries {
		response.Deliveries = append(response.Deliveries, &loansv1.DeliveryAttempt{
			Kind: d.Kind, Status: d.Status, Attempts: int32(d.Attempts), LastError: d.LastError,
			SentAt: stamp(d.SentAt), NextAttemptAt: stamp(&d.NextAttemptAt), Recipient: d.Recipient,
		})
	}
	if granted.followsUp {
		for _, action := range []string{ActionAcknowledge, ActionStartReview, ActionRequestInformation, ActionApprove,
			ActionDecline, ActionDisburse, ActionClose} {
			if _, err := NextStatus(referral.Status, action, ActorStaffCorrection); err == nil {
				response.CorrectionActions = append(response.CorrectionActions, &loansv1.Choice{Value: action, Label: actionLabels[action]})
			}
		}
		for _, action := range []string{ActionWithdraw, ActionClose} {
			if _, err := NextStatus(referral.Status, action, ActorStaff); err == nil && !hasChoice(response.CorrectionActions, action) {
				response.CorrectionActions = append(response.CorrectionActions, &loansv1.Choice{Value: action, Label: actionLabels[action]})
			}
		}
		if referral.MatchStatus != MatchMatched {
			candidates, err := s.candidatesFor(ctx, referral)
			if err != nil {
				return nil, s.internal(ctx, err)
			}
			response.MatchCandidates = candidates
		}
	}
	return connect.NewResponse(response), nil
}

func hasChoice(list []*loansv1.Choice, value string) bool {
	for _, choice := range list {
		if choice.GetValue() == value {
			return true
		}
	}
	return false
}

func (s *Service) candidatesFor(ctx context.Context, referral Referral) ([]*loansv1.SchoolOption, error) {
	place, err := s.store.ResolvePlace(ctx, Input{District: referral.District, SubCounty: referral.SubCounty, Parish: referral.Parish})
	if err != nil {
		return nil, err
	}
	var pool []SchoolCandidate
	if place.DistrictID != "" {
		pool, err = s.store.SchoolsInDistrict(ctx, place.DistrictID)
	} else if word := distinctiveWord(referral.SchoolName); word != "" {
		pool, err = s.store.SchoolsNamed(ctx, word)
	}
	if err != nil {
		return nil, err
	}
	match := DecideMatch(MatchQuery{Name: referral.SchoolName, DistrictKnown: place.DistrictID != "", SubCountyID: place.SubCountyID}, pool, nil)
	found := match.Candidates
	if match.Status == MatchMatched {
		found = []SchoolCandidate{match.School}
	}
	return s.schoolOptions(ctx, found)
}

func (s *Service) schoolOptions(ctx context.Context, schools []SchoolCandidate) ([]*loansv1.SchoolOption, error) {
	ids := make([]string, 0, len(schools))
	for _, school := range schools {
		ids = append(ids, school.DistrictID)
	}
	names, err := s.store.DistrictNames(ctx, ids)
	if err != nil {
		return nil, err
	}
	options := make([]*loansv1.SchoolOption, 0, len(schools))
	for _, school := range schools {
		options = append(options, &loansv1.SchoolOption{Id: school.ID, EdifySchoolId: school.SchoolID, Name: school.Name,
			District: names[school.DistrictID]})
	}
	return options, nil
}

func (s *Service) detailMessage(r Referral, granted access) *loansv1.LoanApplicationDetail {
	row := s.rowMessage(Row{
		ID: r.ID, Reference: r.Reference, SchoolName: r.SchoolName, EdifySchoolID: r.EdifySchoolID, District: r.District,
		DirectorName: r.DirectorName, DirectorPhone: r.DirectorPhone, Total: r.Total, FeesCollected: r.FeesCollected,
		PurposeLabel: r.PurposeLabel, Requested: r.Requested, PartnerID: r.PartnerID, LenderName: r.LenderName,
		SubmittedAt: r.SubmittedAt, Status: r.Status, DeliveryStatus: r.DeliveryStatus, LastFollowUp: r.LastFollowUp,
		NextFollowUp: r.NextFollowUp, ResponsibleBTOName: r.ResponsibleBTOName, MatchStatus: r.MatchStatus,
		Approved: r.Approved, Disbursed: r.Disbursed,
	}, granted)
	detail := &loansv1.LoanApplicationDetail{
		Row: row, Source: r.Source, DirectorEmail: r.DirectorEmail, SubCounty: r.SubCounty, Parish: r.Parish,
		Village: r.Village, Boys: int32(r.Boys), Girls: int32(r.Girls), PurposeOther: r.PurposeOther,
		PurposeDetails: r.PurposeDetails, PreferredTermMonths: int32(r.PreferredTerm), MatchMethod: r.MatchMethod,
		SchoolId: r.SchoolDirectoryID, LenderReceivedAt: stamp(r.LenderReceivedAt), DecidedAt: stamp(r.DecidedAt),
		DisbursementDate: dateText(r.DisbursementDate), DisbursementReference: r.DisbursementReference,
		InterestRate: r.InterestRate, LinkedMfiLoanId: r.LinkedMFILoanID, ConsentVersion: r.ConsentVersion,
	}
	if r.AgreedTerm != nil {
		detail.AgreedTermMonths = int32(*r.AgreedTerm)
	}
	if granted.summaryOnly {
		detail.DirectorEmail = ""
	}
	return detail
}

func timelineMessage(e Event, granted access) *loansv1.TimelineEntry {
	entry := &loansv1.TimelineEntry{
		Kind: e.Kind, Label: eventLabel(e.Kind), ActorKind: e.ActorKind, ActorName: e.ActorName,
		FromStatus: e.FromStatus, ToStatus: e.ToStatus, Note: e.Note, Evidence: e.Evidence,
		At: e.At.UTC().Format(time.RFC3339),
	}
	if granted.summaryOnly && e.ActorKind == "applicant" {
		entry.ActorName = "The school"
	}
	return entry
}

func followUpMessage(f FollowUp) *loansv1.FollowUpEntry {
	next := ""
	if !f.NextFollowUpOn.IsZero() {
		next = f.NextFollowUpOn.Format("2006-01-02")
	}
	return &loansv1.FollowUpEntry{
		Id: f.ID, FollowedUpOn: f.FollowedUpOn.Format("2006-01-02"), StaffName: f.StaffName, StaffRole: f.StaffRole,
		Channel: f.Channel, LenderName: f.LenderName, Notes: f.Notes, LenderFeedback: f.LenderFeedback,
		NextAction: f.NextAction, NextFollowUpOn: next, DocumentReference: f.DocumentReference,
		IsOversight: f.IsOversight, CreatedAt: f.CreatedAt.UTC().Format(time.RFC3339),
	}
}

var followUpChannels = map[string]bool{"phone": true, "email": true, "meeting": true, "whatsapp": true, "other": true}

// RecordFollowUp stores a BTO's follow-up with the lender.
func (s *Service) RecordFollowUp(ctx context.Context, request *connect.Request[loansv1.RecordFollowUpRequest]) (*connect.Response[loansv1.RecordFollowUpResponse], error) {
	principal, granted, err := s.staffCall(ctx)
	if err != nil {
		return nil, err
	}
	if !granted.followsUp {
		return nil, denied(ctx, "Only a BTO records follow-ups with lenders.")
	}
	msg := request.Msg
	on, err := isoDate(msg.GetFollowedUpOn())
	if err != nil || on.IsZero() || on.After(s.today()) {
		return nil, invalid(ctx, "Enter the day of the follow-up, today or earlier.")
	}
	next, err := isoDate(msg.GetNextFollowUpOn())
	if err != nil || (!next.IsZero() && !next.After(s.today())) {
		return nil, invalid(ctx, "The next follow-up must be a date after today.")
	}
	if !followUpChannels[msg.GetChannel()] {
		return nil, invalid(ctx, "Choose how you contacted the lender.")
	}
	if strings.TrimSpace(msg.GetNotes()) == "" || len(msg.GetNotes()) > 4000 {
		return nil, invalid(ctx, "Write what was discussed (up to 4,000 characters).")
	}
	saved, err := s.store.RecordFollowUp(ctx, FollowUp{
		ApplicationID: msg.GetApplicationId(), StaffID: principal.UserID, StaffName: principal.Name,
		StaffRole: principal.ActiveRole, FollowedUpOn: on, Channel: msg.GetChannel(),
		Notes: strings.TrimSpace(msg.GetNotes()), LenderFeedback: strings.TrimSpace(msg.GetLenderFeedback()),
		NextAction: strings.TrimSpace(msg.GetNextAction()), NextFollowUpOn: next,
		DocumentReference: strings.TrimSpace(msg.GetDocumentReference()), CreatedAt: s.now(),
	})
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&loansv1.RecordFollowUpResponse{FollowUp: followUpMessage(saved)}), nil
}

// RecordOversightNote stores a Country Director's or RVP's note.
func (s *Service) RecordOversightNote(ctx context.Context, request *connect.Request[loansv1.RecordOversightNoteRequest]) (*connect.Response[loansv1.RecordOversightNoteResponse], error) {
	principal, granted, err := s.staffCall(ctx)
	if err != nil {
		return nil, err
	}
	if !granted.oversight {
		return nil, denied(ctx, "Oversight notes are for the Country Director and the RVP.")
	}
	msg := request.Msg
	next, err := isoDate(msg.GetNextFollowUpOn())
	if err != nil || (!next.IsZero() && !next.After(s.today())) {
		return nil, invalid(ctx, "The next follow-up must be a date after today.")
	}
	if strings.TrimSpace(msg.GetNotes()) == "" || len(msg.GetNotes()) > 4000 {
		return nil, invalid(ctx, "Write the note (up to 4,000 characters).")
	}
	saved, err := s.store.RecordFollowUp(ctx, FollowUp{
		ApplicationID: msg.GetApplicationId(), StaffID: principal.UserID, StaffName: principal.Name,
		StaffRole: principal.ActiveRole, FollowedUpOn: s.today(), Channel: "oversight",
		Notes: strings.TrimSpace(msg.GetNotes()), NextFollowUpOn: next, IsOversight: true, CreatedAt: s.now(),
	})
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&loansv1.RecordOversightNoteResponse{FollowUp: followUpMessage(saved)}), nil
}

// UpdateTracking makes the caller the responsible BTO, or moves the next
// follow-up.
func (s *Service) UpdateTracking(ctx context.Context, request *connect.Request[loansv1.UpdateTrackingRequest]) (*connect.Response[loansv1.UpdateTrackingResponse], error) {
	principal, granted, err := s.staffCall(ctx)
	if err != nil {
		return nil, err
	}
	if !granted.followsUp {
		return nil, denied(ctx, "Only a BTO updates tracking.")
	}
	next, err := isoDate(request.Msg.GetNextFollowUpOn())
	if err != nil || (!next.IsZero() && !next.After(s.today())) {
		return nil, invalid(ctx, "The next follow-up must be a date after today.")
	}
	if !request.Msg.GetTakeResponsibility() && next.IsZero() {
		return nil, invalid(ctx, "Nothing to change.")
	}
	if err := s.store.UpdateTracking(ctx, request.Msg.GetApplicationId(), principal.UserID, principal.Name,
		request.Msg.GetTakeResponsibility(), next, s.now()); err != nil {
		return nil, s.fail(ctx, err)
	}
	row, err := s.oneRow(ctx, request.Msg.GetApplicationId(), granted)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&loansv1.UpdateTrackingResponse{Row: row}), nil
}

func (s *Service) oneRow(ctx context.Context, id string, granted access) (*loansv1.LoanApplicationRow, error) {
	referral, err := s.store.Referral(ctx, id, "")
	if err != nil {
		return nil, err
	}
	return s.detailMessage(referral, granted).GetRow(), nil
}

// SearchSchools finds directory schools for a BTO resolving a match.
func (s *Service) SearchSchools(ctx context.Context, request *connect.Request[loansv1.SearchSchoolsRequest]) (*connect.Response[loansv1.SearchSchoolsResponse], error) {
	_, granted, err := s.staffCall(ctx)
	if err != nil {
		return nil, err
	}
	if !granted.followsUp {
		return nil, denied(ctx, "Only a BTO resolves school matches.")
	}
	if len(strings.TrimSpace(request.Msg.GetQuery())) < 2 {
		return connect.NewResponse(&loansv1.SearchSchoolsResponse{}), nil
	}
	found, err := s.store.SearchSchools(ctx, request.Msg.GetQuery())
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	options, err := s.schoolOptions(ctx, found)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	return connect.NewResponse(&loansv1.SearchSchoolsResponse{Schools: options}), nil
}

// ResolveSchoolMatch links a submission to its directory school.
func (s *Service) ResolveSchoolMatch(ctx context.Context, request *connect.Request[loansv1.ResolveSchoolMatchRequest]) (*connect.Response[loansv1.ResolveSchoolMatchResponse], error) {
	principal, granted, err := s.staffCall(ctx)
	if err != nil {
		return nil, err
	}
	if !granted.followsUp {
		return nil, denied(ctx, "Only a BTO resolves school matches.")
	}
	msg := request.Msg
	var school *SchoolCandidate
	switch {
	case msg.GetNotInDirectory() && msg.GetSchoolId() == "":
	case !msg.GetNotInDirectory() && msg.GetSchoolId() != "":
		found, err := s.store.School(ctx, msg.GetSchoolId())
		if errors.Is(err, ErrNotFound) {
			return nil, invalid(ctx, "That school is not in the School Directory.")
		}
		if err != nil {
			return nil, s.internal(ctx, err)
		}
		school = &found
	default:
		return nil, invalid(ctx, "Choose the directory school, or say it is not in the directory.")
	}
	if err := s.store.ResolveMatch(ctx, msg.GetApplicationId(), school, principal.UserID, principal.Name,
		strings.TrimSpace(msg.GetNote()), s.now()); err != nil {
		return nil, s.fail(ctx, err)
	}
	row, err := s.oneRow(ctx, msg.GetApplicationId(), granted)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&loansv1.ResolveSchoolMatchResponse{Row: row}), nil
}

// ResendToLender queues the lender's notification again.
func (s *Service) ResendToLender(ctx context.Context, request *connect.Request[loansv1.ResendToLenderRequest]) (*connect.Response[loansv1.ResendToLenderResponse], error) {
	principal, granted, err := s.staffCall(ctx)
	if err != nil {
		return nil, err
	}
	if !granted.followsUp {
		return nil, denied(ctx, "Only a BTO sends an application again.")
	}
	if err := s.store.Resend(ctx, request.Msg.GetApplicationId(), principal.UserID, principal.Name,
		strings.TrimSpace(request.Msg.GetNote()), s.now()); err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&loansv1.ResendToLenderResponse{
		Message: "Queued. It is sent within a minute if the lender has a confirmed receiving address.",
	}), nil
}

// RecordCorrection records the lender's decision with its evidence, or
// withdraws or closes the application.
func (s *Service) RecordCorrection(ctx context.Context, request *connect.Request[loansv1.RecordCorrectionRequest]) (*connect.Response[loansv1.RecordCorrectionResponse], error) {
	principal, granted, err := s.staffCall(ctx)
	if err != nil {
		return nil, err
	}
	if !granted.followsUp {
		return nil, denied(ctx, "Only a BTO records corrections.")
	}
	msg := request.Msg
	details, err := actDetailsFrom(ctx, msg.GetNote(), msg.GetEvidence(), msg.GetApprovedUgx(), msg.GetDisbursedUgx(),
		msg.GetDisbursementDate(), msg.GetDisbursementReference(), msg.GetTermMonths(), msg.GetInterestRate())
	if err != nil {
		return nil, err
	}
	kind := ActorStaffCorrection
	if msg.GetAction() == ActionWithdraw {
		kind = ActorStaff
	}
	if msg.GetAction() == ActionClose && strings.TrimSpace(msg.GetEvidence()) == "" {
		kind = ActorStaff
	}
	to, err := s.store.Act(ctx, msg.GetApplicationId(), Actor{Kind: kind, ID: principal.UserID, Name: principal.Name},
		msg.GetAction(), details, s.now())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&loansv1.RecordCorrectionResponse{Status: to, StatusLabel: StatusLabel(to)}), nil
}

func actDetailsFrom(ctx context.Context, note, evidence string, approved, disbursed int64, date, reference string,
	term int32, rate string) (ActDetails, error) {
	day, err := isoDate(date)
	if err != nil {
		return ActDetails{}, invalid(ctx, "The disbursement date must look like 2026-11-11.")
	}
	if approved < 0 || disbursed < 0 || approved > maxUGX || disbursed > maxUGX {
		return ActDetails{}, invalid(ctx, "Check the amounts.")
	}
	return ActDetails{
		Note: strings.TrimSpace(note), Evidence: strings.TrimSpace(evidence), ApprovedAmount: approved,
		DisbursedAmount: disbursed, DisbursementDate: day, DisbursementReference: strings.TrimSpace(reference),
		TermMonths: int(term), InterestRate: strings.TrimSpace(rate),
	}, nil
}

// LinkRegisteredLoan links an application to its lender's registered loan.
func (s *Service) LinkRegisteredLoan(ctx context.Context, request *connect.Request[loansv1.LinkRegisteredLoanRequest]) (*connect.Response[loansv1.LinkRegisteredLoanResponse], error) {
	principal, granted, err := s.staffCall(ctx)
	if err != nil {
		return nil, err
	}
	if !granted.followsUp {
		return nil, denied(ctx, "Only a BTO links registered loans.")
	}
	if err := s.store.LinkLoan(ctx, request.Msg.GetApplicationId(), strings.TrimSpace(request.Msg.GetMfiLoanId()),
		principal.UserID, principal.Name, s.now()); err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&loansv1.LinkRegisteredLoanResponse{Message: "Linked."}), nil
}

func (s *Service) publicURL(ctx context.Context, path string) (string, error) {
	if s.cfg.PublicBaseURL == "" {
		return "", apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonScreenUnavailable,
			"The public application address is not configured on this server (EDIFY_PUBLIC_BASE_URL).")
	}
	return s.cfg.PublicBaseURL + path, nil
}

// GetApplicationLink is the universal link staff share with schools.
func (s *Service) GetApplicationLink(ctx context.Context, _ *connect.Request[loansv1.GetApplicationLinkRequest]) (*connect.Response[loansv1.GetApplicationLinkResponse], error) {
	if _, _, err := s.staffCall(ctx); err != nil {
		return nil, err
	}
	link, err := s.publicURL(ctx, "/apply/school-loan")
	if err != nil {
		return nil, err
	}
	return connect.NewResponse(&loansv1.GetApplicationLinkResponse{Url: link}), nil
}

// CreateInvitation makes a link that names one directory school.
func (s *Service) CreateInvitation(ctx context.Context, request *connect.Request[loansv1.CreateInvitationRequest]) (*connect.Response[loansv1.CreateInvitationResponse], error) {
	principal, granted, err := s.staffCall(ctx)
	if err != nil {
		return nil, err
	}
	if !granted.followsUp {
		return nil, denied(ctx, "Only a BTO creates school invitation links.")
	}
	if _, err := s.publicURL(ctx, ""); err != nil {
		return nil, err
	}
	school, err := s.store.School(ctx, request.Msg.GetSchoolId())
	if errors.Is(err, ErrNotFound) {
		return nil, invalid(ctx, "That school is not in the School Directory.")
	}
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	token, expires, err := s.store.CreateInvitation(ctx, school, principal.UserID, principal.Name, s.now())
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	link, _ := s.publicURL(ctx, "/apply/school-loan?invite="+url.QueryEscape(token))
	return connect.NewResponse(&loansv1.CreateInvitationResponse{
		Url: link, SchoolName: school.Name, ExpiresOn: expires.In(kampala).Format("2006-01-02"),
	}), nil
}

// ExportLoanApplications is the filtered list as CSV, with only the fields
// the caller's role sees.
func (s *Service) ExportLoanApplications(ctx context.Context, request *connect.Request[loansv1.ExportLoanApplicationsRequest]) (*connect.Response[loansv1.ExportLoanApplicationsResponse], error) {
	_, granted, err := s.staffCall(ctx)
	if err != nil {
		return nil, err
	}
	filter, err := filterFrom(ctx, request.Msg.GetFilter())
	if err != nil {
		return nil, err
	}
	filter.SummaryOnly = granted.summaryOnly
	rows, err := s.store.ExportRows(ctx, filter, s.today())
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	header := []string{"Application Reference", "School Name", "School ID", "District"}
	if !granted.summaryOnly {
		header = append(header, "Director's Name", "Director's Phone")
	}
	header = append(header, "Total Enrollment")
	if !granted.summaryOnly {
		header = append(header, "Average Fees Collected per Term (UGX)")
	}
	header = append(header, "Loan Purpose", "Requested Amount (UGX)", "Approved Amount (UGX)", "Disbursed Amount (UGX)",
		"Selected Lending Partner", "Date Submitted", "Application Status", "Lender Delivery Status",
		"Last Follow-up", "Next Follow-up", "Responsible BTO")
	var buffer bytes.Buffer
	writer := csv.NewWriter(&buffer)
	_ = writer.Write(header)
	for _, r := range rows {
		row := s.rowMessage(r, granted)
		record := []string{row.Reference, row.SchoolName, row.EdifySchoolId, row.District}
		if !granted.summaryOnly {
			record = append(record, row.DirectorName, row.DirectorPhone)
		}
		record = append(record, strconv.Itoa(int(row.TotalEnrollment)))
		if !granted.summaryOnly {
			record = append(record, strconv.FormatInt(row.FeesCollectedUgx, 10))
		}
		record = append(record, row.PurposeLabel, strconv.FormatInt(row.RequestedUgx, 10), blankZero(row.ApprovedUgx),
			blankZero(row.DisbursedUgx), row.LenderName, r.SubmittedAt.In(kampala).Format("2006-01-02 15:04"),
			row.StatusLabel, row.DeliveryLabel, dateOfStamp(r.LastFollowUp), row.NextFollowUpOn, row.ResponsibleBtoName)
		_ = writer.Write(safeCells(record))
	}
	writer.Flush()
	if err := writer.Error(); err != nil {
		return nil, s.internal(ctx, err)
	}
	return connect.NewResponse(&loansv1.ExportLoanApplicationsResponse{
		FileName: "school-loan-applications-" + s.now().In(kampala).Format("2006-01-02") + ".csv",
		Csv:      buffer.String(), Rows: int32(len(rows)),
	}), nil
}

func blankZero(value int64) string {
	if value == 0 {
		return ""
	}
	return strconv.FormatInt(value, 10)
}

func dateOfStamp(at *time.Time) string {
	if at == nil {
		return ""
	}
	return at.In(kampala).Format("2006-01-02")
}

// safeCells stops a spreadsheet reading a typed value as a formula.
func safeCells(record []string) []string {
	out := make([]string, len(record))
	for index, cell := range record {
		if cell != "" && strings.ContainsRune("=+-@\t\r", rune(cell[0])) {
			cell = "'" + cell
		}
		out[index] = cell
	}
	return out
}

// GetSchoolLoanHistory is a directory school's loan history (BTO and
// Country Director: the RVP sees totals only).
func (s *Service) GetSchoolLoanHistory(ctx context.Context, request *connect.Request[loansv1.GetSchoolLoanHistoryRequest]) (*connect.Response[loansv1.GetSchoolLoanHistoryResponse], error) {
	_, granted, err := s.staffCall(ctx)
	if err != nil {
		return nil, err
	}
	if !granted.full {
		return nil, denied(ctx, "A school's loan history is for the BTO and the Country Director.")
	}
	school, err := s.store.School(ctx, request.Msg.GetSchoolId())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	rows, err := s.store.SchoolApplications(ctx, school.ID)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	webForm, registered, err := s.store.SchoolLoanRecords(ctx, school.ID)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	response := &loansv1.GetSchoolLoanHistoryResponse{SchoolName: school.Name}
	for _, row := range rows {
		response.Applications = append(response.Applications, s.rowMessage(row, granted))
	}
	for _, a := range webForm {
		response.WebFormApplications = append(response.WebFormApplications, &loansv1.WebFormApplication{
			Id: a.ID, SubmittedAt: a.SubmittedAt.UTC().Format(time.RFC3339), Purpose: a.Purpose,
			RequestedUgx: a.Requested, Status: a.Status, LenderName: a.LenderName,
		})
	}
	for _, l := range registered {
		response.RegisteredLoans = append(response.RegisteredLoans, &loansv1.RegisteredLoan{
			Id: l.ID, LenderName: l.LenderName, Purpose: l.Purpose, Status: l.Status,
			ApprovedUgx: wholeShillings(l.Approved), DisbursedUgx: wholeShillings(l.Disbursed),
			DisbursementDate: dateText(l.DisbursementDate),
		})
	}
	return connect.NewResponse(response), nil
}

func wholeShillings(value *float64) int64 {
	if value == nil {
		return 0
	}
	return int64(*value + 0.5)
}

// GetLoanDashboard is the totals, breakdowns and measures of the filtered
// applications.
func (s *Service) GetLoanDashboard(ctx context.Context, request *connect.Request[loansv1.GetLoanDashboardRequest]) (*connect.Response[loansv1.GetLoanDashboardResponse], error) {
	if _, _, err := s.staffCall(ctx); err != nil {
		return nil, err
	}
	filter, err := filterFrom(ctx, request.Msg.GetFilter())
	if err != nil {
		return nil, err
	}
	now := s.now()
	totals, err := s.store.Totals(ctx, filter, now)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	response := &loansv1.GetLoanDashboardResponse{
		TotalApplications: int32(totals.Applications), AwaitingLenderReceipt: int32(totals.AwaitingReceipt),
		UnderReview: int32(totals.UnderReview), Approved: int32(totals.Approved), Declined: int32(totals.Declined),
		Disbursed: int32(totals.Disbursed), RequestedUgx: totals.Requested, ApprovedUgx: totals.ApprovedAmount,
		DisbursedUgx: totals.DisbursedAmount, NeedsFollowUp: int32(totals.NeedsFollowUp),
		DeliveryProblems: int32(totals.DeliveryProblems), NeedsSchoolMatch: int32(totals.NeedsSchoolMatch),
	}
	targets := map[string]*[]*loansv1.Breakdown{
		"lender": &response.ByLender, "district": &response.ByDistrict, "month": &response.ByMonth,
		"quarter": &response.ByQuarter, "year": &response.ByFinancialYear, "purpose": &response.ByPurpose,
		"status": &response.ByStatus,
	}
	for by, target := range targets {
		groups, err := s.store.Breakdown(ctx, by, filter, dayOf(now))
		if err != nil {
			return nil, s.internal(ctx, err)
		}
		for _, g := range groups {
			*target = append(*target, &loansv1.Breakdown{
				Key: g.Key, Label: g.Label, Applications: int32(g.Applications), RequestedUgx: g.Requested,
				ApprovedUgx: g.ApprovedAmount, DisbursedUgx: g.DisbursedAmount, Approved: int32(g.Approved),
				Disbursed: int32(g.Disbursed),
			})
		}
	}
	measures, err := s.store.Measures(ctx, filter, now)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	for _, m := range measures {
		response.Measures = append(response.Measures, &loansv1.Measure{
			Key: m.Key, Label: m.Label, Available: m.Available, Value: m.Value, Unit: m.Unit,
			BasedOn: int32(m.BasedOn), Note: m.Note,
		})
	}
	return connect.NewResponse(response), nil
}

func channelMessage(c Channel) *loansv1.LenderChannel {
	return &loansv1.LenderChannel{
		PartnerId: c.PartnerID, LenderName: c.LenderName, HasLenderRecord: c.HasLenderRecord,
		LenderActive: c.LenderActive, DataSharingAgreement: c.DataSharingAgreement,
		ReferralsEnabled: c.ReferralsEnabled, DeliveryEmail: c.DeliveryEmail,
		AddressConfirmed: c.ConfirmedAt != nil && c.ConfirmedEmail == c.DeliveryEmail && c.DeliveryEmail != "",
		ConfirmedAt:      stamp(c.ConfirmedAt), AwaitingConfirmation: c.AwaitingConfirmation,
		Description: c.Description, Eligible: c.Eligible(), Problems: c.Problems(), PortalUsers: int32(c.PortalUsers),
	}
}

// ListLenderChannels lists the Loan Partners and how each receives referrals.
func (s *Service) ListLenderChannels(ctx context.Context, _ *connect.Request[loansv1.ListLenderChannelsRequest]) (*connect.Response[loansv1.ListLenderChannelsResponse], error) {
	_, granted, err := s.staffCall(ctx)
	if err != nil {
		return nil, err
	}
	channels, err := s.store.Channels(ctx, s.now())
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	response := &loansv1.ListLenderChannelsResponse{CanManage: granted.managesLender}
	for _, channel := range channels {
		message := channelMessage(channel)
		if !granted.managesLender {
			message.DeliveryEmail = maskEmail(message.DeliveryEmail)
		}
		response.Channels = append(response.Channels, message)
	}
	return connect.NewResponse(response), nil
}

// SaveLenderChannel stores the Country Director's change and, for a new
// address, emails the lender its confirmation link.
func (s *Service) SaveLenderChannel(ctx context.Context, request *connect.Request[loansv1.SaveLenderChannelRequest]) (*connect.Response[loansv1.SaveLenderChannelResponse], error) {
	principal, granted, err := s.staffCall(ctx)
	if err != nil {
		return nil, err
	}
	if !granted.managesLender {
		return nil, denied(ctx, "Lenders' receiving addresses are the Country Director's to manage.")
	}
	msg := request.Msg
	token, err := s.store.SaveChannel(ctx, ChannelUpdate{
		PartnerID: msg.GetPartnerId(), DeliveryEmail: msg.GetDeliveryEmail(), Description: msg.GetDescription(),
		ReferralsEnabled: msg.GetReferralsEnabled(), ActorID: principal.UserID, ActorName: principal.Name,
	}, s.now())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	message := "Saved."
	if token != "" {
		message = s.sendConfirmation(ctx, msg.GetPartnerId(), strings.ToLower(strings.TrimSpace(msg.GetDeliveryEmail())), token)
	}
	channel, err := s.channel(ctx, msg.GetPartnerId())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&loansv1.SaveLenderChannelResponse{Channel: channelMessage(channel), Message: message}), nil
}

func (s *Service) channel(ctx context.Context, partnerID string) (Channel, error) {
	channels, err := s.store.Channels(ctx, s.now())
	if err != nil {
		return Channel{}, err
	}
	for _, channel := range channels {
		if channel.PartnerID == partnerID {
			return channel, nil
		}
	}
	return Channel{}, ErrNotFound
}

// sendConfirmation emails the lender the link that confirms its address,
// and says in words what happened.
func (s *Service) sendConfirmation(ctx context.Context, partnerID, email, token string) string {
	if s.mailer == nil || s.cfg.PublicBaseURL == "" {
		return "Saved. No email could be sent from this server, so the lender has not been asked to confirm the address yet."
	}
	channel, err := s.channel(ctx, partnerID)
	if err != nil {
		return "Saved, but the confirmation email could not be prepared. Send it again."
	}
	link := s.cfg.PublicBaseURL + "/lender/confirm-address?t=" + url.QueryEscape(token)
	if _, err := s.mailer.Send(ctx, Message{
		To:      email,
		Subject: "Confirm your address for Edify school loan referrals",
		Text: "Edify's Country Director has named this address as where " + channel.LenderName + "\n" +
			"receives school loan applications through Edify.\n\nIf this is right, confirm it here (the link works for 7 days):\n" +
			link + "\n\nIf this address is not " + channel.LenderName + "'s, ignore this email.\n\nEdify School Loans\n",
	}); err != nil {
		s.logger.Error("loans: sending an address confirmation", slog.String("error", err.Error()))
		return "Saved, but the confirmation email could not be sent. Send it again."
	}
	return "Saved. The lender has been emailed a link to confirm " + maskEmail(email) + "."
}

// SendChannelConfirmation emails the lender a new confirmation link.
func (s *Service) SendChannelConfirmation(ctx context.Context, request *connect.Request[loansv1.SendChannelConfirmationRequest]) (*connect.Response[loansv1.SendChannelConfirmationResponse], error) {
	principal, granted, err := s.staffCall(ctx)
	if err != nil {
		return nil, err
	}
	if !granted.managesLender {
		return nil, denied(ctx, "Lenders' receiving addresses are the Country Director's to manage.")
	}
	token, email, err := s.store.RenewConfirmation(ctx, request.Msg.GetPartnerId(), principal.UserID, principal.Name, s.now())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&loansv1.SendChannelConfirmationResponse{
		Message: s.sendConfirmation(ctx, request.Msg.GetPartnerId(), email, token),
	}), nil
}

// lenderCall is the start of every RPC for a lender's own staff.
func (s *Service) lenderCall(ctx context.Context) (Actor, error) {
	principal, err := principalOf(ctx)
	if err != nil {
		return Actor{}, err
	}
	if !IsLenderRole(principal.ActiveRole) {
		return Actor{}, denied(ctx, "This is for a lending partner's own staff.")
	}
	if err := s.checkReady(ctx); err != nil {
		return Actor{}, err
	}
	partnerID, lenderName, err := s.store.LenderPartnerOf(ctx, principal.UserID)
	if errors.Is(err, ErrNotFound) {
		return Actor{}, denied(ctx, "Your account is not linked to a Loan Partner in the Partner Directory.")
	}
	if err != nil {
		return Actor{}, s.internal(ctx, err)
	}
	return Actor{Kind: ActorLender, ID: principal.UserID, Name: principal.Name + " (" + lenderName + ")", PartnerID: partnerID}, nil
}

// ListMyReferrals are the applications addressed to the caller's lender.
func (s *Service) ListMyReferrals(ctx context.Context, _ *connect.Request[loansv1.ListMyReferralsRequest]) (*connect.Response[loansv1.ListMyReferralsResponse], error) {
	actor, err := s.lenderCall(ctx)
	if err != nil {
		return nil, err
	}
	rows, _, err := s.store.Applications(ctx, Filter{PartnerID: actor.PartnerID}, 1, s.today())
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	response := &loansv1.ListMyReferralsResponse{LenderName: actor.Name}
	for _, row := range rows {
		message := s.rowMessage(row, access{full: true})
		// Edify's internal tracking is not the lender's.
		message.ResponsibleBtoName, message.NextFollowUpOn, message.LastFollowUpAt, message.IsOverdue = "", "", "", false
		response.Rows = append(response.Rows, message)
	}
	return connect.NewResponse(response), nil
}

// GetMyReferral is one of the caller's lender's applications.
func (s *Service) GetMyReferral(ctx context.Context, request *connect.Request[loansv1.GetMyReferralRequest]) (*connect.Response[loansv1.GetMyReferralResponse], error) {
	actor, err := s.lenderCall(ctx)
	if err != nil {
		return nil, err
	}
	referral, err := s.store.Referral(ctx, request.Msg.GetApplicationId(), actor.PartnerID)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	if err := s.store.MarkOpened(ctx, referral.ID, actor, s.now()); err != nil {
		return nil, s.internal(ctx, err)
	}
	timeline, err := s.store.Timeline(ctx, referral.ID, true)
	if err != nil {
		return nil, s.internal(ctx, err)
	}
	detail := s.detailMessage(referral, access{full: true})
	detail.Row.ResponsibleBtoName, detail.Row.NextFollowUpOn, detail.Row.LastFollowUpAt = "", "", ""
	detail.MatchMethod = ""
	response := &loansv1.GetMyReferralResponse{Application: detail}
	for _, event := range timeline {
		response.Timeline = append(response.Timeline, timelineMessage(event, access{full: true}))
	}
	for _, action := range lenderActionsFor(referral.Status) {
		response.Actions = append(response.Actions, &loansv1.Choice{Value: action, Label: actionLabels[action]})
	}
	return connect.NewResponse(response), nil
}

// RecordLenderUpdate records a stage, decision or message by the lender.
func (s *Service) RecordLenderUpdate(ctx context.Context, request *connect.Request[loansv1.RecordLenderUpdateRequest]) (*connect.Response[loansv1.RecordLenderUpdateResponse], error) {
	actor, err := s.lenderCall(ctx)
	if err != nil {
		return nil, err
	}
	msg := request.Msg
	if msg.GetAction() == "message" {
		if err := s.store.LenderMessage(ctx, msg.GetApplicationId(), actor, msg.GetNote()); err != nil {
			return nil, s.fail(ctx, err)
		}
		referral, err := s.store.Referral(ctx, msg.GetApplicationId(), actor.PartnerID)
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		return connect.NewResponse(&loansv1.RecordLenderUpdateResponse{Status: referral.Status, StatusLabel: StatusLabel(referral.Status)}), nil
	}
	details, err := actDetailsFrom(ctx, msg.GetNote(), "", msg.GetApprovedUgx(), msg.GetDisbursedUgx(),
		msg.GetDisbursementDate(), msg.GetDisbursementReference(), msg.GetTermMonths(), msg.GetInterestRate())
	if err != nil {
		return nil, err
	}
	to, err := s.store.Act(ctx, msg.GetApplicationId(), actor, msg.GetAction(), details, s.now())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&loansv1.RecordLenderUpdateResponse{Status: to, StatusLabel: StatusLabel(to)}), nil
}
