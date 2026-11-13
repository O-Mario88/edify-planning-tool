package myplan

import (
	"context"
	"strconv"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// TrainingSummaryRow is one row of the reader's own My Training Summary
// (training_ceilings.own_summary), as internal/trainingsummary reads it.
type TrainingSummaryRow struct {
	StaffID, TrainingID, TrainingName string
	// Ceiling is nil when none is set.
	Ceiling                               *int
	InSchool, Partner, PartnerScheduled   int
	Group, Total, AwaitingPartner, Excess int
	// Balance is the places left under the ceiling, nil with none.
	Balance *int
	// Utilization is SummaryRow.utilization, nil with no ceiling.
	Utilization *int
	// State, Flag and FlagTone are SummaryRow.state, .flag and .flag_tone.
	State, Flag, FlagTone string
}

// TrainingSummaryReader reads a person's own summary rows: their staff
// profile, their user id and name, the year (trainingsummary.OwnSummary;
// it lives there, which already reads this package).
type TrainingSummaryReader func(ctx context.Context, q schooldirectory.Querier, staffProfileID, userID, name, fy string, now time.Time) ([]TrainingSummaryRow, error)

// WithTrainingSummary gives the service the reader of My Training Summary.
// Without one, a reader with a training of their own is passed to the
// existing application.
func (s *Service) WithTrainingSummary(read TrainingSummaryReader) *Service {
	s.summary = read
	return s
}

// summaryNote is the line under the summary's table (my_summary.html).
const summaryNote = "A school counts from the day it is committed: planned by you, assigned to a partner — before the partner has scheduled it — or on a group training. Schools covered counts each school once, so it can be less than the columns added up. Awaiting partner are the assigned schools the partner has not dated yet. Your Programme Lead sets the ceiling; with none set you schedule without a limit."

// summaryBlocks are partials/trainings/my_summary.html as the feed reads
// it: the heading (its line of figures is a definition list, which the
// feed does not read), the table and the note.
func summaryBlocks(rows []TrainingSummaryRow, fy string) []*screensv1.PageBlock {
	figure := func(r TrainingSummaryRow, value int, name string) *screensv1.PageCell {
		if value == 0 {
			return &screensv1.PageCell{Text: "0"}
		}
		return &screensv1.PageCell{Text: comma(value), Href: behind(r, fy, name)}
	}
	var out []*screensv1.PageRow
	for _, r := range rows {
		ceiling := &screensv1.PageCell{Text: "Not set"}
		if r.Ceiling != nil {
			ceiling.Text = comma(*r.Ceiling)
		}
		awaiting := &screensv1.PageCell{Text: "0"}
		if r.AwaitingPartner != 0 {
			awaiting = &screensv1.PageCell{Text: comma(r.AwaitingPartner), Href: behind(r, fy, "awaiting"), Tone: "warning"}
		}
		covered := &screensv1.PageCell{Text: "0"}
		if r.Total != 0 {
			covered = &screensv1.PageCell{Text: comma(r.Total), Href: behind(r, fy, "covered"), Strong: true}
		}
		remaining := &screensv1.PageCell{Text: "View", Href: behind(r, fy, "remaining")}
		if r.Balance != nil {
			remaining.Text, remaining.Strong = comma(*r.Balance), true
		}
		excess := &screensv1.PageCell{Text: "0"}
		if r.Excess != 0 {
			excess = &screensv1.PageCell{Text: comma(r.Excess), Tone: "danger"}
		}
		used := &screensv1.PageCell{Text: dash}
		if r.Utilization != nil {
			used.Text = strconv.Itoa(*r.Utilization) + "%"
		}
		out = append(out, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: r.TrainingName, Strong: true}, ceiling,
			figure(r, r.InSchool, "staff"), figure(r, r.Partner, "partner"), awaiting, figure(r, r.Group, "group"),
			covered, remaining, excess, used, {Text: r.Flag, Tone: r.FlagTone},
		}})
	}
	cols := columns("Training", "Ceiling", "Staff Planned", "Partner Assigned", "Awaiting Partner", "Group Scheduled",
		"Schools Covered", "Remaining", "Excess", "Utilization", "Status")
	for i, c := range cols {
		c.Numeric = i > 0 && i < len(cols)-1
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "My training summary FY " + fy}}},
		{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Columns: cols, Rows: out}}},
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: summaryNote}}}}}},
	}
}

// behind is the address of the schools behind one figure.
func behind(r TrainingSummaryRow, fy, figure string) string {
	return "/training-summary/schools?staff=" + r.StaffID + "&training=" + r.TrainingID + "&fy=" + fy + "&figure=" + figure
}
