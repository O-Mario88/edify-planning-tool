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
	p        auth.Principal
	school   school
	item     item
	version  int
	need     schoolNeed
	focus    string
	evidence evidence
	row      activityRow
	ownerUID string
	home     staffHome
	verdict  DayVerdict
	origin   Origin
	now      time.Time
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
	if in(rules.Doors.Requesters, p.ActiveRole) || p.InActingAppointment || p.StaffProfileID == "" ||
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
				// The pin stands, and with it the SSA recommendation's
				// governed costing: not 27.3's case.
				return nil, handOn("the SSA recommendation's pinned item stands")
			}
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
	sc, err := s.visitSchool(ctx, p, req.SchoolID, now)
	if err != nil {
		return nil, err
	}
	return s.create(ctx, p, req, origin, now, today, day, *sc, itemID, recReason, purpose, activityType)
}

// visitSchool is the view's school (2318–2338) for a plain visit. The roles
// that reach it may visit any school, and visit_owner_for files a visit
// outside their portfolio against the person going. Inside it, a school
// someone else holds would be delegation: handed on.
func (s *Service) visitSchool(ctx context.Context, p auth.Principal, schoolID string, now time.Time) (*school, error) {
	sc, mine, err := s.targetSchool(ctx, p, schoolID, now)
	if err != nil {
		return nil, err
	}
	if sc.closed() {
		return nil, &Refusal{Message: rules.ClosedSchoolMessage, Forbidden: true}
	}
	if !mine {
		return sc, nil
	}
	return s.heldByPerson(ctx, p, sc)
}

// ownSchool is the school of a training pair: the person's own school by its
// code, not a Core school, still operating, and owned by them. Anything else
// is handed on.
func (s *Service) ownSchool(ctx context.Context, p auth.Principal, schoolID string, now time.Time) (*school, error) {
	sc, mine, err := s.targetSchool(ctx, p, schoolID, now)
	if err != nil {
		return nil, err
	}
	if !mine {
		return nil, handOn("outside the person's own portfolio")
	}
	if sc.closed() {
		return nil, &Refusal{Message: rules.ClosedSchoolMessage, Forbidden: true}
	}
	return s.heldByPerson(ctx, p, sc)
}

// targetSchool resolves the school again on POST (2318–2338) and says whether
// it is in the person's own portfolio. A Core school takes the package route
// and is handed on.
func (s *Service) targetSchool(ctx context.Context, p auth.Principal, schoolID string, now time.Time) (*school, bool, error) {
	sc, err := schoolByIDOrCode(ctx, s.db, strings.TrimSpace(schoolID))
	if err != nil {
		return nil, false, err
	}
	if sc == nil || sc.Code != strings.TrimSpace(schoolID) || in(rules.Gate.CoreRuleTypes, sc.Type) {
		return nil, false, handOn("not a school code, or a Core school")
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, false, handOn("no scope: " + err.Error())
	}
	return sc, slices.Contains(scope.OwnSchoolIDs, sc.ID), nil
}

// heldByPerson hands on a school in the portfolio that someone else holds.
func (s *Service) heldByPerson(ctx context.Context, p auth.Principal, sc *school) (*school, error) {
	owner, err := schoolOwner(ctx, s.db, sc.ID)
	if err != nil {
		return nil, err
	}
	if owner != p.StaffProfileID {
		return nil, handOn("the school's owner is someone else")
	}
	return sc, nil
}

func dateOnly(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, t.Location())
}

// create is `_create` (2203) for this case, to its transaction.
func (s *Service) create(ctx context.Context, p auth.Principal, req Request, origin Origin, now, today, day time.Time,
	sc school, itemID, recReason, purpose, activityType string) (*plan, error) {
	it, err := selectableItem(ctx, s.db, itemID, day)
	if err != nil {
		return nil, err
	}
	if it == nil {
		return nil, refuse("The selected Activity Catalogue item is inactive, retired, outside its effective dates, or does not exist.")
	}
	if !it.StandardSupport || it.WorkflowKind != activityType || it.IsTrainingCourse ||
		it.CountsTowardClientVisit || (it.ParticipantMode != "" && it.ParticipantMode != "none") ||
		len(it.Modes) == 0 || it.Modes[0] != "any_ssa_intervention" || rules.CalendarBlocksRefuse {
		// A governed or per-participant item, an item that counts toward the
		// client visit through its eligibility rule, a mapping other than
		// any intervention, or a calendar that refuses: not ported.
		return nil, handOn("the catalogue item is not standard support for the purpose")
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
	// and again under the school's lock.
	if err := entitlement(ctx, s.db, sc, activityType, purpose, fy, now); err != nil {
		return nil, err
	}
	responsible := p.StaffProfileID
	home, err := staffHomeOf(ctx, s.db, responsible)
	if err != nil {
		return nil, err
	}
	if !home.Found {
		return nil, handOn("no staff profile")
	}
	// A Training Follow Up names the training it follows (2822–2832).
	if purpose == "training_follow_up" || activityType == "training_follow_up_visit" {
		needs, err := followUpNeedsTraining(ctx, s.db, p.Country, fy)
		if err != nil {
			return nil, err
		}
		if needs {
			return nil, refuse("Select the completed training this visit follows up.")
		}
	}
	need, err := schoolNeedOf(ctx, pgNeed{s.db}, sc.ID, sc.ClusterID, now)
	if err != nil {
		return nil, err
	}
	focus, focusSource := plannedFocus(req.Focus, activityType, it.Modes, need, collects)
	if it.RequiresCluster {
		return nil, refuse("This Catalogue Activity requires a Cluster.")
	}
	reason, source := standardSupport(recReason, focus, it.ID, need.Record)
	version, ok, err := latestVersion(ctx, s.db, it.ID)
	if err != nil {
		return nil, err
	}
	if !ok {
		// _latest_version would write the item's first version: not ported.
		return nil, handOn("the item has no version yet")
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
	})
	ownerUID, err := fundingOwner(ctx, s.db, responsible, p.UserID)
	if err != nil {
		return nil, err
	}
	verdict, err := s.pricing.DayCheck(ctx, row.probe())
	if err != nil {
		return nil, err
	}
	if verdict.Refusal != "" && verdict.Stage == "preview" {
		return nil, &Refusal{Message: verdict.Refusal}
	}
	if !verdict.Pooled && verdict.Refusal == "" {
		// The day does not pool it: the existing save prices it inside the
		// save. Not ported.
		return nil, handOn("the day does not pool the visit")
	}
	return &plan{p: p, school: sc, item: *it, version: version, need: need, focus: focus, evidence: ev,
		row: row, ownerUID: ownerUID, home: home, verdict: verdict, origin: origin, now: now}, nil
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
	if in(rules.Gate.OutreachOnlyTypes, sc.Type) && !in(rules.Gate.OutreachActivityTypes, activityType) {
		label, ok := rules.Gate.SchoolTypeLabels[sc.Type]
		if !ok {
			label = "Programme"
		}
		return refuse("%s is a %s school: it receives no training or assessment, and is planned only for a Donor Visit or a Content/Story Collection visit.", sc.Name, label)
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
