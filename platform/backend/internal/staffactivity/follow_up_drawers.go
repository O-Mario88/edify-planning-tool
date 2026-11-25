package staffactivity

// The follow-up drawers and page drawn in Go: Follow up (§9.2,
// _follow_up_new_drawer.html), the Follow-up Queue (_follow_up_queue_drawer
// .html) and one follow-up (_follow_up_drawer.html as a drawer,
// pages/staff_activity/follow_up.html as a page, both _follow_up_body.html).

import (
	"context"
	"fmt"
	"net/url"
	"regexp"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
)

var (
	followUpNewPath  = regexp.MustCompile(`^/staff-activity/people/([^/]+)/follow-up$`)
	followUpSendPath = regexp.MustCompile(`^/staff-activity/people/([^/]+)/follow-up/send$`)
	followUpOnePath  = regexp.MustCompile(`^/staff-activity/follow-ups/([^/]+)$`)
	followUpStepPath = regexp.MustCompile(`^/staff-activity/follow-ups/([^/]+)/([^/]+)$`)
)

// stepField names the drawer's choice of step: the page shows one button a
// step, a drawer one submit, so the drawer asks which.
const stepField = "step"

func drawerFacts(pairs ...[2]string) *screensv1.DrawerItem {
	facts := make([]*screensv1.PageFact, 0, len(pairs))
	for _, p := range pairs {
		facts = append(facts, &screensv1.PageFact{Label: p[0], Value: p[1]})
	}
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: facts}}}
}

func drawerText(t string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Text{Text: t}}
}

func drawerHeading(t string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Heading{Heading: t}}
}

func drawerNote(t, tone string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: t, Tone: tone}}}
}

func drawerField(f *screensv1.DrawerField) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: f}}
}

func options(pairs [][2]string, blank string) []*screensv1.DrawerOption {
	var out []*screensv1.DrawerOption
	if blank != "" {
		out = append(out, &screensv1.DrawerOption{Value: "", Label: blank})
	}
	for _, p := range pairs {
		out = append(out, &screensv1.DrawerOption{Value: p[0], Label: p[1]})
	}
	return out
}

