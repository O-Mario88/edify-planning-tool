package activities

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/url"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/planningpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// ErrHandOn says the save is not 27.3's case: the existing application
// makes it, unchanged. Nothing was written.
var ErrHandOn = errors.New("activities: handed on to the existing application")

// Refusal is the existing application's words for a refused save.
// Nothing was written.
type Refusal struct {
	Message string
	// Forbidden is the view's 403 (the drawer's gate, a closed school).
	Forbidden bool
}

func (r *Refusal) Error() string { return r.Message }

// handOn names why a save is handed on; errors.Is(err, ErrHandOn) holds.
func handOn(why string) error { return fmt.Errorf("%w: %s", ErrHandOn, why) }

func refuse(format string, args ...any) error {
	return &Refusal{Message: fmt.Sprintf(format, args...)}
}

// Request is the drawer's fields (activities.proto ScheduleSchoolVisitRequest).
type Request struct {
	SchoolID, Purpose, Date, Goal, Outcome      string
	DeviationReason, CatalogueItemID, RecReason string
	// Focus is the intervention the planner named; blank leaves it to the SSA.
	Focus string
	// SourceActivityID is the session a Training Follow Up follows.
	SourceActivityID string
	// Justification is why a requester needs to visit; only a request reads it.
	Justification string
}

// Answer is the saved visit and the confirmation the web shows.
type Answer struct {
	ActivityID, Status, ActivityType, PlannedDate, FY string
	Message, Notice, PlanURL, PlanLinkLabel           string
	// PairedVisitID is the school visit an In-school Training wrote beside
	// itself (32); empty for a visit.
	PairedVisitID string
}

// Request facts the audit pipeline records (the existing request context).
type Origin struct {
	IP, UserAgent, CorrelationID string
}

// Service schedules a school visit.
type Service struct {
	db      *pgxpool.Pool
	pricing Pricing
	logger  *slog.Logger
	now     func() time.Time
	kampala *time.Location
	// The owner's notice for a visit someone else put on their plan.
	noticePush NoticePush
	live       NoticePublisher
	// requests answers an Accountant's visit; nil hands those on.
	requests VisitRequests
	// governed answers for a pinned governed visit; nil hands those on.
	governed GovernedSupport
}

// NewService builds the save over the gateway's pool.
func NewService(db *pgxpool.Pool, pricing Pricing, logger *slog.Logger, now func() time.Time) (*Service, error) {
	loc, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		return nil, fmt.Errorf("activities: loading the time zone: %w", err)
	}
	if now == nil {
		now = time.Now
	}
	return &Service{db: db, pricing: pricing, logger: logger, now: now, kampala: loc}, nil
}

var isoDate = regexp.MustCompile(`^\d{4}-\d{2}-\d{2}$`)

// plan is everything decided before the transaction.
type plan struct {
	p       auth.Principal
	school  school
	item    item
	version int
	// firstVersion: the save writes the item's version 1.
	firstVersion bool
	// core is the Core package this save counts against, if any.
	core *coreBooking
	// interventionRefusal is met inside the save, after the duplicate test.
	interventionRefusal string
	// doorAudit is the audit row of the form the save came through, if any.
	doorAudit string
	// ceilingCourse is the course whose training ceiling is asked again under
	// the school's lock.
	ceilingCourse string
	need          schoolNeed
	focus         string
	evidence      evidence
	row           activityRow
	ownerUID      string
	home          staffHome
	verdict       DayVerdict
	origin        Origin
	now           time.Time
}

// Schedule makes the save, or refuses it in the existing words, or hands it
// on (ErrHandOn).
func (s *Service) Schedule(ctx context.Context, p auth.Principal, req Request, origin Origin) (Answer, error) {
	if IsPairPurpose(req.Purpose) {
		return s.schedulePair(ctx, p, req, origin)
	}
	pl, err := s.prepare(ctx, p, req, origin)
	if err != nil {
		return Answer{}, err
	}
	rowID, err := s.write(ctx, pl)
	if err != nil {
		return Answer{}, err
	}
	s.afterCommit(ctx, pl, rowID)
	return s.answer(ctx, pl)
}

