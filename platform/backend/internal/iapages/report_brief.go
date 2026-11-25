package iapages

// A partner school's impact brief (impact_report_views.brief_page,
// pages/ia/impact_reports_brief.html) as the feed reads it: the school's own
// results from a released report, the findings and limitations scrubbed of
// every other school and person, and for its account owner the form that
// records that it was shared.

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

var briefPath = regexp.MustCompile(`^/impact-briefs/([A-Za-z0-9]{1,30})/$`)

// activeActionStates are action_models.ACTIVE_STATES.
var activeActionStates = []string{"open", "acknowledged", "in_progress", "blocked", "overdue"}

// Brief is brief_for: the release, its to-do, and whether p records the
// sharing; nil when p may not open it.
type Brief struct {
	ReleaseID, ReportID, SchoolID, Country string
	ActionID, ActionState, Resolution      string
	Due, Released                          *time.Time
	Payload                                []byte
	MayRecord                              bool
}

// ReadBrief is reports.brief_for.
func ReadBrief(ctx context.Context, db interface {
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}, p auth.Principal, id string) (*Brief, error) {
	b := &Brief{ReleaseID: id}
	var recipient string
	err := db.QueryRow(ctx, `SELECT r.report_id, COALESCE(r.school_id, ''), rp.country, r.rendered_payload::text, r.released_at,
  COALESCE(a.id, ''), COALESCE(a.state, ''), COALESCE(a.manual_resolution_reason, ''), a.due_date, COALESCE(a.recipient_id, '')
FROM impact_report_release r JOIN impact_report rp ON rp.id = r.report_id
LEFT JOIN LATERAL (SELECT t.id, t.state, t.manual_resolution_reason, t.due_date, t.recipient_id FROM team_action t WHERE t.condition_key = 'impact_brief:' || r.id ORDER BY t.created_at DESC LIMIT 1) a ON TRUE
WHERE r.id = $1 AND r.audience = 'school'`, id).Scan(&b.ReportID, &b.SchoolID, &b.Country, &b.Payload, &b.Released,
		&b.ActionID, &b.ActionState, &b.Resolution, &b.Due, &recipient)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("iapages: the school brief: %w", err)
	}
	isRecipient := b.ActionID != "" && recipient == p.UserID
	allowed := isRecipient || p.ActiveRole == roleAdm
	if !allowed && (p.ActiveRole == roleIA || p.ActiveRole == roleCD) {
		var country string
		_ = db.QueryRow(ctx, `SELECT COALESCE(country, '') FROM staff_profile WHERE user_id = $1 LIMIT 1`, p.UserID).Scan(&country)
		allowed = strings.TrimSpace(country) == b.Country
	}
	if !allowed {
		return nil, nil
	}
	b.MayRecord = isRecipient
	if b.MayRecord {
		found := false
		for _, st := range activeActionStates {
			found = found || st == b.ActionState
		}
		b.MayRecord = found
	}
	return b, nil
}

