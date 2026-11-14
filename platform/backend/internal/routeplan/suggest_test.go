package routeplan

import "testing"

func TestAnInsertionIsTheCheapestSlotAndNeverASaving(t *testing.T) {
	pts := []LatLng{{0, 0}, {0, 10}}
	x := LatLng{0, 5} // on the way: costs nothing extra
	flat := func(a, b LatLng) int64 {
		d := int64(b.Lng - a.Lng)
		if d < 0 {
			d = -d
		}
		return d
	}
	if c, l := insertion(pts, x, flat, flat); c != 0 || l != 0 {
		t.Errorf("on the way: %d %d", c, l)
	}
	if c, _ := insertion(pts, LatLng{0, 12}, flat, flat); c != 2 {
		t.Errorf("past the end: %d", c)
	}
	odd := func(a, b LatLng) int64 { // a detour that measures shorter
		if a == (LatLng{0, 0}) && b == (LatLng{0, 10}) {
			return 30
		}
		return flat(a, b)
	}
	if c, _ := insertion(pts, x, odd, odd); c != 0 {
		t.Errorf("a detour is never a saving: %d", c)
	}
}
