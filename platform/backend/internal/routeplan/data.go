package routeplan

import (
	"context"
	"fmt"
	"strconv"
	"sync/atomic"
	"time"

	"github.com/jackc/pgx/v5"

	routesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/routes/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// kampala is the day the plan is read in.
var kampala = func() *time.Location {
	loc, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		return time.FixedZone("EAT", 3*60*60)
	}
	return loc
}()

// school is a school as the planner reads it.
type school struct {
	pin *routesv1.SchoolPin
	at  LatLng
}

func (s school) placed() bool { return Placed(s.pin.GetLocationStatus()) }

// verifiedLocations is whether field_routes (the reviewed locations) is
// there to read; the gateway sets it once it has checked the schema.
var verifiedLocations atomic.Bool

// schoolCols and schoolFrom read a school with its best point: a verified
// location (field_routes), a corrected point (school_geo_point), then the
// directory's own.
func schoolCols() string {
	verified := "NULL::float8, NULL::float8"
	if verifiedLocations.Load() {
		verified = "vl.lat, vl.lng"
	}
	return `s.id, COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(d.name, ''), COALESCE(c.name, ''),
  COALESCE(s.school_type, ''), ` + verified + `, gp.latitude, gp.longitude, s.latitude, s.longitude`
}

func schoolFrom() string {
	from := `school s LEFT JOIN school_geo_point gp ON gp.school_id = s.id
  LEFT JOIN district d ON d.id = s.district_id LEFT JOIN cluster c ON c.id = s.cluster_id`
	if verifiedLocations.Load() {
		from += ` LEFT JOIN field_routes.verified_location vl ON vl.school_id = s.id`
	}
	return from
}

// latExpr and lngExpr are a school's best point in SQL, for viewport filters.
func latExpr() string {
	if verifiedLocations.Load() {
		return "COALESCE(vl.lat, gp.latitude, s.latitude)"
	}
	return "COALESCE(gp.latitude, s.latitude)"
}

func lngExpr() string {
	if verifiedLocations.Load() {
		return "COALESCE(vl.lng, gp.longitude, s.longitude)"
	}
	return "COALESCE(gp.longitude, s.longitude)"
}

type args []any

func (a *args) add(v any) string {
	*a = append(*a, v)
	return "$" + strconv.Itoa(len(*a))
}

// reach is the schools the reader may see (the directory's own reach) that
// are operating: a closed school is not visited.
func reach(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time, a *args) (string, error) {
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return "", fmt.Errorf("routeplan: resolving the reader's scope: %w", err)
	}
	list := []any(*a)
	cond := schooldirectory.AnalyticsReach(scope, &list)
	*a = args(list)
	return "s.deleted_at IS NULL AND COALESCE(s.operational_status, '') <> ALL(" + a.add(Rules.ClosedStatuses) + ") AND (" + cond + ")", nil
}

func scanSchool(r pgx.CollectableRow, extra ...any) (school, error) {
	var (
		id, code, name, district, cluster, kind string
		vLat, vLng, geoLat, geoLng, lat, lng    *float64
	)
	if err := r.Scan(append([]any{&id, &code, &name, &district, &cluster, &kind, &vLat, &vLng, &geoLat, &geoLng, &lat, &lng}, extra...)...); err != nil {
		return school{}, err
	}
	// A reviewed location stands before the directory's; it is a corrected point too.
	if vLat != nil && vLng != nil {
		geoLat, geoLng = vLat, vLng
	}
	at, status := Locate(geoLat, geoLng, lat, lng)
	label := Rules.SchoolTypes[kind]
	if label == "" {
		label = kind
	}
	pin := &routesv1.SchoolPin{SchoolId: id, Code: code, Name: name, District: district, Cluster: cluster,
		Status: "other", Category: label, LocationStatus: status}
	if Placed(status) {
		pin.Point = &routesv1.Point{Lat: at.Lat, Lng: at.Lng}
	}
	return school{pin: pin, at: at}, nil
}

// plannedDay is the reader's school visits on the day, in the order they
// were planned: those still live, and those done (green).
func plannedDay(ctx context.Context, db schooldirectory.Querier, owners []string, day time.Time) ([]school, error) {
	a := &args{}
	rows, err := db.Query(ctx, `SELECT `+schoolCols()+`, a.id, a.status
FROM activity a JOIN `+schoolFrom()+` ON s.id = a.school_id
WHERE a.deleted_at IS NULL AND a.responsible_staff_id = ANY(`+a.add(owners)+`)
  AND a.activity_type = ANY(`+a.add(Rules.VisitTypes)+`) AND a.status <> ALL(`+a.add(Rules.NotLiveStatuses)+`)
  AND (a.scheduled_date AT TIME ZONE 'Africa/Kampala')::date = `+a.add(day.Format(time.DateOnly))+`::date
ORDER BY a.scheduled_date, a.id`, *a...)
	if err != nil {
		return nil, fmt.Errorf("routeplan: reading the day's visits: %w", err)
	}
	seen := map[string]bool{}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (school, error) {
		var activity, status string
		sc, err := scanSchool(r, &activity, &status)
		sc.pin.ActivityId = activity
		sc.pin.Status = "planned"
		for _, done := range Rules.CompletedStatuses {
			if status == done {
				sc.pin.Status = "completed"
			}
		}
		return sc, err
	})
	if err != nil {
		return nil, fmt.Errorf("routeplan: reading the day's visits: %w", err)
	}
	out := []school{}
	for _, sc := range list {
		// Two visits to one school on a day are one stop.
		if !seen[sc.pin.SchoolId] {
			seen[sc.pin.SchoolId] = true
			out = append(out, sc)
		}
	}
	return out, nil
}

