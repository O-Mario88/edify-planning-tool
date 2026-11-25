package planningoversight

import (
	"math"
	"net/url"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/stafflogs"
)

// The four tables of _officer_panel_body.html with rows in them, the
// headline fold (oversight_service.summarize) and the tiles drawn from it
// (_kpi_items).

const detailDrawer = "/team-planning-oversight/detail?activity_id="

// fold is summarize over staff items.
type fold struct {
	total, atRisk, completed, due, costMissing, awaiting, unpaid int
	budget                                                       int64
}

func summarize(items []*item, today time.Time) fold {
	f := fold{}
	settled := rules.TeamPlan.Items.Risk.PaymentSettledStatuses
	for _, it := range items {
		f.total++
		f.budget += it.plannedCost
		if it.completed() {
			f.completed++
		}
		if it.a.costMissing {
			f.costMissing++
		}
		if it.plannedDate != nil && !it.plannedDate.After(today) {
			f.due++
		}
		if it.risky {
			f.atRisk++
		}
		if it.submittedToIA != nil && it.a.ia == "pending" {
			f.awaiting++
		}
		if it.a.ia == "confirmed" && !contains(settled, first(it.a.payment, "none")) {
			f.unpaid++
		}
	}
	return f
}

func contains(list []string, v string) bool {
	for _, x := range list {
		if x == v {
			return true
		}
	}
	return false
}

// inFamily is oversight_service.in_family.
func inFamily(items []*item, family string) []*item {
	for _, f := range rules.TeamPlan.Items.Families {
		if f.Key == family {
			out := []*item{}
			for _, it := range items {
				if contains(f.Types, it.activityType) {
					out = append(out, it)
				}
			}
			return out
		}
	}
	return items
}

// intcomma is the frontend filter: thousands separated.
func intcomma(n int64) string {
	s := strconv.FormatInt(n, 10)
	neg := strings.HasPrefix(s, "-")
	s = strings.TrimPrefix(s, "-")
	out := []byte{}
	for i := range len(s) {
		if i > 0 && (len(s)-i)%3 == 0 {
			out = append(out, ',')
		}
		out = append(out, s[i])
	}
	if neg {
		return "-" + string(out)
	}
	return string(out)
}

// percent is MetricValue.ratio's figure through format_value: one decimal,
// a whole one without its ".0".
func percent(n, d int) string {
	v := float64(n) / float64(d) * 100
	s := strconv.FormatFloat(v, 'f', 1, 64)
	if r, err := strconv.ParseFloat(s, 64); err == nil && r == math.Trunc(r) {
		s = strconv.FormatFloat(r, 'f', 0, 64)
	}
	return s + "%"
}

// kpiStrip is _kpi_items over the fold, through components/context_metrics.
func kpiStrip(f fold, labels []string, title string) *screensv1.PageBlock {
	z := rules.TeamPlan.ZeroKPIs
	tone := func(on bool, t string) string {
		if on {
			return t
		}
		return "neutral"
	}
	exec := [3]string{z[4].Value, z[4].Helper, "neutral"}
	if f.due > 0 {
		exec = [3]string{percent(f.completed, f.due), strconv.Itoa(f.completed) + " of " + strconv.Itoa(f.due) + " due", "neutral"}
	}
	tiles := [][3]string{
		{intcomma(int64(f.total)), strconv.Itoa(f.total) + " staff · 0 partner", "neutral"},
		{"0", z[1].Helper, "neutral"},
		{intcomma(int64(f.atRisk)), strconv.Itoa(f.costMissing) + " scheduled without a cost", tone(f.atRisk > 0, "danger")},
		{"UGX " + intcomma(f.budget), "From " + strconv.Itoa(f.total) + " scheduled", "neutral"},
		exec,
		{intcomma(int64(f.awaiting)), strconv.Itoa(f.unpaid) + " verified and unpaid", tone(f.awaiting > 0, "warning")},
	}
	figures := []schoolprofile.StripFigure{}
	for i, t := range tiles {
		figures = append(figures, schoolprofile.StripFigure{Label: labels[i], Value: t[0], Helper: t[1]})
	}
	block := schoolprofile.Strip(title, figures)
	for i, m := range block.GetStrip().GetMetrics() {
		if m.Helper != "" {
			m.Tone = tiles[i][2]
		}
	}
	return block
}

