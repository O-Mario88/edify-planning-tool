package screens

import (
	"context"
	"errors"

	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/plreview"
)

const (
	returnCompletionTitle = "Return completion"
	maxReturnReason       = 400
	emptyFactMark         = "—"
)

// returnReasons is apps.activities.return_notes.COMMON_REASONS.
var returnReasons = [][2]string{
	{"Salesforce ID entered, but no participants in Salesforce", "Salesforce ID entered, but no participants in Salesforce"},
	{"Participants not entered in Salesforce", "Participants not entered in Salesforce"},
	{"Activity ID missing or wrong in Salesforce", "Activity ID missing or wrong in Salesforce"},
	{"Participant numbers do not match Salesforce", "Participant numbers do not match Salesforce"},
	{"Wrong school, cluster or activity date", "Wrong school, cluster or activity date"},
}

// plReturnForm is pl_return_drawer. Work this reviewer may not decide opens
// the notice saying why.
func plReturnForm(ctx context.Context, s *Service, p auth.Principal, req fieldFormRequest) (*screensv1.PageDrawer, error) {
	review, err := plreview.Reviewable(ctx, s.db, p, req.id, s.now())
	var refusal *plreview.ReviewRefusal
	if errors.As(err, &refusal) {
		return reviewNoticeDrawer(returnCompletionTitle, refusal.Message), nil
	}
	if err != nil {
		return nil, err
	}
	return plReturnDrawer(review), nil
}

// reviewNoticeDrawer is a review form opened on work not waiting on this reader.
func reviewNoticeDrawer(title, why string) *screensv1.PageDrawer {
	return &screensv1.PageDrawer{
		Title: title, Subtitle: "Not waiting on you", HasRequired: true, CancelLabel: "Cancel",
		Items: []*screensv1.DrawerItem{{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: why, Tone: "info"}}}},
	}
}

// reviewFact is one line of the completion; an empty value shows a dash.
func reviewFact(label, value string) *screensv1.PageFact {
	if value == "" {
		value = emptyFactMark
	}
	return &screensv1.PageFact{Label: label, Value: value}
}

// plReturnDrawer is the return form: the reasons ticked and what the lead writes.
func plReturnDrawer(review plreview.Review) *screensv1.PageDrawer {
	return &screensv1.PageDrawer{
		Title:       returnCompletionTitle,
		Subtitle:    review.Activity,
		HasRequired: true,
		SubmitLabel: "Return to officer",
		CancelLabel: "Cancel",
		CanSubmit:   true,
		Items: []*screensv1.DrawerItem{
			{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: []*screensv1.PageFact{
				reviewFact("Officer", review.Officer),
				reviewFact("Activity", review.Activity),
				reviewFact("School or cluster", review.Where),
				reviewFact("Delivered", review.Delivered),
			}}}},
			formField(&screensv1.DrawerField{Name: "reasons", Label: "Why are you returning it?", Kind: "checklist",
				Options: choiceOptions(returnReasons)}),
			formField(&screensv1.DrawerField{Name: "reason", Label: "What should the officer fix?", Kind: "textarea",
				Placeholder: "Say exactly what to fix, e.g. The attendance form and training ID are uploaded, but the participants are not entered in Salesforce.",
				MaxLength:   proto.Int32(maxReturnReason)}),
		},
	}
}
