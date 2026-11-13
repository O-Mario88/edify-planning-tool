// Package teamperformance builds the Team Performance page (/team-performance/,
// apps.frontend.views.team_performance_views and apps.team_performance): the
// FY27 Weekly Report's six tabs, every figure read from the records when the
// page opens, as the existing feed reads the page's HTML into blocks.
package teamperformance

import (
	_ "embed"
	"encoding/json"
)

//go:embed rules.json
var rulesJSON []byte

// door is what one role may do on the page (rules.json "doors").
type door struct {
	ViewPage   bool   `json:"view_page"`
	OpenURL    bool   `json:"open_url"`
	Reach      string `json:"reach"`
	SetTargets bool   `json:"set_targets"`
}

// matchSpec is the work a measure counts: the predicate maker and the values
// it was made with (measures._training, _visit, _meeting, _topics, or a
// lambda named by its key).
type matchSpec struct {
	Maker        string   `json:"maker"`
	Wanted       []string `json:"wanted"`
	Core         *bool    `json:"core"`
	Online       *bool    `json:"online"`
	Partner      *bool    `json:"partner"`
	ActivityType *string  `json:"activity_type"`
	Names        []string `json:"names"`
	Consts       []string `json:"consts"`
}

// measure is one row of the Weekly Report (measures.Measure).
type measure struct {
	Key       string     `json:"key"`
	Label     string     `json:"label"`
	Section   string     `json:"section"`
	Unit      string     `json:"unit"`
	Source    string     `json:"source"`
	Milestone string     `json:"milestone"`
	Slice     string     `json:"slice"`
	Basis     string     `json:"basis"`
	Tracked   bool       `json:"tracked"`
	Weekly    bool       `json:"weekly"`
	Note      string     `json:"note"`
	People    string     `json:"people"`
	Match     *matchSpec `json:"match"`
}

// strategicRow is one Strategic Milestones row (strategic.StrategicRow).
type strategicRow struct {
	Domain   string   `json:"domain"`
	Title    string   `json:"title"`
	Mode     string   `json:"mode"`
	Kind     string   `json:"kind"`
	Measures []string `json:"measures"`
	Plan     string   `json:"plan"`
	Slice    string   `json:"slice"`
	Basis    string   `json:"basis"`
	Key      string   `json:"key"`
	Lead     string   `json:"lead"`
}

type pageRules struct {
	Doors map[string]door `json:"doors"`
	Roles struct {
		CCEO string `json:"cceo"`
		Lead string `json:"lead"`
	} `json:"roles"`
	Statuses struct {
		Achieved      []string `json:"achieved"`
		Planned       []string `json:"planned"`
		Uploaded      []string `json:"uploaded"`
		ActiveSchool  []string `json:"active_school"`
		DisbursedLoan []string `json:"disbursed_loan"`
		CoreSlotDone  []string `json:"core_slot_done"`
	} `json:"statuses"`
	ActivityTypes struct {
		Visit           []string `json:"visit"`
		Training        []string `json:"training"`
		ClusterMeeting  []string `json:"cluster_meeting"`
		ProgrammeEvent  []string `json:"programme_event"`
		ClusterTraining []string `json:"cluster_training"`
	} `json:"activity_types"`
	CoreFamily     []string       `json:"core_family"`
	Measures       []measure      `json:"measures"`
	Sections       []string       `json:"sections"`
	Strategic      []strategicRow `json:"strategic"`
	StrategicKinds struct {
		Count     string `json:"count"`
		Rate      string `json:"rate"`
		Score     string `json:"score"`
		Untracked string `json:"untracked"`
	} `json:"strategic_kinds"`
	Tabs           [][3]string    `json:"tabs"`
	Kinds          [][2]string    `json:"kinds"`
	Kept           []string       `json:"kept"`
	SummaryKept    []string       `json:"summary_kept"`
	DashboardViews [][2]string    `json:"dashboard_views"`
	Sorts          [][2]string    `json:"sorts"`
	SummaryGroups  []summaryGroup `json:"summary_groups"`
	Delivery       []deliveryRow  `json:"delivery"`
	StatusWords    struct {
		Achieved    string `json:"achieved"`
		OnTrack     string `json:"on_track"`
		Progressing string `json:"progressing"`
		Attention   string `json:"attention"`
	} `json:"status_words"`
	StatusTones      map[string]string    `json:"status_tones"`
	Trackers         map[string][2]string `json:"trackers"`
	EvidenceSources  []string             `json:"evidence_sources"`
	NotPlaced        string               `json:"not_placed"`
	PortfolioSources map[string]string    `json:"portfolio_sources"`
	BreakdownLabels  map[string]string    `json:"breakdown_labels"`
	RegionOrder      []string             `json:"region_order"`
	NoLead           string               `json:"no_lead"`
	RateMeasurements []string             `json:"rate_measurements"`
	CountryID        string               `json:"country_id"`
	NotSet           string               `json:"not_set"`
	Eligible         string               `json:"eligible"`
	Setters          map[string]string    `json:"setters"`
	NotPassed        []string             `json:"not_passed_query_keys"`
}