// dayText is |date:"j M Y".
func dayText(t *time.Time) string {
	if t == nil {
		return "—"
	}
	return strconv.Itoa(t.Day()) + " " + t.Month().String()[:3] + " " + strconv.Itoa(t.Year())
}

func cell(text, href string) *screensv1.PageCell { return &screensv1.PageCell{Text: text, Href: href} }

func orDash(s string) string {
	if s == "" {
		return "—"
	}
	return s
}

// plannedCell is the Planned Date cell: the day it was planned for before
// it moved, else its planned day.
func (it *item) plannedCell() *screensv1.PageCell {
	if it.plannedBefore != nil {
		return cell(dayText(it.plannedBefore), "")
	}
	return cell(dayText(it.plannedDate), "")
}

func (it *item) completedCell() *screensv1.PageCell { return cell(dayText(it.completedOn), "") }

func (it *item) executor(groupName string) *screensv1.PageCell {
	return cell(first(it.ownerName, groupName), "")
}

func (it *item) interventionCell() *screensv1.PageCell {
	return cell(orDash(stafflogs.StatusLabel(it.intervention)), "")
}

func (it *item) costCell() *screensv1.PageCell { return cell("UGX "+intcomma(it.plannedCost), "") }

func (it *item) salesforceCell() *screensv1.PageCell {
	return cell(first(it.salesforceID, rules.TeamPlan.Items.Words.NotInSF), "")
}

func (it *item) statusCell() *screensv1.PageCell {
	switch {
	case it.gap != "":
		return cell(it.gap, "")
	case it.finishedEarly:
		return cell(rules.TeamPlan.Items.Words.FinishedEarly, "")
	}
	return cell(stafflogs.StatusLabel(it.status), "")
}

func (it *item) actionsCell() *screensv1.PageCell {
	return &screensv1.PageCell{Actions: []*screensv1.PageAction{{
		Key: "button", Label: "View", Primary: true, Enabled: true, Href: detailDrawer + it.a.id, Drawer: true,
	}}}
}

func (it *item) participantsCell() *screensv1.PageCell {
	if it.participants == nil || *it.participants == 0 {
		return cell("—", "")
	}
	return cell(strconv.FormatInt(*it.participants, 10), "")
}

func districtCell(name, id string, r Reader) *screensv1.PageCell {
	switch {
	case name == "":
		return cell("—", "")
	case id == "" || !r.OpenDistrict:
		return cell(name, "")
	}
	return cell(name, "/districts/"+id)
}

func (it *item) schoolCell() *screensv1.PageCell {
	if it.schoolPK != "" {
		return cell(orDash(it.schoolName), "/schools/"+it.schoolPK)
	}
	return cell(orDash(it.schoolName), "")
}

func (it *item) activityCell(r Reader, fallback string) *screensv1.PageCell {
	if !r.OpenActivity {
		return cell(first(stafflogs.StatusLabel(it.activityType), fallback), "")
	}
	return cell(stafflogs.StatusLabel(it.activityType), "/activities/"+it.a.id)
}

// visitCells are tables 1 and 2's row (2 adds the District).
func (it *item) visitCells(groupName string, core bool, r Reader) []*screensv1.PageCell {
	cells := []*screensv1.PageCell{cell(first(it.schoolCode, it.schoolPK, "—"), ""), it.schoolCell()}
	fallback := "School Visit"
	if core {
		cells = append(cells, districtCell(it.districtName, it.districtID, r))
		fallback = "Core Visit"
	}
	return append(cells, it.activityCell(r, fallback), it.plannedCell(), it.completedCell(), it.executor(groupName),
		cell(orDash(it.purpose), ""), it.interventionCell(), it.costCell(), it.salesforceCell(), it.statusCell(), it.actionsCell())
}

func (it *item) meetingCells(groupName string, r Reader) []*screensv1.PageCell {
	name := cell(first(it.clusterName, it.contextLabel()), "")
	if it.clusterID != "" {
		name.Href = "/clusters/" + it.clusterID
	}
	return []*screensv1.PageCell{name, districtCell(it.districtName, it.districtID, r), it.plannedCell(), it.completedCell(),
		it.executor(groupName), cell(first(it.purpose, it.rationale, "Cluster Meeting"), ""), it.interventionCell(),
		it.participantsCell(), it.costCell(), it.salesforceCell(), it.statusCell(), it.actionsCell()}
}

