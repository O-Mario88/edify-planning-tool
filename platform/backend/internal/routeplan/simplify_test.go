package routeplan

import "testing"

func TestTheRoadLineKeepsItsShapeAndDropsWhatAMapCannotShow(t *testing.T) {
	// A straight road sampled every ~1 m keeps only its ends.
	line := []LatLng{}
	for i := range 100 {
		line = append(line, LatLng{0.3, 32.7 + float64(i)*0.00001})
	}
	if got := Simplify(line, lineTolerance); len(got) != 2 || got[0] != line[0] || got[1] != line[99] {
		t.Errorf("straight road: %d points", len(got))
	}
	// A turn of ~1 km stays.
	turn := []LatLng{{0.30, 32.70}, {0.30, 32.71}, {0.31, 32.71}}
	if got := Simplify(turn, lineTolerance); len(got) != 3 {
		t.Errorf("turn: %v", got)
	}
	if got := Simplify(turn[:2], lineTolerance); len(got) != 2 {
		t.Error("two points stay two")
	}
}
