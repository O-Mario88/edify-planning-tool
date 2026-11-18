package coreoversight

// records is everything the page reads, as the existing page's statements
// return it (apps.core_schools.intelligence.scoped_core_schools, performance
// and recommendations): rows in the order they come back, before any rule
// is applied. The page is a function of these, of who is reading and of the
// query.
type records struct {
	// Schools are the reader's operating Core schools, newest made first
	// (the School model's order).
	Schools []schoolRow `json:"schools"`
	// Owners name the staff a school is held by, by staff profile id and by
	// user id (clusters.oversight_service._staff_directory and _label).
	Owners map[string]string `json:"owners"`
	// Clusters and SubRegions name the schools' clusters (those not
	// deleted) and sub-regions.
	Clusters   map[string]string `json:"clusters"`
	SubRegions map[string]string `json:"sub_regions"`

	// YearRecords are the confirmed SSA records of the year and the year
	// before, each school's and year's newest first
	// (year_comparison.school_year_scores), and YearCarried the scores of
	// the latest ones that carry no average of their own.
	YearRecords []yearRecordRow `json:"year_records"`
	YearCarried []scoreRow      `json:"year_carried"`
	// CurrentRecords are the year's confirmed records, each school's newest
	// first, and CurrentScores the latest ones' scores
	// (year_comparison.school_current_scores).
	CurrentRecords []yearRecordRow `json:"current_records"`
	CurrentScores  []scoreRow      `json:"current_scores"`
	// Countries are the schools' regions' countries.
	Countries map[string]string `json:"countries"`
	// ChangeRules are the published measurement rules, newest first;
	// LatestNow and LatestBefore each school's latest confirmed record of
	// the year and the year before; PairScores those records' scores
	// (impact_engine.improvement_rows).
	ChangeRules  []changeRuleRow `json:"change_rules"`
	LatestNow    []latestRow     `json:"latest_now"`
	LatestBefore []latestRow     `json:"latest_before"`
	PairScores   []scoreRow      `json:"pair_scores"`

	// Plans are the year's Core plans, filed under a school's id or its
	// School ID.
	Plans []planRow `json:"plans"`
	// Handovers are the year's partner hand-overs counted by state.
	Handovers []handoverRow `json:"handovers"`
	// Register is the delivered cluster sessions' register, and Trainings
	// the schools' own delivered trainings.
	Register  []registerRow `json:"register"`
	Trainings []trainingRow `json:"trainings"`
	// Enrolment and Learning are the two years' figures.
	Enrolment []enrolmentRow `json:"enrolment"`
	Learning  []learningRow  `json:"learning"`

	// Stored are the Core profiles' Champion statuses, by School ID.
	Stored []storedRow `json:"stored"`
	// The Champion rule's inputs (ChampionEligibilityService.scan): the
	// School IDs with a Core profile, their live plans' package slots, their
	// confirmed SSAs oldest first, the latest ones' scores, and the
	// schools' closed activities.
	ScanProfiles []string        `json:"scan_profiles"`
	ScanPlans    []scanPlanRow   `json:"scan_plans"`
	ScanSSAs     []scanSSARow    `json:"scan_ssas"`
	ScanScores   []scanScoreRow  `json:"scan_scores"`
	ScanSchools  []scanSchoolRow `json:"scan_schools"`

	// Recommendations are the schools' recorded SSA recommendations still
	// open or planned, by school, rank and intervention.
	Recommendations []recommendationRow `json:"recommendations"`
}

type schoolRow struct {
	ID   string `json:"id"`
	Code string `json:"code"`
	Name string `json:"name"`
	Type string `json:"type"`
	// District is the school's district's name, "" with none.
	District    string `json:"district"`
	ClusterID   string `json:"cluster_id"`
	OwnerID     string `json:"owner_id"`
	SubRegionID string `json:"sub_region_id"`
}

type yearRecordRow struct {
	ID       string   `json:"id"`
	SchoolID string   `json:"school_id"`
	FY       string   `json:"fy"`
	Average  *float64 `json:"average"`
}

type scoreRow struct {
	RecordID     string  `json:"record_id"`
	Intervention string  `json:"intervention"`
	Score        float64 `json:"score"`
}

type changeRuleRow struct {
	Intervention string   `json:"intervention"`
	Country      string   `json:"country"`
	Direction    string   `json:"direction"`
	Threshold    *float64 `json:"threshold"`
}

type latestRow struct {
	SchoolID string `json:"school_id"`
	RecordID string `json:"record_id"`
	// TakenOn is the assessment's day in UTC.
	TakenOn string `json:"taken_on"`
}

type planRow struct {
	SchoolKey       string `json:"school_key"`
	VisitsDone      int    `json:"visits_done"`
	VisitsTarget    int    `json:"visits_target"`
	TrainingsDone   int    `json:"trainings_done"`
	TrainingsTarget int    `json:"trainings_target"`
}

type handoverRow struct {
	SchoolID  string `json:"school_id"`
	Assigned  int    `json:"assigned"`
	Scheduled int    `json:"scheduled"`
	Completed int    `json:"completed"`
}

type registerRow struct {
	SchoolID string `json:"school_id"`
	Invited  bool   `json:"invited"`
	Attended bool   `json:"attended"`
	Teachers *int   `json:"teachers"`
	Leaders  *int   `json:"leaders"`
}

type trainingRow struct {
	SchoolID string `json:"school_id"`
	Teachers *int   `json:"teachers"`
	Leaders  *int   `json:"leaders"`
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

type storedRow struct {
	Code   string  `json:"code"`
	Status *string `json:"status"`
}

type scanPlanRow struct {
	Code      string `json:"code"`
	FY        string `json:"fy"`
	Total     int    `json:"total"`
	Completed int    `json:"completed"`
}

type scanSSARow struct {
	ID      string   `json:"id"`
	Code    string   `json:"code"`
	Average *float64 `json:"average"`
}

type scanScoreRow struct {
	RecordID     string   `json:"record_id"`
	Score        *float64 `json:"score"`
	Intervention string   `json:"intervention,omitempty"`
}

type scanSchoolRow struct {
	Code   string `json:"code"`
	Closed int    `json:"closed"`
	Clean  int    `json:"clean"`
}

type recommendationRow struct {
	SchoolID     string `json:"school_id"`
	Intervention string `json:"intervention"`
	// Score is the Decimal column's text, nil where none was recorded.
	Score  *string `json:"score"`
	Band   string  `json:"band"`
	Reason string  `json:"reason"`
	State  string  `json:"state"`
	// Item is the recommended catalogue training's name (HasItem when one is
	// linked); Unmapped is why none is mapped.
	Item     string `json:"item"`
	HasItem  bool   `json:"has_item"`
	Unmapped string `json:"unmapped"`
}
