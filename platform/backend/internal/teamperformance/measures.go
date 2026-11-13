package teamperformance

import (
	"fmt"
	"slices"
)

// districtMeeting is the District Meeting's catalogue code, the topic the
// Quarterly Cluster Leaders Meeting row reads (measures.DISTRICT_MEETING):
// the one the District MOU row's own match names.
var districtMeeting = func() string {
	m := byKey["district_meetings"]
	if m == nil || m.Match == nil || len(m.Match.Wanted) != 1 {
		panic("teamperformance: the District Meetings row no longer names one topic")
	}
	return m.Match.Wanted[0]
}()

// lambdaRows are the two rows whose match is a lambda in measures.py, by key,
// with the names and constants the lambda was exported with: a change to
// either lambda changes the export and stops the gateway here.
var lambdaRows = map[string][2][]string{
	"cluster_leaders_meetings": {{"topic", "DISTRICT_MEETING", "meeting"}, {"None", "cluster_leaders"}},
	"alumni_data":              {{"alumni"}, {"None"}},
}

func init() {
	for _, m := range workMeasures {
		switch m.Match.Maker {
		case "_training", "_visit", "_meeting", "_topics":
		case "<lambda>":
			want, ok := lambdaRows[m.Key]
			if !ok || !slices.Equal(want[0], m.Match.Names) || !slices.Equal(want[1], m.Match.Consts) {
				panic(fmt.Sprintf("teamperformance: the %s row's match changed; port it", m.Key))
			}
		default:
			panic("teamperformance: unknown match maker " + m.Match.Maker)
		}
	}
}

// is is Python's `f.core is core` for an optional flag.
func is(value *bool, want bool) bool { return value != nil && *value == want }

// matches is the measure's predicate (measures._training, _visit, _meeting,
// _topics and the two lambdas).
func matches(m *measure, f facts) bool {
	spec := m.Match
	switch spec.Maker {
	case "_training":
		return f.kind == "training" &&
			(len(spec.Wanted) == 0 || slices.Contains(spec.Wanted, f.topic)) &&
			(spec.Core == nil || is(f.core, *spec.Core)) &&
			(spec.Online == nil || f.online == *spec.Online)
	case "_visit":
		return f.kind == "visit" && spec.Core != nil && is(f.core, *spec.Core) &&
			(spec.Partner == nil || f.partner == *spec.Partner)
	case "_meeting":
		return (f.kind == "meeting" || f.meeting == "training") &&
			(spec.ActivityType == nil || f.activityType == *spec.ActivityType) &&
			(spec.Core == nil || is(f.core, *spec.Core))
	case "_topics":
		return slices.Contains(spec.Wanted, f.topic)
	}
	switch m.Key {
	case "cluster_leaders_meetings":
		return f.topic == districtMeeting || f.meeting == "cluster_leaders"
	case "alumni_data":
		return f.alumni
	}
	return false
}
