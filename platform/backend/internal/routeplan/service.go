package routeplan

import (
	"context"
	"log/slog"
	"time"

	"connectrpc.com/connect"

	routesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/routes/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Service answers RoutePlannerService.
type Service struct {
	db     schooldirectory.Querier
	router Router
	name   string
	now    func() time.Time
	logger *slog.Logger
	// verify is the hold on field_routes (location reports); nil when off.
	verify *verification
	// onLocationUpdated notifies downstream caches (e.g. Country Map) on GPS save.
	onLocationUpdated func()
}

// WithLocationInvalidator registers a callback invoked whenever authoritative school
// GPS coordinates change, keeping map & dashboard caches immediately synchronized.
func (s *Service) WithLocationInvalidator(fn func()) *Service {
	s.onLocationUpdated = fn
	return s
}

// RouterFor is the provider the configuration names, guarded. Every
// provider answers from a real source or not at all.
func RouterFor(provider, osrmURL, googleKey string, dailyLimit int, now func() time.Time) Router {
	switch provider {
	case "osrm":
		return Guard(OSRM{Base: osrmURL}, dailyLimit, now)
	case "google":
		return Guard(Google{Key: googleKey}, dailyLimit, now)
	}
	return None{}
}

// NewService plans over db, measuring roads with router (a Guarded
// provider, or None).
func NewService(db schooldirectory.Querier, router Router, now func() time.Time, logger *slog.Logger) *Service {
	return &Service{db: db, router: router, name: router.Name(), now: now, logger: logger}
}

// maxChosen is the most schools one route may carry.
const maxChosen = 20

func (s *Service) reader(ctx context.Context) (auth.Principal, error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return p, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing, "sign in first")
	}
	s.verifyReady(ctx)
	if !MayPlan(p.ActiveRole) {
		return p, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: Your active role does not have permission to plan field routes.")
	}
	return p, nil
}

func (s *Service) fail(ctx context.Context, err error) error {
	return apierr.Internal(ctx, s.logger, err)
}

func (s *Service) provider(note ProviderNote) *routesv1.ProviderStatus {
	return &routesv1.ProviderStatus{Name: s.name, Configured: s.name != "none", Message: note.Message}
}

// day is the asked date in Kampala, today when empty.
func (s *Service) day(ctx context.Context, raw string) (time.Time, error) {
	if raw == "" {
		n := s.now().In(kampala)
		return time.Date(n.Year(), n.Month(), n.Day(), 0, 0, 0, 0, kampala), nil
	}
	d, err := time.ParseInLocation(time.DateOnly, raw, kampala)
	if err != nil {
		return d, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "date must be YYYY-MM-DD")
	}
	return d, nil
}

func owners(p auth.Principal) []string {
	out := []string{}
	for _, id := range []string{p.UserID, p.StaffProfileID} {
		if id != "" {
			out = append(out, id)
		}
	}
	return out
}

func (s *Service) mark(p auth.Principal, list []school) {
	for _, sc := range list {
		sc.pin.CanOpenProfile = MayOpenProfile(p.ActiveRole)
	}
}

