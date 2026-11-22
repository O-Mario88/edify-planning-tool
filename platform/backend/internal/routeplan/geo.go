package routeplan

import "math"

// LatLng is a point on the map.
type LatLng struct{ Lat, Lng float64 }

// Uganda's extent with a margin: a stored point outside it, or at 0,0, is
// taken as a data-entry error and the school is flagged, never placed.
const (
	minLat, maxLat = -1.6, 4.4
	minLng, maxLng = 29.4, 35.2
)

// Location statuses a pin carries.
const (
	LocationVerified = "verified" // a corrected point (school_geo_point)
	LocationRecorded = "recorded" // the directory's own coordinates
	LocationMissing  = "missing"
	LocationInvalid  = "invalid"
)

// Locate is coords_for over the two real points a school can have — a
// corrected geo point first, then the directory's — and the status the pin
// shows. Centroids are not points and place nothing.
func Locate(geoLat, geoLng, lat, lng *float64) (LatLng, string) {
	if geoLat != nil && geoLng != nil {
		return check(*geoLat, *geoLng, LocationVerified)
	}
	if lat != nil && lng != nil {
		return check(*lat, *lng, LocationRecorded)
	}
	return LatLng{}, LocationMissing
}

func check(lat, lng float64, status string) (LatLng, string) {
	if math.IsNaN(lat) || math.IsNaN(lng) || (lat == 0 && lng == 0) ||
		lat < minLat || lat > maxLat || lng < minLng || lng > maxLng {
		return LatLng{}, LocationInvalid
	}
	return LatLng{lat, lng}, status
}

// checkPoint is whether a point is a usable one in Uganda.
func checkPoint(lat, lng float64) (LatLng, bool) {
	at, status := check(lat, lng, LocationRecorded)
	return at, status == LocationRecorded
}

// Placed is whether the status has a point.
func Placed(status string) bool { return status == LocationVerified || status == LocationRecorded }

// earthKm is the radius haversine_km uses.
const earthKm = 6371.0

// StraightMeters is SchoolCoordinateService.haversine_km in metres.
func StraightMeters(a, b LatLng) int64 {
	rad := math.Pi / 180
	dLat, dLng := (b.Lat-a.Lat)*rad, (b.Lng-a.Lng)*rad
	h := math.Pow(math.Sin(dLat/2), 2) + math.Cos(a.Lat*rad)*math.Cos(b.Lat*rad)*math.Pow(math.Sin(dLng/2), 2)
	return int64(math.Round(2 * earthKm * math.Asin(math.Sqrt(h)) * 1000))
}

// Bounds is a geographic bounding box (degrees).
type Bounds struct{ MinLat, MaxLat, MinLng, MaxLng float64 }

// CountryBounds holds the geographic envelopes for Edify Global's four
// registered countries (UG, KE, RW, ET) with a small border margin.
var CountryBounds = map[string]Bounds{
	"UG": {MinLat: -1.6, MaxLat: 4.4, MinLng: 29.4, MaxLng: 35.2},
	"KE": {MinLat: -4.8, MaxLat: 5.2, MinLng: 33.8, MaxLng: 42.0},
	"RW": {MinLat: -2.9, MaxLat: -1.0, MinLng: 28.8, MaxLng: 31.0},
	"ET": {MinLat: 3.3, MaxLat: 15.0, MinLng: 32.9, MaxLng: 48.1},
}

// CheckForCountry validates a point against countryCode's bounding box (falling
// back to Uganda if countryCode is empty or unknown).
func CheckForCountry(countryCode string, lat, lng float64, status string) (LatLng, string) {
	b, ok := CountryBounds[countryCode]
	if !ok {
		b = CountryBounds["UG"]
	}
	if math.IsNaN(lat) || math.IsNaN(lng) || (lat == 0 && lng == 0) ||
		lat < b.MinLat || lat > b.MaxLat || lng < b.MinLng || lng > b.MaxLng {
		return LatLng{}, LocationInvalid
	}
	return LatLng{lat, lng}, status
}

// SearchBox computes a tight lat/lng bounding box around center for fast
// index-backed radius queries before exact Haversine filtering.
func SearchBox(center LatLng, radiusKm float64) Bounds {
	if radiusKm <= 0 {
		return Bounds{center.Lat, center.Lat, center.Lng, center.Lng}
	}
	dLat := (radiusKm / earthKm) * (180 / math.Pi)
	cosLat := math.Cos(center.Lat * math.Pi / 180)
	if math.Abs(cosLat) < 0.01 {
		cosLat = 0.01
	}
	dLng := dLat / cosLat
	return Bounds{
		MinLat: center.Lat - dLat,
		MaxLat: center.Lat + dLat,
		MinLng: center.Lng - dLng,
		MaxLng: center.Lng + dLng,
	}
}

// EstimateSeconds is travel_minutes_for_km: the engine's planning estimate
// over a straight line, in whole minutes.
func EstimateSeconds(meters int64) int64 {
	return int64(math.Round(float64(meters)/1000/Rules.PlanningSpeedKmh*60)) * 60
}
