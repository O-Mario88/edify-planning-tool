package loans

import (
	"regexp"
	"strings"
)

// School-matching outcomes, as stored in application.school_match_status.
const (
	MatchMatched     = "matched"
	MatchNeedsReview = "needs_review"
	MatchUnmatched   = "unmatched"
	// MatchNotInDirectory is a BTO's finding that the school is not in the
	// School Directory yet. No directory record is created for it.
	MatchNotInDirectory = "not_in_directory"
)

// SchoolCandidate is a School Directory record a submission might be.
type SchoolCandidate struct {
	ID          string // the directory's internal id
	SchoolID    string // the Edify School ID people quote
	Name        string
	DistrictID  string
	SubCountyID string
}

// MatchQuery is what a submission says about its school.
type MatchQuery struct {
	Name string
	// DistrictKnown is true when the district was chosen from the directory's
	// own list, so candidates come from that district.
	DistrictKnown bool
	SubCountyID   string // empty when the sub-county was typed in
}

// Match is the outcome. School is set only when the match is reliable.
type Match struct {
	Status     string
	Method     string
	School     SchoolCandidate
	Candidates []SchoolCandidate
}

// DecideMatch links a submission to a directory school only when the link is
// reliable (brief: "Do not assign a School ID based on an uncertain name
// match"):
//
//   - an invitation's school, when the submitted name agrees with it;
//   - otherwise one school, and only one, in the chosen district whose name
//     reads the same once punctuation and common abbreviations are set aside,
//     and whose sub-county (when both sides know it) is the same.
//
// Anything less certain is left for a BTO to resolve, with the schools that
// look alike as candidates; a submission is never blocked for it.
func DecideMatch(query MatchQuery, district []SchoolCandidate, invited *SchoolCandidate) Match {
	name := NormalizeSchoolName(query.Name)
	if invited != nil {
		if NormalizeSchoolName(invited.Name) == name {
			return Match{Status: MatchMatched, Method: "invitation", School: *invited}
		}
		return Match{Status: MatchNeedsReview, Candidates: []SchoolCandidate{*invited}}
	}

	var same, similar []SchoolCandidate
	for _, school := range district {
		candidate := NormalizeSchoolName(school.Name)
		switch {
		case candidate == name:
			same = append(same, school)
		case name != "" && (strings.Contains(candidate, name) || strings.Contains(name, candidate) ||
			sharesDistinctWord(candidate, name)):
			similar = append(similar, school)
		}
	}
	if query.DistrictKnown && len(same) == 1 {
		school := same[0]
		if query.SubCountyID == "" || school.SubCountyID == "" || school.SubCountyID == query.SubCountyID {
			return Match{Status: MatchMatched, Method: "name_and_place", School: school}
		}
	}
	candidates := append(same, similar...)
	if len(candidates) > maxCandidates {
		candidates = candidates[:maxCandidates]
	}
	if len(candidates) == 0 {
		return Match{Status: MatchUnmatched}
	}
	return Match{Status: MatchNeedsReview, Candidates: candidates}
}

const maxCandidates = 8

var (
	punctuation = regexp.MustCompile(`[^a-z0-9 ]+`)
	// Whole-word spellings that mean the same thing in a school's name.
	sameWords = map[string]string{
		"saint": "st", "pri": "primary", "prim": "primary", "sec": "secondary",
		"sch": "school", "schl": "school", "nur": "nursery", "&": "and",
	}
	// Abbreviations written with slashes or points, read before punctuation
	// is removed.
	shortForms = []struct {
		pattern *regexp.Regexp
		meaning string
	}{
		{regexp.MustCompile(`\bp\s*[/.]\s*s\b\.?`), " primary school "},
		{regexp.MustCompile(`\bs\s*[/.]\s*s\b\.?`), " secondary school "},
		{regexp.MustCompile(`\bn\s*[/.]\s*s\b\.?`), " nursery school "},
		{regexp.MustCompile(`&`), " and "},
		{regexp.MustCompile(`'s\b`), "s"},
	}
	// Words too common to say two names are alike.
	commonWords = map[string]bool{
		"st": true, "school": true, "primary": true, "secondary": true, "nursery": true,
		"and": true, "the": true, "of": true, "high": true, "junior": true, "day": true,
		"boarding": true, "community": true, "college": true, "academy": true, "parents": true,
	}
)

// NormalizeSchoolName is a school's name reduced for comparison.
func NormalizeSchoolName(name string) string {
	value := strings.ToLower(name)
	for _, short := range shortForms {
		value = short.pattern.ReplaceAllString(value, short.meaning)
	}
	value = punctuation.ReplaceAllString(value, " ")
	words := strings.Fields(value)
	out := words[:0]
	for _, word := range words {
		if same, ok := sameWords[word]; ok {
			word = same
		}
		if word == "ps" {
			out = append(out, "primary", "school")
			continue
		}
		if word == "ss" {
			out = append(out, "secondary", "school")
			continue
		}
		out = append(out, word)
	}
	return strings.Join(out, " ")
}

func sharesDistinctWord(a, b string) bool {
	words := map[string]bool{}
	for _, word := range strings.Fields(a) {
		if !commonWords[word] && len(word) > 2 {
			words[word] = true
		}
	}
	for _, word := range strings.Fields(b) {
		if words[word] {
			return true
		}
	}
	return false
}