// summaryGroup is one heading of the {Month} {Year} Summary and its columns.
type summaryGroup struct {
	Heading string
	Columns [][2]string
}

func (g *summaryGroup) UnmarshalJSON(b []byte) error {
	var raw []json.RawMessage
	if err := json.Unmarshal(b, &raw); err != nil {
		return err
	}
	if err := json.Unmarshal(raw[0], &g.Heading); err != nil {
		return err
	}
	return json.Unmarshal(raw[1], &g.Columns)
}

// deliveryRow is one Program Delivery milestone: (label, measure, closes).
type deliveryRow struct {
	Label  string
	Key    string
	Closes bool
}

func (d *deliveryRow) UnmarshalJSON(b []byte) error {
	var raw []json.RawMessage
	if err := json.Unmarshal(b, &raw); err != nil {
		return err
	}
	if err := json.Unmarshal(raw[0], &d.Label); err != nil {
		return err
	}
	if err := json.Unmarshal(raw[1], &d.Key); err != nil {
		return err
	}
	return json.Unmarshal(raw[2], &d.Closes)
}

var rules = func() pageRules {
	var r pageRules
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic("teamperformance: rules.json: " + err.Error())
	}
	return r
}()

func set(values []string) map[string]bool {
	out := make(map[string]bool, len(values))
	for _, v := range values {
		out[v] = true
	}
	return out
}

var (
	achievedStatuses = set(rules.Statuses.Achieved)
	plannedStatuses  = set(rules.Statuses.Planned)
	coreSlotDone     = set(rules.Statuses.CoreSlotDone)
	activeStatuses   = set(rules.Statuses.ActiveSchool)
	coreFamily       = set(rules.CoreFamily)
	visitTypes       = set(rules.ActivityTypes.Visit)
	trainingTypes    = set(rules.ActivityTypes.Training)
	meetingTypes     = set(rules.ActivityTypes.ClusterMeeting)
	eventTypes       = set(rules.ActivityTypes.ProgrammeEvent)
	rateMeasurements = set(rules.RateMeasurements)
	evidenceSources  = set(rules.EvidenceSources)
)

// sessionTypes are the cluster sessions (cluster trainings and meetings),
// in the order the ledger names them.
var sessionTypes = append(append([]string{}, rules.ActivityTypes.ClusterTraining...), rules.ActivityTypes.ClusterMeeting...)

var byKey = func() map[string]*measure {
	out := map[string]*measure{}
	for i := range rules.Measures {
		out[rules.Measures[i].Key] = &rules.Measures[i]
	}
	return out
}()

// workMeasures are the measures that count work (measures.WORK_MEASURES).
var workMeasures = func() []*measure {
	out := []*measure{}
	for i := range rules.Measures {
		if rules.Measures[i].Match != nil {
			out = append(out, &rules.Measures[i])
		}
	}
	return out
}()

const (
	unitSchools      = "schools"
	unitSessions     = "sessions"
	unitParticipants = "participants"
)

func isParticipants(key string) bool { return byKey[key].Unit == unitParticipants }
