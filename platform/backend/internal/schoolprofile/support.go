package schoolprofile

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"slices"
	"sort"
	"strings"
	"time"
	"unicode"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The Participation tab's last two panels (partials/schools/_participation.html):
// what follow-up visits found, and the support handed to partners.

// ── School Visit Feedback (school_views._school_participation_context) ─────

func (s *Service) visitFeedback(ctx context.Context, sc school) (*screensv1.PageBlock, error) {
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(f.finding, ''), f.improvements, a.id, COALESCE(a.activity_type, ''), COALESCE(a.salesforce_activity_id, ''),
  a.actual_delivery_date, a.planned_date, a.scheduled_date,
  COALESCE(fu.activity_type, ''), fu.planned_date, fu.id IS NOT NULL
FROM school_visit_feedback f
JOIN activity a ON a.id = f.activity_id
LEFT JOIN activity fu ON fu.id = a.follow_up_of_activity_id
WHERE a.school_id = $1 AND a.deleted_at IS NULL
ORDER BY f.created_at DESC
LIMIT 20`, sc.ID)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading visit feedback: %w", err)
	}
	type feedback struct {
		finding, activityID, kind, salesforce string
		improvements                          []byte
		actual, planned, scheduled            *time.Time
		relatedKind                           string
		relatedPlanned                        *time.Time
		hasRelated                            bool
	}
	found := []feedback{}
	for rows.Next() {
		var f feedback
		if err := rows.Scan(&f.finding, &f.improvements, &f.activityID, &f.kind, &f.salesforce,
			&f.actual, &f.planned, &f.scheduled, &f.relatedKind, &f.relatedPlanned, &f.hasRelated); err != nil {
			rows.Close()
			return nil, err
		}
		found = append(found, f)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(found) == 0 {
		return nil, nil
	}
	// The training paired with a visit speaks for it before the visit it
	// followed up.
	ids := []string{}
	for _, f := range found {
		ids = append(ids, f.activityID)
	}
	paired := map[string]struct {
		kind    string
		planned *time.Time
	}{}
	pairs, err := s.db.Query(ctx, `
SELECT paired_school_visit_id, COALESCE(activity_type, ''), planned_date FROM activity
WHERE paired_school_visit_id = ANY($1) AND deleted_at IS NULL ORDER BY created_at, id`, ids)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading paired trainings: %w", err)
	}
	for pairs.Next() {
		var visit, kind string
		var planned *time.Time
		if err := pairs.Scan(&visit, &kind, &planned); err != nil {
			pairs.Close()
			return nil, err
		}
		paired[visit] = struct {
			kind    string
			planned *time.Time
		}{kind, planned}
	}
	pairs.Close()
	if err := pairs.Err(); err != nil {
		return nil, err
	}

	items := []*screensv1.PagePanelItem{}
	types := rules.Participation.ActivityTypes
	for _, f := range found {
		items = append(items, heading(label(types, f.kind)))
		day := "Date not recorded"
		switch {
		case f.actual != nil:
			day = jMY(*f.actual)
		case f.planned != nil:
			day = jMY(*f.planned)
		case f.scheduled != nil:
			day = jMY(kampalaDay(*f.scheduled))
		}
		if f.salesforce != "" {
			day += " • " + f.salesforce
		}
		items = append(items, text(collapse(day)))
		relatedKind, relatedPlanned, related := f.relatedKind, f.relatedPlanned, f.hasRelated
		if p, ok := paired[f.activityID]; ok {
			relatedKind, relatedPlanned, related = p.kind, p.planned, true
		}
		if related {
			pill := "Related to " + label(types, relatedKind)
			if relatedPlanned != nil {
				pill += " · " + jMY(*relatedPlanned)
			}
			items = append(items, text(collapse(pill)))
		}
		items = append(items, text("Finding"))
		// linebreaksbr: a line break is a <br>, read as nothing.
		if finding := collapse(strings.NewReplacer("\r\n", "", "\r", "", "\n", "").Replace(f.finding)); finding != "" {
			items = append(items, text(finding))
		}
		items = append(items, text("Improvement since the last visit"))
		links := []*screensv1.PageLink{}
		for _, improvement := range improvementsOf(f.improvements) {
			links = append(links, &screensv1.PageLink{Text: collapse(improvement)})
		}
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title:    "School Visit Feedback",
		Subtitle: "Findings and improvements recorded at completed follow-up visits.",
		Badges:   []*screensv1.PageBadge{},
		Items:    pairedItems(items),
	}}}, nil
}

// improvementsOf is the stored list, each entry as the template prints it.
func improvementsOf(raw []byte) []string {
	var values []any
	if err := json.Unmarshal(raw, &values); err != nil {
		return nil
	}
	out := []string{}
	for _, v := range values {
		switch t := v.(type) {
		case string:
			out = append(out, t)
		case nil:
			out = append(out, "None")
		default:
			out = append(out, fmt.Sprint(t))
		}
	}
	return out
}

// ── Partner Support (partner_oversight_service.build_items_for_school) ──────

type handover struct {
	status, partnerName, kind, returnReason string
	created                                 time.Time
	cceoID                                  string
	hasActivity                             bool
	planned, scheduled                      *time.Time
	activityStatus, payment, evidence       string
	salesforce                              string
	cost                                    int64
}

func (s *Service) partnerSupport(ctx context.Context, sc school) (*screensv1.PageBlock, error) {
	pr := rules.Participation
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(pa.status, ''), COALESCE(p.name, ''), COALESCE(NULLIF(act.activity_type, ''), pa.expected_activity_type, ''),
  COALESCE(pa.return_reason, ''), pa.created_at,
  COALESCE(NULLIF(pa.monitoring_staff_id, ''), NULLIF(pa.assigning_staff_id, ''), NULLIF(s.account_owner_id, ''), NULLIF(cl.responsible_staff_id, ''), ''),
  act.id IS NOT NULL, act.planned_date, act.scheduled_date, COALESCE(act.status, ''), COALESCE(act.payment_status, ''),
  COALESCE(act.evidence_status, ''), COALESCE(act.salesforce_activity_id, ''),
  COALESCE((SELECT SUM(l.amount) FROM activity_schedule_cost_line l WHERE l.activity_id = act.id), 0)
FROM partner_assignment pa
LEFT JOIN partner p ON p.id = pa.partner_id
LEFT JOIN activity act ON act.id = pa.scheduled_activity_id
LEFT JOIN school s ON s.id = pa.school_id
LEFT JOIN cluster cl ON cl.id = pa.cluster_id
WHERE pa.school_id = $1
  AND NOT (pa.status = ANY($2) OR (pa.status = $3 AND pa.resolved_at IS NOT NULL))
ORDER BY pa.created_at DESC`, sc.ID, pr.HandoverLeftStatuses, pr.HandoverReturnedStatus)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading partner hand-overs: %w", err)
	}
	handovers := []handover{}
	for rows.Next() {
		var h handover
		if err := rows.Scan(&h.status, &h.partnerName, &h.kind, &h.returnReason, &h.created, &h.cceoID,
			&h.hasActivity, &h.planned, &h.scheduled, &h.activityStatus, &h.payment, &h.evidence, &h.salesforce, &h.cost); err != nil {
			rows.Close()
			return nil, err
		}
		handovers = append(handovers, h)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(handovers) == 0 {
		return nil, nil
	}
	names, err := s.staffDirectory(ctx, handovers)
	if err != nil {
		return nil, err
	}

	// Newest first by the day the work is dated, else the day it was handed
	// over (a stable sort, as Python's).
	sort.SliceStable(handovers, func(i, j int) bool { return handovers[i].when().After(handovers[j].when()) })

	items := []*screensv1.PagePanelItem{}
	for _, h := range handovers {
		returned := h.status == pr.HandoverReturnedStatus
		scheduled := !returned && h.hasActivity
		partner := h.partnerName
		if partner == "" {
			partner = "Partner"
		}
		kind := djangoTitle(strings.ReplaceAll(h.kind, "_", " "))
		if kind == "" {
			kind = "Support"
		}
		items = append(items, heading(collapse(partner+" — "+kind)))
		var line string
		switch {
		case scheduled:
			day := "—"
			if d := h.day(); d != nil {
				day = jMY(*d)
			}
			line = "Scheduled for " + day
		case returned:
			line = "Returned to staff"
			if h.returnReason != "" {
				line += " — " + h.returnReason
			}
		default:
			line = "Assigned " + jMY(h.created.UTC()) + " • no date set yet"
		}
		items = append(items, text(collapse(line)))
		owner, action := h.nextAction(scheduled, returned, partner, names[h.cceoID])
		items = append(items, text(collapse("Next: "+action+" — "+owner)))
		// Cost is the activity's, whatever the hand-over's stage.
		if h.hasActivity {
			items = append(items, text("UGX "+intcomma(int(h.cost))))
		}
		switch {
		case scheduled:
			if st := collapse(djangoTitle(strings.ReplaceAll(h.activityStatus, "_", " "))); st != "" {
				items = append(items, text(st))
			}
		case returned:
			items = append(items, text("Returned"))
		default:
			items = append(items, text("Awaiting partner"))
		}
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title:    "Partner Support",
		Subtitle: "Support handed to a partner. The partner sets the date; you keep the evidence and Salesforce handoff.",
		Badges:   []*screensv1.PageBadge{},
		Items:    pairedItems(items),
	}}}, nil
}

