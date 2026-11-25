package iareports

// The Country Director's response to a released report's recommendation
// (recommendation_drawer, recommendation_respond →
// reports.respond_to_recommendation).

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const eventResponded = "ia.report.recommendation_responded"

// responses are reports.RESPONSES, in their order.
var responses = [][2]string{{"accepted", "Accept"}, {"in_progress", "In progress"}, {"done", "Done"},
	{"deferred", "Defer (say why)"}, {"rejected", "Reject (say why)"}}

var recommendationLabels = map[string]string{"proposed": "Proposed", "accepted": "Accepted", "rejected": "Rejected",
	"deferred": "Deferred", "in_progress": "In progress", "done": "Done"}

type recommendation struct {
	id, text, owner, status, response string
	due                               *time.Time
}

// isCountryCD is _is_country_cd.
func isCountryCD(ctx context.Context, q schooldirectory.Querier, p auth.Principal, country string) (bool, error) {
	if p.ActiveRole != "CountryDirector" || country == "" {
		return false, nil
	}
	mine, err := profileCountry(ctx, q, p)
	return mine == country, err
}

func (r Reports) readRecommendation(ctx context.Context, q schooldirectory.Querier, reportID, id string, lock bool) (*recommendation, error) {
	var x recommendation
	suffix := ""
	if lock {
		suffix = " FOR UPDATE"
	}
	err := q.QueryRow(ctx, `SELECT id, text, owner_role, status, response, due_date FROM impact_report_recommendation
WHERE id = $1 AND report_id = $2`+suffix, id, reportID).Scan(&x.id, &x.text, &x.owner, &x.status, &x.response, &x.due)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("iareports: the recommendation: %w", err)
	}
	return &x, nil
}

// respondDrawer is recommendation_drawer.
func (r Reports) respondDrawer(ctx context.Context, p auth.Principal, reportID, id string) (*screensv1.PageDrawer, error) {
	x, err := r.visible(ctx, r.DB, p, reportID, false)
	if err != nil || x == nil {
		if err == nil {
			err = errNoReport
		}
		return nil, err
	}
	rec, err := r.readRecommendation(ctx, r.DB, reportID, id, false)
	if err != nil || rec == nil {
		if err == nil {
			err = errNoReport
		}
		return nil, err
	}
	due := ""
	if rec.due != nil {
		due = rec.due.Format("2 Jan 2006")
	}
	status := rec.status
	if l, ok := recommendationLabels[status]; ok {
		status = l
	}
	facts := []*screensv1.PageFact{{Label: "Recommendation", Value: orDash(rec.text)}, {Label: "For", Value: orDash(ownerLabel(rec.owner))},
		{Label: "Due by", Value: orDash(due)}, {Label: "Status", Value: orDash(status)}}
	if rec.response != "" {
		facts = append(facts, &screensv1.PageFact{Label: "Response", Value: rec.response})
	}
	factItem := &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: facts}}}
	cd, err := isCountryCD(ctx, r.DB, p, x.country)
	if err != nil {
		return nil, err
	}
	if !(x.status == "released" && cd) {
		return &screensv1.PageDrawer{Title: "Recommendation", Subtitle: x.title, HasRequired: true, CancelLabel: "Cancel",
			Items: []*screensv1.DrawerItem{factItem, note("The country's Country Director responds once the report is released.")}}, nil
	}
	value := rec.status
	if value == "proposed" {
		value = "accepted"
	}
	options := []*screensv1.DrawerOption{}
	for _, o := range responses {
		options = append(options, &screensv1.DrawerOption{Value: o[0], Label: o[1]})
	}
	return &screensv1.PageDrawer{Title: "Respond to the recommendation", Subtitle: x.title, HasRequired: true,
		SubmitLabel: "Save response", CancelLabel: "Cancel", CanSubmit: true, Items: []*screensv1.DrawerItem{factItem,
			field(&screensv1.DrawerField{Name: "status", Label: "Response", Kind: "select", Required: true, Value: value, Options: options}),
			field(&screensv1.DrawerField{Name: "response", Label: "What you decided and why", Kind: "textarea", MaxLength: proto.Int32(4000),
				Value: rec.response}),
		}}, nil
}

