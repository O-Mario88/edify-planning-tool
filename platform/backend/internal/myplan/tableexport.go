package myplan

import (
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// TableExportRules are what My Plan's export reads (export_my_plan_rules
// table_export: apps.core.export_kinds and apps.my_plan.table_export).
type TableExportRules struct {
	KindTypes              map[string][]string `json:"kind_types"`
	OnlineKind             string              `json:"online_kind"`
	OnlineMode             string              `json:"online_mode"`
	CompletedWorkStatuses  []string            `json:"completed_work_statuses"`
	KindTables             map[string][]string `json:"kind_tables"`
	AllSheets              []string            `json:"all_sheets"`
	Titles                 map[string]string   `json:"titles"`
	Headers                map[string][]string `json:"headers"`
	ShortDays              []string            `json:"short_days"`
	MeetingSchoolsTitle    string              `json:"meeting_schools_title"`
	ProgrammeTitle         string              `json:"programme_title"`
	SchoolTypeLabels       map[string]string   `json:"school_type_labels"`
	OperatingStatuses      []string            `json:"operating_statuses"`
	GroupTrainingCostTypes []string            `json:"group_training_cost_types"`
	ClusterMealsRateKey    string              `json:"cluster_meals_rate_key"`
	BudgetSheet            string              `json:"budget_sheet"`
	DayFormat              string              `json:"day_format"`
	ShortDayFormat         string              `json:"short_day_format"`
	MoneyFormat            string              `json:"money_format"`
}

// column is one of table_export's (heading, cell): the value the template
// writes in it, a date as a date and an amount as a number.
type column func(r *planRow) workbook.Cell

func txt(s string) workbook.Cell { return workbook.Text(s) }

// or is {{ value|default:fallback }}.
func or(s, fallback string) workbook.Cell { return txt(orDefault(s, fallback)) }

// plannedCell is _planned: the day planned before completion, else the
// planned date, else unset.
func plannedCell(r *planRow, unset string) workbook.Cell {
	if r.plannedBefore != nil {
		return workbook.Date(*r.plannedBefore)
	}
	if d := date(r.a.plannedDate); d != nil {
		return workbook.Date(*d)
	}
	return txt(unset)
}

func completedCell(r *planRow) workbook.Cell {
	if r.completedOn != nil {
		return workbook.Date(*r.completedOn)
	}
	return txt(dash)
}

// costCell is _cost: the estimate (none reads 0), with an in-school pair's
// note as words when note is asked.
func costCell(r *planRow, note bool) workbook.Cell {
	amount := int64(0)
	if r.budgetTotal != nil {
		amount = *r.budgetTotal
	}
	if note && r.costNote != "" {
		return txt(money(amount) + " " + r.costNote)
	}
	return workbook.Int(amount)
}

// headsCell is {{ row.expected_participants|default:"—" }}.
func headsCell(r *planRow) workbook.Cell {
	if r.expected == nil || *r.expected == 0 {
		return txt(dash)
	}
	return workbook.Int(int64(*r.expected))
}

func code(r *planRow) workbook.Cell { return or(r.schoolID.value, dash) }

// plainCode is {{ row.school_id }}: Django writes None as "None".
func plainCode(r *planRow) workbook.Cell {
	if r.schoolID.null || (r.schoolID.value == "" && !r.a.hasSchool) {
		return txt("None")
	}
	return txt(r.schoolID.value)
}

func executor(r *planRow) workbook.Cell { return or(r.owner, "Staff") }
func focus(r *planRow) workbook.Cell    { return txt(intervention(r.row)) }
func plannedAt(r *planRow) workbook.Cell {
	return plannedCell(r, "Unscheduled")
}

// budgetTail is _BUDGET: Budget status, Verification, Salesforce ID, Status.
var budgetTail = []column{
	func(r *planRow) workbook.Cell { return or(r.budgetStatus, dash) },
	func(r *planRow) workbook.Cell { return or(r.verification, dash) },
	func(r *planRow) workbook.Cell { return txt(salesforce(r.row)) },
	func(r *planRow) workbook.Cell { return or(r.statusLabel, dash) },
}

func withTail(cols ...column) []column { return append(cols, budgetTail...) }

// realSchool is _real_school: the school's name unless it is none or
// "Unknown School".
func realSchool(r *planRow) string {
	if r.schoolName == "Unknown School" {
		return ""
	}
	return r.schoolName
}

// schoolOrCluster is the Trainings table's School / Cluster cell.
func schoolOrCluster(r *planRow) workbook.Cell {
	first := func(vs ...string) string {
		for _, v := range vs {
			if v != "" {
				return v
			}
		}
		return ""
	}
	switch {
	case r.placeURL != "":
		if v := first(realSchool(r), r.clusterName, r.schoolID.value); v != "" {
			return txt(v)
		}
		return workbook.Empty()
	case r.schoolID.truthy():
		return txt(first(realSchool(r), r.schoolID.value))
	}
	return txt(first(realSchool(r), r.clusterName, dash))
}

// plannedFromCell is the Trainings table's Cluster Planned From cell (a row
// carries no delivery_type, so only its type says "in school").
func plannedFromCell(r *planRow) workbook.Cell {
	switch {
	case r.isClusterInvited:
		return txt(joined(orDash(r.clusterName), "Invited"))
	case strings.Contains(r.a.activityType, "in_school"):
		return txt("School Visit")
	}
	return txt(orDash(r.clusterName))
}

// meetingTopic is _meeting_topic: the meeting's kind, the course it
// delivers and its purpose when that says more than its type.
func meetingTopic(r *planRow) string {
	kind := str(r.x.meetingKind)
	if kind == "" {
		return orDefault(r.purpose, "Cluster Meeting")
	}
	text, ok := rules.Tables.MeetingKindLabels[kind]
	if !ok {
		text = kind
	}
	if r.x.meetingTraining != "" {
		text += ": " + r.x.meetingTraining
	}
	if r.purpose != "" && r.purpose != str(r.activityTypeLabel) {
		text += " · " + r.purpose
	}
	return text
}

var trainingColumns = withTail(code, schoolOrCluster,
	func(r *planRow) workbook.Cell { return or(r.districtShown, dash) },
	func(r *planRow) workbook.Cell { return or(r.districtType, dash) },
	plannedFromCell, executor,
	func(r *planRow) workbook.Cell { return or(r.trainingName, "Not yet named") },
	plannedAt, completedCell, focus, headsCell,
	func(r *planRow) workbook.Cell { return or(r.trainingMode, dash) },
	func(r *planRow) workbook.Cell { return costCell(r, true) },
)

// exportColumns are each table's columns (table_export.TABLES), by key.
var exportColumns = map[string][]column{
	"school_visits": withTail(code,
		func(r *planRow) workbook.Cell { return or(r.schoolName, dash) },
		func(r *planRow) workbook.Cell { return or(r.districtShown, dash) },
		func(r *planRow) workbook.Cell { return or(r.districtType, dash) },
		func(r *planRow) workbook.Cell { return or(str(r.activityTypeLabel), "School Visit") },
		plannedAt, completedCell, executor,
		func(r *planRow) workbook.Cell { return or(r.purpose, dash) },
		focus,
		func(r *planRow) workbook.Cell { return costCell(r, true) },
	),
	"cluster_trainings": trainingColumns,
	"meeting_schools":   trainingColumns,
	"group_trainings": withTail(
		func(r *planRow) workbook.Cell { return txt(r.clusterName) },
		func(r *planRow) workbook.Cell { return txt(r.clusterDistrict()) },
		func(r *planRow) workbook.Cell { return or(r.districtType, dash) },
		plannedAt, completedCell, executor,
		func(r *planRow) workbook.Cell {
			for _, v := range []string{r.trainingName, str(r.x.activityName), r.purpose} {
				if v != "" {
					return txt(v)
				}
			}
			return txt("Group Training")
		},
		focus, headsCell,
		func(r *planRow) workbook.Cell { return costCell(r, false) },
	),
	"cluster_meetings": withTail(
		func(r *planRow) workbook.Cell { return txt(r.clusterName) },
		func(r *planRow) workbook.Cell { return txt(r.clusterDistrict()) },
		func(r *planRow) workbook.Cell { return or(r.districtType, dash) },
		plannedAt, completedCell, executor,
		func(r *planRow) workbook.Cell { return txt(meetingTopic(r)) },
		focus, headsCell,
		func(r *planRow) workbook.Cell { return costCell(r, false) },
	),
	"core_school_visits": withTail(code,
		func(r *planRow) workbook.Cell { return or(r.schoolName, dash) },
		func(r *planRow) workbook.Cell { return or(r.schoolDistrict, dash) },
		func(r *planRow) workbook.Cell { return or(r.districtType, dash) },
		func(r *planRow) workbook.Cell { return txt(coreActivity(r.row)) },
		plannedAt, completedCell, executor,
		func(r *planRow) workbook.Cell { return or(r.purpose, dash) },
		focus,
		func(r *planRow) workbook.Cell { return costCell(r, true) },
	),
	"core_school_trainings": withTail(code,
		func(r *planRow) workbook.Cell { return txt(joined(orDash(r.schoolName), str(r.activityTypeLabel))) },
		func(r *planRow) workbook.Cell { return txt(joined(orDash(r.trainingNumber), r.coreProgress)) },
		func(r *planRow) workbook.Cell { return or(r.trainingName, "Not yet named") },
		func(r *planRow) workbook.Cell {
			if r.schoolDistrict != "" && r.schoolDistrict != dash {
				return txt(r.schoolDistrict)
			}
			return txt(dash)
		},
		func(r *planRow) workbook.Cell { return or(r.districtType, dash) },
		plannedAt, completedCell,
		func(r *planRow) workbook.Cell { return txt(r.focus) },
		headsCell,
		func(r *planRow) workbook.Cell { return txt(r.owner) },
	),
	"programme_school_work": {
		plainCode,
		func(r *planRow) workbook.Cell { return txt(r.schoolName) },
		func(r *planRow) workbook.Cell { return or(r.districtShown, dash) },
		func(r *planRow) workbook.Cell { return or(r.districtType, dash) },
		func(r *planRow) workbook.Cell { return txt(str(r.activityTypeLabel)) },
		func(r *planRow) workbook.Cell { return plannedCell(r, "Awaiting schedule") },
		completedCell,
		func(r *planRow) workbook.Cell { return txt(salesforce(r.row)) },
		func(r *planRow) workbook.Cell { return txt(r.statusLabel) },
	},
	"programme_activities": withTail(code,
		func(r *planRow) workbook.Cell {
			if r.schoolID.truthy() {
				return or(r.schoolName, dash)
			}
			// venue_name: no row carries one.
			return txt(dash)
		},
		func(r *planRow) workbook.Cell { return or(r.districtShown, dash) },
		func(r *planRow) workbook.Cell { return or(r.districtType, dash) },
		func(r *planRow) workbook.Cell {
			return or(orDefault(str(r.activityTypeLabel), r.purpose), dash)
		},
		func(r *planRow) workbook.Cell {
			if d := date(r.a.plannedDate); d != nil {
				return workbook.Date(*d)
			}
			return txt("Unscheduled")
		},
	),
}

// framed is table_export._framed: a sheet of these headings and rows, a
// date column formatted as the page writes a day and the Cost as money.
func framed(title string, headers []string, rows [][]workbook.Cell, shortDays bool) workbook.Sheet {
	t := rules.TableExport
	day := t.DayFormat
	if shortDays {
		day = t.ShortDayFormat
	}
	formats := map[int]string{}
	for i, h := range headers {
		switch {
		case strings.HasSuffix(strings.ToLower(h), "date"):
			formats[i+1] = day
		case h == "Cost":
			formats[i+1] = t.MoneyFormat
		}
	}
	return workbook.Sheet{Title: title, Headers: headers, Rows: rows, NumberFormats: formats}
}

// sheetOf writes rows in key's columns.
func sheetOf(title, key string, rows []*planRow, shortDays bool) workbook.Sheet {
	cols := exportColumns[key]
	out := make([][]workbook.Cell, 0, len(rows))
	for _, r := range rows {
		cells := make([]workbook.Cell, len(cols))
		for i, c := range cols {
			cells[i] = c(r)
		}
		out = append(out, cells)
	}
	return framed(title, rules.TableExport.Headers[key], out, shortDays)
}