// pluralize is Django's |pluralize on a count.
func pluralize(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

// FollowUpDrawer draws a follow-up drawer for p; served is false for a path
// that is none of them or a case Go hands on.
func (s *Service) FollowUpDrawer(ctx context.Context, p auth.Principal, rawPath string) (*screensv1.PageDrawer, bool, error) {
	path, rawQuery, _ := strings.Cut(rawPath, "?")
	query, _ := url.ParseQuery(rawQuery)
	var d *screensv1.PageDrawer
	var err error
	switch {
	case path == followUpQueueURL:
		if !rules.Doors[p.ActiveRole].Page {
			return nil, false, nil
		}
		d, err = s.queueDrawer(ctx, p)
	case followUpNewPath.MatchString(path):
		if !rules.Doors[p.ActiveRole].Page {
			return nil, false, nil
		}
		d, err = s.newFollowUpDrawer(ctx, p, followUpNewPath.FindStringSubmatch(path)[1], query.Get("period"), query.Get("on"))
	case followUpOnePath.MatchString(path):
		if !pageaccess.CanOpen(p.ActiveRole, false, path) {
			return nil, false, nil
		}
		d, err = s.oneFollowUpDrawer(ctx, p, followUpOnePath.FindStringSubmatch(path)[1])
	default:
		return nil, false, nil
	}
	if err == errPassOn {
		return nil, false, nil
	}
	return d, err == nil, err
}

// newFollowUp is follow_up_new_view's context.
type newFollowUp struct {
	x                   *person
	p                   period
	assignee            party
	viaManager          bool
	suggested           string
	due, today          time.Time
	subjectName, person string
}

// personFor is person_detail's person for the follow-up drawer and save: in
// the reader's scope, judged alone as the detail judges them.
func (s *Service) personFor(ctx context.Context, p auth.Principal, v *viewerScope, id, periodKey, on string) (*person, period, error) {
	now := s.now()
	today := dateOf(now)
	chosen := choosePeriod(periodKey, on, today)
	if !v.holds(id) {
		return nil, chosen, &Refused{Message: "This person is not in your scope."}
	}
	people, err := buildPeople(ctx, s.db, []string{id}, chosen, now, today)
	if err != nil {
		return nil, chosen, err
	}
	if len(people) == 0 {
		return nil, chosen, &Refused{Message: "This person is not in your scope."}
	}
	x := people[0]
	if x.id == v.selfID {
		x.suggestions, x.reasons = 0, nil
		if x.usageKey == "follow_up" {
			x.usageKey, x.usageLabel = "normal", "Normal"
		}
	}
	for _, reason := range x.reasons {
		if _, ok := rules.Person.SuggestionReasons[reason]; !ok {
			return nil, chosen, errPassOn
		}
	}
	return x, chosen, nil
}

func (s *Service) newFollowUp(ctx context.Context, p auth.Principal, id, periodKey, on string) (*newFollowUp, error) {
	v, err := s.scope(ctx, p)
	if err != nil {
		return nil, err
	}
	if v == nil || !v.canFollowUp {
		return nil, &Refused{Message: "Follow-ups are sent by a Programme Lead or the Country Director."}
	}
	if id == v.selfID {
		return nil, &Refused{Message: "A follow-up is about someone else."}
	}
	x, chosen, err := s.personFor(ctx, p, v, id, periodKey, on)
	if err != nil {
		return nil, err
	}
	subject, err := s.account(ctx, id)
	if err != nil {
		return nil, err
	}
	assignee, route, err := s.recipient(ctx, p, subject)
	if err != nil {
		return nil, err
	}
	today := dateOf(s.now())
	n := &newFollowUp{x: x, p: chosen, assignee: assignee, viaManager: route == routeDirector,
		due: today.AddDate(0, 0, defaultDueDays), today: today, person: x.name}
	if len(x.reasons) > 0 {
		n.suggested = x.reasons[0]
	}
	return n, nil
}

func (s *Service) newFollowUpDrawer(ctx context.Context, p auth.Principal, id, periodKey, on string) (*screensv1.PageDrawer, error) {
	n, err := s.newFollowUp(ctx, p, id, periodKey, on)
	if err != nil {
		return nil, err
	}
	x := n.x
	subtitle := "Sent to " + x.name + "."
	placeholder := "What you would like to talk about, and how you can help"
	if n.viaManager {
		subtitle = fmt.Sprintf("Sent to %s, %s's Program Lead, to follow up with them.", n.assignee.name, x.name)
		placeholder = fmt.Sprintf("What you would like %s to check with %s", n.assignee.name, x.name)
	}
	d := &screensv1.PageDrawer{Title: "Follow up: " + x.name, Subtitle: subtitle, HasRequired: true, CanSubmit: true,
		SubmitLabel: "Send follow-up", CancelLabel: "Cancel"}
	d.Items = append(d.Items, drawerFacts(
		[2]string{"Period", capfirst(n.p.label)}, [2]string{"Logins", fmt.Sprint(x.logins)},
		[2]string{"Active time", minutes(float64(x.seconds))}, [2]string{"Meaningful actions", fmt.Sprint(x.actions)},
		[2]string{"Schools acted on", fmt.Sprint(x.schools)}, [2]string{"Failed actions", fmt.Sprint(x.failed)},
		[2]string{"Usage", x.usageLabel}, [2]string{"Open follow-ups", fmt.Sprint(x.openFollowUps)}))
	if len(x.reasons) > 0 {
		reasons := make([]string, len(x.reasons))
		for i, key := range x.reasons {
			reasons[i] = strings.ReplaceAll(rules.Person.SuggestionReasons[key], "{}", fmt.Sprint(x.failed))
		}
		d.Items = append(d.Items, drawerText(strings.Join(reasons, "; ")+"."))
	}
	maxNote := int32(noteMax)
	d.Items = append(d.Items,
		drawerField(&screensv1.DrawerField{Name: "trigger", Label: "About", Kind: "select", Required: true, Value: n.suggested,
			Options: options(rules.Person.FollowUpTriggers, "Choose…")}),
		drawerField(&screensv1.DrawerField{Name: "note", Label: "Note", Kind: "textarea", Required: true, MaxLength: &maxNote,
			Placeholder: placeholder}),
		drawerField(&screensv1.DrawerField{Name: "due_date", Label: "Due date", Kind: "date", Required: true,
			Value: n.due.Format(time.DateOnly), MinDate: n.today.Format(time.DateOnly)}),
		drawerField(&screensv1.DrawerField{Name: "priority", Label: "Priority", Kind: "select", Required: true, Value: "normal",
			Options: options(priorities, "")}),
		drawerText("A follow-up is support. It does not change anyone's performance record."))
	return d, nil
}

// queueDrawer is the Follow-up Queue.
func (s *Service) queueDrawer(ctx context.Context, p auth.Principal) (*screensv1.PageDrawer, error) {
	q, err := s.queueFor(ctx, p)
	if err != nil {
		return nil, err
	}
	d := &screensv1.PageDrawer{Title: "Follow-up Queue",
		Subtitle: fmt.Sprintf("%d open follow-up%s", q.openCount, pluralize(q.openCount)), CancelLabel: "Close"}
	section := func(title string, rows []*followUp, empty string) {
		d.Items = append(d.Items, drawerHeading(title))
		if len(rows) == 0 {
			if empty != "" {
				d.Items = append(d.Items, drawerText(empty))
			}
			return
		}
		d.Items = append(d.Items, followUpList(rows))
	}
	section("Waiting on you", q.toMe, "Nothing is waiting on you.")
	section("Sent by you", q.fromMe, "You have no open follow-ups.")
	if len(q.recentClosed) > 0 {
		section("Recently resolved", q.recentClosed, "")
	}
	return d, nil
}

// followUpList is _follow_up_list.html.
func followUpList(rows []*followUp) *screensv1.DrawerItem {
	links := make([]*screensv1.PageLink, len(rows))
	for i, f := range rows {
		when := "due"
		if f.overdue {
			when = "overdue since"
		}
		caption := fmt.Sprintf("%s · %s %s", f.statusLabel(), when, jM(f.due))
		if f.assignee.id != f.subject.id {
			caption += " · with " + f.assignee.name
		}
		links[i] = &screensv1.PageLink{Text: f.subject.firstOf() + " · " + f.triggerLabel(), Href: followUpPrefix + f.id, Caption: caption}
	}
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Block{Block: block(&screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
		{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}},
	}})}}
}

