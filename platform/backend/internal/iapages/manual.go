package iapages

import (
	"net/url"
	"slices"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// ManualPath is Add SSA Score (ssa_views.ssa_manual_entry_view,
// pages/ssa/manual_entry.html): one SSA record keyed by hand, the school
// typed (the one asked for written in), today's date and the eight
// intervention scores. A reader the page opens to without the SSA upload
// permission is sent away by the existing page: handed on. Saving stays the
// existing page's.
const ManualPath = "/ssa/manual/"

const (
	schoolIDMax  = 64
	scoreMax     = 10
	scoreStep    = 0.1
	enrolmentKey = "enrolment"
)

func (s *Service) manual(p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if !slices.Contains(rules.SSAUploadRoles, p.ActiveRole) {
		return nil, false, nil
	}
	today := s.now().In(zone).Format("2006-01-02")
	limit := int32(schoolIDMax)
	field := func(f *screensv1.DrawerField) *screensv1.PageFormItem {
		return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: f}}
	}
	items := []*screensv1.PageFormItem{
		{Kind: &screensv1.PageFormItem_Heading{Heading: "Assessment details"}},
		{Kind: &screensv1.PageFormItem_Text{Text: "Choose a school already saved in the School Directory."}},
		field(&screensv1.DrawerField{Name: "school_id", Label: "School", Kind: "text", Required: true,
			Value:       strings.TrimSpace(query.Get("school_id")),
			Help:        "Type at least two characters of the School ID or name, then select the matching directory record.",
			Placeholder: "Type or select a School ID", MaxLength: &limit, ReloadsPath: "/ssa/manual/schools"}),
		field(&screensv1.DrawerField{Name: "date_of_ssa", Label: "Assessment date", Kind: "date", Value: today, Required: true,
			Help: "The assessment date determines the fiscal year and quarter."}),
		{Kind: &screensv1.PageFormItem_Heading{Heading: "Intervention scores"}},
		{Kind: &screensv1.PageFormItem_Text{Text: "Enter a score from 0 to 10 for every intervention."}},
	}
	for _, iv := range rules.SSAInterventions {
		lo, hi, step := float64(0), float64(scoreMax), scoreStep
		help := ""
		if iv[0] == enrolmentKey {
			help = "This is the SSA Enrolment score out of 10, not the number of pupils. Update pupil enrolment through the School Profile or School Upload."
		}
		items = append(items, field(&screensv1.DrawerField{Name: "score_" + iv[0], Label: iv[1], Kind: "number",
			Required: true, Placeholder: "0–10", Help: help, Min: &lo, Max: &hi, Step: &step}))
	}
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{Eyebrow: "Manual entry", Title: "Add SSA Score",
			Description: "Save one School Self-Assessment directly to the SSA database. All eight intervention scores are required. The scores count once a verifier other than you confirms them.",
			Badges:      []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}},
		Blocks: []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{
			Items: items, SubmitLabel: "Save SSA Score", Key: ManualPath}}}},
		Tabs: []*screensv1.PageTab{}, Dialogs: []*screensv1.PageDialog{}, WebPath: ManualPath,
	}, true, nil
}
