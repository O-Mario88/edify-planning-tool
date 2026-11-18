package countryconfig

import (
	"strings"
	"testing"

	countriesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1"
)

const someUnit = "3c9e1f2a-7b4d-4e6f-8a1b-5d2c9e7f1a30"

func TestGeographyRequestChecks(t *testing.T) {
	if l, err := levelOf(&countriesv1.DefineAdminUnitLevelRequest{CountryCode: "KE", CanonicalType: "county",
		LocalLabel: " County ", Level: 1, IsRequired: true}); err != nil || l.label != "County" || !l.required {
		t.Fatalf("a Kenyan county level: %+v, %v", l, err)
	}
	for name, bad := range map[string]*countriesv1.DefineAdminUnitLevelRequest{
		"no country":       {CanonicalType: "county", LocalLabel: "County", Level: 1},
		"a capital letter": {CountryCode: "KE", CanonicalType: "County", LocalLabel: "County", Level: 1},
		"a space":          {CountryCode: "KE", CanonicalType: "sub county", LocalLabel: "Sub-county", Level: 2},
		"a word too long":  {CountryCode: "KE", CanonicalType: strings.Repeat("a", mostTypeWord+1), LocalLabel: "X", Level: 1},
		"no label":         {CountryCode: "KE", CanonicalType: "county", LocalLabel: "  ", Level: 1},
		"a label too long": {CountryCode: "KE", CanonicalType: "county", LocalLabel: strings.Repeat("a", mostLabel+1), Level: 1},
		"level zero":       {CountryCode: "KE", CanonicalType: "county", LocalLabel: "County"},
		"a level too deep": {CountryCode: "KE", CanonicalType: "county", LocalLabel: "County", Level: mostLevel + 1},
	} {
		if _, err := levelOf(bad); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}

	if u, err := unitOf(&countriesv1.AddAdminUnitRequest{CountryCode: "KE", LevelId: someUnit, ParentId: someUnit,
		OfficialName: " Nairobi ", OfficialCode: " 047 "}); err != nil || u.name != "Nairobi" || u.officialCode != "047" {
		t.Fatalf("a Kenyan unit: %+v, %v", u, err)
	}
	for name, bad := range map[string]*countriesv1.AddAdminUnitRequest{
		"no level":           {CountryCode: "KE", OfficialName: "Nairobi"},
		"a level not an id":  {CountryCode: "KE", LevelId: "county", OfficialName: "Nairobi"},
		"a parent not an id": {CountryCode: "KE", LevelId: someUnit, ParentId: "x';--", OfficialName: "Nairobi"},
		"no name":            {CountryCode: "KE", LevelId: someUnit, OfficialName: " "},
		"a name too long":    {CountryCode: "KE", LevelId: someUnit, OfficialName: strings.Repeat("a", mostUnitName+1)},
		"a code too long":    {CountryCode: "KE", LevelId: someUnit, OfficialName: "N", OfficialCode: strings.Repeat("1", mostUnitCode+1)},
	} {
		if _, err := unitOf(bad); err == nil {
			t.Errorf("%s: accepted", name)
		}
	}

	if l, err := listOf(&countriesv1.ListAdminUnitsRequest{CountryCode: "UG"}); err != nil || l.page != 1 || l.parentID != "" {
		t.Fatalf("Uganda's top level: %+v, %v", l, err)
	}
	if _, err := listOf(&countriesv1.ListAdminUnitsRequest{CountryCode: "UG", ParentId: "kampala"}); err == nil {
		t.Error("a parent that is not an id: accepted")
	}
	if _, err := listOf(&countriesv1.ListAdminUnitsRequest{CountryCode: "UG", Query: strings.Repeat("a", mostQuery+1)}); err == nil {
		t.Error("a query too long: accepted")
	}
}
