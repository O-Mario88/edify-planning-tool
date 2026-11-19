package budgetpage

import (
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pydecimal"
	"sort"
	"strconv"
	"strings"
	"time"
)

// period is one of _calendar_periods' four horizons around a date.
type period struct {
	key, label, title string
	start, end        time.Time
}

func date(y int, m time.Month, d int) time.Time { return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }

// operationalFY is get_operational_fy(date).
func operationalFY(d time.Time) int {
	if d.Month() >= time.October {
		return d.Year() + 1
	}
	return d.Year()
}

func quarterOf(m time.Month) (string, time.Month) {
	switch {
	case m >= time.October:
		return "Q1", time.October
	case m <= time.March:
		return "Q2", time.January
	case m <= time.June:
		return "Q3", time.April
	default:
		return "Q4", time.July
	}
}

// periods is _calendar_periods(fy, anchor).
func periods(fy int, anchor time.Time) map[string]period {
	weekStart := anchor.AddDate(0, 0, -((int(anchor.Weekday()) + 6) % 7))
	weekEnd := weekStart.AddDate(0, 0, 6)
	monthStart := date(anchor.Year(), anchor.Month(), 1)
	monthEnd := monthStart.AddDate(0, 1, -1)
	quarter, startMonth := quarterOf(anchor.Month())
	qYear := fy
	if quarter == "Q1" {
		qYear = fy - 1
	}
	qStart := date(qYear, startMonth, 1)
	qEnd := qStart.AddDate(0, 3, -1)
	fyStart := date(fy-1, time.October, 1)
	fyEnd := date(fy, time.September, 30)
	y := strconv.Itoa(fy)
	return map[string]period{
		"week": {key: "week", label: "Week", start: weekStart, end: weekEnd,
			title: "Week of " + weekStart.Format("02 Jan") + " – " + weekEnd.Format("02 Jan 2006")},
		"month": {key: "month", label: "Month", start: monthStart, end: monthEnd, title: anchor.Format("January 2006")},
		"quarter": {key: "quarter", label: "Quarter", start: qStart, end: qEnd,
			title: quarter + " FY " + y + " · " + qStart.Format("02 Jan") + " – " + qEnd.Format("02 Jan 2006")},
		"fy": {key: "fy", label: "Fiscal Year", start: fyStart, end: fyEnd,
			title: "FY " + y + " · " + fyStart.Format("02 Jan 2006") + " – " + fyEnd.Format("02 Jan 2006")},
	}
}

// wholeMonths is planned_period_q's months: the calendar months (by number)
// wholly inside [start, end], which a line dated only by its month joins.
func wholeMonths(start, end time.Time) []int {
	out := []int{}
	for cursor := date(start.Year(), start.Month(), 1); !cursor.After(end); cursor = cursor.AddDate(0, 1, 0) {
		last := cursor.AddDate(0, 1, -1)
		if !start.After(cursor) && !last.After(end) {
			out = append(out, int(cursor.Month()))
		}
	}
	return out
}

// line is one selected cost line with what the ledger reads of its activity.
type line struct {
	activityID, responsibleUser, label, settingKey, lineItemType string
	amount, unitCost                                             int64
	quantity                                                     int64
	plannedDate                                                  *time.Time
	partnerID                                                    *string

	activityType, programmeType, deliveryType string
	teachers, leaders, others, expected       int64
	batchID                                   string
}

func (l line) tableKind() string {
	switch {
	case l.programmeType == "admin":
		return "admin"
	case in(rules.MeetingTypes, l.activityType):
		return "meeting"
	case in(rules.TrainingTypes, l.activityType):
		return "training"
	}
	return "standard"
}

func (l line) groupLabel() string {
	if l.programmeType != "" {
		return label(rules.ProgrammeActivityTypes, l.programmeType)
	}
	return label(rules.ActivityTypes, l.activityType)
}

type row struct {
	item                                    string
	rate                                    int64
	dates                                   map[string]bool
	people                                  map[string]int64
	activityIDs                             map[string]bool
	staffTotal, vendorTotal, total, ordinal int64
	// quantity is a country admin plan row's summed quantity (its "days"
	// when not zero), nil for an activity's row.
	quantity *pydecimal.Decimal
}

type group struct {
	label, kind string
	// isAdmin is the country admin plan's group.
	isAdmin                        bool
	rows                           []*row
	byKey                          map[string]*row
	activityIDs                    map[string]bool
	total, staffTotal, vendorTotal int64
}