// prepare is the view (schedule_action_view) and `_create` up to its
// transaction (3207), in their order.
func (s *Service) prepare(ctx context.Context, p auth.Principal, req Request, origin Origin) (*plan, error) {
	now := s.now()
	today := dateOnly(now.In(s.kampala))
	// The drawer's gate (1987).
	if !in(rules.Doors.Drawer, p.ActiveRole) {
		message := noPermission
		if p.ActiveRole == rules.Doors.AdminRole {
			message = rules.Doors.AdminRefusal
		}
		return nil, &Refusal{Message: message, Forbidden: true}
	}
	// Not 27.3's case: asking for a visit, working in another's seat, no
	// staff profile, a purpose outside the six, a date in another form.
	purpose := strings.TrimSpace(req.Purpose)
	date := strings.TrimSpace(req.Date)
	requester := in(rules.Doors.Requesters, p.ActiveRole)
	if (requester && s.requests == nil) || p.InActingAppointment || p.StaffProfileID == "" ||
		!in(inScopePurposes, purpose) || (date != "" && !isoDate.MatchString(date)) {
		return nil, handOn("not the owner's own visit for one of the six purposes")
	}
	// The date (2061–2072).
	if date == "" {
		return nil, refuse("Pick the date this is planned for before scheduling it.")
	}
	day, err := time.ParseInLocation(time.DateOnly, date, s.kampala)
	if err != nil {
		return nil, refuse("That scheduled date is not a valid calendar date.")
	}
	activityType := rules.Purposes.ActivityTypes[purpose]
	label := rules.Purposes.Labels[purpose]
	if label == "" {
		label = activityType
	}
	noCosting := refuse("No single approved Catalogue Activity costs “%s”. Ask the Country Director to define one costing for it before scheduling this purpose.", label)
	// require_catalogue (2161–2190), then the pinned item against the
	// purpose (2226–2273).
	itemID := strings.TrimSpace(req.CatalogueItemID)
	recReason := strings.TrimSpace(req.RecReason)
	if itemID == "" {
		resolved, err := resolveForKind(ctx, s.db, activityType, today)
		if err != nil {
			return nil, err
		}
		if resolved == nil {
			return nil, noCosting
		}
		itemID = resolved.ID
	} else {
		pinned, err := itemByID(ctx, s.db, itemID)
		if err != nil {
			return nil, err
		}
		if pinned == nil {
			return nil, handOn("the pinned item is unknown")
		}
		if pinned.WorkflowKind != activityType {
			otherPurpose := ""
			for p, kind := range rules.Purposes.ActivityTypes {
				if kind == pinned.WorkflowKind {
					otherPurpose = p
				}
			}
			if !in(rules.Purposes.InterventionFree, purpose) && (otherPurpose == "" || otherPurpose == purpose) {
				// The pin stands, and `_create` takes the type from the item.
				if s.governed == nil || pinned.WorkflowKind != governedVisitKind {
					return nil, handOn("the SSA recommendation's pinned item stands")
				}
				activityType = pinned.WorkflowKind
			} else {
				resolved, err := resolveForKind(ctx, s.db, activityType, today)
				if err != nil {
					return nil, err
				}
				if resolved == nil {
					return nil, noCosting
				}
				itemID, recReason = resolved.ID, ""
			}
		}
	}
	var target *visitTarget
	if requester {
		target, err = s.requestTarget(ctx, p, req.SchoolID, purpose, now)
		if err != nil {
			return nil, err
		}
	} else {
		sc, responsible, err := s.visitSchool(ctx, p, req.SchoolID, purpose, now)
		if err != nil {
			return nil, err
		}
		target = &visitTarget{school: *sc, responsible: responsible}
	}
	booking, err := s.routeCoreVisit(ctx, *target, purpose, day, now)
	if err != nil {
		return nil, err
	}
	target.core = booking
	if booking != nil && booking.route == corePackageVisit {
		// schedule_as_core_visit: the package's own item prices it.
		coreItem, err := resolveForKind(ctx, s.db, coreVisitKind, day)
		if err != nil {
			return nil, err
		}
		if coreItem == nil {
			return nil, refuse(noCoreVisitCosting)
		}
		itemID, activityType = coreItem.ID, coreVisitKind
	}
	return s.create(ctx, p, req, origin, now, today, day, *target, itemID, recReason, purpose, activityType)
}

