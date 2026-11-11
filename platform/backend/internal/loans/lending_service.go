package loans

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sort"
	"strings"
	"sync/atomic"

	"connectrpc.com/connect"

	loansv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1/loansv1connect"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

var _ loansv1connect.LendingServiceHandler = (*LendingService)(nil)

// LendingService serves edify.loans.v1.LendingService.
type LendingService struct {
	*Lending
	isReady atomic.Bool
}

// NewLendingService returns the service.
func NewLendingService(l *Lending) *LendingService { return &LendingService{Lending: l} }

// casePageSize is how many cases a list returns at a time.
const casePageSize = 50

// portfolioLimit bounds how many of one lender's cases are read at once.
const portfolioLimit = 2000

func (s *LendingService) checkReady(ctx context.Context) error {
	if s.ready == nil || s.isReady.Load() {
		return nil
	}
	if err := s.ready(ctx); err != nil {
		s.logger.Warn("school loans schema not ready", slog.String("error", err.Error()))
		return apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable,
			"School loans are not set up on this server yet.")
	}
	s.isReady.Store(true)
	return nil
}

// fail turns an error into what the caller sees. A ledger refusal is
// shown as the ledger worded it: it is the existing system's own rule.
func (s *LendingService) fail(ctx context.Context, err error) error {
	var field *FieldError
	var refusal *LedgerRefusal
	switch {
	case errors.As(err, &field):
		return apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, field.Message)
	case errors.As(err, &refusal):
		return apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument, refusal.Error())
	case errors.Is(err, ErrLedgerUnavailable):
		s.logger.Error("loan ledger unavailable", slog.String("error", err.Error()))
		return apierr.New(ctx, connect.CodeUnavailable, apierr.ReasonScreenUnavailable,
			"The loan ledger could not be reached. Nothing was recorded; try again shortly.")
	case errors.Is(err, ErrNotFound):
		return apierr.New(ctx, connect.CodeNotFound, apierr.ReasonNotFound, "That loan case was not found.")
	case errors.Is(err, ErrNoSMS):
		return apierr.New(ctx, connect.CodeFailedPrecondition, apierr.ReasonInvalidArgument,
			"Text messages are not set up on this server. Send it by email instead.")
	}
	s.logger.Error("lending request failed", slog.String("error", err.Error()))
	return apierr.New(ctx, connect.CodeInternal, apierr.ReasonInternal, "Something went wrong. Try again.")
}

// caller is who is calling: a lender's active staff member, or Edify staff
// with loan access. Anyone else is refused.
func (s *LendingService) caller(ctx context.Context) (viewer, error) {
	principal, err := principalOf(ctx)
	if err != nil {
		return viewer{}, err
	}
	if err := s.checkReady(ctx); err != nil {
		return viewer{}, err
	}
	if IsLenderRole(principal.ActiveRole) {
		identity, err := s.store.LenderIdentityOf(ctx, principal.UserID, principal.ActiveRole, principal.Name)
		if errors.Is(err, ErrNotLenderStaff) {
			return viewer{}, denied(ctx, "Your account is not an active member of a lending partner's team.")
		}
		if err != nil {
			return viewer{}, s.fail(ctx, err)
		}
		return viewer{principal: principal, lender: &identity}, nil
	}
	granted, ok := staffAccess[principal.ActiveRole]
	if !ok {
		return viewer{}, denied(ctx, "Your role cannot see school loans.")
	}
	return viewer{principal: principal, edify: &granted}, nil
}

func (s *LendingService) lenderOnly(ctx context.Context) (viewer, error) {
	v, err := s.caller(ctx)
	if err == nil && !v.isLender() {
		err = denied(ctx, "This is for a lending partner's own staff.")
	}
	return v, err
}

