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
// marked stale (refresh_many). For a missing area Prepare returns ErrHandOn
// and the page passes the reader on to the existing application. A stale
// ledger Go works out in memory, as the rebuild would write it, and reads
// that in place of the stored rows; the existing application stays the only
// writer of the ledger and rebuilds it the next time it reads.
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
	Rebuild     struct {
		Sources      []rebuildSource `json:"sources"`
		Returned     []string        `json:"returned"`
		Completed    []string        `json:"completed"`
		IAVerified   []string        `json:"ia_verified"`
		MSCSCredited []string        `json:"mscs_credited"`
		MSCSPending  []string        `json:"mscs_pending"`
	} `json:"rebuild"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.MetricToArea) == 0 || len(r.OfficialAreas) == 0 ||
		len(r.AnnualFallback) == 0 || len(r.Quarters) != 4 || len(r.MonthLabels) != 12 || r.Bands.HighRisk == 0 ||
		len(r.Rebuild.Sources) == 0 || len(r.Rebuild.Completed) == 0 || len(r.Rebuild.IAVerified) == 0 {
		panic(fmt.Sprintf("targets: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// rebuildSource is an AREA_SOURCES entry in the order the rebuild credits
// it: the area, the kind of record and, for activities, their types.
type rebuildSource struct {
	Area, Kind string
	Types      []string
}

func (s *rebuildSource) UnmarshalJSON(raw []byte) error {
	var triple []json.RawMessage
	if err := json.Unmarshal(raw, &triple); err != nil || len(triple) != 3 {
		return fmt.Errorf("targets: a rebuild source is not a triple: %s", raw)
	}
	for i, into := range []any{&s.Area, &s.Kind, &s.Types} {
		if err := json.Unmarshal(triple[i], into); err != nil {
			return fmt.Errorf("targets: a rebuild source: %w", err)
		}
	}
	return nil
}

// ErrHandOn is a read Go does not answer (a missing official area, which the
// existing engine repairs on read; a calendar Go cannot read; a ledger whose
// rebuild Go cannot tell): the page passes the reader on to the existing
// application.
var ErrHandOn = errors.New("targets: the existing engine writes on this read")
