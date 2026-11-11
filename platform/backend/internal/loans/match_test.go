package loans

import "testing"

var mukono = []SchoolCandidate{
	{ID: "s1", SchoolID: "UG-001", Name: "St. Mary's Primary School", SubCountyID: "goma"},
	{ID: "s2", SchoolID: "UG-002", Name: "Seeta High School", SubCountyID: "goma"},
	{ID: "s3", SchoolID: "UG-003", Name: "Bright Future Nursery & Primary", SubCountyID: "nama"},
	{ID: "s4", SchoolID: "UG-004", Name: "Bright Future Nursery and Primary", SubCountyID: "kyampisi"},
}

func TestAnExactNameInTheSameDistrictAndSubCountyIsMatched(t *testing.T) {
	got := DecideMatch(MatchQuery{Name: "st marys p/s", DistrictKnown: true, SubCountyID: "goma"}, mukono, nil)
	if got.Status != MatchMatched || got.School.ID != "s1" || got.Method != "name_and_place" {
		t.Fatalf("got %+v", got)
	}
}

func TestTwoSchoolsWithTheSameNameAreLeftForReview(t *testing.T) {
	got := DecideMatch(MatchQuery{Name: "Bright Future Nursery and Primary", DistrictKnown: true}, mukono, nil)
	if got.Status != MatchNeedsReview || len(got.Candidates) != 2 {
		t.Fatalf("got %+v", got)
	}
}

func TestASimilarNameIsNeverAssigned(t *testing.T) {
	got := DecideMatch(MatchQuery{Name: "St Mary", DistrictKnown: true, SubCountyID: "goma"}, mukono, nil)
	if got.Status != MatchNeedsReview || got.School.ID != "" || len(got.Candidates) != 1 {
		t.Fatalf("a partial name must be reviewed, got %+v", got)
	}
}

func TestADifferentSubCountyIsLeftForReview(t *testing.T) {
	got := DecideMatch(MatchQuery{Name: "St Marys Primary School", DistrictKnown: true, SubCountyID: "nama"}, mukono, nil)
	if got.Status != MatchNeedsReview {
		t.Fatalf("got %+v", got)
	}
}

func TestATypedDistrictNeverMatchesAutomatically(t *testing.T) {
	got := DecideMatch(MatchQuery{Name: "St. Mary's Primary School", DistrictKnown: false}, mukono, nil)
	if got.Status == MatchMatched {
		t.Fatalf("got %+v", got)
	}
}

func TestNoSimilarSchoolLeavesTheApplicationUnmatched(t *testing.T) {
	got := DecideMatch(MatchQuery{Name: "Kisoga Community School", DistrictKnown: true}, mukono, nil)
	if got.Status != MatchUnmatched || len(got.Candidates) != 0 {
		t.Fatalf("got %+v", got)
	}
}

func TestAnInvitationMatchesOnlyWhenTheNameAgrees(t *testing.T) {
	invited := mukono[1]
	got := DecideMatch(MatchQuery{Name: "Seeta High School", DistrictKnown: true}, mukono, &invited)
	if got.Status != MatchMatched || got.Method != "invitation" || got.School.ID != "s2" {
		t.Fatalf("got %+v", got)
	}
	got = DecideMatch(MatchQuery{Name: "Another School", DistrictKnown: true}, mukono, &invited)
	if got.Status != MatchNeedsReview || got.School.ID != "" || got.Candidates[0].ID != "s2" {
		t.Fatalf("a different name on an invitation must be reviewed, got %+v", got)
	}
}

func TestNamesAreComparedWithoutPunctuationOrAbbreviations(t *testing.T) {
	for _, pair := range [][2]string{
		{"St. Mary's P/S", "Saint Marys Primary School"},
		{"Bright Future Nursery & Primary", "bright future nursery and primary"},
		{"Kampala S.S.", "Kampala Secondary School"},
	} {
		if NormalizeSchoolName(pair[0]) != NormalizeSchoolName(pair[1]) {
			t.Errorf("%q and %q should compare equal: %q vs %q", pair[0], pair[1],
				NormalizeSchoolName(pair[0]), NormalizeSchoolName(pair[1]))
		}
	}
}
