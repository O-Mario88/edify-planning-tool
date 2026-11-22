package country

import "testing"

func TestExpansionTemplatesMatchGlobalSpec(t *testing.T) {
	byCode := map[string]CountryTemplate{}
	for _, tpl := range ExpansionTemplates {
		byCode[tpl.Code] = tpl
	}
	ke, ok := byCode["KE"]
	if !ok || ke.CurrencyCode != "KES" || len(ke.Levels) != 3 || ke.Levels[0].LocalLabel != "County" {
		t.Fatalf("unexpected KE template: %+v", ke)
	}
	rw, ok := byCode["RW"]
	if !ok || rw.CurrencyCode != "RWF" || len(rw.Levels) != 5 || rw.Levels[2].LocalLabel != "Sector" {
		t.Fatalf("unexpected RW template: %+v", rw)
	}
	et, ok := byCode["ET"]
	if !ok || et.CurrencyCode != "ETB" || len(et.Levels) != 4 || et.Calendars[0] != "ethiopian" {
		t.Fatalf("unexpected ET template: %+v", et)
	}
}
