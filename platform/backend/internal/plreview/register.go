package plreview

import (
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// row is a completion as the register writes it.
type row struct {
	ID, Officer, Profile                                  string
	Activity, Code, Where, Date, Intervention, Attendance string
	Salesforce                                            string
	Waited                                                int
}

// option is one officer the filter offers.
type option struct{ Value, Label string }

func plural(n int, word string) string {
	if n == 1 {
		return strconv.Itoa(n) + " " + word
	}
	return strconv.Itoa(n) + " " + word + "s"
}

// attendance is _attendance_label: who the session reached.
func attendance(c completion) string {
	parts := []string{}
	if c.Teachers != 0 {
		parts = append(parts, strconv.Itoa(c.Teachers)+" teachers")
	}
	if c.Leaders != 0 {
		parts = append(parts, strconv.Itoa(c.Leaders)+" leaders")
	}
	if c.Others != 0 {
		parts = append(parts, strconv.Itoa(c.Others)+" others")
	}
	if c.AttendedSchools > 0 {
		parts = append(parts, plural(c.AttendedSchools, "school"))
	}
	return strings.Join(parts, " · ")
}

func orDash(t string) string {
	if t == "" {
		return "—"
	}
	return closedschools.Collapse(t)
}

func day(t time.Time) time.Time { return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC) }

// register is review_register: each completion's row, longest waiting first
// (then by officer), and the officers present, by name.
func register(list []completion, names, profileOf map[string]string, today time.Time) ([]row, []option) {
	officer := func(owner string) string {
		if n := names[owner]; n != "" {
			return n
		}
		return "Unnamed officer"
	}
	profile := func(owner string) string {
		if p, ok := profileOf[owner]; ok {
			return p
		}
		return owner
	}
	rows := make([]row, 0, len(list))
	seen := map[option]bool{}
	options := []option{}
	for _, c := range list {
		if c.Owner != "" {
			if o := (option{profile(c.Owner), officer(c.Owner)}); !seen[o] {
				seen[o] = true
				options = append(options, o)
			}
		}
		kind := c.Name
		if kind == "" {
			kind = c.Type
			if l, ok := rules.ActivityTypes[c.Type]; ok {
				kind = l
			}
		}
		where := c.Venue
		switch {
		case c.School != nil:
			where = *c.School
		case c.Cluster != nil:
			where = *c.Cluster
		}
		where = orDash(where)
		if c.School == nil && c.Cluster != nil {
			where += " (cluster)"
		}
		code := "—"
		if c.School != nil && c.SchoolCode != nil && *c.SchoolCode != "" {
			code = closedschools.Collapse(*c.SchoolCode)
		}
		var when *time.Time
		switch {
		case c.Actual != nil:
			when = c.Actual
		case c.Planned != nil:
			when = c.Planned
		case c.Scheduled != nil:
			local := c.Scheduled.In(zone)
			when = &local
		}
		date := "—"
		if when != nil {
			date = when.Format("2 Jan 2006")
		}
		intervention := "—"
		if c.Intervention != "" {
			intervention = c.Intervention
			if a, ok := rules.InterventionAbbreviations[c.Intervention]; ok {
				intervention = a
			}
		}
		salesforce := "Not entered"
		if c.SalesforceID != "" {
			salesforce = closedschools.Collapse(c.SalesforceID)
		}
		waited := max(int(today.Sub(day(c.Since.In(zone))).Hours()/24), 0)
		rows = append(rows, row{ID: c.ID, Officer: officer(c.Owner), Profile: profile(c.Owner),
			Activity: orDash(kind), Code: code, Where: where, Date: date, Intervention: intervention,
			Attendance: orDash(attendance(c)), Salesforce: salesforce, Waited: waited})
	}
	slices.SortStableFunc(rows, func(a, b row) int {
		if a.Waited != b.Waited {
			return b.Waited - a.Waited
		}
		return strings.Compare(strings.ToLower(a.Officer), strings.ToLower(b.Officer))
	})
	slices.SortStableFunc(options, func(a, b option) int {
		return strings.Compare(strings.ToLower(a.Label), strings.ToLower(b.Label))
	})
	return rows, options
}

// page is pages/my_plan/pl_queue.html as the feed reads it: the register's
// heading, the officer filter when there is a choice, and the table a page
// at a time.
func page(rows []row, options []option, chosen string, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Programme implementation", Title: "Completion Reviews",
		Description: "Your officers' completed work waiting on your decision: Verified, or Return with the reason — for example, participants not entered in Salesforce. The longest waiting comes first."}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Waiting on you"}}}}
	if len(options) > 1 || chosen != "" {
		opts := []*screensv1.PageFilterOption{{Value: "", Label: "Every officer"}}
		value := ""
		for _, o := range options {
			opts = append(opts, &screensv1.PageFilterOption{Value: o.Value, Label: o.Label})
			if o.Value == chosen {
				value = chosen
			}
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{
			{Name: "cceo", Value: value, Caption: "Officer", Options: opts}}}}})
	}
	t := &screensv1.PageTable{}
	for _, c := range []string{"Officer", "Activity", "School ID", "School or cluster", "Date", "Intervention", "Attendance", "Salesforce ID", "Days waiting", ""} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	number, pages := closedschools.PageOf(query.Get(pageParam), len(rows), rules.PageSize)
	for _, r := range rows[min((number-1)*rules.PageSize, len(rows)):min(number*rules.PageSize, len(rows))] {
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: closedschools.Collapse(r.Officer)}, {Text: r.Activity}, {Text: r.Code}, {Text: r.Where}, {Text: r.Date},
			{Text: r.Intervention}, {Text: r.Attendance}, {Text: r.Salesforce}, {Text: strconv.Itoa(r.Waited)},
			{Actions: []*screensv1.PageAction{
				{Key: "menu", Label: "Verify", Enabled: true, Href: Path + "/" + r.ID + "/drawer", Drawer: true},
				{Key: "menu", Label: "Return", Enabled: true, Href: Path + "/" + r.ID + "/return-drawer", Drawer: true},
			}},
		}})
	}
	if len(rows) == 0 {
		t.EmptyMessage = "Nothing is waiting on you"
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "Nothing is waiting on you When an officer you supervise submits completed work, it appears here for your confirmation."}}}}
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel(pageParam, number, pages, len(rows), rules.PageSize, query, nil))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}
