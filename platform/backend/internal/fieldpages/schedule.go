package fieldpages

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"strconv"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The Schedule form (planning_views.schedule_activity_form_view,
// pages/planning/schedule.html) as the existing feed reads it: a school
// visit (a school is typed, so the form lists none; one chosen in the
// reader's direct portfolio fills its code), or a group training or
// cluster meeting over the clusters the reader may plan in, the chosen one
// selected. A chosen school with a confirmed SSA carries the SSA's
// recommended focus areas, which the existing page derives: that is handed
// on.

const schedulePath = "/planning/schedule"

// scheduleAsk is what the request chose.
type scheduleAsk struct {
	action, school, cluster string
}

func askOf(query url.Values) scheduleAsk {
	a := scheduleAsk{action: "visit", school: query.Get("school"), cluster: query.Get("cluster")}
	// request.GET.get("action", "visit"): an empty action is no visit.
	if v, ok := query["action"]; ok && len(v) > 0 {
		a.action = v[len(v)-1]
	}
	return a
}

func field(f *screensv1.DrawerField) *screensv1.PageFormItem {
	return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: f}}
}

// schedule answers the form, or hands it on (served false).
func (s *Service) schedule(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	a := askOf(query)
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return nil, true, err
	}
	if a.action != "visit" {
		clusters, err := s.planningClusters(ctx, scope)
		if err != nil {
			return nil, true, err
		}
		return scheduleForm(a, "", clusters), true, nil
	}
	code := ""
	if a.school != "" {
		var confirmed bool
		code, confirmed, err = s.chosenSchool(ctx, scope, a.school)
		if err != nil {
			return nil, true, err
		}
		if confirmed {
			return nil, false, nil
		}
	}
	return scheduleForm(a, code, nil), true, nil
}

// chosenSchool is selected_school: the direct-portfolio school with that id
// or School ID (the newest first), its School ID, and whether it holds a
// confirmed SSA.
func (s *Service) chosenSchool(ctx context.Context, scope schooldirectory.Scope, key string) (string, bool, error) {
	var args []any
	arg := func(v any) string { args = append(args, v); return "$" + strconv.Itoa(len(args)) }
	where := schooldirectory.DirectPortfolio(scope, arg)
	k := arg(key)
	var code string
	var confirmed bool
	err := s.db.QueryRow(ctx, `SELECT COALESCE(s.school_id, ''), EXISTS (SELECT 1 FROM ssa_record r
  WHERE r.school_id = s.id AND r.deleted_at IS NULL AND r.verification_status = 'confirmed')
FROM school s WHERE `+where+` AND (s.id = `+k+` OR s.school_id = `+k+`)
ORDER BY s.created_at DESC LIMIT 1`, args...).Scan(&code, &confirmed)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", false, nil
	}
	if err != nil {
		return "", false, fmt.Errorf("fieldpages: reading the chosen school: %w", err)
	}
	return code, confirmed, nil
}

// planningClusters are cluster_queryset(scope, direct_only=True), live,
// by name.
func (s *Service) planningClusters(ctx context.Context, scope schooldirectory.Scope) ([][2]string, error) {
	var args []any
	arg := func(v any) string { args = append(args, v); return "$" + strconv.Itoa(len(args)) }
	where, err := clusterpage.ScopedClusters(ctx, s.db, scope, true, arg)
	if err != nil {
		return nil, err
	}
	rows, err := s.db.Query(ctx, `SELECT c.id, c.name FROM cluster c WHERE c.deleted_at IS NULL AND `+where+` ORDER BY c.name`, args...)
	if err != nil {
		return nil, fmt.Errorf("fieldpages: reading the clusters to plan in: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) ([2]string, error) {
		var c [2]string
		return c, r.Scan(&c[0], &c[1])
	})
}

var scheduleTitles = map[string]string{"visit": "Schedule School Visit", "training": "Schedule Group Training"}

var meetingPurposes = [][2]string{
	{"focus_intervention", "Focus Intervention"}, {"planning_meeting", "Planning Meeting"},
	{"operational_admin", "Operational / Administration"}, {"other_admin", "Other Admin"},
}

func options(first string, choices [][2]string) []*screensv1.DrawerOption {
	out := []*screensv1.DrawerOption{}
	if first != "" {
		out = append(out, &screensv1.DrawerOption{Value: "", Label: first})
	}
	for _, c := range choices {
		out = append(out, &screensv1.DrawerOption{Value: c[0], Label: c[1]})
	}
	return out
}

func scheduleForm(a scheduleAsk, schoolCode string, clusters [][2]string) *screensv1.GetPageResponse {
	title, ok := scheduleTitles[a.action]
	if !ok {
		title = "Schedule Cluster Meeting"
	}
	h := header("", title,
		"Configure activity logistics, purpose, and target interventions. Cost is computed from active CD catalogue.")
	h.BackLabel, h.BackHref = "Back to Planning", "/planning"
	visit := a.action == "visit"
	var items []*screensv1.PageFormItem
	if visit {
		items = append(items, field(&screensv1.DrawerField{Name: "school_id", Label: "Target School", Kind: "text", Required: true,
			Value:       schoolCode,
			Help:        "Type at least two characters, then choose a school in your direct portfolio.",
			Placeholder: "Type a School ID or name", ReloadsPath: "/planning/schedule/schools"}))
	} else {
		chosen := ""
		for _, c := range clusters {
			if c[0] == a.cluster {
				chosen = c[0]
			}
		}
		items = append(items, field(&screensv1.DrawerField{Name: "cluster_id", Label: "Target Cluster", Kind: "select",
			Required: true, Value: chosen, Options: options("Select Cluster...", clusters)}))
	}
	items = append(items,
		field(&screensv1.DrawerField{Name: "scheduled_date", Label: "Scheduled Date", Kind: "date", Required: true}),
		field(&screensv1.DrawerField{Name: "focus_intervention", Label: "Primary Focus Intervention", Kind: "select",
			Options: options("Select Intervention...", rules.Interventions)}))
	if a.action == "meeting" {
		items = append(items, field(&screensv1.DrawerField{Name: "purpose_type", Label: "Meeting Purpose Category",
			Kind: "select", Value: "focus_intervention", Options: options("", meetingPurposes)}))
	}
	if a.action == "training" || a.action == "meeting" {
		items = append(items, field(&screensv1.DrawerField{Name: "expected_participants", Label: "Expected Participants", Kind: "number"}))
	}
	if visit {
		items = append(items, &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Text{
			Text: "Staff make this visit. To have a partner make it, use Assign on the school's row in Planning: the partner chooses the date."}})
	}
	items = append(items,
		field(&screensv1.DrawerField{Name: "activity_purpose_text", Label: "Purpose Description", Kind: "textarea",
			Placeholder: "What needs to be achieved in this activity?"}),
		field(&screensv1.DrawerField{Name: "expected_outcome", Label: "Expected Outcome / Goal", Kind: "textarea",
			Placeholder: "Target delta or specific checklist outcome..."}))
	form := &screensv1.PageForm{SubmitLabel: "Confirm & Schedule Activity", Key: "form", Items: items}
	return page(h, schedulePath,
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: form}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Live Costing Breakdown",
			Badges: []*screensv1.PageBadge{}, Items: []*screensv1.PagePanelItem{
				text("Fill out target, date, and participants to see itemized UGX rates fetch live from CD catalogue."),
			}}}})
}
