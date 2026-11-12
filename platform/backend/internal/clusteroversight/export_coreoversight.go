package clusteroversight

// What Core School Oversight (internal/coreoversight) reads from this page:
// each school's SSA verdict, judged as the SSA movement here judges it
// (impact_engine.improvement_rows, change_rules.classify_pairs and
// school_verdicts), so a school moves the same way on both pages.

// SSAReading is a school's latest confirmed SSA record of a year: the record
// and its day in UTC ("2026-04-22").
type SSAReading struct {
	SchoolID, RecordID, TakenOn string
}

// SSAScore is one intervention's score on a record.
type SSAScore struct {
	RecordID, Intervention string
	Score                  float64
}

// ChangeRule is a published measurement rule (activity_intervention_mapping),
// newest first; Threshold is nil where the rule names none.
type ChangeRule struct {
	Intervention, Country, Direction string
	Threshold                        *float64
}

// SchoolVerdict is change_rules.school_verdicts' answer for one school: its
// classification and the mean of its comparable pairs' movement (to four
// places, as the verdict keeps it).
type SchoolVerdict struct {
	Classification string
	MeanDelta      float64
}

// SchoolVerdicts judges every school with a confirmed record in both years
// (now and before, each school's latest, in school order) on the scores
// those records carry, under the published rules, the school's country
// deciding which rule applies. A school with no comparable pair is not in
// the answer.
func SchoolVerdicts(now, before []SSAReading, scores []SSAScore, published []ChangeRule, country map[string]string) map[string]SchoolVerdict {
	r := &records{}
	for _, row := range now {
		r.LatestNow = append(r.LatestNow, latestRow{SchoolID: row.SchoolID, RecordID: row.RecordID, TakenOn: row.TakenOn})
	}
	for _, row := range before {
		r.LatestBefore = append(r.LatestBefore, latestRow{SchoolID: row.SchoolID, RecordID: row.RecordID, TakenOn: row.TakenOn})
	}
	for _, row := range scores {
		r.PairScores = append(r.PairScores, scoreRow{RecordID: row.RecordID, Intervention: row.Intervention, Score: row.Score})
	}
	for _, row := range published {
		r.ChangeRules = append(r.ChangeRules, changeRuleRow{
			Intervention: row.Intervention, Country: row.Country, Direction: row.Direction, Threshold: row.Threshold,
		})
	}
	out := map[string]SchoolVerdict{}
	for school, found := range classify(r, country) {
		deltas := make([]float64, len(found.pairs))
		for i, p := range found.pairs {
			deltas[i] = p.delta
		}
		out[school] = SchoolVerdict{Classification: found.verdict, MeanDelta: pyRound(mean(deltas), 4)}
	}
	return out
}
