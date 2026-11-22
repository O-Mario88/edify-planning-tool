package routeplan

import "testing"

func TestCountryBoundsAndSearchBox(t *testing.T) {
	// Nairobi (KE), Kigali (RW), Addis Ababa (ET), Kampala (UG)
	cases := []struct {
		cc       string
		lat, lng float64
		want     string
	}{
		{"UG", 0.3476, 32.5825, LocationVerified},
		{"KE", -1.2921, 36.8219, LocationVerified},
		{"RW", -1.9441, 30.0619, LocationVerified},
		{"ET", 9.0320, 38.7469, LocationVerified},
		{"UG", 9.0320, 38.7469, LocationInvalid}, // Addis is outside Uganda
	}
	for _, tc := range cases {
		_, got := CheckForCountry(tc.cc, tc.lat, tc.lng, LocationVerified)
		if got != tc.want {
			t.Errorf("%s (%v,%v): got %s, want %s", tc.cc, tc.lat, tc.lng, got, tc.want)
		}
	}

	kampala := LatLng{Lat: 0.3476, Lng: 32.5825}
	box := SearchBox(kampala, 15)
	if box.MinLat >= kampala.Lat || box.MaxLat <= kampala.Lat || box.MinLng >= kampala.Lng || box.MaxLng <= kampala.Lng {
		t.Fatalf("invalid search box: %+v", box)
	}
}
