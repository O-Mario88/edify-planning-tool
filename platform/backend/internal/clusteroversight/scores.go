package clusteroversight

import (
	"encoding/json"
	"math"
	"strconv"
	"strings"
)

// settings are the weights in force (scores.Settings): the newest
// ClusterScoreSetting row over the defaults, else the defaults.
type settings struct {
	weights  map[string]map[string]float64
	maturity map[string]float64
}

// pyFloat is float() of a stored JSON value: a number, a number written as
// text, or true and false; anything else is not a number.
func pyFloat(raw json.RawMessage) (float64, bool) {
	var number float64
	if err := json.Unmarshal(raw, &number); err == nil && string(raw) != "null" {
		return number, true
	}
	var flag bool
	if err := json.Unmarshal(raw, &flag); err == nil && string(raw) != "null" {
		if flag {
			return 1, true
		}
		return 0, true
	}
	var text string
	if err := json.Unmarshal(raw, &text); err != nil {
		return 0, false
	}
	text = strings.ToLower(strings.TrimSpace(text))
	if text == "" || strings.ContainsAny(text, "xp_") {
		return 0, false
	}
	number, err := strconv.ParseFloat(text, 64)
	if err != nil && !math.IsInf(number, 0) {
		return 0, false
	}
	return number, true
}

// notNegative is max(0.0, value), which is 0.0 for a value that is not a
// number.
func notNegative(value float64) float64 {
	if value > 0 {
		return value
	}
	return 0
}

// settingsOf is scores.current_settings: each stored weight and rule that
// is a number and names a part the score has replaces its default, never
// below zero; a part the row does not name keeps its default.
func settingsOf(row *settingRow) settings {
	s := settings{weights: map[string]map[string]float64{}, maturity: map[string]float64{}}
	stored := map[string]map[string]json.RawMessage{}
	if row != nil {
		stored = map[string]map[string]json.RawMessage{
			"health": row.Health, "impact": row.Impact, "teacher": row.Teacher, "leader": row.Leader,
		}
	}
	for key, score := range rules.Scores {
		weights := map[string]float64{}
		for _, d := range score.Dimensions {
			weights[d.Key] = d.Weight
			if value, ok := pyFloat(stored[key][d.Key]); ok {
				weights[d.Key] = notNegative(value)
			}
		}
		s.weights[key] = weights
	}
	for key, value := range rules.MaturityDefaults {
		s.maturity[key] = value
		if row != nil {
			if stored, ok := pyFloat(row.Maturity[key]); ok {
				s.maturity[key] = notNegative(stored)
			}
		}
	}
	return s
}

// part is one part of a score (scores.Dimension): a share out of 100, nil
// where it cannot be measured.
type part struct {
	key    string
	weight float64
	score  *float64
}

// composite is scores.Composite: a weighted mean of the parts that can be
// measured, the weights of those that cannot scaled away.
type composite struct {
	key           string
	parts         []part
	minDimensions int
}

// score is Composite.score: nil with fewer measured parts than the score
// needs, or with no weight among them.
func (c composite) score() *int {
	weights, weighted := []float64{}, []float64{}
	for _, p := range c.parts {
		if p.score != nil && p.weight > 0 {
			weights = append(weights, p.weight)
			weighted = append(weighted, *p.score*p.weight)
		}
	}
	total := pySum(weights)
	if len(weights) < min(c.minDimensions, len(c.parts)) || total == 0 {
		return nil
	}
	score := pyRoundInt(pySum(weighted) / total)
	return &score
}

// band is scores.band: (label, tone) for a score, or for none.
func band(score *int) (string, string) {
	for _, b := range rules.Bands {
		if (score == nil) == (b.Floor == nil) && (score == nil || float64(*score) >= *b.Floor) {
			return b.Label, b.Tone
		}
	}
	last := rules.Bands[len(rules.Bands)-2]
	return last.Label, last.Tone
}

// share is scores._share: part of whole out of 100 to one place, nil of
// nothing.
func share(of, whole int) *float64 {
	if whole == 0 {
		return nil
	}
	value := pyRound(float64(100*of)/float64(whole), 1)
	return &value
}

// facts is what the page knows about one cluster (scores.gather for it).
type facts struct {
	members    []string
	attendance attendance
	movement   map[string]*areaMovement
	enrolment  enrolment
	learning   learning
	stories    stories
	plan       plan
	funded     int
}

// areaShare is scores._area_share: the share of the compared schools that
// improved, or held a strong score, on one SSA area.
func (f facts) areaShare(area string) *float64 {
	a := f.movement[area]
	if a == nil || a.compared == 0 {
		return nil
	}
	return share(a.improved+a.maintainedStrong, a.compared)
}

// trainedPairs is scores.trained_pairs, counted: for each group training of
// the two years with a named SSA area, each member school that attended and
// can be compared on that area, and how many of those readings rose (or held
// a strong score).
func (f facts) trainedPairs(fy string) (better, pairs int) {
	previous := previousFY(fy)
	for _, s := range f.attendance.allSessions {
		if !s.isTraining || s.area == "" || (s.fy != fy && s.fy != previous) {
			continue
		}
		area := f.movement[s.area]
		if area == nil {
			continue
		}
		for school := range s.attended {
			verdict, compared := area.verdicts[school]
			if !compared {
				continue
			}
			pairs++
			if verdict == rules.Change.Improved || verdict == rules.Change.MaintainedStrong {
				better++
			}
		}
	}
	return better, pairs
}