// day is activity_day: the planned day, else the scheduled moment's day in
// Kampala.
func (h handover) day() *time.Time {
	if !h.hasActivity {
		return nil
	}
	if h.planned != nil {
		return h.planned
	}
	if h.scheduled != nil {
		d := kampalaDay(*h.scheduled)
		return &d
	}
	return nil
}

// when is the sort key: the activity's day, else the day it was handed
// over (created_at's UTC date).
func (h handover) when() time.Time {
	if d := h.day(); d != nil {
		return *d
	}
	c := h.created.UTC()
	return time.Date(c.Year(), c.Month(), c.Day(), 0, 0, 0, 0, time.UTC)
}

// nextAction is partner_oversight_service._set_next_action: who the
// hand-over waits on, and for what.
func (h handover) nextAction(scheduled, returned bool, partner, cceo string) (owner, action string) {
	pr := rules.Participation
	if cceo == "" {
		cceo = "CCEO"
	}
	switch {
	case returned:
		return cceo, "Review the return and decide what happens next"
	case !scheduled:
		return partner, "Schedule the assignment"
	case slices.Contains(pr.OversightCompleteStatuses, h.activityStatus):
		if h.payment == "" || h.payment == "none" || h.payment == "pending" {
			return "Accountant", "Pay the partner"
		}
		return "System", "Close the activity"
	case slices.Contains(pr.OversightAwaitingIAStatuses, h.activityStatus):
		if h.salesforce == "" {
			return cceo, "Enter the Salesforce Activity ID"
		}
		return "Impact Assessment", "Verify the submission"
	case slices.Contains(pr.OversightEvidenceReviewStatuses, h.activityStatus):
		return partner, "Submit the evidence to IA"
	case h.evidence == "" || h.evidence == "none":
		return partner, "Execute and upload evidence"
	}
	return partner, "Continue delivery"
}

