package uploadcenter

import (
	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// NewDocumentPath is New Policy or Manual (documents.views.new_document_view,
// pages/documents/new_document.html) as the feed reads its one form: the
// document's details, the acknowledgement it asks of readers and how it is
// delivered; with ?kind=training, New Training Resource (its training types
// and no acknowledgement). The save stays with the existing application. A
// reader without the kind's create permission is redirected, which Go hands
// on.
const NewDocumentPath = "/uploads/new"

const (
	titleMaxLength     = 255
	readingMinutes     = "1"
	readingMinutesMin  = 1
	readingMinutesMax  = 180
	acknowledgementMin = 1
)

func newDocumentPage(training bool) *screensv1.GetPageResponse {
	heading := func(h string) *screensv1.PageFormItem {
		return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Heading{Heading: h}}
	}
	text := func(t string) *screensv1.PageFormItem {
		return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Text{Text: t}}
	}
	field := func(f *screensv1.DrawerField) *screensv1.PageFormItem {
		return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: f}}
	}
	plain := func(name, kind string) *screensv1.PageFormItem {
		return field(&screensv1.DrawerField{Name: name, Kind: kind})
	}
	checked := func(name string) *screensv1.PageFormItem {
		return field(&screensv1.DrawerField{Name: name, Kind: "checkbox", Value: "on"})
	}
	maxLength := int32(titleMaxLength)
	types := &screensv1.DrawerField{Name: "document_type", Kind: "select"}
	choices, title := rules.NewDocumentTypes, "New Policy or Manual"
	if training {
		choices, title = rules.NewTrainingTypes, "New Training Resource"
	}
	for i, t := range choices {
		if i == 0 {
			types.Value = t[0] // no choice is marked: the first is the one sent
		}
		types.Options = append(types.Options, &screensv1.DrawerOption{Value: t[0], Label: t[1]})
	}
	audience := &screensv1.DrawerField{Name: "target_roles", Label: "Who is this for?", Kind: "checklist",
		Help: "A document with no audience reaches nobody — it is not published to everyone by default."}
	for _, r := range rules.RoleChoices {
		audience.Options = append(audience.Options, &screensv1.DrawerOption{Value: r, Label: r})
	}
	dueMin, minutesMin, minutesMax := float64(acknowledgementMin), float64(readingMinutesMin), float64(readingMinutesMax)
	form := &screensv1.PageForm{
		Items: []*screensv1.PageFormItem{
			heading("Document details"),
			text("What it is, who it is for and the file readers open."),
			field(&screensv1.DrawerField{Name: "title", Kind: "text", Required: true, MaxLength: &maxLength}),
			field(types),
			field(&screensv1.DrawerField{Name: "description", Kind: "textarea", Required: true,
				Placeholder: "What this is, in plain language. Readers see this in the Help Center and on the agreement page."}),
			field(audience),
			plain("effective_date", "date"), plain("review_date", "date"), plain("expiry_date", "date"),
			field(&screensv1.DrawerField{Name: "file", Kind: "file", Required: true}),
		},
		SubmitLabel: "Save draft", Key: "form",
	}
	if !training {
		form.Items = append(form.Items,
			heading("Acknowledgement What a reader must do before this counts as read."),
			plain("acknowledgement_required", "checkbox"), plain("agreement_required", "checkbox"),
			plain("comment_required", "checkbox"), plain("blocks_application_access", "checkbox"),
			plain("acknowledgement_reason", "text"),
			field(&screensv1.DrawerField{Name: "acknowledgement_due_days", Kind: "number", Min: &dueMin}),
			field(&screensv1.DrawerField{Name: "required_reading_minutes", Kind: "number", Value: readingMinutes, Required: true,
				Min: &minutesMin, Max: &minutesMax}))
	}
	form.Items = append(form.Items,
		heading("Delivery How readers may take the document away, and where it is found."),
		checked("download_allowed"), checked("print_allowed"), checked("help_visible"),
		plain("help_keywords", "text"))
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{BackLabel: "Back to Upload Center", BackHref: PagePath, Title: title,
			Description: "This creates a draft. It reaches nobody until it has been reviewed and published."},
		Blocks:  []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Form{Form: form}}},
		WebPath: NewDocumentPath,
	}
}
