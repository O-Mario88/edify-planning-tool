package clusteroversight

import "encoding/json"

// records is everything the Command Center reads, as the existing page's
// statements return it (apps.clusters.workspace.load and _command): rows in
// the order they come back, before any rule is applied. The page is a
// function of these and of who is reading.
type records struct {
	// Clusters are the reader's clusters by name.
	Clusters []clusterRow `json:"clusters"`
	// Owners are the staff a cluster can be filed under, by staff profile id
	// and by user id, each as the page names them.
	Owners map[string]string `json:"owners"`
	// Members are the clusters' operating schools by name.
	Members []memberRow `json:"members"`
	// Sessions are the delivered meetings and group trainings, newest made
	// first, and Register who was invited to and came to each.
	Sessions []sessionRow  `json:"sessions"`
	Register []registerRow `json:"register"`
	// LatestNow and LatestBefore are each school's latest confirmed SSA
	// record of the year and of the year before, in school order, and
	// PairScores those records' scores.
	LatestNow    []latestRow `json:"latest_now"`
	LatestBefore []latestRow `json:"latest_before"`
	PairScores   []scoreRow  `json:"pair_scores"`
	// ChangeRules are the published measurement rules, newest first.
	ChangeRules []changeRuleRow `json:"change_rules"`
	// Enrolment is each school's figure for the year and the year before.
	Enrolment []enrolmentRow `json:"enrolment"`
	// Learning is the confirmed class results of the two years.
	Learning []learningRow `json:"learning"`
	// Funded is one school id for each funded loan the page's statement
	// tells apart (see funded in read.go).
	Funded []string `json:"funded"`
	// Stories are the change stories that are not drafts.
	Stories []storyRow `json:"stories"`
	// Plan is the year's meetings and group trainings still in the plan.
	Plan []planRow `json:"plan"`
	// Setting is the newest weights row, or nil for the defaults.
	Setting *settingRow `json:"setting"`
	// YearRecords are the year's confirmed SSA records, each school's
	// newest first, and YearScores their scores.
	YearRecords []yearRecordRow `json:"year_records"`
	YearScores  []scoreRow      `json:"year_scores"`
	// LastDelivered is each cluster's latest delivered meeting or training.
	LastDelivered map[string]string `json:"last_delivered"`
}

type clusterRow struct {
	ID          string  `json:"id"`
	Name        string  `json:"name"`
	District    string  `json:"district"`
	OwnerID     *string `json:"owner_id"`
	LeaderName  *string `json:"leader_name"`
	LeaderPhone *string `json:"leader_phone"`
}

type memberRow struct {
	ID        string `json:"id"`
	ClusterID string `json:"cluster_id"`
	// Country is the school's region's, "" where it has none.
	Country string `json:"country"`
}

type sessionRow struct {
	ID        string   `json:"id"`
	ClusterID string   `json:"cluster_id"`
	Type      string   `json:"type"`
	FY        string   `json:"fy"`
	Focus     string   `json:"focus"`
	Attended  []string `json:"attended"`
	// HeldOn is the delivery date, else the planned one, else "".
	HeldOn string `json:"held_on"`
}

type registerRow struct {
	ActivityID string `json:"activity_id"`
	SchoolID   string `json:"school_id"`
	Invited    bool   `json:"invited"`
	Attended   bool   `json:"attended"`
}

type latestRow struct {
	SchoolID string `json:"school_id"`
	RecordID string `json:"record_id"`
	// TakenOn is the assessment's day in UTC.
	TakenOn string `json:"taken_on"`
}

type scoreRow struct {
	RecordID     string  `json:"record_id"`
	Intervention string  `json:"intervention"`
	Score        float64 `json:"score"`
}

type changeRuleRow struct {
	Intervention string `json:"intervention"`
	Country      string `json:"country"`
	Direction    string `json:"direction"`
	// Threshold is min_meaningful_change, nil where the rule names none.
	Threshold *float64 `json:"threshold"`
}

type enrolmentRow struct {
	SchoolID   string `json:"school_id"`
	FY         string `json:"fy"`
	Enrollment int    `json:"enrollment"`
}

type learningRow struct {
	SchoolID string  `json:"school_id"`
	FY       string  `json:"fy"`
	Mean     float64 `json:"mean"`
	Max      float64 `json:"max"`
	Learners int     `json:"learners"`
}

type storyRow struct {
	ClusterID string `json:"cluster_id"`
	SchoolID  string `json:"school_id"`
	Status    string `json:"status"`
}

type planRow struct {
	ClusterID string `json:"cluster_id"`
	Type      string `json:"type"`
	Status    string `json:"status"`
	Planned   string `json:"planned"`
}

// settingRow is a ClusterScoreSetting row's stored weights and rules.
type settingRow struct {
	Health   map[string]json.RawMessage `json:"health"`
	Impact   map[string]json.RawMessage `json:"impact"`
	Teacher  map[string]json.RawMessage `json:"teacher"`
	Leader   map[string]json.RawMessage `json:"leader"`
	Maturity map[string]json.RawMessage `json:"maturity"`
}

type yearRecordRow struct {
	ID       string   `json:"id"`
	SchoolID string   `json:"school_id"`
	Average  *float64 `json:"average"`
}