// portfolio is every case the viewer may see, with its ledger position.
func (s *LendingService) portfolio(ctx context.Context, v viewer) ([]*caseData, error) {
	partner, officer := "", ""
	if v.isLender() {
		partner = v.lender.PartnerID
		if !v.seesAllLenderCases() {
			officer = v.lender.UserID
		}
	}
	ids, err := s.store.CaseIDs(ctx, partner, officer, portfolioLimit)
	if err != nil {
		return nil, err
	}
	out := make([]*caseData, 0, len(ids))
	for _, id := range ids {
		c, err := s.load(ctx, id, v)
		if errors.Is(err, ErrNotFound) {
			continue
		}
		if err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, nil
}

func (c *caseData) row(v viewer) *loansv1.CaseRow {
	r := c.record.Referral
	stage := c.stage()
	row := &loansv1.CaseRow{ApplicationId: r.ID, Reference: r.Reference, SchoolName: r.SchoolName,
		EdifySchoolId: r.EdifySchoolID, District: r.District, Stage: stage, StageLabel: StageLabels[stage],
		LenderName: r.LenderName, Requested: FormatUGX(r.Requested), SubmittedAt: day(r.SubmittedAt.In(kampala))}
	if a := c.record.Assignment; a != nil {
		row.OfficerName = a.OfficerName
	}
	if c.disbursed() {
		row.Outstanding = ugx(c.position.TotalOutstanding)
		row.ServicingLabel = ledger.Label(c.position.Status)
		row.IsOverdue = c.position.Status == ledger.StatusOverdue
		if next := c.position.NextDue; next != nil {
			row.NextDueOn = day(next.DueDate)
		}
	}
	return row
}

func stageChoices(counts map[string]int) []*loansv1.Choice {
	out := []*loansv1.Choice{{Value: "", Label: "All"}}
	for _, stage := range StageOrder {
		out = append(out, &loansv1.Choice{Value: stage, Label: fmt.Sprintf("%s (%d)", StageLabels[stage], counts[stage])})
	}
	out = append(out, &loansv1.Choice{Value: "overdue", Label: fmt.Sprintf("Overdue (%d)", counts["overdue"])},
		&loansv1.Choice{Value: "payments_pending", Label: fmt.Sprintf("Payments to verify (%d)", counts["payments_pending"])})
	return out
}

func (c *caseData) matches(filter, search string) bool {
	switch filter {
	case "":
	case "overdue":
		if !(c.disbursed() && c.position.Status == ledger.StatusOverdue) {
			return false
		}
	case "payments_pending":
		if len(c.pendingEvidence()) == 0 {
			return false
		}
	default:
		if c.stage() != filter {
			return false
		}
	}
	if search = strings.ToLower(strings.TrimSpace(search)); search != "" {
		r := c.record.Referral
		haystack := strings.ToLower(strings.Join([]string{r.Reference, r.SchoolName, r.EdifySchoolID, r.District}, " "))
		return strings.Contains(haystack, search)
	}
	return true
}

func countStages(cases []*caseData) map[string]int {
	counts := map[string]int{}
	for _, c := range cases {
		counts[c.stage()]++
		if c.disbursed() && c.position.Status == ledger.StatusOverdue {
			counts["overdue"]++
		}
		if len(c.pendingEvidence()) > 0 {
			counts["payments_pending"]++
		}
	}
	return counts
}

// GetLenderHome is the lender's dashboard and the caller's own tasks.
func (s *LendingService) GetLenderHome(ctx context.Context, _ *connect.Request[loansv1.GetLenderHomeRequest]) (*connect.Response[loansv1.GetLenderHomeResponse], error) {
	v, err := s.lenderOnly(ctx)
	if err != nil {
		return nil, err
	}
	cases, err := s.portfolio(ctx, v)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	response := &loansv1.GetLenderHomeResponse{LenderName: v.lender.LenderName}
	for _, role := range lenderRoleOrder {
		if v.has(role) {
			response.Roles = append(response.Roles, LenderRoleLabels[role])
		}
	}
	response.Kpis = portfolioKpis(cases)
	response.Tasks = tasksFor(cases, v)
	return connect.NewResponse(response), nil
}

var lenderRoleOrder = []string{RoleAdministrator, RoleLoanOfficer, RoleCreditApprover, RoleFinance, RoleCollections}

type totals struct {
	disbursed, collected, outstanding, overdue ledger.Money
	active, overdueLoans, settledPending       int
}

func sum(cases []*caseData) totals {
	var t totals
	for _, c := range cases {
		if !c.disbursed() {
			continue
		}
		t.disbursed += c.position.NetDisbursed
		t.collected += c.position.TotalVerifiedRepayments
		t.outstanding += c.position.TotalOutstanding
		t.overdue += c.position.AmountOverdue
		switch {
		case c.stage() == StageSettledPending:
			t.settledPending++
		case c.stage() == StageActive:
			t.active++
			if c.position.Status == ledger.StatusOverdue {
				t.overdueLoans++
			}
		}
	}
	return t
}

func portfolioKpis(cases []*caseData) []*loansv1.Kpi {
	counts, t := countStages(cases), sum(cases)
	newCases := counts[StageUnassigned]
	inReview := counts[StageContactPending] + counts[StageAssessment] + counts[StageAwaitingAgreement] + counts[StageAwaitingCredit]
	tone := func(n int, bad string) string {
		if n > 0 {
			return bad
		}
		return "plain"
	}
	rate := "—"
	if due := t.collected + t.overdue; due > 0 {
		rate = fmt.Sprintf("%d%%", int64(t.collected)*100/int64(due))
	}
	return []*loansv1.Kpi{
		{Key: "unassigned", Label: "New, unassigned", Value: fmt.Sprint(newCases), Tone: tone(newCases, "caution"), Filter: StageUnassigned},
		{Key: "in_review", Label: "In review", Value: fmt.Sprint(inReview), Tone: "info"},
		{Key: "awaiting_disbursement", Label: "Awaiting disbursement", Value: fmt.Sprint(counts[StageAwaitingDisbursement] + counts[StageApproved]),
			Tone: "info", Filter: StageAwaitingDisbursement},
		{Key: "active", Label: "Active loans", Value: fmt.Sprint(t.active), Tone: "plain", Filter: StageActive},
		{Key: "overdue_loans", Label: "Overdue loans", Value: fmt.Sprint(t.overdueLoans), Tone: tone(t.overdueLoans, "alert"), Filter: "overdue"},
		{Key: "payments_pending", Label: "Payments to verify", Value: fmt.Sprint(counts["payments_pending"]),
			Tone: tone(counts["payments_pending"], "caution"), Filter: "payments_pending"},
		{Key: "disbursed", Label: "Disbursed", Value: ugx(t.disbursed), Tone: "plain"},
		{Key: "collected", Label: "Verified collections", Value: ugx(t.collected), Tone: "good"},
		{Key: "outstanding", Label: "Outstanding", Value: ugx(t.outstanding), Tone: "plain"},
		{Key: "overdue_amount", Label: "Overdue amount", Value: ugx(t.overdue), Tone: tone(int(min(t.overdue, 1)), "alert"), Filter: "overdue"},
		{Key: "collection_rate", Label: "Collected of amount due", Value: rate, Tone: "plain"},
		{Key: "settled_pending", Label: "Settled, collateral to release", Value: fmt.Sprint(t.settledPending),
			Tone: tone(t.settledPending, "caution"), Filter: StageSettledPending},
	}
}

// tasksFor are the caller's own next steps, by their duties.
func tasksFor(cases []*caseData, v viewer) []*loansv1.Kpi {
	type task struct{ key, label, filter string }
	var tasks []task
	if v.has(RoleAdministrator) {
		tasks = append(tasks, task{"assign", "Applications to assign", StageUnassigned})
	}
	if v.has(RoleLoanOfficer) {
		tasks = append(tasks, task{"contact", "Schools to contact", StageContactPending},
			task{"assess", "Assessments in progress", StageAssessment},
			task{"agreement", "Waiting for the school's agreement", StageAwaitingAgreement})
	}
	if v.has(RoleCreditApprover) {
		tasks = append(tasks, task{"credit", "Awaiting your credit decision", StageAwaitingCredit})
	}
	if v.has(RoleFinance) {
		tasks = append(tasks, task{"disburse", "Ready to disburse", StageAwaitingDisbursement},
			task{"verify", "Payments to verify", "payments_pending"})
	}
	if v.has(RoleCollections) || v.has(RoleLoanOfficer) {
		tasks = append(tasks, task{"overdue", "Overdue loans to follow up", "overdue"})
	}
	if v.has(RoleAdministrator) || v.has(RoleFinance) {
		tasks = append(tasks, task{"release", "Collateral to release", StageSettledPending})
	}
	counts := countStages(cases)
	var out []*loansv1.Kpi
	for _, t := range tasks {
		tone := "plain"
		if counts[t.filter] > 0 {
			tone = "caution"
		}
		out = append(out, &loansv1.Kpi{Key: t.key, Label: t.label, Value: fmt.Sprint(counts[t.filter]), Tone: tone, Filter: t.filter})
	}
	return out
}

// ListLenderCases lists the cases the caller may see, by stage.
func (s *LendingService) ListLenderCases(ctx context.Context, request *connect.Request[loansv1.ListLenderCasesRequest]) (*connect.Response[loansv1.ListLenderCasesResponse], error) {
	v, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	cases, err := s.portfolio(ctx, v)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	filter := request.Msg.GetFilter()
	if _, known := StageLabels[filter]; filter != "" && !known && filter != "overdue" && filter != "payments_pending" {
		return nil, invalid(ctx, "Choose a filter from the list.")
	}
	var rows []*loansv1.CaseRow
	for _, c := range cases {
		if c.matches(filter, request.Msg.GetSearch()) {
			rows = append(rows, c.row(v))
		}
	}
	page := max(int(request.Msg.GetPage()), 1)
	start := min((page-1)*casePageSize, len(rows))
	end := min(start+casePageSize, len(rows))
	return connect.NewResponse(&loansv1.ListLenderCasesResponse{Rows: rows[start:end], Total: int32(len(rows)),
		Page: int32(page), PageSize: casePageSize, Filters: stageChoices(countStages(cases))}), nil
}

// GetCase is one case, as the caller may see it.
func (s *LendingService) GetCase(ctx context.Context, request *connect.Request[loansv1.GetCaseRequest]) (*connect.Response[loansv1.GetCaseResponse], error) {
	v, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	c, err := s.load(ctx, request.Msg.GetApplicationId(), v)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	view, err := s.view(ctx, c, v)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	if v.isLender() {
		if err := s.store.MarkOpened(ctx, c.record.Referral.ID, lenderActor(v), s.now()); err != nil {
			s.logger.Warn("marking a case opened failed", slog.String("error", err.Error()))
		}
	}
	return connect.NewResponse(&loansv1.GetCaseResponse{View: view}), nil
}

// maxActionFile bounds an action's attached file.
const maxActionFile = 5 << 20

// RunCaseAction takes one action, only if the caller may take it now.
func (s *LendingService) RunCaseAction(ctx context.Context, request *connect.Request[loansv1.RunCaseActionRequest]) (*connect.Response[loansv1.RunCaseActionResponse], error) {
	v, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	if len(request.Msg.GetFile()) > maxActionFile {
		return nil, invalid(ctx, "Files must be 5 MB or smaller.")
	}
	c, err := s.load(ctx, request.Msg.GetApplicationId(), v)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	var action *caseAction
	for _, candidate := range s.actionsFor(c, v) {
		if candidate.key == request.Msg.GetAction() {
			action = &candidate
			break
		}
	}
	if action == nil {
		return nil, denied(ctx, "That action is not available to you on this case now.")
	}
	in := actionInput{values: request.Msg.GetValues(), file: request.Msg.GetFile(), fileName: request.Msg.GetFileName(), today: c.today}
	if in.values == nil {
		in.values = map[string]string{}
	}
	message, err := action.run(ctx, s.Lending, c, v, in)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	s.logger.Info("case action", slog.String("application", c.record.Referral.ID), slog.String("action", action.key),
		slog.String("user", v.principal.UserID))
	fresh, err := s.load(ctx, c.record.Referral.ID, v)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	view, err := s.view(ctx, fresh, v)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&loansv1.RunCaseActionResponse{Message: message, View: view}), nil
}

