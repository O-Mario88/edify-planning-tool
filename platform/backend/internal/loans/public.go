package loans

import (
	"context"
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"html/template"
	"io/fs"
	"log/slog"
	"mime"
	"net"
	"net/http"
	"net/url"
	"path"
	"strconv"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

//go:embed web
var webFiles embed.FS

// Public serves the pages a school uses without an account: the
// application form, its receipt and status page, and the privacy notice.
// Nothing on them needs, sets or reads a cookie.
type Public struct {
	store   *Store
	keys    Keys
	cfg     config.Loans
	limits  *Limiter
	logger  *slog.Logger
	now     func() time.Time
	pages   *template.Template
	version string
}

// Rate limits per client address.
const (
	pageViewsPerMinute   = 60
	submissionsPer10Min  = 8
	placeLookupsPerMin   = 120
	minimumFillTime      = 3 * time.Second
	formLifetime         = 24 * time.Hour
	maxFormBytes         = 64 << 10
	maxPlacesInAResponse = 500
)

// NewPublic returns the public pages.
func NewPublic(store *Store, keys Keys, cfg config.Loans, limits *Limiter, logger *slog.Logger, now func() time.Time) (*Public, error) {
	if now == nil {
		now = time.Now
	}
	pages, err := template.New("").Funcs(pageFuncs).ParseFS(webFiles, "web/templates/*.html")
	if err != nil {
		return nil, err
	}
	return &Public{store: store, keys: keys, cfg: cfg, limits: limits, logger: logger, now: now,
		pages: pages, version: assetVersion()}, nil
}

// Register adds the public routes to mux.
func (p *Public) Register(mux *http.ServeMux) {
	// The first links pointed here; they now lead to /loans/apply.
	mux.HandleFunc("GET /apply/school-loan", p.legacyForm)
	mux.HandleFunc("POST /apply/school-loan", p.submit)
	mux.HandleFunc("GET /apply/school-loan/places", p.places)
	mux.HandleFunc("GET /apply/school-loan/receipt", p.legacyReceipt)
	mux.HandleFunc("GET /apply/school-loan/privacy", p.privacy)
	mux.HandleFunc("GET /apply/static/{file}", serveStatic)
}

// assetVersion changes whenever the stylesheet or script does, so a phone
// never keeps an old copy past a change.
func assetVersion() string {
	sum := sha256.New()
	for _, name := range []string{"web/static/portal.css", "web/static/apply.js"} {
		raw, _ := webFiles.ReadFile(name)
		sum.Write(raw)
	}
	return hex.EncodeToString(sum.Sum(nil))[:10]
}

var staticFiles = map[string]bool{
	"portal.css": true, "apply.js": true, "edify-logo-white.png": true, "edify-logo-navy.png": true,
}

func serveStatic(writer http.ResponseWriter, request *http.Request) {
	name := request.PathValue("file")
	if !staticFiles[name] {
		http.NotFound(writer, request)
		return
	}
	raw, err := fs.ReadFile(webFiles, "web/static/"+name)
	if err != nil {
		http.NotFound(writer, request)
		return
	}
	writer.Header().Set("Content-Type", mime.TypeByExtension(path.Ext(name)))
	// The URL carries the asset version, so a long cache is safe.
	writer.Header().Set("Cache-Control", "public, max-age=604800, immutable")
	_, _ = writer.Write(raw)
}

// pageHeaders are the public pages' hardening: no framing, no inline
// script, no third-party anything, forms posting only to this site.
func pageHeaders(writer http.ResponseWriter) {
	header := writer.Header()
	header.Set("Content-Type", "text/html; charset=utf-8")
	header.Set("Content-Security-Policy", "default-src 'none'; style-src 'self'; script-src 'self'; "+
		"img-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
	header.Set("X-Frame-Options", "DENY")
	header.Set("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
	header.Set("Cross-Origin-Opener-Policy", "same-origin")
}

// clientKey is a keyed hash of the caller's address, for rate limits.
func (p *Public) clientKey(request *http.Request) string {
	return clientKey(p.keys, p.cfg.TrustProxyHeaders, request)
}

func clientKey(keys Keys, trustProxy bool, request *http.Request) string {
	address := request.RemoteAddr
	if host, _, err := net.SplitHostPort(address); err == nil {
		address = host
	}
	if trustProxy {
		if forwarded := request.Header.Get("X-Forwarded-For"); forwarded != "" {
			address = strings.TrimSpace(strings.Split(forwarded, ",")[0])
		}
	}
	return keys.NetworkKey(address)
}

type page struct {
	Title, Eyebrow, Heading, Lede string
	Facts                         []string
	Version                       string
	Script                        bool
}

type problemItem struct{ Field, Message string }

type duplicateView struct{ Reference, When string }

type formPage struct {
	page
	Values         url.Values
	Problems       Problems
	ProblemList    []problemItem
	Lenders        []Lender
	Purposes       []Purpose
	Religions      []Purpose
	Districts      []Place
	IdempotencyKey string
	Stamp          string
	Invite         string
	InvitedSchool  string
	InviteProblem  string
	// A lender's or a sharer's link: its id, the lender it fixes, and why
	// it could not be used.
	LinkID       string
	LockedLender string
	LinkProblem  string
	Total        string
	Duplicate    *duplicateView
}

// Value is a field as last submitted.
func (f formPage) Value(field string) string { return f.Values.Get(field) }

// Problem is what is wrong with a field.
func (f formPage) Problem(field string) string { return f.Problems[field] }

// Invalid marks a field with a problem for assistive technology.
func (f formPage) Invalid(field string) template.HTMLAttr {
	if f.Problems[field] == "" {
		return ""
	}
	return template.HTMLAttr(`aria-invalid="true"`)
}

// fieldOrder is the order problems are listed in, top to bottom.
var fieldOrder = []string{
	"form", "school_name", "director_name", "director_phone", "director_email", "religion",
	"district", "sub_county", "parish", "village", "boys", "girls", "fees_collected",
	"purpose", "purpose_other", "requested", "partner", "purpose_details", "term_months", "consent",
}

func (p *Public) formPage(ctx context.Context, values url.Values, problems Problems) (formPage, error) {
	lenders, err := p.store.Lenders(ctx)
	if err != nil {
		return formPage{}, err
	}
	districts, err := p.store.Districts(ctx)
	if err != nil {
		return formPage{}, err
	}
	key, err := NewIdempotencyKey()
	if err != nil {
		return formPage{}, err
	}
	// A re-shown form keeps its key, so the corrected submission is the
	// same application, never a second one.
	if previous := values.Get("idempotency_key"); idempotencyPattern.MatchString(previous) {
		key = previous
	}
	page := formPage{
		page: page{
			Title: "Apply for a school loan", Eyebrow: "Edify school loans", Heading: "Apply for a school loan",
			Lede:    "Tell us about your school and the loan you need. Edify sends your application to the lending partner you choose.",
			Facts:   []string{"About 5 minutes", "No account or password", "Reference given at once"},
			Version: p.version, Script: true,
		},
		Values: Cleaned(values), Problems: problems, Lenders: lenders, Purposes: Purposes,
		Religions: Religions, Districts: districts, IdempotencyKey: key,
		Stamp: p.keys.FormStamp(p.now()), Total: "—",
	}
	if boys, girls := wholeOrNil(values.Get("boys")), wholeOrNil(values.Get("girls")); boys != nil && girls != nil {
		page.Total = strconv.Itoa(*boys + *girls)
	}
	for _, field := range fieldOrder {
		if message := problems[field]; message != "" {
			target := field
			if field == "form" {
				target = "submit-button"
			}
			page.ProblemList = append(page.ProblemList, problemItem{Field: target, Message: message})
		}
	}
	return page, nil
}

func wholeOrNil(raw string) *int {
	value, err := strconv.Atoi(strings.ReplaceAll(strings.TrimSpace(raw), ",", ""))
	if err != nil || value < 0 {
		return nil
	}
	return &value
}

func (p *Public) render(writer http.ResponseWriter, status int, name string, data any) {
	pageHeaders(writer)
	writer.WriteHeader(status)
	if err := p.pages.ExecuteTemplate(writer, name, data); err != nil {
		p.logger.Error("loans: rendering a page", slog.String("page", name), slog.String("error", err.Error()))
	}
}

type messagePage struct {
	page
	MessageTitle, Message, Back, BackLabel string
}

func (p *Public) message(writer http.ResponseWriter, status int, title, message string) {
	p.render(writer, status, "message.html", messagePage{
		page:         page{Title: title, Eyebrow: "Edify school loans", Heading: title, Version: p.version},
		MessageTitle: title, Message: message, Back: "/apply/school-loan", BackLabel: "Go to the application form",
	})
}

func (p *Public) tooMany(writer http.ResponseWriter) {
	writer.Header().Set("Retry-After", "600")
	p.message(writer, http.StatusTooManyRequests, "Please wait a few minutes",
		"We have had many requests from your connection in a short time. Please wait a few minutes and try again.")
}

func (p *Public) unavailable(writer http.ResponseWriter, err error) {
	p.logger.Error("loans: public page failed", slog.String("error", err.Error()))
	p.message(writer, http.StatusServiceUnavailable, "Something went wrong",
		"We could not complete that just now, and nothing was submitted. Please try again in a few minutes.")
}

func (p *Public) form(writer http.ResponseWriter, request *http.Request) {
	if !p.limits.Allow("view:"+p.clientKey(request), pageViewsPerMinute, time.Minute) {
		p.tooMany(writer)
		return
	}
	values := url.Values{}
	data, err := p.formPage(request.Context(), values, Problems{})
	if err != nil {
		p.unavailable(writer, err)
		return
	}
	p.render(writer, http.StatusOK, "apply.html", data)
}

// legacyForm sends the first links, and their ?invite= tokens, to the
// /loans/apply paths.
func (p *Public) legacyForm(writer http.ResponseWriter, request *http.Request) {
	target := applyPath
	if token := request.URL.Query().Get("invite"); token != "" {
		target = invitationPath + url.PathEscape(token)
	}
	http.Redirect(writer, request, target, http.StatusMovedPermanently)
}

// legacyReceipt sends a receipt link of the first form to its new path.
func (p *Public) legacyReceipt(writer http.ResponseWriter, request *http.Request) {
	target := applyPath + "/receipt/" + url.PathEscape(request.URL.Query().Get("r"))
	if request.URL.Query().Get("new") == "1" {
		target += "?new=1"
	}
	http.Redirect(writer, request, target, http.StatusMovedPermanently)
}

// invitationForm is the form opened from a school's invitation link. An
// invalid or expired link still opens the ordinary form, saying so.
func (p *Public) invitationForm(writer http.ResponseWriter, request *http.Request) {
	if !p.limits.Allow("view:"+p.clientKey(request), pageViewsPerMinute, time.Minute) {
		p.tooMany(writer)
		return
	}
	data, err := p.formPage(request.Context(), url.Values{}, Problems{})
	if err != nil {
		p.unavailable(writer, err)
		return
	}
	p.applyInvitation(request.Context(), &data, request.PathValue("token"))
	p.render(writer, http.StatusOK, "apply.html", data)
}

// linkForm is the form opened from a lender's link (lender preselected,
// fixed when its policy says so) or a sharer's link (counted only).
func (p *Public) linkForm(kind string) http.HandlerFunc {
	return func(writer http.ResponseWriter, request *http.Request) {
		if !p.limits.Allow("view:"+p.clientKey(request), pageViewsPerMinute, time.Minute) {
			p.tooMany(writer)
			return
		}
		data, err := p.formPage(request.Context(), url.Values{}, Problems{})
		if err != nil {
			p.unavailable(writer, err)
			return
		}
		if link := p.applyLink(request.Context(), &data, request.PathValue("id")); link != nil && link.Kind != kind {
			data.LinkID, data.LockedLender, data.LinkProblem = "", "", "This link is not valid. You can still apply below."
			data.Values.Del("partner")
		}
		p.render(writer, http.StatusOK, "apply.html", data)
	}
}

// applyLink applies a share link to the form: a live lender link preselects
// its lender (fixes it, if its policy says so) while that lender is
// receiving applications. It reveals nothing and proves nothing.
func (p *Public) applyLink(ctx context.Context, data *formPage, id string) *ShareLink {
	if id == "" {
		return nil
	}
	link, err := p.store.LiveShareLink(ctx, id)
	if err != nil {
		data.LinkProblem = "This link has been replaced or is not valid. You can still apply below."
		return nil
	}
	data.LinkID = link.ID
	if link.Kind != LinkPartner {
		return &link
	}
	for _, lender := range data.Lenders {
		if lender.PartnerID == link.PartnerID {
			data.Values.Set("partner", link.PartnerID)
			if link.LockPartner {
				data.LockedLender = lender.Name
			}
			return &link
		}
	}
	data.LinkProblem = link.LenderName + " is not receiving applications through Edify right now. You can choose another lending partner below."
	return &link
}

// applyInvitation shows which school an invitation link was sent to and
// fills in its name; it fills in nothing confidential and proves nothing.
func (p *Public) applyInvitation(ctx context.Context, data *formPage, token string) *Invitation {
	if token == "" {
		return nil
	}
	invitation, err := p.store.InvitationByToken(ctx, HashToken(token), p.now())
	if err != nil {
		data.InviteProblem = "This invitation link has expired or is not valid."
		return nil
	}
	data.Invite = token
	data.InvitedSchool = invitation.School.Name
	if data.Values.Get("school_name") == "" {
		data.Values.Set("school_name", invitation.School.Name)
	}
	return &invitation
}

func (p *Public) submit(writer http.ResponseWriter, request *http.Request) {
	client := p.clientKey(request)
	if !p.limits.Allow("submit:"+client, submissionsPer10Min, 10*time.Minute) {
		p.tooMany(writer)
		return
	}
	request.Body = http.MaxBytesReader(writer, request.Body, maxFormBytes)
	if err := request.ParseForm(); err != nil {
		p.message(writer, http.StatusBadRequest, "The form could not be read",
			"Please go back, check your answers and submit again.")
		return
	}
	values := request.PostForm
	input, problems := ParseForm(values)
	if strings.TrimSpace(values.Get("website")) != "" {
		problems["form"] = "We could not accept this form. Please reload the page and try again."
		p.logger.Warn("loans: a submission filled the hidden field", slog.String("client", client))
	}
	switch age, ok := p.keys.StampAge(values.Get("stamp"), p.now()); {
	case !ok || age > formLifetime:
		problems["form"] = "This form has expired. Please check your answers and submit again."
	case age < minimumFillTime:
		problems["form"] = "Please check your answers, then submit again."
	}

	ctx := request.Context()
	if len(problems) > 0 {
		p.reshow(writer, request, values, problems)
		return
	}
	data := formPage{Values: url.Values{}}
	invitation := p.applyInvitation(ctx, &data, input.InviteToken)
	shareLinkID := ""
	if link, err := p.store.LiveShareLink(ctx, values.Get("link")); err == nil {
		shareLinkID = link.ID
		if link.Kind == LinkPartner && link.LockPartner && input.PartnerID != link.PartnerID {
			// A lender's fixed link sends to that lender, whatever was posted.
			p.reshow(writer, request, values, Problems{"partner": "This link sends applications to " + link.LenderName + " only."})
			return
		}
	}
	place, err := p.store.ResolvePlace(ctx, input)
	if err != nil {
		p.unavailable(writer, err)
		return
	}
	match, err := p.match(ctx, input, place, invitation)
	if err != nil {
		p.unavailable(writer, err)
		return
	}
	submitted, err := p.store.Submit(ctx, p.keys, NewApplication{
		Input: input, Place: place, Match: match, Invitation: invitation, ShareLinkID: shareLinkID, Now: p.now(),
	})
	var duplicate *DuplicateError
	switch {
	case errors.Is(err, ErrLenderUnavailable):
		p.reshow(writer, request, values, Problems{
			"partner": "That lending partner is not receiving applications right now. Choose another, or try again later.",
		})
		return
	case errors.As(err, &duplicate):
		data, renderErr := p.formPage(ctx, values, Problems{})
		if renderErr != nil {
			p.unavailable(writer, renderErr)
			return
		}
		p.applyInvitation(ctx, &data, values.Get("invite"))
		p.applyLink(ctx, &data, values.Get("link"))
		data.Duplicate = &duplicateView{Reference: duplicate.Reference, When: longDay(duplicate.SubmittedAt)}
		p.render(writer, http.StatusOK, "apply.html", data)
		return
	case err != nil:
		p.unavailable(writer, err)
		return
	}
	p.logger.Info("loans: application received", slog.String("reference", submitted.Reference),
		slog.Bool("replayed", submitted.Replayed), slog.String("school_match", match.Status))
	http.Redirect(writer, request, applyPath+"/receipt/"+url.PathEscape(submitted.ReceiptToken)+"?new=1", http.StatusSeeOther)
}

func (p *Public) reshow(writer http.ResponseWriter, request *http.Request, values url.Values, problems Problems) {
	data, err := p.formPage(request.Context(), values, problems)
	if err != nil {
		p.unavailable(writer, err)
		return
	}
	p.applyInvitation(request.Context(), &data, values.Get("invite"))
	p.applyLink(request.Context(), &data, values.Get("link"))
	p.render(writer, http.StatusUnprocessableEntity, "apply.html", data)
}

// match finds the submission's school in the directory, or leaves it for a
// BTO. A typed district is searched by name across the country, and then
// only for candidates.
func (p *Public) match(ctx context.Context, input Input, place ResolvedPlace, invitation *Invitation) (Match, error) {
	if invitation != nil {
		return DecideMatch(MatchQuery{Name: input.SchoolName}, nil, &invitation.School), nil
	}
	query := MatchQuery{Name: input.SchoolName, DistrictKnown: place.DistrictID != "", SubCountyID: place.SubCountyID}
	if place.DistrictID != "" {
		schools, err := p.store.SchoolsInDistrict(ctx, place.DistrictID)
		if err != nil {
			return Match{}, err
		}
		return DecideMatch(query, schools, nil), nil
	}
	word := distinctiveWord(input.SchoolName)
	if word == "" {
		return Match{Status: MatchUnmatched}, nil
	}
	schools, err := p.store.SchoolsNamed(ctx, word)
	if err != nil {
		return Match{}, err
	}
	return DecideMatch(query, schools, nil), nil
}

func distinctiveWord(name string) string {
	longest := ""
	for _, word := range strings.Fields(NormalizeSchoolName(name)) {
		if !commonWords[word] && len(word) > len(longest) {
			longest = word
		}
	}
	if len(longest) < 3 {
		return ""
	}
	return longest
}

type receiptPage struct {
	page
	Receipt       Receipt
	Fresh         bool
	SubmittedOn   string
	StatusLabel   string
	DeliveryLabel string
	Progress      string
	TrackLink     string
}

func (p *Public) receiptPage(writer http.ResponseWriter, request *http.Request) {
	if !p.limits.Allow("view:"+p.clientKey(request), pageViewsPerMinute, time.Minute) {
		p.tooMany(writer)
		return
	}
	writer.Header().Set("Cache-Control", "no-store")
	writer.Header().Set("Referrer-Policy", "no-referrer")
	token := request.PathValue("token")
	receipt, err := p.store.ReceiptByToken(request.Context(), HashToken(token), p.now())
	if errors.Is(err, ErrNotFound) || token == "" {
		p.message(writer, http.StatusNotFound, "This link is not valid",
			"This application link has expired or is not valid. If you applied, contact your Edify officer and quote your application reference.")
		return
	}
	if err != nil {
		p.unavailable(writer, err)
		return
	}
	fresh := request.URL.Query().Get("new") == "1"
	heading := "Your loan application"
	if fresh {
		heading = "Application received"
	}
	p.render(writer, http.StatusOK, "receipt.html", receiptPage{
		page: page{Title: "Your loan application", Eyebrow: "Edify school loans", Heading: heading,
			Version: p.version, Script: true},
		Receipt: receipt, Fresh: fresh, SubmittedOn: longMoment(receipt.SubmittedAt),
		StatusLabel: StatusLabel(receipt.Status), DeliveryLabel: DeliveryLabel(receipt.DeliveryStatus),
		Progress: progressOf(receipt), TrackLink: p.cfg.PublicBaseURL + trackPath,
	})
}

// progressOf tells the applicant only what has been established: Edify
// received it; it was or was not yet sent; the lender opened it or recorded
// a stage. Nothing is claimed before it happened.
func progressOf(r Receipt) string {
	switch r.Status {
	case StatusReceived, StatusUnderReview:
		return r.LenderName + " has received your application and is reviewing it."
	case StatusInformationRequested:
		return r.LenderName + " has asked for more information. Expect them to contact the director."
	case StatusApproved:
		return r.LenderName + " has recorded that your loan is approved. They will contact the director about next steps."
	case StatusDeclined:
		return r.LenderName + " has recorded that it cannot offer this loan. Your Edify officer can talk you through other options."
	case StatusDisbursed:
		return r.LenderName + " has recorded that the loan was disbursed."
	case StatusWithdrawn:
		return "This application was withdrawn."
	case StatusClosed:
		return "This application is closed."
	}
	switch r.DeliveryStatus {
	case DeliveryOpened:
		return "Edify has sent your application to " + r.LenderName + ", and the lender has opened it."
	case DeliverySent:
		return "Edify has sent your application to " + r.LenderName + ". The lender has not yet confirmed receipt."
	case DeliveryFailed:
		return "Edify has received your application. Sending it to " + r.LenderName + " is delayed; Edify staff have been alerted and will forward it."
	}
	return "Edify has received your application and will send it to " + r.LenderName + ". This page will show when it has been sent."
}

type privacyPage struct {
	page
	Contact, ConsentVersion string
}

func (p *Public) privacy(writer http.ResponseWriter, request *http.Request) {
	contact := p.cfg.PrivacyContact
	if contact == "" {
		contact = "Speak to your Edify officer, or contact Edify's office in your country."
	}
	p.render(writer, http.StatusOK, "privacy.html", privacyPage{
		page: page{Title: "Privacy notice", Eyebrow: "Edify school loans", Heading: "How Edify uses your application",
			Version: p.version},
		Contact: contact, ConsentVersion: ConsentVersion,
	})
}

func (p *Public) places(writer http.ResponseWriter, request *http.Request) {
	if !p.limits.Allow("places:"+p.clientKey(request), placeLookupsPerMin, time.Minute) {
		writer.WriteHeader(http.StatusTooManyRequests)
		return
	}
	query := request.URL.Query()
	district, subCounty := strings.TrimSpace(query.Get("district")), strings.TrimSpace(query.Get("sub_county"))
	var found []Place
	var err error
	switch {
	case district != "" && subCounty != "":
		found, err = p.store.Parishes(request.Context(), district, subCounty)
	case district != "":
		found, err = p.store.SubCounties(request.Context(), district)
	}
	if err != nil {
		p.logger.Error("loans: reading places", slog.String("error", err.Error()))
		writer.WriteHeader(http.StatusServiceUnavailable)
		return
	}
	// Names only: the directory's ids never leave the server.
	names := make([]string, 0, len(found))
	for index, place := range found {
		if index == maxPlacesInAResponse {
			break
		}
		names = append(names, place.Name)
	}
	writer.Header().Set("Content-Type", "application/json")
	writer.Header().Set("Cache-Control", "public, max-age=3600")
	_ = json.NewEncoder(writer).Encode(map[string][]string{"places": names})
}

// pageFuncs are the helpers the templates use.
var pageFuncs = template.FuncMap{
	"ugx": FormatUGX,
	"ugxp": func(value *int64) string {
		if value == nil {
			return ""
		}
		return FormatUGX(*value)
	},
	"day":         longDay,
	"moment":      longMoment,
	"money":       moneyText,
	"status":      StatusLabel,
	"actionLabel": func(action string) string { return actionLabels[action] },
	"eventLabel":  func(kind string) string { return eventLabel(kind) },
}

var actionLabels = map[string]string{
	ActionAcknowledge:        "Acknowledge receipt",
	ActionStartReview:        "Mark as under review",
	ActionRequestInformation: "Request more information",
	ActionApprove:            "Record approval",
	ActionDecline:            "Record decline",
	ActionDisburse:           "Confirm disbursement",
	ActionClose:              "Close",
	ActionWithdraw:           "Withdraw",
}

var eventLabels = map[string]string{
	"submitted":             "Application submitted",
	"school_matched":        "Linked to the School Directory",
	"delivery_sent":         "Sent to the lender",
	"delivery_failed":       "Delivery failed",
	"delivery_resent":       "Sent again",
	"lender_opened":         "Opened by the lender",
	"lender_acknowledged":   "Receipt acknowledged",
	"status_changed":        "Under review",
	"information_requested": "More information requested",
	"approved":              "Approved",
	"declined":              "Declined",
	"disbursed":             "Disbursement confirmed",
	"closed":                "Closed",
	"withdrawn":             "Withdrawn",
	"lender_message":        "Message from the lender",
	"follow_up":             "Follow-up recorded",
	"oversight_note":        "Oversight note",
	"tracking_updated":      "Tracking updated",
	"school_match_resolved": "School match resolved",
	"loan_linked":           "Linked to a registered loan",
}

func eventLabel(kind string) string {
	if label, ok := eventLabels[kind]; ok {
		return label
	}
	return kind
}

func longDay(at time.Time) string { return at.In(kampala).Format("2 January 2006") }

func longMoment(at time.Time) string { return at.In(kampala).Format("2 January 2006, 15:04") + " EAT" }

// moneyText formats a stored decimal amount, such as "1500000.00", as UGX.
func moneyText(raw string) string {
	m, err := ledger.ParseMoney(raw)
	if err != nil {
		return raw
	}
	return ledger.FormatUGX(m)
}
