package myplan

import (
	"strconv"
	"strings"
	"time"
)

// The cells table_export writes and table_export.shown formats: a date as
// "5 Oct 2026", a cost as "UGX 40,000", the same fallbacks as the page.
const dash = "—"

func orDash(s string) string {
	if s == "" {
		return dash
	}
	return s
}

func shownDay(t *time.Time) string {
	return strconv.Itoa(t.Day()) + " " + t.Format("Jan 2006")
}

// planned is _planned: the day planned before completion, else the planned
// date, else "Unscheduled".
func planned(r *row) string {
	if r.plannedBefore != nil {
		return shownDay(r.plannedBefore)
	}
	if d := date(r.a.plannedDate); d != nil {
		return shownDay(d)
	}
	return "Unscheduled"
}

func completed(r *row) string {
	if r.completedOn != nil {
		return shownDay(r.completedOn)
	}
	return dash
}

func intervention(r *row) string { return orDash(r.focus) }

// money is f"UGX {value:,}".
func money(n int64) string {
	s := strconv.FormatInt(n, 10)
	neg := strings.HasPrefix(s, "-")
	s = strings.TrimPrefix(s, "-")
	var b strings.Builder
	for i, c := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteRune(c)
	}
	if neg {
		return "UGX -" + b.String()
	}
	return "UGX " + b.String()
}

// cost is _cost: the estimate (none reads 0), with an in-school pair's note.
func cost(r *row, note bool) string {
	amount := int64(0)
	if r.budgetTotal != nil {
		amount = *r.budgetTotal
	}
	if note && r.costNote != "" {
		return money(amount) + " " + r.costNote
	}
	return money(amount)
}

func salesforce(r *row) string {
	if r.salesforceID == "" {
		return "Not in SF"
	}
	return r.salesforceID
}

func owner(r *row) string {
	if r.owner == "" {
		return "Staff"
	}
	return r.owner
}

func joined(parts ...string) string {
	var kept []string
	for _, p := range parts {
		if p != "" {
			kept = append(kept, p)
		}
	}
	return strings.Join(kept, " ")
}

func coreActivity(r *row) string {
	label := "Core Visit"
	if r.activityTypeLabel != nil && *r.activityTypeLabel != "" {
		label = *r.activityTypeLabel
	}
	if r.visitNumber == "" {
		return label
	}
	return joined(label, r.visitNumber, r.coreProgress)
}

func participants(r *row) string {
	if r.expected == nil || *r.expected == 0 {
		return dash
	}
	return strconv.Itoa(*r.expected)
}

// visitCells are CORE_SCHOOL_VISITS.columns.
func visitCells(r *row) []string {
	return []string{
		orDash(r.schoolID.value), orDash(r.schoolName), orDash(r.schoolDistrict), orDash(r.districtType),
		coreActivity(r), planned(r), completed(r), owner(r), orDash(r.purpose), intervention(r),
		cost(r, true), orDash(r.budgetStatus), orDash(r.verification), salesforce(r), orDash(r.statusLabel),
	}
}

func deliveryType(r *row) string {
	switch {
	case r.trainingMode == rules.Rows.OnlineTrainingLabel:
		return "Online"
	case in(rules.Rows.ClusterMeetingTypes, r.a.activityType):
		return "Cluster Meeting"
	case r.isClusterInvited || (r.clusterID != "" && !r.schoolID.truthy()):
		return "Group Training"
	}
	return "In-school"
}

func plannedFrom(r *row) string {
	if r.isClusterInvited {
		return orDash(r.clusterName)
	}
	return "In-school Visit"
}

func trainingName(r *row) string {
	if r.trainingName == "" {
		return "Not yet named"
	}
	return r.trainingName
}

// trainingCells are CORE_TRAINING_PLAN_COLUMNS.
func trainingCells(r *row) []string {
	return []string{
		orDash(r.schoolID.value), orDash(r.schoolName), plannedFrom(r), owner(r), trainingName(r), intervention(r),
		planned(r), completed(r), orDash(r.trainingNumber), participants(r), deliveryType(r), cost(r, false),
		salesforce(r), orDash(r.statusLabel),
	}
}