// GetDocument is one of a case's documents, to someone who may see the case.
func (s *LendingService) GetDocument(ctx context.Context, request *connect.Request[loansv1.GetDocumentRequest]) (*connect.Response[loansv1.GetDocumentResponse], error) {
	v, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	if v.edify != nil && v.edify.summaryOnly {
		return nil, denied(ctx, "Documents are not part of the summary view.")
	}
	c, err := s.load(ctx, request.Msg.GetApplicationId(), v)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	meta, content, err := s.store.Document(ctx, c.record.Referral.ID, request.Msg.GetDocumentId())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	return connect.NewResponse(&loansv1.GetDocumentResponse{FileName: meta.FileName, ContentType: meta.ContentType, Content: content}), nil
}

func memberMessage(m TeamMember) *loansv1.TeamMember {
	roles := append([]string(nil), m.Roles...)
	sort.Strings(roles)
	return &loansv1.TeamMember{UserId: m.UserID, Name: m.Name, Email: m.Email, OfficerReference: m.OfficerReference,
		MembershipActive: m.MembershipActive, PlatformActive: m.PlatformActive, Roles: roles, OpenCases: int32(m.OpenCases)}
}

// GetLenderTeam is the caller's lender's team.
func (s *LendingService) GetLenderTeam(ctx context.Context, _ *connect.Request[loansv1.GetLenderTeamRequest]) (*connect.Response[loansv1.GetLenderTeamResponse], error) {
	v, err := s.lenderOnly(ctx)
	if err != nil {
		return nil, err
	}
	members, err := s.store.Team(ctx, v.lender.PartnerID)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	response := &loansv1.GetLenderTeamResponse{LenderName: v.lender.LenderName, CanManage: v.has(RoleAdministrator),
		AddMemberNote: "People join your team through your existing lender team in Edify. Ask Edify's Business Transformation Officer to add someone; you then give them their duties here."}
	for _, m := range members {
		response.Members = append(response.Members, memberMessage(m))
	}
	for _, role := range lenderRoleOrder {
		response.Roles = append(response.Roles, &loansv1.Choice{Value: role, Label: LenderRoleLabels[role]})
	}
	return connect.NewResponse(response), nil
}

