package uploadcenter

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
)

// AgreementPath is the Policy Agreement Center
// (documents.views.agreement_center_view,
// pages/documents/agreement_center.html, under base.html's own chrome): each
// required policy waiting for the reader's response, with its reading time
// and the response and attestation forms, then their completed responses.
// Handed on: a reading that would give the reader a pending agreement first
// (AcknowledgementService.ensure_pending_for writes one for every mandatory
// policy in force whose audience holds them and that they have none for),
// and a reader with Safeguarding or the Apostles' Creed pending, whom the
// view sends to that document. Every save stays with the existing
// application.
const AgreementPath = "/policy-agreement"

// completedLimit is the view's [:50] of completed responses.
const completedLimit = 50

// firstAgreements are the onboarding commitments the view opens in place
// of the center while either is pending.
var firstAgreements = []string{"edify-safeguarding-policy", "edify-apostles-creed"}

// ack is a DocumentAcknowledgement with its document and version as the
// template reads them.
type ack struct {
	id, state, title, description, slug, reason, statement string
	version, required, active, sessions                    int
	effective, due, responded                              *time.Time
	download, commentRequired, offline                     bool
}

const ackColumns = `a.id, a.state, d.title, d.description, d.slug, d.acknowledgement_reason, d.agreement_statement,
  v.version_number, d.required_reading_minutes, a.active_reading_seconds, a.session_count,
  v.effective_date, a.due_date, a.responded_at, d.download_allowed, d.comment_required, a.offline_attestation`

const ackFrom = ` FROM document_acknowledgement a JOIN document_asset d ON d.id = a.document_id
JOIN document_version v ON v.id = a.version_id`

func readAcks(ctx context.Context, s *Service, where, order string, args ...any) ([]ack, error) {
	rows, err := s.db.Query(ctx, `SELECT `+ackColumns+ackFrom+` WHERE `+where+` ORDER BY `+order, args...)
	if err != nil {
		return nil, fmt.Errorf("uploadcenter: reading the reader's agreements: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (ack, error) {
		var x ack
		err := r.Scan(&x.id, &x.state, &x.title, &x.description, &x.slug, &x.reason, &x.statement, &x.version, &x.required,
			&x.active, &x.sessions, &x.effective, &x.due, &x.responded, &x.download, &x.commentRequired, &x.offline)
		return x, err
	})
	if err != nil {
		return nil, fmt.Errorf("uploadcenter: reading the reader's agreements: %w", err)
	}
	return list, nil
}

// completion is reading_completion_key and its label: reading time is a
// fact of its own, never the agreement.
func (x ack) completion() (key, label string) {
	switch {
	case x.offline:
		return "completed_offline", "Completed outside viewer"
	case x.required*60 <= 0:
		return "not_monitored", "Not monitored"
	case x.active >= x.required*60:
		return "completed", "Completed reading"
	case x.active <= 0:
		return "not_read", "Did not read"
	}
	return "partial", "Partial read"
}

// wouldAssign is whether ensure_pending_for would write: a mandatory
// policy in force, with a current version, that the reader has no
// acknowledgement of and whose audience holds them.
func (s *Service) wouldAssign(ctx context.Context, r reader, today time.Time) (bool, error) {
	rows, err := s.db.Query(ctx, `SELECT d.id FROM document_asset d
WHERE d.status = ANY($1) AND d.acknowledgement_required AND d.current_version_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM document_acknowledgement a WHERE a.document_id = d.id AND a.user_id = $2)`, readableStatuses, r.userID)
	if err != nil {
		return false, fmt.Errorf("uploadcenter: reading the policies in force: %w", err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil || len(ids) == 0 {
		return false, err
	}
	audiences, err := audienceRules(ctx, s.db, ids)
	if err != nil {
		return false, err
	}
	for _, id := range ids {
		aimed, err := matches(audiences[id], r, today)
		if errors.Is(err, errHandOn) || aimed {
			return true, nil
		}
		if err != nil {
			return false, err
		}
	}
	return false, nil
}

func (s *Service) agreement(ctx context.Context, p auth.Principal) (*screensv1.GetPageResponse, bool, error) {
	now := s.now().In(zone)
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	r := reader{userID: p.UserID, role: p.ActiveRole, slug: rules.Roles[p.ActiveRole].Slug}
	if err := s.db.QueryRow(ctx, `SELECT COALESCE((SELECT country FROM staff_profile WHERE user_id = $1 LIMIT 1), '')`, p.UserID).
		Scan(&r.country); err != nil {
		return nil, true, fmt.Errorf("uploadcenter: reading the reader's country: %w", err)
	}
	if assign, err := s.wouldAssign(ctx, r, today); err != nil || assign {
		return nil, err != nil, err
	}
	pending, err := readAcks(ctx, s, `a.user_id = $1 AND a.state = 'pending' AND d.status = ANY($2)`, "a.due_date, a.created_at",
		p.UserID, readableStatuses)
	if err != nil {
		return nil, true, err
	}
	for _, x := range pending {
		for _, first := range firstAgreements {
			if x.slug == first {
				return nil, false, nil // the view opens that document instead
			}
		}
	}
	completed, err := readAcks(ctx, s, `a.user_id = $1 AND a.state IN ('agreed', 'disagreed')`,
		"a.created_at DESC LIMIT "+strconv.Itoa(completedLimit), p.UserID)
	if err != nil {
		return nil, true, err
	}
	text := func(lines ...string) *screensv1.PageBlock {
		panel := &screensv1.PagePanel{}
		for _, l := range lines {
			panel.Items = append(panel.Items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: l}})
		}
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: panel}}
	}
	// base.html's own parts as the feed reads them (as on the policy
	// response page): the title, the loading and offline notices, Sign out.
	blocks := []*screensv1.PageBlock{
		text("Policy Agreement — Edify"),
		text("Loading your workspace…", "Preparing your dashboard…"),
		text("You are offline", "Changes cannot be sent. Keep this page open and reconnect to continue."),
		text("Sign out"),
	}
	content := feeddom.El("div", "")
	for _, x := range pending {
		content.Add(pendingCard(x), " ")
	}
	if len(pending) == 0 {
		content.Add(feeddom.El("div", "card p-16", " ", feeddom.El("p", "", "Nothing is waiting for you"), " ",
			feeddom.El("p", "", "You have responded to every policy required of you."), " ",
			feeddom.El("a", "", "Go to Edify").Attr("href", "/dashboard"), " "), " ")
	}
	if len(completed) > 0 {
		content.Add(completedCard(completed), " ")
	}
	blocks = feeddom.Walk(content, blocks)
	header := &screensv1.PageHeader{Eyebrow: "Required", Title: "Policy Agreement Center",
		Description: "Please read each document and record your response."}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: AgreementPath}, true, nil
}