// GetFieldDay is the reader's day: planned schools in the recommended order
// and, where one fits, the best nearby eligible school added to it.
func (s *Service) GetFieldDay(ctx context.Context, req *connect.Request[routesv1.GetFieldDayRequest]) (*connect.Response[routesv1.GetFieldDayResponse], error) {
	p, err := s.reader(ctx)
	if err != nil {
		return nil, err
	}
	day, err := s.day(ctx, req.Msg.GetDate())
	if err != nil {
		return nil, err
	}
	now := s.now()
	planned, err := plannedDay(ctx, s.db, owners(p), day)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	s.mark(p, planned)
	saved, err := s.savedDay(ctx, p, day)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	t := trip{schools: planned, kinds: map[string]string{}, mode: ModeFastest}
	if len(saved.order) > 0 {
		if t, err = s.savedTrip(ctx, p, now, planned, saved.order); err != nil {
			return nil, s.fail(ctx, err)
		}
	}
	route, note := s.build(ctx, t)
	district, cluster := req.Msg.GetDistrictId(), req.Msg.GetClusterId()
	var focus *school
	if ref := req.Msg.GetNearSchoolId(); ref != "" {
		sc, found, err := schoolByRef(ctx, s, p, ref)
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		if !found {
			// A school the reader may not see is never named or placed.
			return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonSchoolNotFound, "school not found")
		}
		sc.pin.CanOpenProfile = MayOpenProfile(p.ActiveRole)
		focus = &sc
	}
	var suggestions []*routesv1.Suggestion
	switch {
	case focus == nil:
		suggestions, err = s.suggest(ctx, p, route, planned, now, district, cluster)
	case focus.placed():
		except := []string{focus.pin.SchoolId}
		for _, sc := range planned {
			except = append(except, sc.pin.SchoolId)
		}
		suggestions, err = s.suggestAround(ctx, p, []LatLng{focus.at}, except, route.GetTotals().GetFieldMinutes(), focus.pin.Name, now, district, cluster)
	}
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	for _, sg := range suggestions {
		sg.School.CanOpenProfile = MayOpenProfile(p.ActiveRole)
	}
	// The best nearby school joins the day as a suggestion; not when the reader
	// asked about one school's surroundings, nor once they saved their order.
	if focus == nil && len(saved.order) == 0 && len(suggestions) > 0 && suggestions[0].FitsDay && len(route.GetStops()) > 0 {
		top := suggestions[0]
		add, err := schoolsByID(ctx, s.db, p, now, []string{top.School.SchoolId})
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		if sc, ok := add[top.School.SchoolId]; ok {
			sc.pin = top.School
			t.schools = append(append([]school(nil), planned...), sc)
			t.kinds[sc.pin.SchoolId] = "recommended"
			t.mode = ModeRecommended
			route, note = s.build(ctx, t)
		}
	}
	districts, clusters, err := areaOptions(ctx, s.db, p, now)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	out := &routesv1.GetFieldDayResponse{Date: day.Format(time.DateOnly), DateLabel: day.Format("Mon, 02 Jan 2006"),
		Recommended: route, Suggestions: suggestions, Provider: s.provider(note), Districts: districts, Clusters: clusters,
		AreaLabel: area(planned)}
	if focus != nil {
		out.Focus = focus.pin
	}
	if saved.saved != nil || saved.started != nil {
		out.Saved = saved.message()
	}
	for _, sc := range planned {
		out.Planned = append(out.Planned, sc.pin)
	}
	return connect.NewResponse(out), nil
}

// area is the district most of the day's schools are in.
func area(list []school) string {
	count, best := map[string]int{}, ""
	for _, sc := range list {
		if d := sc.pin.District; d != "" {
			count[d]++
			if count[d] > count[best] {
				best = d
			}
		}
	}
	return best
}

// PlanRoute is an itinerary over schools the reader chose.
func (s *Service) PlanRoute(ctx context.Context, req *connect.Request[routesv1.PlanRouteRequest]) (*connect.Response[routesv1.PlanRouteResponse], error) {
	p, err := s.reader(ctx)
	if err != nil {
		return nil, err
	}
	ids := req.Msg.GetSchoolIds()
	if len(ids) == 0 || len(ids) > maxChosen {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "choose 1 to 20 schools")
	}
	mode := req.Msg.GetMode()
	if mode != ModeFastest && mode != ModeRecommended && mode != ModeAsGiven {
		mode = ModeFastest
	}
	day, err := s.day(ctx, req.Msg.GetDate())
	if err != nil {
		return nil, err
	}
	found, err := schoolsByID(ctx, s.db, p, s.now(), ids)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	planned, err := plannedDay(ctx, s.db, owners(p), day)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	onPlan := map[string]*routesv1.SchoolPin{}
	for _, sc := range planned {
		onPlan[sc.pin.SchoolId] = sc.pin
	}
	t := trip{kinds: map[string]string{}, locked: map[string]bool{}, mode: mode, startLabel: req.Msg.GetStartLabel()}
	for _, id := range req.Msg.GetLockedSchoolIds() {
		t.locked[id] = true
	}
	seen := map[string]bool{}
	for _, id := range ids {
		sc, ok := found[id]
		if !ok || seen[id] {
			// A school the reader may not see is never routed or named.
			return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonSchoolNotFound, "a chosen school is not one of yours")
		}
		seen[id] = true
		if pin, ok := onPlan[id]; ok {
			sc.pin.Status, sc.pin.ActivityId = pin.Status, pin.ActivityId
		} else {
			sc.pin.Status = "suggested"
			t.kinds[id] = "recommended"
		}
		t.schools = append(t.schools, sc)
	}
	s.mark(p, t.schools)
	if pt := req.Msg.GetStart(); pt != nil {
		at, status := Locate(nil, nil, &pt.Lat, &pt.Lng)
		if !Placed(status) {
			return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "the start is not a point in Uganda")
		}
		t.start = &at
		if t.startLabel == "" {
			t.startLabel = "Start"
		}
	}
	route, note := s.build(ctx, t)
	return connect.NewResponse(&routesv1.PlanRouteResponse{Itinerary: route, Provider: s.provider(note)}), nil
}

