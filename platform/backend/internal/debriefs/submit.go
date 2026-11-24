package debriefs

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partnerassigned"
)

// The Daily Debrief (debrief_views.field_debrief_submit_view over
// DailyDebriefFlowService.get_state, pages/debriefs/submit.html) as the
// existing feed reads it: the reader's work for today (and the one activity
// they came to discuss) to tick, their day's debrief if they began one, and
// the five questions; once submitted and no longer editable, what they
// wrote. It reads; the form's saves stay the existing page's.

// SubmitPath is the Daily Debrief's path.
const SubmitPath = "/debriefs/submit"

const otherWorkMax = 1000

// dailyWork is one activity the day's form offers.
type dailyWork struct {
	id, kind, status, focus, place string
	scheduled                      *time.Time
	planned                        *time.Time
}

// dailyDebrief is the reader's debrief for the day.
type dailyDebrief struct {
	id, status                                       string
	otherWork, wentWell, notWell, challenges, advice string
	links                                            []string
}

func (s *Service) submit(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if !rules.SubmitPages[p.ActiveRole] {
		return nil, true, pagegate.ErrNotAvailable
	}
	today := day(s.now().In(zone))
	focus := query.Get("activity")
	existing, err := s.dailyDebrief(ctx, p, today)
	if err != nil {
		return nil, true, err
	}
	work, err := s.dailyWork(ctx, p, today, focus)
	if err != nil {
		return nil, true, err
	}
	h := &screensv1.PageHeader{Eyebrow: "My Work", Title: "Daily Debrief",
		Description: "Share what you worked on, what happened and what support could improve tomorrow.",
		Badges:      []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
	editable := existing == nil || slices.Contains(rules.DailyEditableStatuses, existing.status)
	submitted := existing != nil && existing.status != "draft"
	var block *screensv1.PageBlock
	switch {
	case submitted && !editable:
		block = submittedPanel(existing)
	case !slices.Contains(rules.SubmitterRoles, p.ActiveRole):
		block = &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: "Daily Debrief is not available for your role."}}
	default:
		block = dailyForm(existing, work, focus, today)
		// The web draws and saves the form itself when Go makes the save.
		block.GetForm().CanSave = s.Saves()
	}
	return &screensv1.GetPageResponse{Header: h, Blocks: []*screensv1.PageBlock{block},
		Tabs: []*screensv1.PageTab{}, Dialogs: []*screensv1.PageDialog{}, WebPath: SubmitPath}, true, nil
}

// dailyDebrief is get_state's `existing`: the reader's daily debrief whose
// day is today (its local midnight), not deleted.
func (s *Service) dailyDebrief(ctx context.Context, p auth.Principal, today time.Time) (*dailyDebrief, error) {
	midnight := time.Date(today.Year(), today.Month(), today.Day(), 0, 0, 0, 0, zone)
	var d dailyDebrief
	err := s.db.QueryRow(ctx, `
SELECT id, status, COALESCE(other_work_description, ''), COALESCE(what_went_well, ''),
  COALESCE(what_did_not_go_well, ''), COALESCE(challenges_faced, ''), COALESCE(recommendations, '')
FROM daily_debrief
WHERE submitted_by_user_id = $1 AND kind = 'daily' AND date = $2 AND deleted_at IS NULL
ORDER BY date DESC LIMIT 1`, p.UserID, midnight).Scan(&d.id, &d.status, &d.otherWork, &d.wentWell, &d.notWell, &d.challenges, &d.advice)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the day's debrief: %w", err)
	}
	rows, err := s.db.Query(ctx, `SELECT activity_id FROM daily_debrief_activity_link WHERE debrief_id = $1`, d.id)
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the debrief's work: %w", err)
	}
	d.links = []string{}
	err = forEach(rows, func(r pgx.Rows) error {
		var id string
		if err := r.Scan(&id); err != nil {
			return err
		}
		d.links = append(d.links, id)
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the debrief's work: %w", err)
	}
	return &d, nil
}

