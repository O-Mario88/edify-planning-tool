package coreoversight

import (
	"context"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Candidate is one school ChampionEligibilityService.evaluate_all lists: an
// eligible Core school with the figures the candidates queue shows.
type Candidate struct {
	Code string
	// Status is the profile's stored champion status.
	Status             string
	Score, LatestAvg   float64
	Delta, LowestScore float64
	LowestIntervention string
	Completed, Total   int
}

// ChampionCandidates is evaluate_all's list, read only: every Core profile
// in the table's own order, judged by the official rule, the eligible ones
// kept. Whether a candidate's stored status would be moved to Potential
// Champion is the caller's to read from Status.
func ChampionCandidates(ctx context.Context, q schooldirectory.Querier, operational string) ([]Candidate, error) {
	codes, status := []string{}, map[string]string{}
	// CoreSchoolProfile.objects.all(): the model has no ordering, so the
	// table's own (a second column keeps the read off the School ID index).
	if err := each(ctx, q, "every Core profile", `SELECT school_id, champion_status FROM core_school_profile`, func(rows pgx.Rows) error {
		var code, stored string
		if err := rows.Scan(&code, &stored); err != nil {
			return err
		}
		codes, status[code] = append(codes, code), stored
		return nil
	}); err != nil {
		return nil, err
	}
	r := &records{}
	if err := readChampionInputs(ctx, q, r, codes); err != nil {
		return nil, err
	}
	r.ScanProfiles = codes
	out := []Candidate{}
	for _, j := range judge(r, operational) {
		if !j.metrics.eligible {
			continue
		}
		c := Candidate{Code: j.code, Status: status[j.code], Score: j.metrics.score, LatestAvg: j.latestAvg,
			Delta: pyRound(j.latestAvg-j.earliestAvg, 1), LowestIntervention: "None", Completed: j.completed, Total: j.total}
		// min(latest_scores, key=score): the first of the lowest.
		for i, row := range j.latestScores {
			if v := orZero(row.Score); i == 0 || v < c.LowestScore {
				c.LowestScore, c.LowestIntervention = v, row.Intervention
			}
		}
		out = append(out, c)
	}
	return out, nil
}