func (it *item) trainingCells(groupName string, r Reader) []*screensv1.PageCell {
	code := "—"
	switch {
	case it.schoolCode != "" && it.schoolCode != "—":
		code = it.schoolCode
	case it.schoolPK != "":
		code = it.schoolPK
	}
	named := it.schoolName != "" && it.schoolName != "Unknown School"
	school := cell("—", "")
	switch {
	case it.schoolPK != "" && named:
		school = cell(it.schoolName, "/schools/"+it.schoolPK)
	case it.schoolPK != "" && it.clusterName != "":
		school = cell(it.clusterName, "/schools/"+it.schoolPK)
	case it.schoolPK != "":
		school = cell(first(it.schoolCode, it.schoolPK), "/schools/"+it.schoolPK)
	case named:
		school = cell(it.schoolName, "")
	case it.clusterName != "":
		school = cell(it.clusterName, "")
		if it.clusterID != "" && r.OpenCluster {
			school.Href = "/clusters/" + it.clusterID
		}
	}
	from := cell(it.plannedFrom, "")
	if it.plannedFrom != "School Visit" && it.clusterID != "" {
		from.Href = "/clusters/" + it.clusterID
	}
	if it.invited {
		from.Text += " Invited"
	}
	training := stafflogs.StatusLabel(it.training)
	if training == "" {
		training = stafflogs.StatusLabel(it.activityType)
	}
	return []*screensv1.PageCell{cell(code, ""), school, from, it.executor(groupName), cell(training, ""),
		it.plannedCell(), it.completedCell(), it.interventionCell(), it.participantsCell(),
		cell(first(it.delivery, "group"), ""), it.costCell(), it.salesforceCell(), it.statusCell(), it.actionsCell()}
}

// streamColumns are each table's headings, the right-aligned ones numeric.
var streamColumns = [4][]string{
	{"School ID", "School Name", "Activity", "Planned Date", "Completed Date", "Executor", "Purpose of Visit", "SSA Intervention", "#Cost", "Salesforce ID", "Status", "#Actions"},
	{"School ID", "School Name", "District", "Activity", "Planned Date", "Completed Date", "Executor", "Purpose of Visit", "SSA Intervention", "#Cost", "Salesforce ID", "Status", "#Actions"},
	{"Cluster Name", "District", "Planned Date", "Completed Date", "Executor", "Purpose (Meeting Topic)", "SSA Intervention", "Participants", "#Cost", "Salesforce ID", "Status", "#Actions"},
	{"School ID", "School Name", "Cluster Planned From", "Executor", "Training Name", "Planned Date", "Completed Date", "SSA Intervention", "Participants", "Delivery Type", "#Cost", "Salesforce ID", "Status", "#Actions"},
}

// streamBlocks are one table's blocks: its heading and empty line, or the
// table of its rows.
func streamBlocks(t int, rows []*item, groupName string, query url.Values, r Reader, pageParam string) []*screensv1.PageBlock {
	s := sections[t]
	if len(rows) == 0 {
		return []*screensv1.PageBlock{panel("", "", heading(s[0]), text("0"), text(s[1])), panel("", "", text(s[2]))}
	}
	cols := []*screensv1.PageColumn{}
	for _, c := range streamColumns[t] {
		cols = append(cols, &screensv1.PageColumn{Label: strings.TrimPrefix(c, "#"), Numeric: strings.HasPrefix(c, "#")})
	}
	param := pageParam + streamPageKeys[t]
	number, pages, start, end := pageOf(query, param, len(rows))
	out := []*screensv1.PageRow{}
	for _, it := range rows[start:end] {
		var cells []*screensv1.PageCell
		switch t {
		case clientVisits, coreVisits:
			cells = it.visitCells(groupName, t == coreVisits, r)
		case clusterMeetings:
			cells = it.meetingCells(groupName, r)
		default:
			cells = it.trainingCells(groupName, r)
		}
		out = append(out, &screensv1.PageRow{Cells: cells, Tone: it.rowState})
	}
	table := &screensv1.PageTable{Subtitle: s[1], Columns: cols, Rows: out}
	if pages > 1 {
		table.Pager = pager(number, pages, len(rows), end-start, query, param)
		// The feed takes the first line under the table for its note, and
		// with a pager that is the pager's own "Showing 1–50 of 100".
		table.Footnote = table.Pager.GetSummary()
	}
	return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: table}}}
}