// pinLimit is the most pins one viewport sends; past it the reader zooms in.
const pinLimit = 400

// viewport is the reader's schools inside a box, filtered.
func viewport(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time, sw, ne LatLng, district, cluster string) ([]school, bool, error) {
	a := &args{}
	where, err := reach(ctx, db, p, now, a)
	if err != nil {
		return nil, false, err
	}
	where += filters(a, district, cluster)
	lat, lng := latExpr(), lngExpr()
	where += " AND " + lat + " BETWEEN " + a.add(sw.Lat) + " AND " + a.add(ne.Lat) +
		" AND " + lng + " BETWEEN " + a.add(sw.Lng) + " AND " + a.add(ne.Lng)
	rows, err := db.Query(ctx, `SELECT `+schoolCols()+` FROM `+schoolFrom()+` WHERE `+where+` ORDER BY s.name, s.id LIMIT `+strconv.Itoa(pinLimit+1), *a...)
	if err != nil {
		return nil, false, fmt.Errorf("routeplan: reading the schools in view: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (school, error) { return scanSchool(r) })
	if err != nil {
		return nil, false, fmt.Errorf("routeplan: reading the schools in view: %w", err)
	}
	if len(list) > pinLimit {
		return list[:pinLimit], true, nil
	}
	return list, false, nil
}

func filters(a *args, district, cluster string) string {
	out := ""
	if district != "" {
		out += " AND s.district_id = " + a.add(district)
	}
	if cluster != "" {
		out += " AND s.cluster_id = " + a.add(cluster)
	}
	return out
}

// candidateLimit bounds the schools weighed as suggestions.
const candidateLimit = 300

// nearby is the reader's placed schools within the engine's radius of any
// of the points, except those listed: the first cut, by straight line.
func nearby(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time, around []LatLng, except []string, district, cluster string) ([]school, error) {
	if len(around) == 0 {
		return nil, nil
	}
	a := &args{}
	where, err := reach(ctx, db, p, now, a)
	if err != nil {
		return nil, err
	}
	where += filters(a, district, cluster) + " AND s.id <> ALL(" + a.add(except) + ")"
	deg := Rules.NearbyRadiusKm / 111.0
	minLat, maxLat, minLng, maxLng := around[0].Lat, around[0].Lat, around[0].Lng, around[0].Lng
	for _, x := range around {
		minLat, maxLat = min(minLat, x.Lat), max(maxLat, x.Lat)
		minLng, maxLng = min(minLng, x.Lng), max(maxLng, x.Lng)
	}
	lat, lng := latExpr(), lngExpr()
	where += " AND " + lat + " BETWEEN " + a.add(minLat-deg) + " AND " + a.add(maxLat+deg) +
		" AND " + lng + " BETWEEN " + a.add(minLng-deg) + " AND " + a.add(maxLng+deg)
	rows, err := db.Query(ctx, `SELECT `+schoolCols()+` FROM `+schoolFrom()+` WHERE `+where+` ORDER BY s.id LIMIT `+strconv.Itoa(candidateLimit), *a...)
	if err != nil {
		return nil, fmt.Errorf("routeplan: reading the nearby schools: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (school, error) { return scanSchool(r) })
	if err != nil {
		return nil, fmt.Errorf("routeplan: reading the nearby schools: %w", err)
	}
	radius := int64(Rules.NearbyRadiusKm * 1000)
	out := []school{}
	for _, sc := range list {
		if !sc.placed() {
			continue
		}
		for _, x := range around {
			if StraightMeters(x, sc.at) <= radius {
				out = append(out, sc)
				break
			}
		}
	}
	return out, nil
}

// schoolsByID is the reader's schools among ids, in reach.
func schoolsByID(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time, ids []string) (map[string]school, error) {
	a := &args{}
	where, err := reach(ctx, db, p, now, a)
	if err != nil {
		return nil, err
	}
	rows, err := db.Query(ctx, `SELECT `+schoolCols()+` FROM `+schoolFrom()+` WHERE `+where+` AND s.id = ANY(`+a.add(ids)+`)`, *a...)
	if err != nil {
		return nil, fmt.Errorf("routeplan: reading the chosen schools: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (school, error) { return scanSchool(r) })
	if err != nil {
		return nil, fmt.Errorf("routeplan: reading the chosen schools: %w", err)
	}
	out := map[string]school{}
	for _, sc := range list {
		out[sc.pin.SchoolId] = sc
	}
	return out, nil
}

// areaOptions is the districts and clusters of the reader's schools.
func areaOptions(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) ([]*routesv1.FilterOption, []*routesv1.FilterOption, error) {
	a := &args{}
	where, err := reach(ctx, db, p, now, a)
	if err != nil {
		return nil, nil, err
	}
	read := func(col, table string) ([]*routesv1.FilterOption, error) {
		rows, err := db.Query(ctx, `SELECT DISTINCT x.id, x.name FROM school s JOIN `+table+` x ON x.id = s.`+col+` WHERE `+where+` ORDER BY x.name LIMIT 500`, *a...)
		if err != nil {
			return nil, fmt.Errorf("routeplan: reading the filter options: %w", err)
		}
		return pgx.CollectRows(rows, func(r pgx.CollectableRow) (*routesv1.FilterOption, error) {
			o := &routesv1.FilterOption{}
			return o, r.Scan(&o.Value, &o.Label)
		})
	}
	districts, err := read("district_id", "district")
	if err != nil {
		return nil, nil, err
	}
	clusters, err := read("cluster_id", "cluster")
	return districts, clusters, err
}