// staffDirectory is _staff_directory's names: the CCEO on each hand-over,
// by either of their ids.
func (s *Service) staffDirectory(ctx context.Context, handovers []handover) (map[string]string, error) {
	names := map[string]string{}
	ids := []string{}
	for _, h := range handovers {
		if h.cceoID != "" {
			ids = append(ids, h.cceoID)
		}
	}
	if len(ids) == 0 {
		return names, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(NULLIF(u.name, ''), u.email, '')
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1))`, ids)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading hand-over officers: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, userID, name string
		if err := rows.Scan(&id, &userID, &name); err != nil {
			return nil, err
		}
		names[id] = name
		if userID != "" {
			names[userID] = name
		}
	}
	return names, rows.Err()
}

// djangoTitle is Django's |title: str.title(), then a letter after an
// apostrophe and one after a digit kept lower case.
func djangoTitle(s string) string {
	t := apostrophe.ReplaceAllStringFunc(pyTitle(s), strings.ToLower)
	return digitLetter.ReplaceAllStringFunc(t, strings.ToLower)
}

var (
	apostrophe  = regexp.MustCompile(`[a-z]'[A-Z]`)
	digitLetter = regexp.MustCompile(`\d[A-Z]`)
)

// ── The page reader's pairing (page_blocks._paired) ─────────────────────────

var (
	figure       = regexp.MustCompile(`^(?:—|[-+−]?(?:UGX\s+)?\d[\d,]*(?:\.\d+)?\s*(?:%|[KMB])?(?:\s*/\s*\d[\d,]*(?:\.\d+)?)?)$`)
	pagerCaption = regexp.MustCompile(`^Showing\s+\d`)
)

// pairedItems reads a label line followed by its figure ("Next: Pay the
// partner — Accountant", "UGX 40,000") as one data row, consecutive rows
// sharing a list, as the app is sent the existing page.
func pairedItems(items []*screensv1.PagePanelItem) []*screensv1.PagePanelItem {
	out := []*screensv1.PagePanelItem{}
	for i := 0; i < len(items); i++ {
		item := items[i]
		label := item.GetText()
		var after *screensv1.PagePanelItem
		if i+1 < len(items) {
			after = items[i+1]
		}
		isPair := isTextItem(item) && !pagerCaption.MatchString(label) && after != nil && isTextItem(after) &&
			strings.IndexFunc(label, unicode.IsLetter) >= 0 && figure.MatchString(strings.TrimSpace(after.GetText()))
		if !isPair {
			out = append(out, item)
			continue
		}
		row := &screensv1.PageDataRow{Label: label, Value: strings.TrimSpace(after.GetText()), Tone: after.GetTone()}
		if n := len(out); n > 0 && out[n-1].GetRows() != nil {
			out[n-1].GetRows().Rows = append(out[n-1].GetRows().Rows, row)
		} else {
			out = append(out, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: []*screensv1.PageDataRow{row}}}})
		}
		i++
	}
	return out
}

func isTextItem(item *screensv1.PagePanelItem) bool {
	_, ok := item.GetKind().(*screensv1.PagePanelItem_Text)
	return ok
}
