package partneroversight

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/jackc/pgx/v5"
)

// The partnership register (partner_engagement_views.engagement_register
// over partials/partners/engagement_register.html): the engagements a
// Programme Lead or the Country Director holds with a Partner, for the
// page's FY and the Partner tab in view.

// improvementsShown is how much of the agreed improvements a row shows.
const improvementsShown = 120

// engagement is one row of the register.
type engagement struct {
	id, author, partner, kind, subject, improvements, authorName string
	held                                                         time.Time
	due                                                          *time.Time
	done                                                         bool
	shared                                                       *time.Time
}

// engagementRegister is what the register shows: its rows, its counts and
// whether the reader sees who recorded each.
type engagementRegister struct {
	rows                              []engagement
	recorded, partnersEngaged, dueNow int
	authors                           bool
	reader                            string
	today                             time.Time
	// observations are the Regional Lead observations waiting on the
	// Partner, for a Programme Lead.
	observations []observation
}

// engagementsVisible is engagements_visible_to as a WHERE condition on e,
// its one argument (if any) written as {arg}: the Admin every engagement, a
// Programme Lead their own, the Country Director their country's (every one
// with no country on file); no one else any.
func engagementsVisible(ctx context.Context, db schooldirectory.Querier, p auth.Principal) (string, []any, error) {
	switch p.ActiveRole {
	case "Admin":
		return "TRUE", nil, nil
	case rules.PlanningLeadRole:
		return "e.author_id = {arg}", []any{p.UserID}, nil
	case "CountryDirector":
		var country string
		err := db.QueryRow(ctx, `SELECT COALESCE(btrim(country), '') FROM staff_profile WHERE user_id = $1 ORDER BY id LIMIT 1`,
			p.UserID).Scan(&country)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return "", nil, fmt.Errorf("partneroversight: reading the reader's country: %w", err)
		}
		if country == "" {
			return "TRUE", nil, nil
		}
		return "e.country = {arg}", []any{country}, nil
	}
	return "FALSE", nil, nil
}

