// Package targets is the target engine the people pages stand on
// (apps.targets.my_targets, team_targets and fy_calendar): the areas a person
// is measured on for a year (their agreed priorities, else their legacy
// monthly targets), the monthly targets and validated achievements of each,
// the weighted share, the pace a period expects from the working days already
// gone (weekdays less public holidays less the person's approved leave), and
// the pace-aware status.
//
// It reads; it never writes. The existing engine writes on two reads: it
// repairs a missing official target area, and it rebuilds a person's ledger
// marked stale (refresh_many). Go answers neither: Prepare returns ErrHandOn
// and the page passes the reader on to the existing application, which
// writes as it always has.
//
// The constants are exported to rules.json by `manage.py
// export_targets_rules`; apps/targets/test_targets_rules_export.py fails when
// the two differ.
package targets

import (
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	MetricToArea        map[string]string   `json:"metric_to_area"`
	OfficialAreas       []string            `json:"official_areas"`
	AnnualFallback      map[string][]string `json:"annual_fallback"`
	AgreementReviewType string              `json:"agreement_review_type"`
	UnagreedStages      []string            `json:"unagreed_stages"`
	Bands               struct {
		OnTrack  int `json:"on_track"`
		Slight   int `json:"slight"`
		HighRisk int `json:"high_risk"`
	} `json:"bands"`
	Quarters    []string `json:"quarters"`
	MonthLabels []string `json:"month_labels"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.MetricToArea) == 0 || len(r.OfficialAreas) == 0 ||
		len(r.AnnualFallback) == 0 || len(r.Quarters) != 4 || len(r.MonthLabels) != 12 || r.Bands.HighRisk == 0 {
		panic(fmt.Sprintf("targets: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// ErrHandOn is a read the existing engine would write on (a missing official
// area, a stale ledger, a calendar Go cannot read): the page passes the reader
// on to the existing application.
var ErrHandOn = errors.New("targets: the existing engine writes on this read")
