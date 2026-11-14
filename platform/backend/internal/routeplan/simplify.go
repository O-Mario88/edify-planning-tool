package routeplan

import "math"

// lineTolerance is how far (metres) a dropped point may sit from the drawn
// line: well under a pixel at the zooms a field day is shown at.
const lineTolerance = 5.0

// Simplify is Douglas–Peucker over the road line: the same shape with the
// points a map cannot show removed. The ends are always kept.
func Simplify(path []LatLng, tolerance float64) []LatLng {
	if len(path) < 3 {
		return path
	}
	// Metres on a local flat projection (fine over a field day's extent).
	lat0 := path[0].Lat * math.Pi / 180
	xy := func(p LatLng) (float64, float64) {
		return p.Lng * math.Pi / 180 * math.Cos(lat0) * earthKm * 1000, p.Lat * math.Pi / 180 * earthKm * 1000
	}
	keep := make([]bool, len(path))
	keep[0], keep[len(path)-1] = true, true
	var walk func(a, b int)
	walk = func(a, b int) {
		ax, ay := xy(path[a])
		bx, by := xy(path[b])
		far, at := 0.0, -1
		for i := a + 1; i < b; i++ {
			px, py := xy(path[i])
			if d := segmentDistance(px, py, ax, ay, bx, by); d > far {
				far, at = d, i
			}
		}
		if at >= 0 && far > tolerance {
			keep[at] = true
			walk(a, at)
			walk(at, b)
		}
	}
	walk(0, len(path)-1)
	out := []LatLng{}
	for i, k := range keep {
		if k {
			out = append(out, path[i])
		}
	}
	return out
}

func segmentDistance(px, py, ax, ay, bx, by float64) float64 {
	dx, dy := bx-ax, by-ay
	if dx == 0 && dy == 0 {
		return math.Hypot(px-ax, py-ay)
	}
	t := math.Max(0, math.Min(1, ((px-ax)*dx+(py-ay)*dy)/(dx*dx+dy*dy)))
	return math.Hypot(px-(ax+t*dx), py-(ay+t*dy))
}