// readRegister reads the register for the reader, the page's FY and the
// Partner in view ("" for every Partner). It is false when it holds more
// rows than one page, which is not drawn yet.
func (s *Service) readRegister(ctx context.Context, p auth.Principal, role Role, fy, partner string, today time.Time) (*engagementRegister, bool, error) {
	visible, args, err := engagementsVisible(ctx, s.db, p)
	if err != nil {
		return nil, true, err
	}
	reg := &engagementRegister{authors: p.ActiveRole != rules.PlanningLeadRole, reader: p.UserID, today: today}
	if err := s.db.QueryRow(ctx, `
SELECT count(*) FILTER (WHERE e.fy = $2), count(DISTINCT e.partner_id) FILTER (WHERE e.fy = $2),
  count(*) FILTER (WHERE e.follow_up_due <= $3 AND e.follow_up_done_at IS NULL)
FROM partner_engagement e WHERE ($1 = '' OR e.partner_id = $1) AND `+strings.ReplaceAll(visible, "{arg}", "$4"),
		append([]any{partner, fy, today}, args...)...).Scan(&reg.recorded, &reg.partnersEngaged, &reg.dueNow); err != nil {
		return nil, true, fmt.Errorf("partneroversight: counting the engagements: %w", err)
	}
	rows, err := s.db.Query(ctx, `
SELECT e.id, e.author_id, COALESCE(pt.name, ''), e.kind, e.held_on, e.subject, e.agreed_improvements,
  e.follow_up_due, e.follow_up_done_at IS NOT NULL, e.shared_with_partner_at, COALESCE(u.name, '')
FROM partner_engagement e
JOIN partner pt ON pt.id = e.partner_id
LEFT JOIN "user" u ON u.id = e.author_id
WHERE ($1 = '' OR e.partner_id = $1) AND e.fy = $2 AND `+strings.ReplaceAll(visible, "{arg}", "$3")+`
ORDER BY e.held_on DESC, e.created_at DESC, e.id
LIMIT `+strconv.Itoa(rules.EngagementRowLimit), append([]any{partner, fy}, args...)...)
	if err != nil {
		return nil, true, fmt.Errorf("partneroversight: reading the engagements: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var e engagement
		if err := rows.Scan(&e.id, &e.author, &e.partner, &e.kind, &e.held, &e.subject, &e.improvements,
			&e.due, &e.done, &e.shared, &e.authorName); err != nil {
			return nil, true, fmt.Errorf("partneroversight: reading the engagements: %w", err)
		}
		reg.rows = append(reg.rows, e)
	}
	if err := rows.Err(); err != nil {
		return nil, true, err
	}
	if role.ObservationsTile {
		if reg.observations, err = s.readObservations(ctx, p, partner); err != nil {
			return nil, true, err
		}
	}
	return reg, len(reg.rows) <= tablePageSize, nil
}

// followUpState is follow_up_state's words.
func (e engagement) followUpState(today time.Time) string {
	switch {
	case e.due == nil:
		return "No follow-up"
	case e.done:
		return "Followed up"
	case e.due.Before(today):
		return "Overdue since " + dayMonth(*e.due)
	case e.due.Equal(today):
		return "Due today"
	}
	return "Due " + dayMonth(*e.due)
}

func dayMonth(t time.Time) string { return strconv.Itoa(t.Day()) + " " + t.Month().String()[:3] }

// orDashText is the register cell's "—" for no text.
func orDashText(s string) string {
	if s == "" {
		return "—"
	}
	return s
}

// row is one engagement as the feed reads it: its text cells, then its
// buttons (Open; Follow up once the author's follow-up is due; Share until
// the author shares it).
func (r *engagementRegister) row(e engagement) *screensv1.PageRow {
	improvements := []rune(e.improvements)
	if len(improvements) > improvementsShown {
		improvements = improvements[:improvementsShown]
	}
	shared := "Not shared"
	if e.shared != nil {
		// The stored moment's own (UTC) day, as Django formats it.
		shared = "Shared " + jMY(ptr(e.shared.UTC()))
	}
	kind := e.kind
	if label, ok := rules.EngagementKindLabels[e.kind]; ok {
		kind = label
	}
	texts := []string{orDashText(e.subject), orDashText(e.partner), orDashText(kind), jMY(&e.held),
		orDashText(string(improvements)), e.followUpState(r.today), shared}
	if r.authors {
		texts = append(texts, orDashText(e.authorName))
	}
	cells := make([]*screensv1.PageCell, 0, len(texts)+1)
	for _, t := range texts {
		cells = append(cells, &screensv1.PageCell{Text: t})
	}
	base := rules.EngagementBaseURL + "/" + e.id
	button := func(label, href string) *screensv1.PageAction {
		return &screensv1.PageAction{Key: "button", Label: label, Primary: true, Enabled: true, Href: href, Drawer: true}
	}
	actions := []*screensv1.PageAction{button("Open", base)}
	mine := e.author == r.reader
	if mine && e.due != nil && !e.done && !e.due.After(r.today) {
		actions = append(actions, button("Follow up", base+"/follow-up"))
	}
	if mine && e.shared == nil {
		actions = append(actions, button("Share", base+"/share"))
	}
	return &screensv1.PageRow{Cells: append(cells, &screensv1.PageCell{Actions: actions})}
}

func ptr[T any](v T) *T { return &v }

// register is partials/partners/engagement_register.html: its title, its
// tiles (each a sentence, so the line under the figure is the note) and its
// table, the empty state when it has no rows.
func register(w workspace, reg *engagementRegister) []*screensv1.PageBlock {
	keys := []string{"recorded", "partners_engaged", "follow_ups_due"}
	if w.role.ObservationsTile {
		keys = append(keys, "observations")
	}
	values := map[string]int{}
	if reg != nil {
		values = map[string]int{"recorded": reg.recorded, "partners_engaged": reg.partnersEngaged, "follow_ups_due": reg.dueNow,
			"observations": len(reg.observations)}
	}
	figures := []schoolprofile.StripFigure{}
	for _, key := range keys {
		words := rules.EngagementMetricWords[key]
		figures = append(figures, schoolprofile.StripFigure{
			Label: words[0], Value: strconv.Itoa(values[key]), Helper: strings.ReplaceAll(words[1], "{fy}", w.period.fy),
		})
	}
	table := &screensv1.PageTable{}
	if reg == nil || len(reg.rows) == 0 {
		message, hint := readerEmpty, readerHint
		if w.role.RecordsEngagements {
			message, hint = recordedEmpty, recordedHint
		}
		table.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: message + " " + hint}}}}
		table.EmptyMessage = message
	} else {
		labels := []string{"Engagement", "Partner", "Kind", "Held", "Agreed improvements", "Follow-up", "Shared with partner"}
		if reg.authors {
			labels = append(labels, "Recorded by")
		}
		for _, l := range append(labels, "") {
			table.Columns = append(table.Columns, &screensv1.PageColumn{Label: l})
		}
		for _, e := range reg.rows {
			table.Rows = append(table.Rows, reg.row(e))
		}
	}
	out := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: registerTitle}}},
		schoolprofile.Strip(registerTilesTitle, figures),
	}
	if reg != nil && len(reg.observations) > 0 {
		out = append(out, observationsBlock(reg.observations, w.role.RecordsEngagements))
	}
	return append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}})
}

// observation is a Regional Lead observation still waiting on work with
// its Partner (open_observation_follow_ups).
type observation struct {
	partner, partnerName, label string
	held                        time.Time
}