func (s *Service) briefPage(ctx context.Context, p auth.Principal, id string) (*screensv1.GetPageResponse, bool, error) {
	if !pageaccess.CanOpen(p.ActiveRole, false, "/impact-briefs/"+id+"/") {
		return nil, true, pagegate.ErrNotAvailable
	}
	b, err := ReadBrief(ctx, s.db, p, id)
	if err != nil {
		return nil, true, err
	}
	if b == nil {
		return nil, true, pagegate.ErrNotAvailable
	}
	d := json.NewDecoder(bytes.NewReader(b.Payload))
	d.UseNumber()
	var payload map[string]any
	if err := d.Decode(&payload); err != nil {
		return nil, true, fmt.Errorf("iapages: reading the brief: %w", err)
	}
	school := strOr(obj(payload["school"])["name"])
	report := obj(payload["report"])
	header := &screensv1.PageHeader{Eyebrow: "Impact findings for the school", Title: school,
		Description: strOr(report["title"]) + " · " + strOr(report["period_start"]) + " to " + strOr(report["period_end"])}
	blocks := []*screensv1.PageBlock{}
	if b.ActionID != "" {
		words := b.Resolution
		if b.ActionState != "resolved" {
			due := ""
			if b.Due != nil {
				due = b.Due.Format("2 Jan 2006")
			}
			words = "Share this brief with the school on your next visit, then record what the school said below. Due " + due + "."
		}
		blocks = append(blocks, titled("", text(words)))
	}
	results := [][]string{}
	for _, raw := range list(payload["results"]) {
		r := obj(raw)
		before, after := "Not assessed", "Not assessed"
		if r["baseline"] != nil {
			before = pyStr(r["baseline"])
		}
		if r["follow_up"] != nil {
			after = pyStr(r["follow_up"])
		}
		change := signedText(r["change"])
		if change == "" {
			change = "Not measured"
		}
		results = append(results, []string{strOr(r["area"]), strOr(r["programme"]), before, after, change, strOr(r["status"])})
	}
	blocks = append(blocks, frozenTable(school, "The school's results", "results_page",
		[]string{"Area", "Programme", "Before", "After", "Change", "Status"}, results,
		"No results", "The report held no before-and-after assessment for this school.", nil)...)
	narrative := obj(payload["narrative"])
	findings, limitations := strOr(narrative["findings"]), strOr(narrative["limitations"])
	if findings == "" {
		findings = "—"
	}
	if limitations == "" {
		limitations = "—"
	}
	facts := []string{"Findings", linebreaksRead(findings), "Limitations", linebreaksRead(limitations)}
	for _, l := range list(payload["limitations"]) {
		facts = append(facts, "How to read the scores", strOr(l))
	}
	blocks = append(blocks, titled("What Impact Assessment found", paired(facts)...))
	if b.MayRecord {
		today := localDay(s.now()).Format(time.DateOnly)
		items := []*screensv1.PageFormItem{{Kind: &screensv1.PageFormItem_Field{Field: &screensv1.DrawerField{Name: "shared_on",
			Label: "Date shared", Kind: "date", Value: today, Required: true, MaxDate: today}}}}
		visits, err := s.ownerVisits(ctx, p, b)
		if err != nil {
			return nil, true, err
		}
		if len(visits) > 0 {
			options := []*screensv1.DrawerOption{{Label: "Not during a recorded visit"}}
			options = append(options, visits...)
			items = append(items, &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: &screensv1.DrawerField{Name: "visit",
				Label: "Visit it was shared on", Kind: "select", Options: options}}})
		}
		items = append(items, &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: &screensv1.DrawerField{Name: "school_response",
			Label: "What the school said", Kind: "textarea", Required: true, MaxLength: int32Ptr(2000)}}})
		// The feed could not save this form (it is not one of its saves); Go
		// saves it, so the phone can (a deliberate difference, doc 189).
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{
			Title: "Record that the findings were shared", Items: items, SubmitLabel: "Record as shared",
			Key: "/impact-briefs/" + id + "/shared", CanSave: true}}})
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: "/impact-briefs/" + id + "/"}, true, nil
}

func int32Ptr(v int32) *int32 { return &v }

// ownerVisits is _owner_visits: the reader's own visits to the school since
// the brief was released, newest first.
func (s *Service) ownerVisits(ctx context.Context, p auth.Principal, b *Brief) ([]*screensv1.DrawerOption, error) {
	if p.StaffProfileID == "" {
		return nil, nil
	}
	since := s.now()
	if b.Released != nil {
		since = *b.Released
	}
	rows, err := s.db.Query(ctx, `SELECT id, activity_type, planned_date FROM activity WHERE school_id = $1 AND responsible_staff_id = $2
  AND deleted_at IS NULL AND planned_date >= $3::date ORDER BY planned_date DESC LIMIT 20`, b.SchoolID, p.StaffProfileID,
		since.In(zone).Format(time.DateOnly))
	if err != nil {
		return nil, fmt.Errorf("iapages: the owner's visits: %w", err)
	}
	defer rows.Close()
	out := []*screensv1.DrawerOption{}
	for rows.Next() {
		var id, kind string
		var planned time.Time
		if err := rows.Scan(&id, &kind, &planned); err != nil {
			return nil, fmt.Errorf("iapages: an owner's visit: %w", err)
		}
		words := strings.ReplaceAll(kind, "_", " ")
		if words != "" {
			words = strings.ToUpper(words[:1]) + strings.ToLower(words[1:])
		}
		out = append(out, &screensv1.DrawerOption{Value: id, Label: words + " · " + planned.Format("2 Jan 2006")})
	}
	return out, rows.Err()
}
