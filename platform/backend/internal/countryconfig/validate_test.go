package countryconfig

import (
	"strings"
	"testing"

	countriesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1"
)

// kenya is settings a Kenyan pilot could be given.
func kenya() *countriesv1.RecordCountryConfigRequest {
	return &countriesv1.RecordCountryConfigRequest{
		CountryCode: "KE", DefaultLanguage: "en", Languages: []string{"en", "sw"}, CurrencyCode: "KES",
		CurrencyMinorUnits: 0, TimeZone: "Africa/Nairobi", DateFormat: "j M Y", Calendars: []string{"gregorian"},
		FyStartMonth: 7, EffectiveFrom: "2027-01-01", ChangeReason: "Kenya pilot settings",
	}
}

func TestSettingsAPilotCouldBeGivenAreAccepted(t *testing.T) {
	got, err := settingsOf(kenya())
	if err != nil {
		t.Fatal(err)
	}
	if got.code != "KE" || got.timeZone != "Africa/Nairobi" || got.from != "2027-01-01" || got.reason != "Kenya pilot settings" {
		t.Errorf("settings %+v", got)
	}
	ethiopia := kenya()
	ethiopia.CountryCode, ethiopia.DefaultLanguage, ethiopia.Languages = "ET", "am", []string{"am", "en"}
	ethiopia.CurrencyCode, ethiopia.CurrencyMinorUnits, ethiopia.TimeZone = "ETB", 2, "Africa/Addis_Ababa"
	ethiopia.Calendars, ethiopia.EffectiveFrom = []string{"gregorian", "ethiopian"}, ""
	if got, err := settingsOf(ethiopia); err != nil || got.from != "" {
		t.Errorf("Ethiopia: %+v, %v", got, err)
	}
}

func TestSettingsThatCouldNotBeRunAreRefused(t *testing.T) {
	for name, change := range map[string]func(*countriesv1.RecordCountryConfigRequest){
		"a lower-case code":               func(r *countriesv1.RecordCountryConfigRequest) { r.CountryCode = "ke" },
		"no languages":                    func(r *countriesv1.RecordCountryConfigRequest) { r.Languages = nil },
		"a language twice":                func(r *countriesv1.RecordCountryConfigRequest) { r.Languages = []string{"en", "en"} },
		"a language that is not a code":   func(r *countriesv1.RecordCountryConfigRequest) { r.Languages = []string{"en", "Swahili"} },
		"a default outside the languages": func(r *countriesv1.RecordCountryConfigRequest) { r.DefaultLanguage = "fr" },
		"a currency that is not a code":   func(r *countriesv1.RecordCountryConfigRequest) { r.CurrencyCode = "KSh" },
		"too many minor units":            func(r *countriesv1.RecordCountryConfigRequest) { r.CurrencyMinorUnits = 4 },
		"negative minor units":            func(r *countriesv1.RecordCountryConfigRequest) { r.CurrencyMinorUnits = -1 },
		"an unknown time zone":            func(r *countriesv1.RecordCountryConfigRequest) { r.TimeZone = "Africa/Atlantis" },
		"the server's own time zone":      func(r *countriesv1.RecordCountryConfigRequest) { r.TimeZone = "Local" },
		"no time zone":                    func(r *countriesv1.RecordCountryConfigRequest) { r.TimeZone = "" },
		"an unknown date format":          func(r *countriesv1.RecordCountryConfigRequest) { r.DateFormat = "%d/%m/%Y" },
		"no Gregorian calendar":           func(r *countriesv1.RecordCountryConfigRequest) { r.Calendars = []string{"ethiopian"} },
		"an unknown calendar":             func(r *countriesv1.RecordCountryConfigRequest) { r.Calendars = []string{"gregorian", "julian"} },
		"month 0":                         func(r *countriesv1.RecordCountryConfigRequest) { r.FyStartMonth = 0 },
		"month 13":                        func(r *countriesv1.RecordCountryConfigRequest) { r.FyStartMonth = 13 },
		"a date that is not one":          func(r *countriesv1.RecordCountryConfigRequest) { r.EffectiveFrom = "1 January 2027" },
		"no reason":                       func(r *countriesv1.RecordCountryConfigRequest) { r.ChangeReason = "   " },
		"a reason too long":               func(r *countriesv1.RecordCountryConfigRequest) { r.ChangeReason = strings.Repeat("x", maxReason+1) },
	} {
		request := kenya()
		change(request)
		if got, err := settingsOf(request); err == nil {
			t.Errorf("%s: accepted %+v", name, got)
		}
	}
}
