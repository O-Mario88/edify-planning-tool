package routeplan

import (
	"context"
	"fmt"

	"connectrpc.com/connect"
	"github.com/jackc/pgx/v5"

	routesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/routes/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/apierr"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// GetSchoolLocation is a school's Location & Directions card: its stored
// point and how sure that point is, and how many of the reader's schools
// are near it. Anyone who may open the school's profile or plan routes may
// read it, for schools in their own reach only.
func (s *Service) GetSchoolLocation(ctx context.Context, req *connect.Request[routesv1.GetSchoolLocationRequest]) (*connect.Response[routesv1.GetSchoolLocationResponse], error) {
	p, ok := auth.PrincipalFrom(ctx)
	if !ok {
		return nil, apierr.New(ctx, connect.CodeUnauthenticated, apierr.ReasonAuthMissing, "sign in first")
	}
	if !MayOpenProfile(p.ActiveRole) && !MayPlan(p.ActiveRole) {
		return nil, apierr.New(ctx, connect.CodePermissionDenied, apierr.ReasonPermissionDenied,
			"Access Denied: Your active role does not have permission to view school locations.")
	}
	ref := req.Msg.GetSchoolId()
	if ref == "" {
		return nil, apierr.New(ctx, connect.CodeInvalidArgument, apierr.ReasonInvalidArgument, "school_id is required")
	}
	now := s.now()
	verify := s.verifyReady(ctx)
	sc, found, err := schoolByRef(ctx, s, p, ref)
	if err != nil {
		return nil, s.fail(ctx, err)
	}
	if !found {
		return nil, apierr.New(ctx, connect.CodeNotFound, apierr.ReasonSchoolNotFound, "school not found")
	}
	sc.pin.CanOpenProfile = MayOpenProfile(p.ActiveRole)
	out := &routesv1.GetSchoolLocationResponse{School: sc.pin, NearbyRadiusKm: Rules.NearbyRadiusKm, CanPlan: MayPlan(p.ActiveRole),
		LocationSource: locationSource("", false, sc.placed())}
	if sc.placed() {
		near, err := nearby(ctx, s.db, p, now, []LatLng{sc.at}, []string{sc.pin.SchoolId}, "", "")
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		out.NearbySchools = int32(len(near))
	}
	if verify {
		pending, err := s.pendingFor(ctx, p, sc.pin.GetSchoolId())
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		f, err := s.facts(ctx, sc.pin.GetSchoolId())
		if err != nil {
			return nil, s.fail(ctx, err)
		}
		out.PendingReport, out.AccessNote = pending, f.accessNote
		out.CanReport = MayOpenProfile(p.ActiveRole) && pending == nil
		out.CanReview = MayReview(p.ActiveRole)
		out.CanCapture = MayCaptureGPS(p.ActiveRole)
		out.Version, out.VerifiedAt, out.VerifiedByName = sc.pin.GetLocationVersion(), f.verifiedAt, f.verifiedByName
		out.LastConfirmedAt, out.Entrance, out.Policy = f.lastConfirmedAt, sc.pin.GetEntrance(), policyOf(DefaultPolicy)
		out.AccuracyMeters, out.LocationSource = f.accuracy, locationSource(f.captureSource, f.reviewed, sc.placed())
	}
	return connect.NewResponse(out), nil
}

// schoolByRef is one school in the reader's reach by its own id or its
// School ID.
func schoolByRef(ctx context.Context, s *Service, p auth.Principal, ref string) (school, bool, error) {
	a := &args{}
	where, err := reach(ctx, s.db, p, s.now(), a)
	if err != nil {
		return school{}, false, err
	}
	r := a.add(ref)
	rows, err := s.db.Query(ctx, `SELECT `+schoolCols()+` FROM `+schoolFrom()+` WHERE `+where+` AND (s.id = `+r+` OR s.school_id = `+r+`) LIMIT 1`, *a...)
	if err != nil {
		return school{}, false, fmt.Errorf("routeplan: reading the school: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (school, error) { return scanSchool(r) })
	if err != nil {
		return school{}, false, fmt.Errorf("routeplan: reading the school: %w", err)
	}
	if len(list) == 0 {
		return school{}, false, nil
	}
	return list[0], true, nil
}
