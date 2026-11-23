package screens

import (
	"context"
	"errors"
	"strings"

	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/plreview"
)

const (
	verifyCompletionTitle = "Verify completion"
	returnCompletionTitle = "Return completion"
	maxReturnReason       = 400
	emptyFactMark         = "—"
	partnerTrainingsDoor  = "partner-trainings"
)

// plReviewForm is pl_review_drawer: the whole completion, read-only, with the
// decision at its foot.
func plReviewForm(ctx context.Context, s *Service, p auth.Principal, req fieldFormRequest) (*screensv1.PageDrawer, error) {
	review, err := plreview.Reviewable(ctx, s.db, p, req.id, s.now())
	var refusal *plreview.ReviewRefusal
	if errors.As(err, &refusal) {
		return reviewNoticeDrawer(verifyCompletionTitle, refusal.Message), nil
	}
	if err != nil {
		return nil, err
	}
	detail, err := plreview.ReadReviewDetail(ctx, s.db, req.id)
	if err != nil {
		return nil, err
	}
	return plReviewDrawer(review, detail, req.query.Get("from")), nil
}

// plReviewDrawer is pl_review_drawer.html. Nothing can be confirmed without
// the ID when Salesforce records this work: the lead returns it instead.
func plReviewDrawer(review plreview.Review, detail plreview.ReviewDetail, door string) *screensv1.PageDrawer {
	decision := "Verified"
	if door == partnerTrainingsDoor {
		decision = "Confirm Verification"
	}
	facts := []*screensv1.PageFact{
		reviewFact("Officer", review.Officer),
		reviewFact("Activity", review.Activity),
		reviewFact("School or cluster", review.Where),
		reviewFact("Delivered", review.Delivered),
		reviewFact("Intervention", detail.Intervention),
	}
	if detail.SSABasis != "" {
		facts = append(facts, reviewFact("SSA basis", detail.SSABasis))
		if detail.SSADeparture != "" {
			facts = append(facts, reviewFact("Why it departs from the SSA", detail.SSADeparture))
		}
	}
	facts = append(facts,
		reviewFact("Attendance", detail.Attendance),
		reviewFact("Purpose", detail.Purpose),
		reviewFact("Outcome", detail.Outcome),
		reviewFact("Observations", detail.Observations),
		reviewFact("Follow-up", detail.FollowUp),
	)
	items := []*screensv1.DrawerItem{{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: facts}}}}
	items = append(items, completionIDItems(detail)...)
	if detail.UploadedForm != "" {
		items = append(items, textLine("Uploaded "+detail.UploadedForm),
			reviewNote("This device cannot show a PDF inside the page. Download the "+detail.UploadedForm+" to read it.", "info"))
	}
	items = append(items, reviewNote(decision+" confirms the completion against Salesforce and marks it complete. "+
		"Return sends it back to the officer with your reason — for example, participants not entered in Salesforce.", "info"))

	drawer := &screensv1.PageDrawer{
		Title: verifyCompletionTitle, Subtitle: review.Activity, HasRequired: true, CancelLabel: "Cancel", Items: items,
	}
	if detail.SalesforceID != "" || detail.SalesforceKind == "" {
		drawer.SubmitLabel, drawer.CanSubmit = decision, true
	}
	return drawer
}

// completionIDItems is the panel for the visit ID or training ID the officer
// completed the work with.
func completionIDItems(detail plreview.ReviewDetail) []*screensv1.DrawerItem {
	heading := "Salesforce ID"
	switch detail.SalesforceKind {
	case "training":
		heading = "Training ID"
	case "visit":
		heading = "Visit ID"
	}
	switch {
	case detail.SalesforceID != "":
		return []*screensv1.DrawerItem{headingLine(heading), textLine(detail.SalesforceID),
			textLine("Find this record in Salesforce and check it against the details above before you decide.")}
	case detail.SalesforceKind != "":
		return []*screensv1.DrawerItem{headingLine(heading),
			reviewNote("No "+detail.SalesforceKind+" ID was entered with this completion. Return it to the officer with the reason.", "warning")}
	}
	return []*screensv1.DrawerItem{headingLine(heading), textLine("This activity has no Salesforce record, so it carries no ID.")}
}

func reviewNote(text, tone string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: text, Tone: tone}}}
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
		Items: []*screensv1.DrawerItem{reviewNote(why, "info")},
	}
}

// reviewFact is one line of the completion; an empty value shows a dash.
func reviewFact(label, value string) *screensv1.PageFact {
	if value = strings.TrimSpace(value); value == "" {
		value = emptyFactMark
	}
	return &screensv1.PageFact{Label: label, Value: value}
}

// plReturnDrawer is the return form: the reasons ticked and what the lead writes.
func plReturnDrawer(review plreview.Review) *screensv1.PageDrawer {
	reasons := make([]*screensv1.DrawerOption, 0, len(plreview.ReturnReasons()))
	for _, reason := range plreview.ReturnReasons() {
		reasons = append(reasons, &screensv1.DrawerOption{Value: plreview.ReturnReasonValue(reason), Label: reason})
	}
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
				Options: reasons}),
			formField(&screensv1.DrawerField{Name: "reason", Label: "What should the officer fix?", Kind: "textarea",
				Placeholder: "Say exactly what to fix, e.g. The attendance form and training ID are uploaded, but the participants are not entered in Salesforce.",
				MaxLength:   proto.Int32(maxReturnReason)}),
		},
	}
}