func orDash(s string) string {
	if s == "" {
		return "—"
	}
	return s
}

// respond is reports.respond_to_recommendation.
func (r Reports) respond(ctx context.Context, p auth.Principal, reportID, id string, values map[string]string) (Saved, error) {
	status := values["status"]
	words := strings.TrimSpace(values["response"])
	known := false
	for _, o := range responses {
		known = known || o[0] == status
	}
	if !known {
		return Saved{}, refuse("Choose a response from the list.")
	}
	if (status == "rejected" || status == "deferred") && words == "" {
		return Saved{}, refuse("Say why the recommendation is rejected or deferred.")
	}
	if utf8.RuneCountInString(words) > 4000 {
		return Saved{}, refuse("The response must be 4000 characters or fewer.")
	}
	now := r.now()
	var x *report
	var rec *recommendation
	err := pgx.BeginTxFunc(ctx, r.DB, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		var err error
		if x, err = r.visible(ctx, tx, p, reportID, false); err != nil {
			return err
		}
		if x != nil {
			rec, err = r.readRecommendation(ctx, tx, reportID, id, true)
			if err != nil {
				return err
			}
		}
		if x == nil || rec == nil {
			return refuse("That recommendation is not in your country.")
		}
		cd, err := isCountryCD(ctx, tx, p, x.country)
		if err != nil {
			return err
		}
		if !cd {
			return refuse("The country's Country Director responds to recommendations.")
		}
		if x.status != "released" {
			return refuse("Recommendations are answered once the report is released.")
		}
		if _, err := tx.Exec(ctx, `UPDATE impact_report_recommendation SET status = $2, response = $3, responded_by_id = $4,
  responded_at = $5, updated_at = $5 WHERE id = $1`, id, status, words, p.UserID, now); err != nil {
			return fmt.Errorf("iareports: saving the response: %w", err)
		}
		var hash string
		_ = tx.QueryRow(ctx, `SELECT snapshot_hash FROM impact_report WHERE id = $1`, reportID).Scan(&hash)
		var noted any
		if words != "" {
			noted = words
		}
		e := reportAudit("ia.report.recommendation_responded", reportID, p, x.country, x.version, x.status, hash,
			map[string]any{"recommendation_id": id, "response_status": status, "note": noted})
		if words != "" {
			reason := words
			if len([]rune(reason)) > 500 {
				reason = string([]rune(reason)[:500])
			}
			e.Reason = &reason
		}
		_, err = audit.Append(ctx, tx, e, now)
		return err
	})
	if err != nil {
		return Saved{}, err
	}
	body := words
	if body == "" {
		body = rec.text
		if len([]rune(body)) > 300 {
			body = string([]rune(body)[:300])
		}
	}
	if len([]rune(body)) > 500 {
		body = string([]rune(body)[:500])
	}
	title := "Recommendation " + lower(recommendationLabels[status]) + ": " + x.title
	if len([]rune(title)) > 200 {
		title = string([]rune(title)[:200])
	}
	if err := activities.SendNotices(ctx, r.DB, r.Push, r.Live, r.Logger, r.now(), x.id, "", activities.Origin{},
		activities.Notice{Title: title, Body: body, Event: eventResponded, Category: "ia", ContextType: "ImpactReport", Priority: "normal"},
		[]activities.NoticeTo{{UserID: x.author, Route: PagePath + x.id + "/#recommendations", Label: "Open Report"}}); err != nil && r.Logger != nil {
		r.Logger.Warn("iareports: Impact Assessment was not told", "report", x.id, "err", err)
	}
	return Saved{Message: "Response recorded; Impact Assessment has been told.", ReportID: reportID}, nil
}
