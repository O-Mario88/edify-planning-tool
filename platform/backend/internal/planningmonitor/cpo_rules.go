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