// groups is budget_groups(selected_lines) for the plan's own lines (no
// country admin plan): one group an activity label, one row an item and
// the rate it was priced at, both by total, largest first.
func groups(lines []line, dayRates map[string]map[string]int64) []*group {
	participants := map[string]int64{}
	for _, l := range lines {
		attended := l.teachers + l.leaders + l.others
		switch {
		case attended != 0:
			participants[l.activityID] = attended
		case l.expected != 0:
			participants[l.activityID] = l.expected
		case (l.tableKind() == "training" || l.tableKind() == "meeting") &&
			(in(rules.ParticipantLineTypes, l.lineItemType) || in(rules.ParticipantSettingKeys, l.settingKey)):
			participants[l.activityID] = max(participants[l.activityID], l.quantity)
		}
	}
	byLabel := map[string]*group{}
	order := []*group{}
	for _, l := range lines {
		name := l.groupLabel()
		g, ok := byLabel[name]
		if !ok {
			g = &group{label: name, kind: l.tableKind(), byKey: map[string]*row{}, activityIDs: map[string]bool{}}
			byLabel[name] = g
			order = append(order, g)
		}
		item := l.label
		if item == "" {
			item = pyTitle(strings.ReplaceAll(l.settingKey, "_", " "))
		}
		if l.settingKey == "partner_training_lump_sum" {
			item = "Facilitation fee"
		}
		rate := l.unitCost
		if in(rules.DayRateKeys, l.settingKey) && l.batchID != "" {
			// dayRates holds only the rates the day's snapshot sets (a
			// truthy value), as int() reads them.
			if v, ok := dayRates[l.batchID][l.settingKey]; ok {
				rate = v
			}
		}
		key := item + "\x00" + strconv.FormatInt(rate, 10)
		r, ok := g.byKey[key]
		if !ok {
			r = &row{item: item, rate: rate, dates: map[string]bool{}, people: map[string]int64{}, activityIDs: map[string]bool{}}
			g.byKey[key] = r
			g.rows = append(g.rows, r)
		}
		day := "none"
		if l.plannedDate != nil {
			day = l.plannedDate.Format(time.DateOnly)
		}
		r.dates[day] = true
		if _, seen := r.people[l.activityID]; !seen {
			count, ok := participants[l.activityID]
			if !ok {
				count = 1
			}
			r.people[l.activityID] = count
		}
		r.activityIDs[l.activityID] = true
		if l.deliveryType == "partner" || l.partnerID != nil {
			r.vendorTotal += l.amount
			g.vendorTotal += l.amount
		} else {
			r.staffTotal += l.amount
			g.staffTotal += l.amount
		}
		r.total += l.amount
		g.total += l.amount
		g.activityIDs[l.activityID] = true
	}
	for _, g := range order {
		sort.SliceStable(g.rows, func(i, j int) bool {
			a, b := g.rows[i], g.rows[j]
			if a.total != b.total {
				return a.total > b.total
			}
			if a.item != b.item {
				return a.item < b.item
			}
			return a.rate < b.rate
		})
	}
	sort.SliceStable(order, func(i, j int) bool {
		if order[i].total != order[j].total {
			return order[i].total > order[j].total
		}
		return order[i].label < order[j].label
	})
	return order
}

// member is one person's line of the team cost summary.
type member struct {
	name       string
	activities int
	total      int64
}

// teamSummary is the Program Lead's team cost summary: each owner's
// activities and total, largest first.
func teamSummary(lines []line, names map[string]string) []member {
	byOwner := map[string]*struct {
		name string
		ids  map[string]bool
		sum  int64
	}{}
	owners := []string{}
	for _, l := range lines {
		owner := l.responsibleUser
		if owner == "" {
			owner = "unassigned"
		}
		s, ok := byOwner[owner]
		if !ok {
			name, known := names[owner]
			if !known {
				name = "Unassigned work"
			}
			s = &struct {
				name string
				ids  map[string]bool
				sum  int64
			}{name: name, ids: map[string]bool{}}
			byOwner[owner] = s
			owners = append(owners, owner)
		}
		s.ids[l.activityID] = true
		s.sum += l.amount
	}
	out := make([]member, 0, len(owners))
	for _, owner := range owners {
		s := byOwner[owner]
		out = append(out, member{name: s.name, activities: len(s.ids), total: s.sum})
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].total != out[j].total {
			return out[i].total > out[j].total
		}
		return out[i].name < out[j].name
	})
	return out
}
