package dataqualityscan

import (
	"slices"
	"testing"
)

func sp(s string) *string { return &s }

func ip(n int) *int { return &n }

func types(issues []issue) []string {
	out := make([]string, 0, len(issues))
	for _, is := range issues {
		out = append(out, is.issueType)
	}
	return out
}

func TestACompleteSchoolHasNoIssues(t *testing.T) {
	s := school{id: "s1", hasCoordinates: true, phone: sp("+256"), contact: sp("Head"), schoolType: sp("Core"),
		subCounty: sp("sc"), duplicateStatus: sp("none"), enrollment: ip(300), ownerID: sp("u1"), ownerStatus: sp("matched"),
		clusterID: sp("c1"), ssaStatus: sp("done")}
	if got := build(s, nil); len(got) != 0 {
		t.Fatalf("issues for a complete school: %v", types(got))
	}
}

func TestAnEmptySchoolHasEveryIssueInTheBuildersOrder(t *testing.T) {
	got := build(school{id: "s2", enrollment: ip(0), duplicateStatus: sp("potential"), ownerRaw: sp("J. Okello")}, nil)
	want := []string{"no_coordinates", "missing_phone", "missing_contact", "missing_enrollment", "missing_school_type",
		"missing_sub_county", "duplicate_risk", "unmatched_staff", "no_cluster", "no_ssa"}
	if !slices.Equal(types(got), want) {
		t.Fatalf("issues = %v, want %v", types(got), want)
	}
	for _, is := range got {
		if is.conditionKey != "school:s2|dq:"+is.issueType || is.schoolID != "s2" {
			t.Fatalf("issue %s keyed %q", is.issueType, is.conditionKey)
		}
		switch is.issueType {
		case "missing_enrollment":
			if is.currentValue == nil || *is.currentValue != "0" {
				t.Fatalf("enrollment current value = %v", is.currentValue)
			}
		case "unmatched_staff":
			if is.currentValue == nil || *is.currentValue != "J. Okello" {
				t.Fatalf("owner current value = %v", is.currentValue)
			}
		case "no_cluster":
			if is.severity != "critical" {
				t.Fatalf("no_cluster severity = %s", is.severity)
			}
		case "no_ssa":
			if is.severity != "info" {
				t.Fatalf("no_ssa severity = %s", is.severity)
			}
		}
	}
}

func TestAGeoPointCountsAsALocation(t *testing.T) {
	got := build(school{id: "s3"}, map[string]bool{"s3": true})
	if slices.Contains(types(got), "no_coordinates") {
		t.Fatal("a school with a geo point override was asked for coordinates")
	}
}

func TestAPairIsTheSameEitherWayRound(t *testing.T) {
	if pairKey("a", "b") != pairKey("b", "a") {
		t.Fatal("a pair read the other way round is a new pair")
	}
}
