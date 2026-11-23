package screens

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"

	"github.com/jackc/pgx/v5"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/rbac"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	maxExtraWorkAssignees  = 200
	maxExtraWorkMilestones = 120
	milestoneLabelLength   = 70
	maxExtraWorkTitle      = 200
	maxExpectedOutput      = 255
)

// extraWorkCategories is ExtraAssignment.CATEGORIES.
var extraWorkCategories = [][2]string{
	{"priority_linked", "Priority-linked additional work"},
	{"operational_support", "Operational support"},
	{"strategic", "Strategic assignment"},
	{"emergency", "Emergency assignment"},
	{"cross_team", "Cross-team support"},
	{"special_project", "Special project"},
	{"leadership", "Leadership responsibility"},
	{"non_scoreable_support", "Non-scoreable support task"},
}

// extraWorkAssignee is a person the assigner may give extra work to.
type extraWorkAssignee struct{ id, name, role string }

// extraWorkAssignForm is extra_work_assign_drawer. Others who hold the page
// see why they cannot assign.
func extraWorkAssignForm(ctx context.Context, s *Service, p auth.Principal, req fieldFormRequest) (*screensv1.PageDrawer, error) {
	if p.ActiveRole != roleCD && p.ActiveRole != rbac.ProgramLead {
		return extraWorkNoticeDrawer(), nil
	}
	assignees, err := s.extraWorkAssignees(ctx, p)
	if err != nil {
		return nil, err
	}
	today := s.now().In(exportDayZone)
	fy := strings.TrimSpace(req.query.Get("fy"))
	if !slices.Contains(schooldirectory.FYOptions(today), fy) {
		fy = schooldirectory.OperationalFY(today)
	}
	milestones, err := s.extraWorkMilestones(ctx, p, fy)
	if err != nil {
		return nil, err
	}
	return extraWorkDrawer(assignees, milestones), nil
}

// extraWorkAssignees is the CD's Program Leads and CCEOs, or a Program Lead's
// own supervisees, active and never the assigner.
func (s *Service) extraWorkAssignees(ctx context.Context, p auth.Principal) ([]extraWorkAssignee, error) {
	const columns = `SELECT id, COALESCE(name, ''), COALESCE(active_role, '') FROM "user"`
	var rows pgx.Rows
	var err error
	if p.ActiveRole == roleCD {
		rows, err = s.db.Query(ctx, columns+`
 WHERE active_role IN ('Program Lead', 'CCEO') AND is_active AND id <> $1
 ORDER BY name LIMIT $2`, p.UserID, maxExtraWorkAssignees)
	} else {
		rows, err = s.db.Query(ctx, columns+`
 WHERE id IN (SELECT sp.user_id FROM staff_supervisor_assignment a
                JOIN staff_profile sp ON sp.id = a.supervisee_id
               WHERE a.supervisor_id = $3)
   AND is_active AND id <> $1
 ORDER BY name LIMIT $2`, p.UserID, maxExtraWorkAssignees, p.StaffProfileID)
	}
	if err != nil {
		return nil, fmt.Errorf("screens: reading the extra work assignees: %w", err)
	}
	assignees, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (extraWorkAssignee, error) {
		var a extraWorkAssignee
		err := row.Scan(&a.id, &a.name, &a.role)
		return a, err
	})
	if err != nil {
		return nil, fmt.Errorf("screens: reading an assignee: %w", err)
	}
	return assignees, nil
}

// extraWorkMilestones is _milestone_options: the assigner's country's
// priorities in the year's cycle, else the regional ones it would translate.
// A year with no milestones opens the newest cycle that is not archived.
func (s *Service) extraWorkMilestones(ctx context.Context, p auth.Principal, fy string) ([]fieldChoice, error) {
	cycle, err := s.milestoneCycle(ctx, fy)
	if err != nil || cycle == "" {
		return nil, err
	}
	var country string
	err = s.db.QueryRow(ctx, `SELECT COALESCE(country, '') FROM staff_profile WHERE user_id = $1 LIMIT 1`, p.UserID).Scan(&country)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, fmt.Errorf("screens: reading the assigner's country: %w", err)
	}
	if country = strings.TrimSpace(country); country != "" {
		own, err := s.readMilestones(ctx, cycle, "country", country)
		if err != nil {
			return nil, err
		}
		if len(own) > 0 {
			return own, nil
		}
	}
	return s.readMilestones(ctx, cycle, "regional", "")
}

func (s *Service) milestoneCycle(ctx context.Context, fy string) (string, error) {
	var hasMilestones bool
	err := s.db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM hr_priority_milestone m JOIN hr_strategic_priority p ON p.id = m.priority_id
                WHERE p.status IS DISTINCT FROM 'archived' AND p.fy = $1)`, fy).Scan(&hasMilestones)
	if err != nil {
		return "", fmt.Errorf("screens: reading the year's milestones: %w", err)
	}
	if hasMilestones {
		return fy, nil
	}
	var cycle string
	err = s.db.QueryRow(ctx, `
