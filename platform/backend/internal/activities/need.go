package activities

import (
	"context"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// A school's verified need, as apps.ssa.plan_alignment.school_need reads it
// from the recommendation engine (apps.ssa.recommendation_engine
// prioritized_interventions, _rank_interventions).

type ssaRecord struct {
	ID, FY       string
	Date         *time.Time
	CreatedAt    time.Time
	AverageScore *float64
	// Scores in the order the existing prefetch reads them.
	Scores []ssaScore
}

type ssaScore struct {
	Intervention string
	Score        *float64
}

// rankedNeed is one row of prioritized_interventions, as far as the save
// keeps it.
type rankedNeed struct {
	Intervention, Label, Band string
	// Score is round(latest, 1); Priority the composite.
	Score, Priority float64
}

type schoolNeed struct {
	Record       *ssaRecord
	Ranked       []rankedNeed
	Priorities   []string
	Stale        bool
	PendingSince *time.Time
}

func (n schoolNeed) assessed() bool { return n.Record != nil && len(n.Ranked) > 0 }

// needReader is the read the need takes.
type needReader interface {
	confirmedHistory(ctx context.Context, schoolID string) ([]ssaRecord, error)
	pendingSince(ctx context.Context, schoolID string, after *time.Time) (*time.Time, error)
	peerScores(ctx context.Context, clusterID, schoolID string) ([]map[string]float64, error)
}

// schoolNeedOf is plan_alignment.school_need(school).
func schoolNeedOf(ctx context.Context, r needReader, schoolID, clusterID string, now time.Time) (schoolNeed, error) {
	history, err := r.confirmedHistory(ctx, schoolID)
	if err != nil {
		return schoolNeed{}, err
	}
	if len(history) == 0 {
		pending, err := r.pendingSince(ctx, schoolID, nil)
		return schoolNeed{PendingSince: pending}, err
	}
	// latest_applicable_record: newest date, then newest created (the
	// history is read oldest first, so it is the last of the newest date).
	record := latestApplicable(history)
	var peers []map[string]float64
	if clusterID != "" {
		if peers, err = r.peerScores(ctx, clusterID, schoolID); err != nil {
			return schoolNeed{}, err
		}
	}
	ranked := rankInterventions(history, peerStats(peers))
	pairs := make([]scored, len(ranked))
	for i, row := range ranked {
		pairs[i] = scored{row.Intervention, row.Score}
	}
	pending, err := r.pendingSince(ctx, schoolID, record.Date)
	if err != nil {
		return schoolNeed{}, err
	}
	return schoolNeed{
		Record: record, Ranked: ranked, Priorities: priorityCodes(pairs),
		Stale: !isCurrent(record, now), PendingSince: pending,
	}, nil
}

func latestApplicable(history []ssaRecord) *ssaRecord {
	best := &history[0]
	for i := range history {
		h := &history[i]
		switch {
		case dateAfter(h.Date, best.Date):
			best = h
		case sameDate(h.Date, best.Date) && h.CreatedAt.After(best.CreatedAt):
			best = h
		}
	}
	return best
}

// dateAfter orders as Postgres orders "-date_of_ssa": NULLs first.
func dateAfter(a, b *time.Time) bool {
	switch {
	case a == nil:
		return b != nil
	case b == nil:
		return false
	}
	return a.After(*b)
}

func sameDate(a, b *time.Time) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	return a.Equal(*b)
}

type scored struct {
	code  string
	score float64
}

// priorityCodes is plan_alignment._priority_codes.
func priorityCodes(ranked []scored) []string {
	a := rules.Alignment
	needs := []string{}
	for _, r := range ranked {
		if r.score < a.StrongScore {
			needs = append(needs, r.code)
		}
	}
	chosen := append([]string{}, needs[:min(len(needs), a.PriorityDepth)]...)
	for _, r := range ranked {
		if r.score < a.CriticalScore && !in(chosen, r.code) {
			chosen = append(chosen, r.code)
		}
	}
	if len(chosen) == 0 && len(ranked) > 0 {
		chosen = []string{ranked[0].code}
	}
	return chosen
}

// recordFY is plan_alignment._record_fy.
func recordFY(r *ssaRecord) (int, bool) {
	raw := strings.TrimSpace(r.FY)
	if raw == "" && r.Date != nil {
		raw = schooldirectory.OperationalFY(*r.Date)
	}
	if len(raw) > 4 {
		raw = raw[len(raw)-4:]
	}
	n, err := strconv.Atoi(raw)
	return n, err == nil
}

// isCurrent is plan_alignment.is_current: the record's year is one of the
// last CURRENT_SSA_FYS.
func isCurrent(r *ssaRecord, now time.Time) bool {
	fy, ok := recordFY(r)
	if !ok {
		return false
	}
	running, _ := strconv.Atoi(schooldirectory.OperationalFY(now))
	return fy > running-rules.Alignment.CurrentSSAFYs
}

type peerStat struct {
	mean, std float64
	count     int
}

// peerStats is recommendation_engine._peer_stats over the peers' latest
// scores (the school itself left out), with numpy's mean and ddof=1 std.
func peerStats(peers []map[string]float64) map[string]peerStat {
	out := map[string]peerStat{}
	if len(peers) == 0 {
		return out
	}
	for _, code := range rules.order {
		values := []float64{}
		for _, scores := range peers {
			if v, ok := scores[code]; ok {
				values = append(values, v)
			}
		}
		if len(values) < rules.Engine.MinPeers {
			continue
		}
		mean := npSum(values) / float64(len(values))
		sq := make([]float64, len(values))
		for i, v := range values {
			d := v - mean
			sq[i] = d * d
		}
		std := math.Sqrt(npSum(sq) / float64(len(values)-1))
		out[code] = peerStat{mean: mean, std: std, count: len(values)}
	}
	return out
}