// plural is the template's pluralize: "s" unless exactly one.
func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

// day is the template's date:"d M Y" in the site's zone, nothing for none.
func dayOf(t *time.Time) string {
	if t == nil {
		return ""
	}
	return t.In(zone).Format("02 Jan 2006")
}

// pendingCard is one pending policy's <section class="card">.
func pendingCard(x ack) *feeddom.Node {
	el := feeddom.El
	meta := "Version " + strconv.Itoa(x.version)
	if x.effective != nil {
		meta += " · effective " + x.effective.Format("02 Jan 2006")
	}
	if x.due != nil {
		meta += " · due " + x.due.Format("02 Jan 2006")
	}
	lead := el("div", "", " ", el("h2", "", x.title), " ", el("p", "", x.description), " ", el("p", "", meta), " ")
	if x.reason != "" {
		lead.Add(el("p", "", el("strong", "", "Why this is required:"), " ", x.reason), " ")
	}
	links := el("div", "flex", " ", el("a", "", "Read this document").Attr("href", "/documents/"+x.slug+"/"), " ")
	if x.download {
		links.Add(el("a", "", "Download").Attr("href", "/documents/"+x.slug+"/download"))
	}
	links.Add(" ")
	_, label := x.completion()
	minutes := x.required
	reading := el("p", "", "Active reading time ", el("span", "tabular-nums", strconv.Itoa(x.active)+"s"),
		" across "+strconv.Itoa(x.sessions)+" session"+plural(x.sessions)+" · "+strconv.Itoa(minutes)+" minute"+plural(minutes)+
			" required · ", el("strong", "", label), ". Only foreground, focused viewer time counts; agreement is recorded separately.")
	comment := "Comment"
	textarea := el("textarea", "").Attr("name", "comment", "rows", "3", "placeholder", "Anything you want HR to know. This is private.")
	if x.commentRequired {
		comment += " (required)"
		textarea.Attr("required", "")
	}
	respond := el("form", "", " ", el("input", "").Attr("type", "hidden", "name", "csrfmiddlewaretoken"), " ",
		el("p", "", x.statement), " ",
		el("fieldset", "", " ", el("legend", "", "Your response"), " ",
			el("label", "", " ", el("input", "").Attr("type", "radio", "name", "choice", "value", "agree", "required", ""), " I Agree "), " ",
			el("label", "", " ", el("input", "").Attr("type", "radio", "name", "choice", "value", "disagree", "required", ""), " I Disagree "), " "), " ",
		el("label", "flex flex-col gap-1", " ", el("span", "", " "+comment+" "), " ", textarea, " "), " ",
		el("label", "flex flex-col gap-1", " ", el("span", "", " Type your full name "), " ", el("input", "").Attr("name", "typed_full_name"), " "), " ",
		el("button", "", "Submit response").Attr("type", "submit"), " ").
		Attr("method", "post", "action", "/api/documents/acknowledge/"+x.id)
	attest := el("form", "", " ", el("input", "").Attr("type", "hidden", "name", "csrfmiddlewaretoken"), " ",
		el("label", "sr-only", "How you reviewed this document").Attr("for", "attest-"+x.id), " ",
		el("input", "").Attr("id", "attest-"+x.id, "name", "note", "placeholder", "Reviewed with a screen reader / a printed copy"), " ",
		el("button", "", "I reviewed this outside the viewer").Attr("type", "submit"), " ").
		Attr("method", "post", "action", "/api/documents/attest/"+x.id)
	return el("section", "card p-4 space-y-3", " ", lead, " ", links, " ", reading, " ", respond, " ", attest, " ")
}

// completedCard is "Your completed responses".
func completedCard(list []ack) *feeddom.Node {
	el := feeddom.El
	card := el("section", "card p-4", " ", el("h2", "", "Your completed responses"), " ")
	for _, x := range list {
		_, label := x.completion()
		tone := "bg-rose-100"
		if x.state == "agreed" {
			tone = "bg-emerald-100"
		}
		card.Add(el("div", "py-2", " ", el("div", "min-w-0", " ", el("p", "", x.title), " ",
			el("p", "", "v"+strconv.Itoa(x.version)+" · "+dayOf(x.responded)), " ",
			el("p", "", label+" · "+strconv.Itoa(x.active)+"s active"), " "), " ",
			el("span", "px-1.5 rounded-pill "+tone, rules.AcknowledgementStates[x.state]), " "), " ")
	}
	return card
}
