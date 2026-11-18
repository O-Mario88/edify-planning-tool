// Package stafflogs is the staff members' own logs in Go: the visits log
// (/visits: staff_views.visits_log_view, pages/visits/index.html) and the
// trainings log (/trainings: trainings_log_view, pages/trainings/index.html),
// as the existing feed reads them.
package stafflogs

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"strings"
	"unicode"
)

//go:embed rules.json
var rulesJSON []byte

// role is what one role is given.
type role struct {
	Visits     bool `json:"visits"`
	Trainings  bool `json:"trainings"`
	OpenSchool bool `json:"open_school"`
}

var rules = func() (r struct {
	Roles               map[string]role   `json:"roles"`
	VisitTypes          []string          `json:"visit_types"`
	TrainingTypes       []string          `json:"training_types"`
	TrainingsRedirected []string          `json:"trainings_redirected"`
	CompletedStatuses   []string          `json:"completed_statuses"`
	NotFinishedStatuses []string          `json:"not_finished_statuses"`
	RowLimit            int               `json:"row_limit"`
	StatusInitialisms   map[string]string `json:"status_initialisms"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("stafflogs: reading rules.json: %v", err))
	}
	if len(r.Roles) == 0 || len(r.VisitTypes) == 0 || len(r.TrainingTypes) == 0 || r.RowLimit == 0 {
		panic("stafflogs: rules.json lacks the doors, the visit or training types, or the row limit")
	}
	return r
}()

// capitalize is Python's str.capitalize: the first letter upper, the rest
// lower.
func capitalize(word string) string {
	runes := []rune(strings.ToLower(word))
	if len(runes) > 0 {
		runes[0] = unicode.ToUpper(runes[0])
	}
	return string(runes)
}

// statusLabel is frontend_filters.status_label: a stored token as the
// phrase a person would say, its initialisms kept.
func statusLabel(value string) string {
	words := strings.Fields(strings.NewReplacer("_", " ", "-", " ").Replace(value))
	for i, w := range words {
		c := capitalize(w)
		if kept, ok := rules.StatusInitialisms[c]; ok {
			c = kept
		}
		words[i] = c
	}
	return strings.Join(words, " ")
}

// StatusLabel is frontend_filters.status_label, for other pages that print
// a bare status token.
func StatusLabel(value string) string { return statusLabel(value) }