// visitSchool is the view's school (2318–2338) and visit_owner_for: whose
// visit this is. Outside the person's portfolio it is the person going; inside
// it, the school's owner, who may be a colleague.
func (s *Service) visitSchool(ctx context.Context, p auth.Principal, schoolID, purpose string, now time.Time) (*school, string, error) {
	sc, mine, err := s.targetSchool(ctx, p, schoolID, purpose, now)
	if err != nil {
		return nil, "", err
	}
	if sc.closed() {
		return nil, "", &Refusal{Message: rules.ClosedSchoolMessage, Forbidden: true}
	}
	if !mine {
		return sc, p.StaffProfileID, nil
	}
	owner, err := schoolOwner(ctx, s.db, sc.ID)
	if err != nil {
		return nil, "", err
	}
	if owner == "" {
		// resolve_monitoring_staff's fallbacks past the assignment.
		return nil, "", handOn("the school has no assigned owner")
	}
	return sc, owner, nil
}

// targetSchool resolves the school again on POST (2318–2338) and says whether
// it is in the person's own portfolio.
func (s *Service) targetSchool(ctx context.Context, p auth.Principal, schoolID, purpose string, now time.Time) (*school, bool, error) {
	sc, err := schoolByIDOrCode(ctx, s.db, strings.TrimSpace(schoolID))
	if err != nil {
		return nil, false, err
	}
	if sc == nil || sc.Code != strings.TrimSpace(schoolID) ||
		(in(rules.Gate.CoreRuleTypes, sc.Type) && !in(inScopePurposes, purpose) && !IsPairPurpose(purpose)) {
		return nil, false, handOn("not a school code, or a purpose Go does not take at a Core school")
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, false, handOn("no scope: " + err.Error())
	}
	return sc, slices.Contains(scope.OwnSchoolIDs, sc.ID), nil
}

func dateOnly(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, t.Location())
}

