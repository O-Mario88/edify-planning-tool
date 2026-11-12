package myplan

// RowRules are what the plan's rows are drawn from (get_frontend_context's
// loop and the modules each column reads, docs/migration/25-my-plan.md
// 25.7), exported under "rows" by `manage.py export_my_plan_rules`.
type RowRules struct {
	ActivityTypeLabels        map[string]string   `json:"activity_type_labels"`
	FocusInterventionLabels   map[string]string   `json:"focus_intervention_labels"`
	PurposeLabels             map[string]string   `json:"purpose_labels"`
	VisitTypes                []string            `json:"visit_types"`
	TrainingTypes             []string            `json:"training_types"`
	ClusterMeetingTypes       []string            `json:"cluster_meeting_types"`
	ProgrammeEventTypes       []string            `json:"programme_event_types"`
	ProgrammeSchoolTypes      []string            `json:"programme_school_types"`
	NonFundableStatuses       []string            `json:"non_fundable_statuses"`
	OperatingStatuses         []string            `json:"operating_statuses"`
	ApprovedStatuses          []string            `json:"approved_statuses"`
	LeadVerifiedRoles         []string            `json:"lead_verified_roles"`
	PartnerSSASupportTypes    []string            `json:"partner_ssa_support_types"`
	SSAHoldingStatuses        []string            `json:"ssa_holding_statuses"`
	NotAssessedTypes          []string            `json:"not_assessed_types"`
	OnlineTrainingTypes       []string            `json:"online_training_types"`
	OnlineMode                string              `json:"online_mode"`
	OnlineFreeNote            string              `json:"online_free_note"`
	OnlineTrainingLabel       string              `json:"online_training_label"`
	ModeOfDelivery            map[string]string   `json:"mode_of_delivery"`
	CompanionGoneStatuses     []string            `json:"companion_gone_statuses"`
	CapturedInVisitNote       string              `json:"captured_in_visit_note"`
	CapturedInTrainingNote    string              `json:"captured_in_training_note"`
	RetiredCostSettingKeys    []string            `json:"retired_cost_setting_keys"`
	RateAliases               map[string][]string `json:"rate_aliases"`
	MealsRateKeys             []string            `json:"meals_rate_keys"`
	GroupTrainingMealsRateKey string              `json:"group_training_meals_rate_key"`
	CatalogueCountry          string              `json:"catalogue_country"`
	CatalogueKind             string              `json:"catalogue_kind"`
	CatalogueStatus           string              `json:"catalogue_status"`
	CanonicalRateKeys         []string            `json:"canonical_rate_keys"`
	CompleteLabel             string              `json:"complete_label"`
	FinishedEarly             string              `json:"finished_early"`
	MissingSF                 string              `json:"missing_sf"`
	MissingEvidence           string              `json:"missing_evidence"`
	// completion_columns.expected_evidence: the form a partner's work is
	// completed with.
	EvidenceAttendanceTypes []string          `json:"evidence_attendance_types"`
	EvidenceAttendanceKind  string            `json:"evidence_attendance_kind"`
	EvidenceVisitKind       string            `json:"evidence_visit_kind"`
	MissingBoth             string            `json:"missing_both"`
	AwaitingSSALabel        string            `json:"awaiting_ssa_label"`
	FieldRoles              []string          `json:"field_roles"`
	FieldRoleAliases        []string          `json:"field_role_aliases"`
	HQPrimaryDistricts      []string          `json:"hq_primary_districts"`
	DayMarkLabels           map[string]string `json:"day_mark_labels"`
	CoreVisits              SheetRules        `json:"core_visits"`
	CoreTrainings           SheetRules        `json:"core_trainings"`
}

// SheetRules are one of table_export's sheets: its title and headings.
type SheetRules struct {
	Title   string   `json:"title"`
	Headers []string `json:"headers"`
}