// dailyWork is activities_for: the reader's own work planned or scheduled
// for today, cancelled work left out, in time order then by id; and the
// activity they came to discuss, read through the same ownership, after
// them when it is not already among them.
func (s *Service) dailyWork(ctx context.Context, p auth.Principal, today time.Time, focus string) ([]dailyWork, error) {
	var ownership string
	args := []any{}
	arg := func(v any) string { args = append(args, v); return fmt.Sprintf("$%d", len(args)) }
	if slices.Contains(rules.PartnerRoles, p.ActiveRole) {
		ids, err := partnerassigned.PartnerIDs(ctx, s.db, p)
		if err != nil {
			return nil, err
		}
		if len(ids) == 0 {
			ids = []string{"-"}
		}
		ownership = "a.assigned_partner_id = ANY(" + arg(ids) + ")"
	} else {
		owners := []string{}
		for _, id := range []string{p.UserID, p.StaffProfileID} {
			if id != "" {
				owners = append(owners, id)
			}
		}
		o := arg(owners)
		ownership = "(a.responsible_staff_id = ANY(" + o + ") OR (a.monitored_by_staff_id = ANY(" + o + ") AND a.delivery_type = 'partner'))"
	}
	base := `
SELECT a.id, a.activity_type, a.status, COALESCE(a.focus_intervention, ''), a.scheduled_date, a.planned_date,
  COALESCE(s.name, c.name, '—')
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE ` + ownership + ` AND a.deleted_at IS NULL AND a.status <> ALL(` + arg(rules.DailyHiddenStatuses) + `)`
	// Each query sends only the parameters it names: the shared ones, then
	// its own (the day, or the one activity carried in).
	shared := len(args)
	at := fmt.Sprintf("$%d", shared+1)
	work, err := s.readWork(ctx, base+` AND (a.planned_date = `+at+`::date OR (a.scheduled_date AT TIME ZONE '`+zone.String()+`')::date = `+at+`::date)
ORDER BY a.scheduled_date ASC NULLS LAST, a.id`, append(slices.Clip(args), today.Format(time.DateOnly))...)
	if err != nil || focus == "" || slices.ContainsFunc(work, func(w dailyWork) bool { return w.id == focus }) {
		return work, err
	}
	carried, err := s.readWork(ctx, base+` AND a.id = `+at+` LIMIT 1`, append(slices.Clip(args), focus)...)
	if err != nil {
		return nil, err
	}
	return append(work, carried...), nil
}

func (s *Service) readWork(ctx context.Context, sql string, args ...any) ([]dailyWork, error) {
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the day's work: %w", err)
	}
	out := []dailyWork{}
	err = forEach(rows, func(r pgx.Rows) error {
		var w dailyWork
		if err := r.Scan(&w.id, &w.kind, &w.status, &w.focus, &w.scheduled, &w.planned, &w.place); err != nil {
			return err
		}
		out = append(out, w)
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("debriefs: reading the day's work: %w", err)
	}
	return out, nil
}

// checked is get_state's tick: the activity the reader came to discuss;
// else, once the day's debrief exists, the work it names; else work whose
// state says it happened.
func (w dailyWork) checked(existing *dailyDebrief, focus string) bool {
	if focus != "" && w.id == focus {
		return true
	}
	if existing != nil {
		return slices.Contains(existing.links, w.id)
	}
	return slices.Contains(rules.DailyPreselectStatuses, w.status)
}

// words is what the row prints under its name: the intervention, the time
// and the state, and where carried-in work was planned.
func (w dailyWork) words(focus string, today time.Time) string {
	var parts []string
	if w.focus != "" {
		parts = append(parts, label(rules.Interventions, w.focus))
	}
	if w.scheduled != nil {
		parts = append(parts, w.scheduled.In(zone).Format("3:04 PM"))
	}
	state := label(rules.ActivityStatuses, w.status)
	if focus != "" && w.id == focus && w.planned != nil && !day(*w.planned).Equal(today) {
		state += " · carried in from " + w.planned.Format("2 Jan")
	}
	return strings.Join(append(parts, state), " · ")
}

func (w dailyWork) title(focus string) string {
	t := label(rules.ActivityTypes, w.kind)
	if focus != "" && w.id == focus {
		t += " Discussing"
	}
	return t
}

func formField(f *screensv1.DrawerField) *screensv1.PageFormItem {
	return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: f}}
}

