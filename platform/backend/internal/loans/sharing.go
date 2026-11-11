package loans

import (
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"net/url"
	"strings"
	"time"

	"rsc.io/qr"
)

// Sharing the public application: its links, the approved messages that
// carry them, and their QR codes and posters. Every link opens the same
// public form; none opens anything private.

// Public application paths.
const (
	applyPath      = "/loans/apply"
	invitationPath = "/loans/apply/i/"
	partnerPath    = "/loans/apply/p/"
	referralPath   = "/loans/apply/r/"
	trackPath      = "/loans/track"
)

// Placeholders a share template may use.
const (
	placeholderLink   = "{application_link}"
	placeholderLender = "{lender_name}"
)

// defaultTemplates are the texts Edify ships with (owner's brief,
// 2026-11-11); a saved template replaces its channel's.
var defaultTemplates = map[string]ShareTemplate{
	"whatsapp": {Body: "Dear School Director,\nYou can now submit a school loan application through Edify's participating lending partners.\n" +
		"Open the link below, fill in your school details, select your preferred lender, and submit.\nApply: {application_link}\n" +
		"No signup or login is required.\nApplications are subject to the selected lender's assessment and approval.\nEdify Uganda."},
	"sms": {Body: "Edify Uganda: Apply for a school development loan through a participating lending partner. No signup required. Apply: {application_link}"},
	"email": {Subject: "Apply for a school loan through Edify",
		Body: "Dear School Director,\n\nYou can now submit a school loan application through Edify's participating lending partners.\n\n" +
			"Open the link below, fill in your school details, select your preferred lender, and submit.\n\nApply: {application_link}\n\n" +
			"No signup or login is required. Applications are subject to the selected lender's assessment and approval.\n\nEdify Uganda"},
}

// lenderTemplates carry a lender's link when it fixes the lender: the
// school does not choose, so the message says who receives it.
var lenderTemplates = map[string]ShareTemplate{
	"whatsapp": {Body: "Dear School Director,\nYou can now apply for a school loan from {lender_name} through Edify.\n" +
		"Open the link below, fill in your school details and submit. Your application goes to {lender_name}.\n" +
		"Apply: {application_link}\nNo signup or login is required.\nApplications are subject to {lender_name}'s assessment and approval.\nEdify Uganda."},
	"sms": {Body: "Edify Uganda: Apply for a school loan from {lender_name}. No signup required. Apply: {application_link}"},
	"email": {Subject: "Apply for a school loan from {lender_name}",
		Body: "Dear School Director,\n\nYou can now apply for a school loan from {lender_name} through Edify.\n\n" +
			"Open the link below, fill in your school details and submit. Your application goes to {lender_name}.\n\n" +
			"Apply: {application_link}\n\nNo signup or login is required. Applications are subject to {lender_name}'s assessment and approval.\n\nEdify Uganda"},
}

// Template limits.
const (
	maxSMSParts       = 3
	maxWhatsAppLength = 1000
	maxEmailLength    = 3000
	maxSubjectLength  = 150
)

// checkTemplate refuses a text that could not carry the link or would run
// to too many SMS parts.
func checkTemplate(t ShareTemplate) error {
	switch t.Channel {
	case "whatsapp", "sms", "email":
	default:
		return need("channel", "Choose WhatsApp, SMS or email.")
	}
	if !strings.Contains(t.Body, placeholderLink) {
		return need("body", "The message must include "+placeholderLink+", where the link goes.")
	}
	rest := strings.NewReplacer(placeholderLink, "", placeholderLender, "").Replace(t.Body + t.Subject)
	if strings.Contains(rest, "{") || strings.Contains(rest, "}") {
		return need("body", "Use only "+placeholderLink+" and "+placeholderLender+" in curly brackets.")
	}
	sample := renderShare(t, "https://edify.example/loans/apply/r/AAAAAAAAAAAAAAAAAAAAAA", "Example Lending Partner Ltd")
	switch {
	case t.Channel == "sms" && smsParts(sample.Body) > maxSMSParts:
		return need("body", fmt.Sprintf("With a link this runs to %d text messages; keep it to %d.", smsParts(sample.Body), maxSMSParts))
	case t.Channel == "whatsapp" && len([]rune(t.Body)) > maxWhatsAppLength:
		return need("body", fmt.Sprintf("Keep the WhatsApp message to %d characters.", maxWhatsAppLength))
	case t.Channel == "email" && (len([]rune(t.Body)) > maxEmailLength || len([]rune(t.Subject)) > maxSubjectLength):
		return need("body", "Keep the email shorter.")
	case t.Channel == "email" && strings.TrimSpace(t.Subject) == "":
		return need("subject", "An email needs a subject.")
	}
	return nil
}

// renderShare fills a template with a link and a lender's name.
func renderShare(t ShareTemplate, link, lender string) ShareTemplate {
	replace := strings.NewReplacer(placeholderLink, link, placeholderLender, lender)
	t.Body, t.Subject = replace.Replace(t.Body), replace.Replace(t.Subject)
	return t
}

// gsm7 is the GSM 03.38 basic character set; any other character makes an
// SMS Unicode, with fewer characters per part.
const gsm7 = "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"

// gsm7Extended characters take two places each.
const gsm7Extended = "^{}\\[~]|€\f"