// SetLenderTeamMember sets a member's duties; the administrator's alone.
func (s *LendingService) SetLenderTeamMember(ctx context.Context, request *connect.Request[loansv1.SetLenderTeamMemberRequest]) (*connect.Response[loansv1.SetLenderTeamMemberResponse], error) {
	v, err := s.lenderOnly(ctx)
	if err != nil {
		return nil, err
	}
	if !v.has(RoleAdministrator) {
		return nil, denied(ctx, "Only your lending partner's administrator sets team duties.")
	}
	msg := request.Msg
	if msg.GetUserId() == v.lender.UserID && !contains(msg.GetRoles(), RoleAdministrator) {
		return nil, invalid(ctx, "You cannot remove your own administrator role.")
	}
	members, err := s.store.Team(ctx, v.lender.PartnerID)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	var member *TeamMember
	for index := range members {
		if members[index].UserID == msg.GetUserId() {
			member = &members[index]
		}
	}
	if member == nil {
		return nil, s.fail(ctx, ErrNotFound)
	}
	if reference := strings.TrimSpace(msg.GetOfficerReference()); reference != member.OfficerReference {
		// The existing application keeps the reference, on loan officers'
		// memberships only (it would make an administrator a loan officer).
		if member.AccountRole != roleMFIOfficer {
			return nil, invalid(ctx, "Officer references are for loan officers' accounts.")
		}
		if len(reference) > 64 {
			return nil, invalid(ctx, "Keep the officer reference to 64 characters.")
		}
		if err := s.ledger.SetOfficerReference(ctx, v.lender.MFIID, member.UserID, reference); err != nil {
			return nil, s.fail(ctx, err)
		}
	}
	if err := s.store.SetTeamMember(ctx, v.lender.PartnerID, msg.GetUserId(), msg.GetRoles(), msg.GetPlatformActive(),
		v.lender.UserID, v.lender.Name, strings.TrimSpace(msg.GetNote()), s.now()); err != nil {
		return nil, s.fail(ctx, err)
	}
	if members, err = s.store.Team(ctx, v.lender.PartnerID); err != nil {
		return nil, s.fail(ctx, err)
	}
	for _, m := range members {
		if m.UserID == msg.GetUserId() {
			return connect.NewResponse(&loansv1.SetLenderTeamMemberResponse{Member: memberMessage(m)}), nil
		}
	}
	return nil, s.fail(ctx, ErrNotFound)
}

