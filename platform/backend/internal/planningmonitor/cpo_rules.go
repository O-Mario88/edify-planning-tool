package planningmonitor

// Country Planning Oversight (apps.planning.country_oversight) shares the
// planning rulebook with the Planning Monitor; these are its own words
// (policy, coverage, requirements), exported beside the rulebook's.

type cpoSlots struct {
	Staff    int `json:"staff"`
	Partner  int `json:"partner"`
	Flexible int `json:"flexible"`
}

type cpoRules struct {
	PolicyVersion               string              `json:"policy_version"`
	Families                    map[string]string   `json:"families"`
	FamilyLabels                map[string]string   `json:"family_labels"`
	UnmappedFamily              string              `json:"unmapped_family"`
	CoreFamily                  string              `json:"core_family"`
	ClientFamily                string              `json:"client_family"`
	FamilySlots                 map[string]cpoSlots `json:"family_slots"`
	StaffCeilings               map[string]int      `json:"staff_ceilings"`
	PlannedStates               []string            `json:"planned_states"`
	VerifiedStates              []string            `json:"verified_states"`
	ExcludedDuplicateStatuses   []string            `json:"excluded_duplicate_statuses"`
	ClosedStatuses              []string            `json:"closed_statuses"`
	Phasing                     map[string]float64  `json:"phasing"`
	AttendanceTypes             []string            `json:"attendance_types"`
	UnscheduledHandoverStatuses []string            `json:"unscheduled_handover_statuses"`
	ReturnedToStaff             string              `json:"returned_to_staff"`
	ClosedHandoverStatuses      []string            `json:"closed_handover_statuses"`
	PackageTrainingTypes        []string            `json:"package_training_types"`
	PackageVisitTypes           []string            `json:"package_visit_types"`
	NonPackageVisitPurposes     []string            `json:"non_package_visit_purposes"`
	PurposeActivityTypes        map[string]string   `json:"purpose_activity_types"`
	NoOwner                     [2]string           `json:"no_owner"`
	NoLead                      [2]string           `json:"no_lead"`
	Fields                      []string            `json:"fields"`
	PeopleFields                []string            `json:"people_fields"`
	PhasedFields                []string            `json:"phased_fields"`
	TypeFields                  map[string]string   `json:"type_fields"`
	Page                        struct {
		KPITables map[string]string `json:"kpi_tables"`
		KPILabels map[string]string `json:"kpi_labels"`
		// The card's drawer: what it counts, the gap it opens on, the gap's
		// words.
		KPIDefinitions map[string]string `json:"kpi_definitions"`
		KPIGaps        map[string]string `json:"kpi_gaps"`
		GapFigures     map[string]string `json:"gap_figures"`
		TypeViews      [][2]string       `json:"type_views"`
		TableViews     [][2]string       `json:"table_views"`
		TableColumns   [][3]string       `json:"table_columns"`
		TypeOptions    [][2]string       `json:"type_options"`
		ChannelOptions [][2]string       `json:"channel_options"`
		ClusterOptions [][2]string       `json:"cluster_options"`
		StatusOptions  [][2]string       `json:"status_options"`
		LensTabs       [][4]string       `json:"lens_tabs"`
		// The Open Follow-ups panel's words.
		FollowUpOpenStates   []string          `json:"followup_open_states"`
		FollowUpStatusLabels map[string]string `json:"followup_status_labels"`
		FollowUpIssueLabels  map[string]string `json:"followup_issue_labels"`
		FollowUpIssues       []cpoIssueRule    `json:"followup_issues"`
		PolicyVersion        string            `json:"policy_version"`
		// The consolidated tables (tables.SPECS) and their tab order.
		Tables      []cpoTableSpec    `json:"tables"`
		TableTabs   []string          `json:"table_tabs"`
		TableLabels map[string]string `json:"table_labels"`
		TableWords  struct {
			Statuses      map[string]string `json:"statuses"`
			Types         map[string]string `json:"types"`
			Interventions map[string]string `json:"interventions"`
			Kinds         map[string]string `json:"kinds"`
			WaitingStates []string          `json:"waiting_states"`
			Duplicates    map[string]string `json:"duplicate_labels"`
			// Evidence, Verification and Payment are the workbook's words
			// for those fields (_field_labels).
			Evidence     map[string]string `json:"evidence"`
			Verification map[string]string `json:"verification"`
			Payment      map[string]string `json:"payment"`
		} `json:"table_words"`
		// The roles the drill-down offers Export to (can_export).
		ExportRoles []string `json:"export_roles"`
		// The data-quality queue's vocabularies (country_oversight.data_quality).
		DataQuality struct {
			SessionTypes                []string          `json:"session_types"`
			PendingFamilyDecisions      map[string]string `json:"pending_family_decisions"`
			Sample                      int               `json:"sample"`
			PackageVisitTypes           []string          `json:"package_visit_types"`
			PackageTrainingTypes        []string          `json:"package_training_types"`
			NonPackageVisitPurposes     []string          `json:"non_package_visit_purposes"`
			CompanionVisitPurpose       string            `json:"companion_visit_purpose"`
			DataCollectionVisitTypes    []string          `json:"data_collection_visit_types"`
			DataCollectionVisitPurposes []string          `json:"data_collection_visit_purposes"`
			OutreachVisitTypes          []string          `json:"outreach_visit_types"`
			OutreachVisitPurposes       []string          `json:"outreach_visit_purposes"`
			UncreditedStatuses          []string          `json:"uncredited_statuses"`
			PurposeActivityTypes        map[string]string `json:"purpose_activity_types"`
		} `json:"data_quality"`
	} `json:"page"`
}

// family is policy.family_of.
func (c cpoRules) family(schoolType string) string {
	if f, ok := c.Families[schoolType]; ok {
		return f
	}
	return c.UnmappedFamily
}

// slots is policy.requirement_for.
func (c cpoRules) slots(family string) cpoSlots {
	if s, ok := c.FamilySlots[family]; ok {
		return s
	}
	return c.FamilySlots[c.UnmappedFamily]
}

// cpoTableSpec is tables.Spec.
type cpoTableSpec struct {
	Key, Title, Short, Unit, Description string
	Columns                              []cpoColumn `json:"columns"`
	ExportOnly                           []string    `json:"export_only"`
}

// cpoColumn is tables.Column.
type cpoColumn struct {
	Key, Label string
	Numeric    bool   `json:"numeric"`
	IsDate     bool   `json:"is_date"`
	IsSchool   bool   `json:"is_school"`
	Blank      string `json:"blank"`
	Quiet      bool   `json:"quiet"`
	Kind       string `json:"kind"`
}

// cpoIssueRule is followups.Issue: a planning gap's tally fields (required,
// planned, remaining) and the school-level test that puts a school in it.
type cpoIssueRule struct {
	Key            string `json:"key"`
	Label          string `json:"label"`
	Required       string `json:"required"`
	Planned        string `json:"planned"`
	Remaining      string `json:"remaining"`
	SchoolTest     string `json:"school_test"`
	ResolutionRule string `json:"resolution_rule"`
}