// observationsShown is how many open observations the register lists.
const observationsShown = 5

// readObservations is open_observation_follow_ups for a Programme Lead:
// observations shared with them of a Partner-delivered training that ask to
// strengthen or replace it, oldest first, leaving out any an engagement
// names and any older than the Partner's latest engagement (by anyone).
// partner keeps the Partner in view's ("" every Partner's).
func (s *Service) readObservations(ctx context.Context, p auth.Principal, partner string) ([]observation, error) {
	staff := p.StaffProfileID
	if staff == "" {
		err := s.db.QueryRow(ctx, `SELECT id FROM staff_profile WHERE user_id = $1 ORDER BY id LIMIT 1`, p.UserID).Scan(&staff)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return nil, fmt.Errorf("partneroversight: reading the reader's staff profile: %w", err)
		}
	}
	if staff == "" {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `
WITH obs AS (
  SELECT r.id, r.held_on, r.created_at, r.recommendation, a.assigned_partner_id AS partner, a.planned_date,
    COALESCE(a.activity_name_snapshot, '') AS snapshot, COALESCE(a.activity_type, '') AS kind,
    COALESCE(sc.name, cl.name, '') AS place
  FROM cce_regional_engagement r
  JOIN activity a ON a.id = r.activity_id
  LEFT JOIN school sc ON sc.id = a.school_id
  LEFT JOIN cluster cl ON cl.id = a.cluster_id
  WHERE r.kind = 'training_observation' AND r.feedback_shared_at IS NOT NULL AND $1 = ANY(r.program_lead_ids)
    AND a.delivery_type = $2 AND a.assigned_partner_id IS NOT NULL AND r.recommendation = ANY($3)
), answering AS (
  SELECT e.partner_id, e.held_on, e.source_engagement_id FROM partner_engagement e
  WHERE e.partner_id IN (SELECT partner FROM obs)
)
SELECT o.partner, COALESCE(pt.name, 'the partner'), o.held_on, o.recommendation, o.planned_date, o.snapshot, o.kind, o.place
FROM obs o
LEFT JOIN partner pt ON pt.id = o.partner AND pt.deleted_at IS NULL
WHERE ($4 = '' OR o.partner = $4)
  AND NOT EXISTS (SELECT 1 FROM answering e WHERE e.source_engagement_id = o.id)
  AND NOT EXISTS (SELECT 1 FROM answering e WHERE e.partner_id = o.partner AND e.held_on >= o.held_on)
ORDER BY o.held_on, o.created_at, o.id`, staff, rules.PartnerDelivery, rules.PartnerActionRecommendations, partner)
	if err != nil {
		return nil, fmt.Errorf("partneroversight: reading the Regional Lead observations: %w", err)
	}
	defer rows.Close()
	out := []observation{}
	for rows.Next() {
		var o observation
		var recommendation, snapshot, kind, place string
		var planned *time.Time
		if err := rows.Scan(&o.partner, &o.partnerName, &o.held, &recommendation, &planned, &snapshot, &kind, &place); err != nil {
			return nil, fmt.Errorf("partneroversight: reading the Regional Lead observations: %w", err)
		}
		// cce_leadership.services.training_label, then the recommendation.
		when := "Undated"
		if planned != nil {
			when = dayMonth(*planned)
		}
		name := snapshot
		if name == "" {
			name = choiceLabel(kind, rules.Work.ActivityTypeLabels)
		}
		parts := []string{}
		for _, part := range []string{when, name, place, rules.ObservationRecommendations[recommendation]} {
			if part != "" {
				parts = append(parts, part)
			}
		}
		o.label = strings.Join(parts, " · ")
		out = append(out, o)
	}
	return out, rows.Err()
}

// observationsBlock is the register's note of the observations waiting on
// a Partner, as the feed reads it: its title, its sentence and a line for
// each of the first five (with its Follow up button's words for a reader
// who records engagements).
func observationsBlock(list []observation, records bool) *screensv1.PageBlock {
	text := func(t string) *screensv1.PagePanelItem {
		return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
	}
	partners, trainings := "a partner", "training"
	if len(list) != 1 {
		partners, trainings = "partners", "trainings"
	}
	links := []*screensv1.PageLink{}
	for i, o := range list {
		if i == observationsShown {
			break
		}
		line := o.partnerName + " · " + o.label + " · observed " + jMY(&o.held)
		if records {
			line += " Follow up"
		}
		links = append(links, &screensv1.PageLink{Text: line})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Badges: []*screensv1.PageBadge{},
		Items: []*screensv1.PagePanelItem{
			text("Regional Lead observations waiting on the partner"),
			text("The Regional Lead asked for work with " + partners + " after observing " + strconv.Itoa(len(list)) +
				" " + trainings + ", and no engagement has been recorded since."),
			{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: links}}},
		},
	}}}
}