// workFields are the tick boxes: Select all, then one box, or the boxes
// read as one list once there are two.
func workFields(existing *dailyDebrief, work []dailyWork, focus string, today time.Time) []*screensv1.PageFormItem {
	if len(work) == 0 {
		return nil
	}
	items := []*screensv1.PageFormItem{formField(&screensv1.DrawerField{Kind: "checkbox", Label: "Select all"})}
	if len(work) == 1 {
		w := work[0]
		value := ""
		if w.checked(existing, focus) {
			value = w.id
		}
		return append(items, formField(&screensv1.DrawerField{Name: "activity_ids", Kind: "checkbox", Value: value,
			Label: strings.Join([]string{w.title(focus), w.place, w.words(focus, today)}, " ")}))
	}
	options := make([]*screensv1.DrawerOption, 0, len(work))
	ticked := []string{}
	for _, w := range work {
		options = append(options, &screensv1.DrawerOption{Value: w.id, Label: w.title(focus),
			Detail: w.place + " · " + w.words(focus, today)})
		if w.checked(existing, focus) {
			ticked = append(ticked, w.id)
		}
	}
	return append(items, formField(&screensv1.DrawerField{Name: "activity_ids", Kind: "checklist",
		Options: options, Value: strings.Join(ticked, ",")}))
}

// question is one of the four reflections.
type question struct{ name, label, help string }

var reflections = []question{
	{"what_went_well", "2 · What worked well?", "Describe what helped today's work succeed."},
	{"what_did_not_go_well", "3 · What did not work well?", "Describe anything that did not go as expected."},
	{"challenges_faced", "4 · What challenges did you face during the course of the day?",
		"Describe the barriers that affected your work today — e.g. transport, roads, funds, school leader availability, weather, network."},
	{"recommendations", "5 · What do you suggest should be done to improve?", "What practical action would improve the situation?"},
}

func (d *dailyDebrief) answers() [5]string {
	if d == nil {
		return [5]string{}
	}
	return [5]string{d.otherWork, d.wentWell, d.notWell, d.challenges, d.advice}
}

func dailyForm(existing *dailyDebrief, work []dailyWork, focus string, today time.Time) *screensv1.PageBlock {
	written := existing.answers()
	limit := int32(otherWorkMax)
	items := []*screensv1.PageFormItem{
		{Kind: &screensv1.PageFormItem_Heading{Heading: "1 · What did you work on today?"}},
		{Kind: &screensv1.PageFormItem_Text{Text: "Your scheduled activities from My Plan. Tick the ones you worked on — this never starts, completes or credits an activity."}},
	}
	items = append(items, workFields(existing, work, focus, today)...)
	items = append(items, formField(&screensv1.DrawerField{Name: "other_work_description", Kind: "textarea",
		Label: "Authorized work not in My Plan (short description)", Value: strings.TrimSpace(written[0]),
		Help:        "Repeated or material unplanned work is routed to your manager for future planning.",
		Placeholder: "e.g. Covered a colleague's school visit at St. Jude Primary", MaxLength: &limit}))
	for i, q := range reflections {
		items = append(items, formField(&screensv1.DrawerField{Name: q.name, Kind: "textarea", Label: q.label,
			Help: q.help, Value: strings.TrimSpace(written[i+1])}))
	}
	items = append(items, &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Text{
		Text: "Safeguarding, fraud, harassment or another confidential concern? Report a Sensitive Issue — it follows a restricted workflow, not this form."}})
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{
		Items: items, SubmitLabel: "Submit Daily Debrief", Key: "daily-debrief-form"}}}
}

// submittedPanel is the read-only summary: the other work beneath the
// title, then each reflection written, the note and the record's link. The
// feed does not read the list of work covered.
func submittedPanel(d *dailyDebrief) *screensv1.PageBlock {
	p := &screensv1.PagePanel{Title: "Work covered", Badges: []*screensv1.PageBadge{}}
	if d.otherWork != "" {
		p.Subtitle = "Other work: " + oneLine(d.otherWork)
	}
	for _, r := range []struct{ heading, text string }{
		{"What worked well", d.wentWell}, {"What did not work well", d.notWell},
		{"Challenges", d.challenges}, {"Suggestions", d.advice},
	} {
		if r.text != "" {
			p.Items = append(p.Items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: r.heading}},
				text(oneLine(r.text)))
		}
	}
	p.Items = append(p.Items, text("Your Program Lead, Country Director and HR can now review it."),
		links(&screensv1.PageLink{Text: "View full record", Href: "/debriefs/" + d.id}))
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: p}}
}

// oneLine is the text as the feed reads it: runs of white space as one.
func oneLine(s string) string { return strings.Join(strings.Fields(s), " ") }