// npSum is numpy's pairwise summation of a float64 array (umath
// pairwise_sum, blocks of 128 with eight accumulators).
func npSum(a []float64) float64 {
	n := len(a)
	switch {
	case n < 8:
		s := 0.0
		for _, v := range a {
			s += v
		}
		return s
	case n <= 128:
		var r [8]float64
		copy(r[:], a[:8])
		i := 8
		for ; i < n-n%8; i += 8 {
			for j := 0; j < 8; j++ {
				r[j] += a[i+j]
			}
		}
		res := ((r[0] + r[1]) + (r[2] + r[3])) + ((r[4] + r[5]) + (r[6] + r[7]))
		for ; i < n; i++ {
			res += a[i]
		}
		return res
	}
	n2 := n / 2
	n2 -= n2 % 8
	return npSum(a[:n2]) + npSum(a[n2:])
}

func clip01(v float64) float64 { return math.Max(0, math.Min(1, v)) }

type component struct {
	measurable bool
	urgency    float64
}

// rankInterventions is recommendation_engine._rank_interventions.
func rankInterventions(history []ssaRecord, peers map[string]peerStat) []rankedNeed {
	if len(history) == 0 {
		return nil
	}
	series := map[string][]float64{}
	for _, record := range history {
		for _, s := range record.Scores {
			if s.Score != nil && rules.labels[s.Intervention] != "" {
				series[s.Intervention] = append(series[s.Intervention], *s.Score)
			}
		}
	}
	latest := map[string]float64{}
	for _, s := range history[len(history)-1].Scores {
		if s.Score != nil {
			latest[s.Intervention] = *s.Score
		}
	}
	ranked := []rankedNeed{}
	for _, code := range rules.order {
		score, ok := latest[code]
		if !ok {
			continue
		}
		components := map[string]component{
			"severity":    {true, clip01((10.0 - score) / 10.0)},
			"trend":       trendComponent(series[code]),
			"peer_gap":    peerGapComponent(score, peers, code),
			"persistence": persistenceComponent(series[code]),
		}
		band, _ := schooldirectory.SSABand(score)
		ranked = append(ranked, rankedNeed{
			Intervention: code, Label: rules.labels[code], Band: band,
			Score: schooldirectory.PyRound1(score), Priority: composite(components),
		})
	}
	sort.SliceStable(ranked, func(i, j int) bool {
		if ranked[i].Priority != ranked[j].Priority {
			return ranked[i].Priority > ranked[j].Priority
		}
		return ranked[i].Intervention < ranked[j].Intervention
	})
	return ranked
}

// trendComponent is _component_trend over platform_engine.trend_analysis:
// the least-squares slope against the record's position, rounded to four
// places as trend_analysis returns it.
func trendComponent(series []float64) component {
	if len(series) < 2 {
		return component{}
	}
	slope := 0.0
	if !allEqual(series) {
		x := make([]float64, len(series))
		for i := range x {
			x[i] = float64(i)
		}
		xm, ym := npSum(x)/float64(len(x)), npSum(series)/float64(len(series))
		var sxy, sxx float64
		for i := range x {
			dx := x[i] - xm
			sxy += float64(dx * (series[i] - ym))
			sxx += float64(dx * dx)
		}
		slope = sxy / sxx
	}
	slope = pyRound(slope, 4)
	return component{true, clip01(0.5 - slope/2.0)}
}

func allEqual(values []float64) bool {
	for _, v := range values[1:] {
		if v != values[0] {
			return false
		}
	}
	return true
}

func peerGapComponent(score float64, peers map[string]peerStat, code string) component {
	stat, ok := peers[code]
	if !ok || stat.std <= 0 {
		return component{}
	}
	z := (score - stat.mean) / stat.std
	return component{true, clip01(0.5 - z/4.0)}
}

func persistenceComponent(series []float64) component {
	if len(series) < 2 {
		return component{}
	}
	window := series[max(0, len(series)-rules.Engine.PersistenceWindow):]
	below := 0
	for _, v := range window {
		if v <= rules.Engine.WeaknessThreshold {
			below++
		}
	}
	return component{true, clip01(float64(below) / float64(len(window)))}
}

// composite is _composite_priority: the weighted mean of the measurable
// urgencies, out of 100, to one place. Each product is rounded before it is
// added, as Python does (no fused multiply-add).
func composite(components map[string]component) float64 {
	num, denom := 0.0, 0.0
	for _, w := range rules.weights {
		c := components[w.name]
		if !c.measurable {
			continue
		}
		num += float64(w.value * c.urgency)
		denom += w.value
	}
	if denom == 0 {
		return 0
	}
	return pyRound(float64(num/denom*100.0), 1)
}

// pyRound is Python's round(x, n): correctly rounded, ties to even on the
// decimal string the shortest repr gives.
func pyRound(x float64, digits int) float64 {
	if math.IsNaN(x) || math.IsInf(x, 0) {
		return x
	}
	text := strconv.FormatFloat(x, 'f', digits, 64)
	v, err := strconv.ParseFloat(text, 64)
	if err != nil {
		panic(fmt.Sprintf("activities: rounding %v: %v", x, err))
	}
	return v
}