// create is `_create` (2203) for this case, to its transaction.
func (s *Service) create(ctx context.Context, p auth.Principal, req Request, origin Origin, now, today, day time.Time,
	target visitTarget, itemID, recReason, purpose, activityType string) (*plan, error) {
	sc, responsible, isRequest := target.school, target.responsible, target.approvalOwner != ""
	it, err := selectableItem(ctx, s.db, itemID, day)
	if err != nil {
		return nil, err
	}
	if it == nil {
		return nil, refuse("The selected Activity Catalogue item is inactive, retired, outside its effective dates, or does not exist.")
	}
	standard := it.StandardSupport && !it.IsTrainingCourse && !it.CountsTowardClientVisit &&
		(it.ParticipantMode == "" || it.ParticipantMode == "none") &&
		len(it.Modes) > 0 && it.Modes[0] == "any_ssa_intervention"
	governed := s.governed != nil && (it.governedVisit() || it.coreVisit())
	if (!standard && !governed) || it.WorkflowKind != activityType || rules.CalendarBlocksRefuse {
		// A per-participant item, an item that counts toward the client visit
		// through its eligibility rule, another governed mapping, or a
		// calendar that refuses: not ported.
		return nil, handOn("the catalogue item is not one Go saves for the purpose")
	}
	scheduledUTC := day.UTC()
	fy := schooldirectory.OperationalFY(scheduledUTC)
	// assert_date_plannable (fy_policy 169).
	if day.Before(today) {
		return nil, refuse("%s has passed. Schedule work from %s onwards.", longDate(day), longDate(today))
	}
	collects := in(ssaCollectionTypes, activityType)
	// assert_operating and the drawer's own closed-school door are above.
	// The entitlement (_assert_schedule_entitlement 1322), asked once here
	// and again under the school's lock. A request waits for the owner, and
	// the rule is applied when they approve it.
	if isRequest {
		if err := requestEntitlement(sc, activityType); err != nil {
			return nil, err
		}
	} else if err := entitlement(ctx, s.db, sc, activityType, purpose, fy, now); err != nil {
		return nil, err
	}
	home, err := staffHomeOf(ctx, s.db, responsible)
	if err != nil {
		return nil, err
	}
	if !home.Found {
		return nil, handOn("no staff profile")
	}
	// A Training Follow Up names the training it follows (2822–2832).
	if req.SourceActivityID == "" && (purpose == followUpPurpose || activityType == followUpActivityType) {
		needs, err := followUpNeedsTraining(ctx, s.db, p.Country, fy)
		if err != nil {
			return nil, err
		}
		if needs {
			return nil, refuse("Select the completed training this visit follows up.")
		}
	}
	followed, err := s.followedSessionFor(ctx, req, sc, purpose, activityType, fy)
	if err != nil {
		return nil, err
	}
	need, err := schoolNeedOf(ctx, pgNeed{s.db}, sc.ID, sc.ClusterID, now)
	if err != nil {
		return nil, err
	}
	if followed != nil && need.Record == nil && followed.SSAID != "" {
		// apply_catalogue_snapshot would borrow the session's own SSA.
		return nil, handOn("the follow-up takes its SSA from the session")
	}
	focus, focusSource := plannedFocus(req.Focus, activityType, it.Modes, need, collects)
	if followed != nil {
		// The session, not the form, owns the intervention and its lineage.
		focus, focusSource = followed.inherited(), sourceFocus
	}
	if it.RequiresCluster {
		return nil, refuse("This Catalogue Activity requires a Cluster.")
	}
	// A follow-up item inherits: with no session and no named need it has no
	// intervention, and the snapshot refuses it inside the save.
	interventionRefusal := ""
	if it.coreVisit() && followed == nil && focus == "" {
		interventionRefusal = followUpNeedsTarget
	}
	var reason string
	var source map[string]any
	if governed {
		// resolve_activity_intervention: the plan's own, else the item's.
		if focus == "" && it.governedVisit() {
			if focus, err = primaryIntervention(ctx, s.db, it.ID); err != nil {
				return nil, err
			}
		}
		word, recommended, err := s.governed.GovernedWord(ctx, sc.Code, it.ID)
		if err != nil {
			return nil, fmt.Errorf("activities: reading the recommendation: %w", err)
		}
		reason, source = word, governedSource(it.ID, need, recommended)
	} else {
		reason, source = standardSupport(recReason, focus, it.ID, need.Record)
	}
	followUpOf := ""
	var secondary []string
	if followed != nil {
		source, followUpOf, secondary = followed.inheritInto(source), followed.ID, followed.Secondary
	}
	version, ok, err := latestVersion(ctx, s.db, it.ID)
	if err != nil {
		return nil, err
	}
	// _latest_version writes an unversioned item's version 1 inside the save.
	firstVersion := !ok
	if firstVersion {
		version = 1
	}
	if focusSource == "" && focus != "" {
		focusSource = "catalogue"
	}
	ev := assess(activityType, focus, focusOrPlanner(focusSource), it.Modes, need, collects, today)
	row := newRow(rowInput{
		now: now, day: day, fy: fy, quarter: quarterOf(scheduledUTC), activityType: activityType,
		purpose: purpose, school: sc, responsible: responsible, item: *it, version: version,
		goal: req.Goal, outcome: req.Outcome, deviation: req.DeviationReason, collects: collects,
		focus: focus, reason: reason, source: source, need: need, evidence: ev,
		followUpOf: followUpOf, secondary: secondary,
		approvalOwner: target.approvalOwner, justification: req.Justification,
	})
	if isRequest && req.Justification == "" {
		return nil, refuse(justificationRequired)
	}
	ownerUID, err := fundingOwner(ctx, s.db, responsible, p.UserID)
	if err != nil {
		return nil, err
	}
	// A request draws no money and joins no day until it is approved.
	var verdict DayVerdict
	if !isRequest {
		verdict, err = s.pricing.DayCheck(ctx, row.probe())
		if err != nil {
			return nil, err
		}
		if verdict.Refusal != "" && verdict.Stage == "preview" {
			return nil, &Refusal{Message: verdict.Refusal}
		}
		if !verdict.Pooled && verdict.Refusal == "" {
			// The day does not pool it: the existing save prices it inside
			// the save. Not ported.
			return nil, handOn("the day does not pool the visit")
		}
	}
	return &plan{p: p, school: sc, item: *it, version: version, firstVersion: firstVersion, need: need, focus: focus,
		core: target.core, interventionRefusal: interventionRefusal, evidence: ev, row: row, ownerUID: ownerUID, home: home, verdict: verdict, origin: origin, now: now}, nil
}