SELECT financial_year FROM hr_strategic_priority_cycle
 WHERE status IS DISTINCT FROM 'archived' ORDER BY financial_year DESC LIMIT 1`).Scan(&cycle)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("screens: reading the newest cycle: %w", err)
	}
	return cycle, nil
}

// readMilestones reads one level of the cycle: a country's own priorities, or
// the regional ones, which belong to no country.
func (s *Service) readMilestones(ctx context.Context, cycle, level, country string) ([]fieldChoice, error) {
	rows, err := s.db.Query(ctx, `
SELECT m.id, m.title
  FROM hr_priority_milestone m JOIN hr_strategic_priority p ON p.id = m.priority_id
 WHERE p.status IS DISTINCT FROM 'archived' AND p.fy = $1 AND p.level = $2
   AND (($2 = 'country' AND p.country_id = $3) OR ($2 = 'regional' AND p.country_id IS NULL))
 ORDER BY p.sequence, m.source_order
 LIMIT $4`, cycle, level, country, maxExtraWorkMilestones)
	if err != nil {
		return nil, fmt.Errorf("screens: reading the milestones: %w", err)
	}
	milestones, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (fieldChoice, error) {
		var c fieldChoice
		err := row.Scan(&c.id, &c.name)
		return c, err
	})
	if err != nil {
		return nil, fmt.Errorf("screens: reading a milestone: %w", err)
	}
	return milestones, nil
}

// extraWorkNoticeDrawer is refusal_drawer's answer to a role that holds the
// page and does not assign.
func extraWorkNoticeDrawer() *screensv1.PageDrawer {
	return &screensv1.PageDrawer{
		Title: "Extra work", HasRequired: true, CancelLabel: "Close",
		Items: []*screensv1.DrawerItem{{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{
			Text: "Only the CD or a Program Lead assigns extra work.", Tone: "info",
		}}}},
	}
}

// extraWorkDrawer is extra_work_assign_drawer.html.
func extraWorkDrawer(assignees []extraWorkAssignee, milestones []fieldChoice) *screensv1.PageDrawer {
	people := make([]*screensv1.DrawerOption, 0, len(assignees)+1)
	people = append(people, &screensv1.DrawerOption{Label: "Choose a staff member…"})
	for _, a := range assignees {
		people = append(people, &screensv1.DrawerOption{Value: a.id, Label: a.name + " — " + a.role})
	}
	links := make([]*screensv1.DrawerOption, 0, len(milestones)+1)
	links = append(links, &screensv1.DrawerOption{Label: "None"})
	for _, m := range milestones {
		links = append(links, &screensv1.DrawerOption{Value: m.id, Label: closedschools.TruncateChars(m.name, milestoneLabelLength)})
	}
	return &screensv1.PageDrawer{
		Title:       "Assign extra work",
		HasRequired: true,
		SubmitLabel: "Assign work",
		CancelLabel: "Cancel",
		CanSubmit:   true,
		Items: []*screensv1.DrawerItem{
			textLine("Verified independently and counted separately; it never changes a distributed target."),
			formField(&screensv1.DrawerField{Name: "assignee_id", Label: "Assign to", Kind: "select", Required: true, Options: people}),
			formField(&screensv1.DrawerField{Name: "due_date", Label: "Due date", Kind: "date", Required: true}),
			formField(&screensv1.DrawerField{Name: "title", Label: "Title", Kind: "text", Required: true,
				Placeholder: "What is being asked, in one line", MaxLength: proto.Int32(maxExtraWorkTitle)}),
			formField(&screensv1.DrawerField{Name: "instruction", Label: "Detailed instruction", Kind: "textarea", Required: true,
				Placeholder: "What to deliver and how it is judged"}),
			formField(&screensv1.DrawerField{Name: "category", Label: "Category", Kind: "select", Value: "priority_linked", Required: true,
				Options: choiceOptions(extraWorkCategories)}),
			formField(&screensv1.DrawerField{Name: "complexity", Label: "Complexity", Kind: "select", Value: "medium",
				Options: choiceOptions([][2]string{{"low", "Low"}, {"medium", "Medium"}, {"high", "High"}})}),
			formField(&screensv1.DrawerField{Name: "urgency", Label: "Urgency", Kind: "select", Value: "normal",
				Options: choiceOptions([][2]string{{"normal", "Normal"}, {"high", "High"}, {"urgent", "Urgent"}})}),
			formField(&screensv1.DrawerField{Name: "linked_milestone_id", Label: "Linked priority milestone (optional)", Kind: "select", Options: links}),
			formField(&screensv1.DrawerField{Name: "expected_output", Label: "Expected output (optional)", Kind: "text",
				Placeholder: "e.g. One report, 3 sessions", MaxLength: proto.Int32(maxExpectedOutput)}),
			formField(&screensv1.DrawerField{Name: "evidence_required", Label: "Evidence required at submission", Kind: "checkbox", Value: "on"}),
			formField(&screensv1.DrawerField{Name: "reason", Label: "Business reason (optional)", Kind: "textarea"}),
		},
	}
}
