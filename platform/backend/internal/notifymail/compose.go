package notifymail

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"text/template"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

// Message is MailMessage: one email.
type Message struct {
	To, Subject, Text, HTML string
}

// view is compose's template context.
type view struct {
	RecipientName, SenderName, Title, Body, ActionLabel, OpenURL, SettingsURL, SentAt string
	Urgent                                                                            bool
}

// compose is email_delivery.compose: the notification as the recipient reads
// it, with a subject that names only the kind of thing waiting.
func (h Handler) compose(ctx context.Context, pool *pgxpool.Pool, n notice, to recipient) (Message, error) {
	sender := ""
	if n.senderID != nil && *n.senderID != "" {
		err := pool.QueryRow(ctx, `SELECT COALESCE(name, '') FROM "user" WHERE id = $1`, *n.senderID).Scan(&sender)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return Message{}, fmt.Errorf("notifymail: reading the sender: %w", err)
		}
	}
	first := strings.Split(to.name, " ")[0]
	if first == "" {
		first = "there"
	}
	label := "Open in Edify"
	if n.actionLabel != nil && *n.actionLabel != "" {
		label = *n.actionLabel
	}
	base := strings.TrimRight(h.BaseURL, "/")
	zone := h.Kampala
	if zone == nil {
		zone = time.UTC
	}
	v := view{
		RecipientName: first, SenderName: sender, Title: n.title, Body: n.body, ActionLabel: label,
		OpenURL:     base + "/notifications/" + n.id + "/open",
		SettingsURL: base + "/notifications/#delivery-settings",
		SentAt:      n.sentAt.In(zone).Format("2 Jan 2006, 15:04"),
		Urgent:      n.priority == "urgent",
	}
	var text, html strings.Builder
	if err := textTemplate.Execute(&text, v); err != nil {
		return Message{}, err
	}
	if err := htmlTemplate.Execute(&html, escaped(v)); err != nil {
		return Message{}, err
	}
	return Message{To: to.email, Subject: subjectFor(n), Text: text.String(), HTML: html.String()}, nil
}

// subjectFor is subject_for.
func subjectFor(n notice) string {
	kind := n.category
	if kind == "" {
		kind = "general"
	}
	kind = strings.ReplaceAll(kind, "_", " ")
	wording := "Edify: a new " + kind + " notification"
	if n.actionRequired {
		wording = "Edify: a " + kind + " item needs your action"
	}
	if n.priority == "urgent" {
		return "Urgent: " + wording
	}
	return wording
}

// djangoEscape is Django's escape(): the five characters it replaces.
var djangoEscape = strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;", `"`, "&quot;", "'", "&#x27;")

// escaped is the context as the HTML template's autoescaping prints it.
func escaped(v view) view {
	e := djangoEscape.Replace
	return view{RecipientName: e(v.RecipientName), SenderName: e(v.SenderName), Title: e(v.Title), Body: e(v.Body),
		ActionLabel: e(v.ActionLabel), OpenURL: e(v.OpenURL), SettingsURL: e(v.SettingsURL), SentAt: e(v.SentAt),
		Urgent: v.Urgent}
}

// textTemplate is templates/emails/notification.txt.
var textTemplate = template.Must(template.New("txt").Parse(`Hello {{.RecipientName}},

{{if .SenderName}}{{.SenderName}} sent you this on Edify{{else}}Edify has {{if .Urgent}}an urgent notice{{else}}a notification{{end}} for you{{end}}:

{{.Title}}
{{if .Body}}
{{.Body}}
{{end}}
{{.ActionLabel}}: {{.OpenURL}}
You will be asked to sign in first if you are not already.

Sent {{.SentAt}}.

{{if .Urgent}}Urgent notices are always emailed.{{else}}Choose what Edify emails you: {{.SettingsURL}}{{end}}

— Edify Planning and Monitoring Tool

`))

// htmlTemplate is templates/emails/notification.html; the context arrives
// escaped as Django's autoescaping escapes it.
var htmlTemplate = template.Must(template.New("html").Parse(`<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><title>Edify</title></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:Geist,-apple-system,'Segoe UI',Helvetica,sans-serif;color:#1f2933">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f8;padding:24px 12px">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:8px;border:1px solid #dde3ea">
        <tr><td style="background:#2d4862;color:#ffffff;padding:14px 24px;border-radius:8px 8px 0 0;font-size:15px;font-weight:700">Edify Planning and Monitoring</td></tr>
        <tr><td style="padding:24px">
          <p style="margin:0 0 12px;font-size:14px">Hello {{.RecipientName}},</p>
          <p style="margin:0 0 16px;font-size:14px;color:#52606d">{{if .SenderName}}<strong style="color:#1f2933">{{.SenderName}}</strong> sent you this on Edify{{else}}Edify has {{if .Urgent}}an urgent notice{{else}}a notification{{end}} for you{{end}}:</p>
          {{if .Urgent}}<p style="margin:0 0 8px;font-size:12px;font-weight:700;color:#b42318;text-transform:uppercase;letter-spacing:.04em">Urgent</p>{{end}}
          <p style="margin:0 0 8px;font-size:16px;font-weight:700">{{.Title}}</p>
          {{if .Body}}<p style="margin:0 0 20px;font-size:14px;line-height:1.5;white-space:pre-line">{{.Body}}</p>{{end}}
          <p style="margin:0 0 20px"><a href="{{.OpenURL}}" style="display:inline-block;background:#2d4862;color:#ffffff;text-decoration:none;font-weight:700;font-size:14px;padding:10px 18px;border-radius:6px">{{.ActionLabel}}</a></p>
          <p style="margin:0 0 4px;font-size:12px;color:#7b8794">You will be asked to sign in first if you are not already.</p>
          <p style="margin:0;font-size:12px;color:#7b8794">Sent {{.SentAt}}.</p>
        </td></tr>
        <tr><td style="padding:14px 24px;border-top:1px solid #eef1f4;font-size:12px;color:#7b8794">{{if .Urgent}}Urgent notices are always emailed.{{else}}<a href="{{.SettingsURL}}" style="color:#2d4862">Choose what Edify emails you</a>.{{end}}</td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
`))