// smsParts is how many messages an SMS body is sent as.
func smsParts(body string) int {
	units, unicode := 0, false
	for _, r := range body {
		switch {
		case strings.ContainsRune(gsm7, r):
			units++
		case strings.ContainsRune(gsm7Extended, r):
			units += 2
		default:
			unicode = true
		}
	}
	single, multi := 160, 153
	if unicode {
		units, single, multi = len([]rune(body)), 70, 67
	}
	if units <= single {
		return 1
	}
	return (units + multi - 1) / multi
}

// publicLink is an absolute link on the configured public address. Outside
// a developer's machine it must be HTTPS.
func publicLink(base, path string) (string, error) {
	base = strings.TrimRight(base, "/")
	parsed, err := url.Parse(base)
	if base == "" || err != nil || parsed.Host == "" {
		return "", errNoPublicAddress
	}
	local := parsed.Hostname() == "localhost" || parsed.Hostname() == "127.0.0.1"
	if parsed.Scheme != "https" && !local {
		return "", errNoPublicAddress
	}
	return base + path, nil
}

var errNoPublicAddress = errors.New("loans: no HTTPS public address is configured (EDIFY_PUBLIC_BASE_URL)")

// qrPNG encodes link at the "Q" level (a quarter of the code may be
// smudged or torn and it still scans), with a four-module quiet zone.
func qrPNG(link string) ([]byte, error) {
	code, err := qr.Encode(link, qr.Q)
	if err != nil {
		return nil, err
	}
	code.Scale = 12
	return code.PNG(), nil
}

type posterPage struct {
	page
	QR, Link, Lender string
}

// shareTarget is the public link a QR path stands for, if it still works.
func (p *Public) shareTarget(request *http.Request, kind, id string) (link, lender string, ok bool) {
	path := applyPath
	if kind != "" {
		shared, err := p.store.LiveShareLink(request.Context(), id)
		if err != nil || shared.Kind != kind {
			return "", "", false
		}
		path, lender = partnerPath+shared.ID, shared.LenderName
		if kind == LinkReferral {
			path, lender = referralPath+shared.ID, ""
		}
	}
	link, err := publicLink(p.cfg.PublicBaseURL, path)
	return link, lender, err == nil
}

func (p *Public) qr(kind string) http.HandlerFunc {
	return func(writer http.ResponseWriter, request *http.Request) {
		if !p.limits.Allow("qr:"+p.clientKey(request), pageViewsPerMinute, time.Minute) {
			p.tooMany(writer)
			return
		}
		link, _, ok := p.shareTarget(request, kind, request.PathValue("id"))
		if !ok {
			http.NotFound(writer, request)
			return
		}
		png, err := qrPNG(link)
		if err != nil {
			p.logger.Error("loans: drawing a QR code", slog.String("error", err.Error()))
			http.Error(writer, "unavailable", http.StatusServiceUnavailable)
			return
		}
		writer.Header().Set("Content-Type", "image/png")
		writer.Header().Set("Cache-Control", "public, max-age=3600")
		writer.Header().Set("X-Content-Type-Options", "nosniff")
		if request.URL.Query().Get("download") == "1" {
			writer.Header().Set("Content-Disposition", `attachment; filename="edify-school-loan-qr.png"`)
		}
		_, _ = writer.Write(png)
	}
}

func (p *Public) poster(kind string) http.HandlerFunc {
	return func(writer http.ResponseWriter, request *http.Request) {
		if !p.limits.Allow("qr:"+p.clientKey(request), pageViewsPerMinute, time.Minute) {
			p.tooMany(writer)
			return
		}
		id := request.PathValue("id")
		link, lender, ok := p.shareTarget(request, kind, id)
		if !ok {
			p.message(writer, http.StatusNotFound, "This poster's link has been replaced",
				"Ask Edify or your lender for the current poster.")
			return
		}
		image := applyPath + "/qr.png"
		switch kind {
		case LinkPartner:
			image = partnerPath + id + "/qr.png"
		case LinkReferral:
			image = referralPath + id + "/qr.png"
		}
		p.render(writer, http.StatusOK, "poster.html", posterPage{
			page: page{Title: "Scan to apply for a school loan", Eyebrow: "Edify school loans",
				Heading: "Scan to Apply for a School Loan", Version: p.version},
			QR: image, Link: link, Lender: lender,
		})
	}
}

// RegisterShare adds the shared application routes to mux: the universal
// form, invitation, lender and referral links, their QR codes and posters.
func (p *Public) RegisterShare(mux *http.ServeMux) {
	mux.HandleFunc("GET "+applyPath, p.form)
	mux.HandleFunc("POST "+applyPath, p.submit)
	mux.HandleFunc("GET "+invitationPath+"{token}", p.invitationForm)
	mux.HandleFunc("GET "+partnerPath+"{id}", p.linkForm(LinkPartner))
	mux.HandleFunc("GET "+referralPath+"{id}", p.linkForm(LinkReferral))
	mux.HandleFunc("GET "+applyPath+"/qr.png", p.qr(""))
	mux.HandleFunc("GET "+partnerPath+"{id}/qr.png", p.qr(LinkPartner))
	mux.HandleFunc("GET "+referralPath+"{id}/qr.png", p.qr(LinkReferral))
	mux.HandleFunc("GET "+applyPath+"/poster", p.poster(""))
	mux.HandleFunc("GET "+partnerPath+"{id}/poster", p.poster(LinkPartner))
	mux.HandleFunc("GET "+referralPath+"{id}/poster", p.poster(LinkReferral))
	mux.HandleFunc("GET "+applyPath+"/receipt/{token}", p.receiptPage)
}