// stallStages are stages where a case waits on the lender.
var stallStages = map[string]bool{StageUnassigned: true, StageContactPending: true, StageAssessment: true,
	StageAwaitingCredit: true, StageApproved: true, StageAwaitingDisbursement: true, StageSettledPending: true}

// staleAfterDays: a waiting case untouched this long is shown to Edify.
const staleAfterDays = 14

// GetServicingOverview is Edify's view across lenders.
func (s *LendingService) GetServicingOverview(ctx context.Context, _ *connect.Request[loansv1.GetServicingOverviewRequest]) (*connect.Response[loansv1.GetServicingOverviewResponse], error) {
	v, err := s.caller(ctx)
	if err != nil {
		return nil, err
	}
	if v.isLender() {
		return nil, denied(ctx, "This is Edify's oversight across lenders.")
	}
	cases, err := s.portfolio(ctx, v)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	byLender := map[string][]*caseData{}
	var order []string
	for _, c := range cases {
		partner := c.record.Referral.PartnerID
		if _, seen := byLender[partner]; !seen {
			order = append(order, partner)
		}
		byLender[partner] = append(byLender[partner], c)
	}
	response := &loansv1.GetServicingOverviewResponse{Kpis: portfolioKpis(cases)}
	for _, partner := range order {
		group := byLender[partner]
		counts, t := countStages(group), sum(group)
		waiting := 0
		for stage := range stallStages {
			waiting += counts[stage]
		}
		response.Lenders = append(response.Lenders, &loansv1.LenderPortfolio{PartnerId: partner,
			LenderName: group[0].record.Referral.LenderName, Applications: int32(len(group)),
			AwaitingLenderAction: int32(waiting), Approved: int32(counts[StageApproved] + counts[StageAwaitingDisbursement]),
			ActiveLoans: int32(t.active), OverdueLoans: int32(t.overdueLoans), Closed: int32(counts[StageClosed]),
			CollateralReleasePending: int32(t.settledPending), Disbursed: ugx(t.disbursed),
			VerifiedCollections: ugx(t.collected), Outstanding: ugx(t.outstanding), Overdue: ugx(t.overdue)})
	}
	sort.SliceStable(response.Lenders, func(i, j int) bool { return response.Lenders[i].LenderName < response.Lenders[j].LenderName })
	cutoff := s.now().AddDate(0, 0, -staleAfterDays)
	for _, c := range cases {
		if stallStages[c.stage()] && c.record.Referral.UpdatedAt.Before(cutoff) {
			response.Stalled = append(response.Stalled, c.row(v))
		}
	}
	return connect.NewResponse(response), nil
}
