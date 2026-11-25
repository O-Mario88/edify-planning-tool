package planningmonitor

import (
	"slices"
	"time"
)

// cexRules are the Execution & Completion stage's words and sets
// (apps.planning.country_execution: stages, dataset).
type cexRules struct {
	Stages struct {
		NotAPlan      []string          `json:"not_a_plan"`
		OffPlan       []string          `json:"off_plan"`
		WaitingStart  []string          `json:"waiting_start"`
		InField       []string          `json:"in_field"`
		Returned      []string          `json:"returned"`
		AtPL          []string          `json:"at_pl"`
		AtIA          []string          `json:"at_ia"`
		Verified      []string          `json:"verified"`
		Closed        []string          `json:"closed"`
		ReadStates    []string          `json:"read_states"`
		NotOperating  []string          `json:"not_operating"`
		StageLabels   [][2]string       `json:"stage_labels"`
		OverdueLabels map[string]string `json:"overdue_labels"`
		OwnerLabels   [][2]string       `json:"owner_labels"`
		AgeGroups     [][4]any          `json:"age_groups"`
		Policy        string            `json:"policy"`
	} `json:"stages"`
	BaseFields  []string `json:"base_fields"`
	TrendSeries []string `json:"trend_series"`
	StaffKey    string   `json:"staff_key"`
	// The money, form and trail reads.
	AwaitingDisbursement []string `json:"awaiting_disbursement"`
	MoneyMoved           []string `json:"money_moved"`
	TrailMigration       string   `json:"trail_migration"`
	AttendanceFormTypes  []string `json:"attendance_form_types"`
	Page                 cexPage  `json:"page"`
}

// cexStage is stages.Stage: one activity's position in the spine.
type cexStage struct {
	stage                                     string
	started, executed, plApplicable, reviewed bool
	verified, closed, returned, cancelled     bool
	overdue, owner                            string
	financeOpen                               bool
	timing                                    string
	age                                       int
}

// cexAgeGroup is stages.age_group.
func cexAgeGroup(age int) string {
	for _, g := range rules.CountryExecution.Stages.AgeGroups {
		low, high := int(g[2].(float64)), int(g[3].(float64))
		if low <= age && age <= high {
			return g[0].(string)
		}
	}
	return ""
}

// cexInput is classify's arguments.
type cexInput struct {
	status          string
	partner         bool
	due, start      *time.Time
	plReviewed      bool
	plPath          bool // reviewer_path == "pl"
	schoolOperating bool
	fundsPending    bool
	closureOwner    string
	today           time.Time
}

// cexClassify is stages.classify.
func cexClassify(in cexInput) cexStage {
	st := rules.CountryExecution.Stages
	has := func(set []string) bool { return slices.Contains(set, in.status) }
	pastDue := in.due != nil && in.due.Before(in.today)
	age := 0
	if pastDue {
		age = int(in.today.Sub(*in.due).Hours() / 24)
	}
	fieldOwner := "staff"
	if in.partner {
		fieldOwner = "partner"
	}
	if has(st.OffPlan) {
		return cexStage{stage: "cancelled", cancelled: true, timing: "cancelled"}
	}
	plApplicable := !in.partner && in.plPath
	if has(st.WaitingStart) {
		s := cexStage{stage: "scheduled", plApplicable: plApplicable, timing: "upcoming", age: age}
		if pastDue {
			s.overdue, s.timing = "execution", "not_started"
			switch {
			case !in.schoolOperating:
				s.owner = "external"
			case in.fundsPending && !in.partner:
				s.owner = "finance"
			default:
				s.owner = fieldOwner
			}
		}
		return s
	}
	timing := "unknown"
	if in.start != nil && in.due != nil {
		timing = "late"
		if !in.start.After(*in.due) {
			timing = "on_time"
		}
	}
	when := func(label, owner string) (string, string) {
		if pastDue {
			return label, owner
		}
		return "", ""
	}
	switch {
	case has(st.InField):
		od, ow := when("evidence", fieldOwner)
		return cexStage{stage: "in_field", started: true, plApplicable: plApplicable, overdue: od, owner: ow, timing: timing, age: age}
	case has(st.Returned):
		od, ow := when("correction", fieldOwner)
		return cexStage{stage: "returned", started: true, plApplicable: plApplicable, returned: true, overdue: od, owner: ow,
			timing: timing, age: age}
	case has(st.AtPL):
		od, ow := when("pl_review", "pl")
		return cexStage{stage: "pl_review", started: true, executed: true, plApplicable: true, overdue: od, owner: ow,
			timing: timing, age: age}
	}
	// Past the Lead, the PL stage applied only if the Lead reviewed the work.
	reviewed := plApplicable && in.plReviewed
	if has(st.AtIA) {
		od, ow := when("ia_review", "ia")
		return cexStage{stage: "ia_review", started: true, executed: true, plApplicable: reviewed, reviewed: reviewed,
			overdue: od, owner: ow, timing: timing, age: age}
	}
	if has(st.Closed) {
		return cexStage{stage: "closed", started: true, executed: true, plApplicable: reviewed, reviewed: reviewed,
			verified: true, closed: true, timing: timing, age: age}
	}
	owner := ""
	if pastDue {
		owner = in.closureOwner
		if owner == "" {
			owner = "staff"
		}
	}
	return cexStage{stage: "verified", started: true, executed: true, plApplicable: reviewed, reviewed: reviewed, verified: true,
		owner: owner, financeOpen: pastDue, timing: timing, age: age}
}