// plannedFocus is _create's target: the intervention the planner named, else
// the SSA's default for support the planner left open.
func plannedFocus(named, activityType string, modes []string, need schoolNeed, collects bool) (string, string) {
	if named != "" {
		return named, "planner"
	}
	focus := defaultFocus(activityType, modes, need, collects)
	if focus == "" {
		return "", ""
	}
	return focus, "ssa_default"
}

// canonicalFocus is resolve_activity_intervention's test for standard
// support: blank, or one of the eight SSA interventions.
func canonicalFocus(focus string) bool {
	if focus == "" {
		return true
	}
	_, ok := rules.labels[focus]
	return ok
}

func focusOrPlanner(source string) string {
	if source == "" {
		return "planner"
	}
	return source
}

// longDate is fy_policy._format: "1 October 2026".
func longDate(t time.Time) string { return fmt.Sprintf("%d %s %d", t.Day(), t.Month(), t.Year()) }

// shortDate is "%-d %b %Y": "24 Nov 2026".
func shortDate(t time.Time) string {
	return fmt.Sprintf("%d %s %d", t.Day(), t.Month().String()[:3], t.Year())
}

// quarterOf is core.fy.get_quarter_for_date on the UTC month.
func quarterOf(t time.Time) string {
	switch m := t.UTC().Month(); {
	case m >= 10:
		return "Q1"
	case m <= 3:
		return "Q2"
	case m <= 6:
		return "Q3"
	}
	return "Q4"
}

// fundingOwner is _funding_owner_id: the user behind the responsible
// staff profile.
func fundingOwner(ctx context.Context, q Querier, staffID, fallback string) (string, error) {
	var userID *string
	err := q.QueryRow(ctx, `SELECT user_id FROM staff_profile WHERE id = $1 AND deleted_at IS NULL`, staffID).Scan(&userID)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("activities: reading the funding owner: %w", err)
	}
	if userID != nil && *userID != "" {
		return *userID, nil
	}
	return fallback, nil
}

