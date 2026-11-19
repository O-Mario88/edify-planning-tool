package iapages

import (
	"slices"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// UploadCenterPath is Upload SSA Scores (ssa_views.ssa_upload_center_view,
// pages/ssa/upload_center.html): the sheet's columns (one per intervention),
// the two notes and the file picker, for the roles that may upload official
// SSA. A role the page opens to without that permission is sent away by the
// existing page: handed on. Uploading stays the existing page's.
const UploadCenterPath = "/ssa/upload/"

// uploadColumns are the sheet's fixed columns before the scores.
var uploadColumns = [][3]string{
	{"School ID", "Must match a school in the directory", "SCH-0001"},
	{"Assessment Date", "Date of the SSA assessment (YYYY-MM-DD)", "2026-07-01"},
	{"SSA Year", `The operational FY this assessment belongs to. Use "last" for an imported baseline or "current" for this FY.`, "last / current / 2025 / 2026"},
}

func (s *Service) uploadCenter(p auth.Principal) (*screensv1.GetPageResponse, bool, error) {
	if !slices.Contains(rules.SSAUploadRoles, p.ActiveRole) {
		return nil, false, nil
	}
	row := func(name, description, example string) *screensv1.PageRow {
		return &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: name}, {Text: "Yes", Tone: "primary", Badge: true}, {Text: description}, {Text: example}}}
	}
	t := &screensv1.PageTable{}
	for _, c := range []string{"Column Header", "Required", "Description", "Example"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	for _, c := range uploadColumns {
		t.Rows = append(t.Rows, row(c[0], c[1], c[2]))
	}
	for _, iv := range rules.SSAInterventions {
		t.Rows = append(t.Rows, row(iv[1]+" (0-10)", "SSA score for "+iv[1], "7.5"))
	}
	note := func(lead, rest string) *screensv1.PageBlock {
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Badges: []*screensv1.PageBadge{},
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: lead + " " + rest}, Lead: lead}}}}}
	}
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{Eyebrow: "Quality & Insights", Title: "Upload SSA Scores",
			BackLabel: "Back to Upload Center", BackHref: "/uploads",
			Description: "Upload a sheet of initial and monitoring SSA scores to map directly to school records in your country. Imported scores wait for a verifier other than you before they count.",
			Badges:      []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{
				{Key: "upload_history", Label: "Upload history", Enabled: true, Href: UploadHistoryPath},
				{Key: "add_ssa_score", Label: "Add SSA Score", Enabled: true, Href: ManualPath},
			}},
		Blocks: []*screensv1.PageBlock{
			{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Required Column Format",
				Subtitle: "Download the template, fill in your scores, and upload it below.", Badges: []*screensv1.PageBadge{},
				Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{
					Links: []*screensv1.PageLink{{Text: "Download Template", Href: "/ssa/upload/template"}}}}}}}}},
			{Kind: &screensv1.PageBlock_Table{Table: t}},
			note("Enrolment:", "In this SSA file, Enrolment is a performance score from 0 to 10. Pupil headcount belongs in the School Upload file or can be updated from the School Profile."),
			note("Assessment history:", "A school may have several SSA assessments in one FY when the dates differ. The same School ID and Assessment Date can only appear once. A first-ever current-FY assessment is accepted as that school's baseline."),
			{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{SubmitLabel: "Upload and Import", Key: "form",
				Items: []*screensv1.PageFormItem{{Kind: &screensv1.PageFormItem_Field{Field: &screensv1.DrawerField{
					Name: "file", Label: "Browse Files", Kind: "file", Required: true, Help: "Drag & drop your SSA file here"}}}}}}},
		},
		Tabs: []*screensv1.PageTab{}, Dialogs: []*screensv1.PageDialog{}, WebPath: UploadCenterPath,
	}, true, nil
}