// GetSchoolPins is the reader's schools in view, marked with the day's plan.
func (s *Service) GetSchoolPins(ctx context.Context, req *connect.Request[routesv1.GetSchoolPinsRequest]) (*connect.Response[routesv1.GetSchoolPinsResponse], error) {
	p, err := s.reader(ctx)
	if err != nil {
		return nil, err
	}
	sw, ne := req.Msg.GetSouthWest(), req.Msg.GetNorthEast()
	if sw == nil || ne == nil || sw.Lat >= ne.Lat || sw.Lng >= ne.Lng || ne.Lat-sw.Lat > 6 || ne.Lng-sw.Lng > 6 {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "the viewport must be a box no wider than the country")
	}
	day, err := s.day(ctx, req.Msg.GetDate())
	if err != nil {
		return nil, err
	}
	list, truncated, err := viewport(ctx, s.db, p, s.now(), LatLng{sw.Lat, sw.Lng}, LatLng{ne.Lat, ne.Lng}, req.Msg.GetDistrictId(), req.Msg.GetClusterId())
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	planned, err := plannedDay(ctx, s.db, owners(p), day)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	status := map[string]*routesv1.SchoolPin{}
	for _, sc := range planned {
		status[sc.pin.SchoolId] = sc.pin
	}
	s.mark(p, list)
	out := &routesv1.GetSchoolPinsResponse{Truncated: truncated}
	for _, sc := range list {
		if on, ok := status[sc.pin.SchoolId]; ok {
			sc.pin.Status, sc.pin.ActivityId = on.Status, on.ActivityId
		}
		out.Pins = append(out.Pins, sc.pin)
	}
	return connect.NewResponse(out), nil
}

// GetSchoolDistance is the straight-line and road distance between two of
// the reader's schools.
func (s *Service) GetSchoolDistance(ctx context.Context, req *connect.Request[routesv1.GetSchoolDistanceRequest]) (*connect.Response[routesv1.GetSchoolDistanceResponse], error) {
	p, err := s.reader(ctx)
	if err != nil {
		return nil, err
	}
	from, to := req.Msg.GetFromSchoolId(), req.Msg.GetToSchoolId()
	found, err := schoolsByID(ctx, s.db, p, s.now(), []string{from, to})
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	a, okA := found[from]
	b, okB := found[to]
	if !okA || !okB || from == to {
		return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonSchoolNotFound, "choose two of your schools")
	}
	s.mark(p, []school{a, b})
	leg := &routesv1.RouteLeg{FromLabel: a.pin.Name, ToSchoolId: b.pin.SchoolId}
	out := &routesv1.GetSchoolDistanceResponse{Leg: leg, From: a.pin, To: b.pin, CalculatedAt: s.now().UTC().Format(time.RFC3339)}
	note := ProviderNote{}
	if !a.placed() || !b.placed() {
		leg.RoadStatus = "A school has no usable coordinates, so no distance can be measured."
	} else {
		leg.StraightLineMeters = StraightMeters(a.at, b.at)
		leg.EstimateSeconds = EstimateSeconds(leg.StraightLineMeters)
		r, err := s.router.Route(ctx, []LatLng{a.road(), b.road()})
		if err == nil && len(r.Legs) == 1 && r.Legs[0].OK {
			leg.RoadAvailable, leg.RoadMeters, leg.RoadSeconds = true, r.Legs[0].Meters, r.Legs[0].Seconds
			for _, x := range Simplify(r.Path, lineTolerance) {
				leg.Path = append(leg.Path, &routesv1.Point{Lat: x.Lat, Lng: x.Lng})
			}
		} else {
			note = noteFor(err)
			leg.RoadStatus = note.Message
		}
	}
	out.Provider = s.provider(note)
	return connect.NewResponse(out), nil
}