// values is scores._dimension_values: every part of every score for one
// cluster, as a share out of 100, nil where it cannot be measured.
func (f facts) values(fy string) map[string]*float64 {
	v := map[string]*float64{}
	schools := len(f.members)
	memberSet := map[string]bool{}
	for _, school := range f.members {
		memberSet[school] = true
	}
	number := func(x float64) *float64 { return &x }

	v["meetings"] = share(f.plan.meetingsDelivered, f.plan.meetingsDue)
	v["trainings"] = share(f.plan.trainingsDelivered, f.plan.trainingsDue)
	if f.attendance.rate != nil {
		v["attendance"] = number(float64(*f.attendance.rate))
	}
	if schools > 0 && len(f.attendance.sessions) > 0 {
		v["participation"] = share(f.attendance.represented, schools)
	}
	planned := 0.0
	if f.plan.meetingPlanned {
		planned++
	}
	if f.plan.trainingPlanned {
		planned++
	}
	v["planning"] = number(planned * 50)
	invitedEver := 0
	for _, s := range f.attendance.schools {
		if s.invited > 0 || s.lastAttended != "" {
			invitedEver++
		}
	}
	if schools > 0 && (invitedEver > 0 || f.attendance.drifting > 0) {
		v["follow_up"] = share(schools-f.attendance.drifting, schools)
	}

	v["ssa"] = f.areaShare(overall)
	if better, pairs := f.trainedPairs(fy); pairs > 0 {
		v["training_effect"] = share(better, pairs)
	}
	kept, asked := f.attendance.kindAttendance(memberSet, false)
	v["meeting_engagement"] = share(kept, asked)
	v["meeting_attendance"] = v["meeting_engagement"]
	kept, asked = f.attendance.kindAttendance(memberSet, true)
	v["training_attendance"] = share(kept, asked)
	v["teaching_ssa"] = f.areaShare("teaching_environment")
	v["learning_env_ssa"] = f.areaShare("learning_environment")
	v["leadership_ssa"] = f.areaShare("leadership")
	v["finance_ssa"] = f.areaShare("financial_health")
	v["compliance_ssa"] = f.areaShare("government_requirement")

	v["enrolment"] = share(f.enrolment.grew, f.enrolment.compared)
	v["exams"] = share(f.learning.improved, f.learning.compared)
	bt := []float64{}
	for _, key := range []string{"finance_ssa", "compliance_ssa"} {
		if v[key] != nil {
			bt = append(bt, *v[key])
		}
	}
	if len(bt) > 0 {
		v["bt"] = number(pyRound(mean(bt), 1))
	}
	v["loans"] = share(f.funded, schools)
	return v
}

func compositeOf(key string, values map[string]*float64, s settings) composite {
	c := composite{key: key, minDimensions: int(s.maturity["min_dimensions"])}
	for _, d := range rules.Scores[key].Dimensions {
		c.parts = append(c.parts, part{key: d.Key, weight: s.weights[key][d.Key], score: values[d.Key]})
	}
	return c
}

// scorecard is scores.Scorecard, as far as the page reads it.
type scorecard struct {
	health, impact composite
	maturity       int
}

// maturityLabel is the level's name; a cluster on no level has no schools.
func maturityLabel(level int) string {
	for _, l := range rules.MaturityLevels {
		if l.Number == level {
			return l.Label
		}
	}
	return "No schools yet"
}

// scorecardOf is scores.scorecards for one cluster. The Teacher and Leader
// indices are themselves parts of Cluster Impact.
func scorecardOf(f facts, fy string, s settings) scorecard {
	values := f.values(fy)
	for _, key := range []string{"teacher", "leader"} {
		values[key] = nil
		if score := compositeOf(key, values, s).score(); score != nil {
			index := float64(*score)
			values[key] = &index
		}
	}
	card := scorecard{health: compositeOf("health", values, s), impact: compositeOf("impact", values, s)}
	card.maturity = maturity(f, card, values["ssa"], s.maturity)
	return card
}

// maturity is scores._maturity's level: a level is reached only when every
// level below it is.
func maturity(f facts, card scorecard, ssa *float64, r map[string]float64) int {
	schools := len(f.members)
	participation := 0.0
	if p := share(f.attendance.represented, schools); p != nil {
		participation = *p
	}
	health, impact := card.health.score(), card.impact.score()
	atLeast := func(value *int, floor float64) bool { return value != nil && float64(*value) >= floor }
	met := []bool{
		schools > 0,
		float64(len(f.attendance.sessions)) >= r["active_sessions"] && participation >= r["active_participation"],
		atLeast(health, r["healthy_health"]) && ssa != nil && *ssa >= r["healthy_ssa_improved"],
		atLeast(impact, r["high_impact"]),
		atLeast(health, r["model_health"]) && atLeast(impact, r["model_impact"]) && float64(f.stories.approved) >= r["model_stories"],
	}
	level := 0
	for i, ok := range met {
		if !ok {
			break
		}
		level = i + 1
	}
	return level
}