// openFollowUp is follow_up_detail_view's reading: the row, the steps open
// to the reader and whether they are its subject.
// swept is whether the read runs the existing sweep first (the detail view
// does; the step's save does not).
func (s *Service) openFollowUp(ctx context.Context, p auth.Principal, id, refusal string, swept bool) (*followUp, []StepAction, error) {
	f, err := s.loadFollowUp(ctx, id)
	if err != nil {
		return nil, nil, err
	}
	if f == nil {
		return nil, nil, &Refused{Message: "This was not found.", NotFound: true}
	}
	ok, err := s.canView(ctx, f, p)
	if err != nil {
		return nil, nil, err
	}
	if !ok {
		return nil, nil, &Refused{Message: refusal}
	}
	if swept {
		if err := s.asSwept(ctx, []*followUp{f}); err != nil {
			return nil, nil, err
		}
	}
	return f, f.actionsFor(p), nil
}

func (s *Service) oneFollowUpDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	f, actions, err := s.openFollowUp(ctx, p, id, "This follow-up is not yours to open.", true)
	if err != nil {
		return nil, err
	}
	d := &screensv1.PageDrawer{Title: "Follow-up: " + f.triggerLabel(), Subtitle: f.subject.firstOf() + " · " + f.statusLabel(),
		Items: s.followUpBody(f, p), CancelLabel: "Close"}
	if len(actions) == 0 {
		return d, nil
	}
	if len(actions) > 1 {
		choices := make([][2]string, len(actions))
		for i, a := range actions {
			choices[i] = [2]string{a.Key, a.Label}
		}
		d.Items = append(d.Items, drawerField(&screensv1.DrawerField{Name: stepField, Label: "Step", Kind: "select", Required: true,
			Value: actions[0].Key, Options: options(choices, "")}))
		d.HasRequired = true
	}
	maxNote := int32(noteMax)
	d.Items = append(d.Items, drawerField(&screensv1.DrawerField{Name: "note", Label: "Note", Kind: "textarea", MaxLength: &maxNote,
		Help: "Needed for some steps"}))
	d.CanSubmit, d.SubmitLabel = true, actions[0].Label
	if len(actions) > 1 {
		d.SubmitLabel = "Save step"
	}
	return d, nil
}

// snapshotCount is a snapshot figure as the template prints it.
func snapshotCount(v any) (string, int) {
	switch n := v.(type) {
	case float64:
		return fmt.Sprint(int(n)), int(n)
	case nil:
		return "", 0
	default:
		return fmt.Sprint(n), 0
	}
}

func snapshotText(v any) string {
	if v == nil {
		return ""
	}
	if s, ok := v.(string); ok {
		return s
	}
	return fmt.Sprint(v)
}