// entitlement is _assert_schedule_entitlement for a client-rule school's
// staff visit (Core schools are handed on before it).
func entitlement(ctx context.Context, q Querier, sc school, activityType, purpose, fy string, now time.Time) error {
	if err := requestEntitlement(sc, activityType); err != nil {
		return err
	}
	if !in(rules.Gate.ClientRuleTypes, sc.Type) {
		return nil
	}
	// client_visit_pool: the SSA pool never closes; a visit no pool counts
	// has no limit; the support pool is the one-visit rule.
	switch {
	case purpose == rules.Gate.CompanionPurpose, in(rules.Gate.SSASupportVisitTypes, activityType):
		return nil
	case in(rules.Gate.InSchoolSupportTypes, activityType), in(rules.Gate.FollowUpVisitTypes, activityType):
	default:
		return nil
	}
	gate, err := visitgate.Of(ctx, q, schoolprofile.GateRules(),
		visitgate.School{ID: sc.ID, Code: sc.Code, Name: sc.Name, Type: sc.Type}, fy, schooldirectory.OperationalFY(now))
	if err != nil {
		return err
	}
	if !gate.StaffCanSchedule {
		return refuse("%s", gate.StaffReason)
	}
	return nil
}

// answer is the view's confirmation (2476–2528).
func (s *Service) answer(ctx context.Context, pl *plan) (Answer, error) {
	day := pl.row.plannedDate
	fy := schooldirectory.OperationalFY(time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, time.UTC))
	if pl.row.isRequest() {
		name, err := staffName(ctx, s.db, pl.row.approvalOwner, schoolOwnerStandIn)
		if err != nil {
			s.logger.WarnContext(ctx, "activities: the owner's name was not read", "activity", pl.row.id, "err", err)
			name = schoolOwnerStandIn
		}
		return Answer{
			ActivityID: pl.row.id, Status: awaitingOwnerApproval, ActivityType: pl.row.activityType,
			PlannedDate: day.Format(time.DateOnly), FY: pl.row.fy, Message: requestedMessage(name),
			PlanURL: visitRequestQueue, PlanLinkLabel: requestQueueLabel,
		}, nil
	}
	if owner := pl.row.responsible; owner != pl.p.StaffProfileID && owner != pl.p.UserID {
		name, err := staffName(ctx, s.db, owner, schoolCCEOStandIn)
		if err != nil {
			// The visit is saved; only the name in the sentence is missing.
			s.logger.WarnContext(ctx, "activities: the owner's name was not read", "activity", pl.row.id, "err", err)
			name = schoolCCEOStandIn
		}
		message, planURL, label := colleagueConfirmation(name, day)
		return Answer{
			ActivityID: pl.row.id, Status: "scheduled", ActivityType: pl.row.activityType,
			PlannedDate: day.Format(time.DateOnly), FY: pl.row.fy, Message: message,
			PlanURL: planURL, PlanLinkLabel: label,
		}, nil
	}
	notice := ""
	planned, ceiling, err := planningpage.VisitCeiling(ctx, s.db, pl.p, fy)
	if err == nil && ceiling > 0 && planned > ceiling {
		notice = fmt.Sprintf("You have now planned %s visits for FY%s: %s past the %s your role plans in a year. Visits past it are the Partner's share, so hand those schools to a Partner.",
			thousands(planned), fy, thousands(planned-ceiling), thousands(ceiling))
	}
	return Answer{
		ActivityID: pl.row.id, Status: "scheduled", ActivityType: pl.row.activityType,
		PlannedDate: day.Format(time.DateOnly), FY: pl.row.fy, Message: scheduledMessage, Notice: notice,
		PlanURL:       "/my-plan?fy=" + url.QueryEscape(fy) + "&month=" + strconv.Itoa(int(day.Month())) + "&period=month",
		PlanLinkLabel: myPlanLabel,
	}, nil
}

func thousands(n int) string {
	text := strconv.Itoa(n)
	for i := len(text) - 3; i > 0; i -= 3 {
		text = text[:i] + "," + text[i:]
	}
	return text
}

// truncateRunes is Python's text[:n].
func truncateRunes(text string, n int) string {
	if utf8.RuneCountInString(text) <= n {
		return text
	}
	return string([]rune(text)[:n])
}