// followUpBody is _follow_up_body.html without its step form.
func (s *Service) followUpBody(f *followUp, p auth.Principal) []*screensv1.DrawerItem {
	from := f.createdBy.name
	if from == "" {
		from = "—"
	}
	period := snapshotText(f.snapshot["period"])
	if period == "" {
		period = "—"
	}
	items := []*screensv1.DrawerItem{drawerFacts(
		[2]string{"About", f.subject.firstOf()}, [2]string{"Topic", f.triggerLabel()}, [2]string{"Status", f.statusLabel()},
		[2]string{"Priority", choice(priorities, f.priority)}, [2]string{"Due", f.due.Format("Mon 2 Jan 2006")},
		[2]string{"From", from}, [2]string{"To", f.assignee.firstOf()}, [2]string{"Period", period})}
	if len(f.snapshot) > 0 && f.subject.id != p.UserID {
		logins, nl := snapshotCount(f.snapshot["logins"])
		actions, na := snapshotCount(f.snapshot["actions"])
		schools, ns := snapshotCount(f.snapshot["schools"])
		items = append(items, drawerText(fmt.Sprintf("When sent: %s login%s · %s active · %s meaningful action%s · %s school%s",
			logins, pluralize(nl), snapshotText(f.snapshot["active"]), actions, pluralize(na), schools, pluralize(ns))))
	}
	items = append(items, drawerText(f.note))
	if f.resolution != "" {
		items = append(items, drawerText("Resolution: "+f.resolution))
	}
	items = append(items, drawerHeading("History"))
	for _, h := range f.history {
		at := ""
		if raw, ok := h["at"].(string); ok {
			if t, err := time.Parse(time.RFC3339Nano, raw); err == nil {
				at = t.In(zone).Format("02/01 15:04")
			}
		}
		status := snapshotText(h["status"])
		line := strings.TrimSpace(at + " " + snapshotText(h["by_name"]) + " · " + choice(rules.Person.FollowUpStatuses, status))
		items = append(items, drawerText(line))
		if n := snapshotText(h["note"]); n != "" {
			items = append(items, drawerText(n))
		}
	}
	return items
}

// followUpPage is follow_up_detail_view as a page: where a notification or
// the To-Do list opens it, one form a step.
func (s *Service) followUpPage(ctx context.Context, p auth.Principal, id string) (*screensv1.GetPageResponse, bool, error) {
	if !pageaccess.CanOpen(p.ActiveRole, false, followUpPrefix+id) {
		return nil, false, nil
	}
	f, actions, err := s.openFollowUp(ctx, p, id, "This follow-up is not yours to open.", true)
	if err != nil {
		return nil, true, err
	}
	description := "About " + f.subject.firstOf()
	if f.subject.id == p.UserID {
		description = "Your manager followed up with you. Acknowledge it, or ask for clarification."
	}
	var body []*screensv1.PagePanelItem
	for _, item := range s.followUpBody(f, p) {
		body = append(body, panelItem(item)...)
	}
	blocks := []*screensv1.PageBlock{block(&screensv1.PagePanel{Items: body})}
	maxNote := int32(noteMax)
	for _, a := range actions {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{
			Key: a.Key, SubmitLabel: a.Label, CanSave: true,
			Items: []*screensv1.PageFormItem{{Kind: &screensv1.PageFormItem_Field{Field: &screensv1.DrawerField{
				Name: "note", Label: "Note", Kind: "textarea", MaxLength: &maxNote, Required: a.NoteRequired}}}},
		}}})
	}
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{Eyebrow: "Staff Activity · Follow-up", Title: f.triggerLabel(), Description: description},
		Blocks: blocks, WebPath: followUpPrefix + id,
	}, true, nil
}

// panelItem is a drawer item read as a page panel's.
func panelItem(item *screensv1.DrawerItem) []*screensv1.PagePanelItem {
	switch k := item.GetKind().(type) {
	case *screensv1.DrawerItem_Heading:
		return []*screensv1.PagePanelItem{heading(k.Heading)}
	case *screensv1.DrawerItem_Text:
		return []*screensv1.PagePanelItem{text(k.Text)}
	case *screensv1.DrawerItem_Facts:
		var out []*screensv1.PagePanelItem
		for _, f := range k.Facts.GetFacts() {
			out = append(out, text(f.GetLabel()), text(f.GetValue()))
		}
		return out
	}
	return nil
}
