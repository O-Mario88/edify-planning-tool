package mypd

import (
	"context"
	"errors"
	"fmt"
	"math"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// DB is what the page reads and writes through: the gateway's pool.
type DB interface {
	schooldirectory.Querier
	BeginTx(ctx context.Context, opts pgx.TxOptions) (pgx.Tx, error)
}

// Service builds the page.
type Service struct {
	db     DB
	now    func() time.Time
	writes bool
}

// NewService is the page over db; writes is whether EDIFY_GO_PAGE_WRITES
// names it (off, the page is passed on).
func NewService(db DB, now func() time.Time, writes bool) *Service {
	return &Service{db: db, now: now, writes: writes}
}

// zone is the application's TIME_ZONE (and the process's, which
// date.today() reads).
var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		panic("mypd: " + err.Error())
	}
	return z
}()

// The model's field lengths and defaults the read's writes meet.
const (
	maxFY            = 16
	allocationStatus = "active"
	allocationCcy    = "USD"
	defaultCountry   = "Uganda"
)

type staff struct{ id, country string }

// Build answers the page; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != PagePath {
		return nil, false, nil
	}
	doors, known := rules.Doors[p.ActiveRole]
	if !known || !doors.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	for key := range query {
		if key != "fy" {
			return nil, false, nil
		}
	}
	if !s.writes {
		return nil, false, nil
	}
	now := s.now()
	fy := strings.TrimSpace(query.Get("fy"))
	if fy == "" {
		fy = schooldirectory.OperationalFY(now)
	}
	if len(fy) > maxFY {
		return nil, false, nil
	}
	sp, ok, err := s.staffOf(ctx, p.UserID)
	if err != nil {
		return nil, true, err
	}
	if !ok {
		// No staff profile: the page says why, and writes no allocation
		// (not built here).
		return nil, false, nil
	}
	today := dateOf(now.In(zone))
	if err := s.write(ctx, sp, fy, today); err != nil {
		return nil, true, err
	}
	v, err := s.read(ctx, p, sp, fy, today)
	if err != nil {
		return nil, true, err
	}
	if len(v.rows) > pageSize {
		return nil, false, nil
	}
	return v.page(doors, schooldirectory.FYOptions(now), now.In(zone)), true, nil
}

// pageSize is TABLE_PAGE_SIZE: a longer table has a pager (not built here).
const pageSize = 50

func dateOf(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}

// staffOf is user.staff_profile (the reverse one-to-one: the base manager).
func (s *Service) staffOf(ctx context.Context, userID string) (staff, bool, error) {
	var sp staff
	err := s.db.QueryRow(ctx, `SELECT id, COALESCE(country, '') FROM staff_profile WHERE user_id = $1 ORDER BY id LIMIT 1`,
		userID).Scan(&sp.id, &sp.country)
	if errors.Is(err, pgx.ErrNoRows) {
		return sp, false, nil
	}
	if err != nil {
		return sp, false, fmt.Errorf("mypd: reading the staff profile: %w", err)
	}
	return sp, true, nil
}

// write is what the existing read writes, in one transaction:
// PDCourseTrackingService.sync_all, then the year's allocation.
func (s *Service) write(ctx context.Context, sp staff, fy string, today time.Time) error {
	tx, err := s.db.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted})
	if err != nil {
		return fmt.Errorf("mypd: opening the read's writes: %w", err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	rows, err := tx.Query(ctx, `SELECT id, status, start_date, end_date FROM pd_request
		WHERE staff_id = $1 AND status = ANY($2) FOR UPDATE`, sp.id, []string{"enrollment_confirmed", "in_progress"})
	if err != nil {
		return fmt.Errorf("mypd: reading the courses to move on: %w", err)
	}
	type moving struct {
		id, status string
		start, end time.Time
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (moving, error) {
		var m moving
		return m, row.Scan(&m.id, &m.status, &m.start, &m.end)
	})
	if err != nil {
		return fmt.Errorf("mypd: reading the courses to move on: %w", err)
	}
	for _, m := range list {
		status, satisfied := m.status, []string{}
		if status == "enrollment_confirmed" && !today.Before(m.start) {
			status, satisfied = "in_progress", append(satisfied, rules.StartingEvent)
		}
		if status == "in_progress" && !today.Before(m.end) {
			status, satisfied = "ended", append(satisfied, rules.InProgressEvent)
		}
		if status == m.status {
			continue
		}
		if _, err := tx.Exec(ctx, `UPDATE pd_request SET status = $2, updated_at = now() WHERE id = $1`, m.id, status); err != nil {
			return fmt.Errorf("mypd: moving course %s on: %w", m.id, err)
		}
		// notifications.services.resolve_condition for the reminders the
		// clock ends, through its one narrow function
		// (deploy/db/mypd_roles.sql).
		if _, err := tx.Exec(ctx, `SELECT gateway_pd.close_course_reminders($1, $2)`, m.id, satisfied); err != nil {
			return fmt.Errorf("mypd: closing course %s's reminders: %w", m.id, err)
		}
	}
	country := sp.country
	if country == "" {
		country = defaultCountry
	}
	if _, err := tx.Exec(ctx, `INSERT INTO pd_allocation (created_at, updated_at, id, staff_id, fy, country, currency,
		annual_allocation, status, set_by) VALUES (now(), now(), $1, $2, $3, $4, $5, 0, $6, NULL)
		ON CONFLICT (staff_id, fy) DO NOTHING`, cuid.New(), sp.id, fy, country, allocationCcy, allocationStatus); err != nil {
		return fmt.Errorf("mypd: making the year's allocation: %w", err)
	}
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("mypd: committing the read's writes: %w", err)
	}
	return nil
}

type course struct {
	id, status, name, institution, kind, funding, currency string
	category                                               *string
	start, end                                             time.Time
	requested                                              int64
	accounted, returned                                    *int64
	netsuite                                               string
	created, updated                                       time.Time
	markedComplete, submitted, supervisor, hr              *time.Time
	enrolled, bamboo, accountability, signedOff            *time.Time
}

type document struct {
	name, kind, status string
	created            time.Time
}

type message struct {
	sender, body, status, context string
}

type view struct {
	fy          string
	today       time.Time
	allocation  int64
	currency    string
	rows        []course
	documents   map[string][]document // by course, newest first
	uploaded    map[string]time.Time  // the newest uploaded proof, by course
	messages    []message
	senderNames map[string]string
}

func (s *Service) read(ctx context.Context, p auth.Principal, sp staff, fy string, today time.Time) (*view, error) {
	v := &view{fy: fy, today: today, currency: allocationCcy, documents: map[string][]document{},
		uploaded: map[string]time.Time{}, senderNames: map[string]string{}}
	err := s.db.QueryRow(ctx, `SELECT annual_allocation, currency FROM pd_allocation WHERE staff_id = $1 AND fy = $2`,
		sp.id, fy).Scan(&v.allocation, &v.currency)
	if err != nil {
		return nil, fmt.Errorf("mypd: reading the allocation: %w", err)
	}
	rows, err := s.db.Query(ctx, `
		SELECT id, COALESCE(status, ''), COALESCE(course_name, ''), COALESCE(institution, ''), COALESCE(course_type, ''),
		       COALESCE(funding_type, ''), COALESCE(currency, ''), course_category, start_date, end_date,
		       COALESCE(requested_amount_cents, 0), accounted_amount, returned_amount, COALESCE(accountability_netsuite_id, ''),
		       created_at, updated_at, marked_complete_at, submitted_at, supervisor_reviewed_at, hr_reviewed_at,
		       enrollment_confirmed_at, bamboohr_uploaded_at, accountability_submitted_at, signed_off_at
		FROM pd_request WHERE staff_id = $1 AND fy = $2 ORDER BY created_at DESC`, sp.id, fy)
	if err != nil {
		return nil, fmt.Errorf("mypd: reading the courses: %w", err)
	}
	v.rows, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (course, error) {
		var c course
		return c, row.Scan(&c.id, &c.status, &c.name, &c.institution, &c.kind, &c.funding, &c.currency, &c.category,
			&c.start, &c.end, &c.requested, &c.accounted, &c.returned, &c.netsuite, &c.created, &c.updated,
			&c.markedComplete, &c.submitted, &c.supervisor, &c.hr, &c.enrolled, &c.bamboo, &c.accountability, &c.signedOff)
	})
	if err != nil {
		return nil, fmt.Errorf("mypd: reading the courses: %w", err)
	}
	ids := make([]string, 0, len(v.rows))
	for _, c := range v.rows {
		ids = append(ids, c.id)
	}
	docs, err := s.db.Query(ctx, `SELECT request_id, COALESCE(original_name, ''), COALESCE(document_type, ''),
		COALESCE(status, ''), created_at FROM pd_certificate WHERE request_id = ANY($1) ORDER BY created_at DESC`, ids)
	if err != nil {
		return nil, fmt.Errorf("mypd: reading the proof on file: %w", err)
	}
	defer docs.Close()
	for docs.Next() {
		var request string
		var d document
		if err := docs.Scan(&request, &d.name, &d.kind, &d.status, &d.created); err != nil {
			return nil, fmt.Errorf("mypd: reading the proof on file: %w", err)
		}
		v.documents[request] = append(v.documents[request], d)
		if _, seen := v.uploaded[request]; !seen && d.status == "uploaded" {
			v.uploaded[request] = d.created
		}
	}
	if err := docs.Err(); err != nil {
		return nil, fmt.Errorf("mypd: reading the proof on file: %w", err)
	}
	return v, s.readMessages(ctx, p, v)
}

// readMessages is _recent_messages: the six newest PD messages to the reader.
func (s *Service) readMessages(ctx context.Context, p auth.Principal, v *view) error {
	rows, err := s.db.Query(ctx, `SELECT COALESCE(sender_id, ''), COALESCE(body, ''), COALESCE(status, ''),
		COALESCE(context_id, '') FROM message WHERE recipient_id = $1 AND category = 'professional_development'
		ORDER BY created_at DESC LIMIT 6`, p.UserID)
	if err != nil {
		return fmt.Errorf("mypd: reading the messages: %w", err)
	}
	v.messages, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (message, error) {
		var m message
		return m, row.Scan(&m.sender, &m.body, &m.status, &m.context)
	})
	if err != nil {
		return fmt.Errorf("mypd: reading the messages: %w", err)
	}
	ids := []string{}
	for _, m := range v.messages {
		if m.sender != "" && m.sender != "system" {
			ids = append(ids, m.sender)
		}
	}
	names, err := s.db.Query(ctx, `SELECT id, COALESCE(name, '') FROM "user" WHERE id = ANY($1)`, ids)
	if err != nil {
		return fmt.Errorf("mypd: reading the senders: %w", err)
	}
	defer names.Close()
	for names.Next() {
		var id, name string
		if err := names.Scan(&id, &name); err != nil {
			return fmt.Errorf("mypd: reading the senders: %w", err)
		}
		v.senderNames[id] = name
	}
	return names.Err()
}

// ── The page ────────────────────────────────────────────────────────────────

// pyRound is Python's round() to an int (half to even).
func pyRound(x float64) int { return int(math.RoundToEven(x)) }

// money is f"{currency} {cents / 100:,.0f}".
func money(currency string, cents int64) string {
	whole := strconv.FormatFloat(float64(cents)/100, 'f', 0, 64)
	neg := strings.HasPrefix(whole, "-")
	whole = strings.TrimPrefix(whole, "-")
	for i := len(whole) - 3; i > 0; i -= 3 {
		whole = whole[:i] + "," + whole[i:]
	}
	if neg {
		whole = "-" + whole
	}
	return currency + " " + whole
}

func day(t time.Time) string { return t.Format("02 Jan 2006") }

// localDay is the template's |date:"d M Y" of a stored moment.
func localDay(t time.Time) string { return day(t.In(zone)) }

// utcDate is a stored moment's .date() (Django hands moments back in UTC).
func utcDate(t time.Time) time.Time { return dateOf(t.UTC()) }

func days(from, to time.Time) int { return int(to.Sub(from).Hours() / 24) }

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func links(ls ...*screensv1.PageLink) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}
}

func panel(title string, badges []*screensv1.PageBadge, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: title, Badges: badges, Items: feeddom.Paired(items)}}}
}

func drawer(t, href string) *screensv1.PageLink {
	return &screensv1.PageLink{Text: t, Href: href, Drawer: true}
}

func requestHref(id string) string { return "/my-professional-development/request?id=" + id }

func (v *view) page(doors Doors, years []string, now time.Time) *screensv1.GetPageResponse {
	blocks := []*screensv1.PageBlock{}
	if doors.Strip != nil {
		tabs := []*screensv1.PageLinkTab{}
		for _, t := range doors.Strip.Tabs {
			tabs = append(tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: &screensv1.PageLinkTabs{
			Tabs: tabs, Label: doors.Strip.Label, Scrolls: doors.Strip.Scrolls}}})
	}
	blocks = append(blocks, v.filters(years), v.figures())
	current := v.current()
	blocks = append(blocks, v.courseCard(current), v.tracker(current), v.nextActions(), v.reminders(),
		v.messagesPanel(), v.quickActions(current))
	blocks = append(blocks, v.courses()...)
	blocks = append(blocks, panel("", nil, text("Last refreshed "+now.Format("02 Jan 2006 15:04"))))
	return &screensv1.GetPageResponse{Header: v.header(), Blocks: blocks, Dialogs: []*screensv1.PageDialog{policy()},
		WebPath: PagePath}
}

func (v *view) header() *screensv1.PageHeader {
	return &screensv1.PageHeader{
		Eyebrow:     "My Performance",
		Title:       "My Professional Development",
		Description: "Request, track and close out your professional development — the same workflow for every role.",
		Actions: []*screensv1.PageAction{
			{Key: "pd_policy", Label: "PD Policy", Enabled: true, Href: "#dialog=showPolicy", Drawer: true},
			{Key: "new_pd_request", Label: "New PD Request", Primary: true, Enabled: true,
				Href: "/my-professional-development/request", Drawer: true},
			{Key: "download_report", Label: "Download Report", Enabled: true,
				Href: "/my-professional-development/export?fy=" + v.fy, Download: true},
		},
	}
}

// filters is the year select; one asked for that it does not offer shows
// its first, as a browser does.
func (v *view) filters(years []string) *screensv1.PageBlock {
	f := &screensv1.PageFilter{Name: "fy", Label: "Financial year"}
	for _, y := range years {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: y, Label: "FY " + y})
		if y == v.fy {
			f.Value = y
		}
	}
	if f.Value == "" && len(years) > 0 {
		f.Value = years[0]
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{f}}}}
}

func (c course) accountedAmount() int64 {
	if c.accounted == nil {
		return 0
	}
	return *c.accounted
}

// figures is the KPI strip (StaffPDService.balances and get_page).
func (v *view) figures() *screensv1.PageBlock {
	var committed, accounted int64
	var active, certs, accountability, completed int
	for _, c := range v.rows {
		if in(rules.CommittedStatuses, c.status) && c.accountedAmount() == 0 {
			committed += c.requested
		}
		accounted += c.accountedAmount()
		if in(rules.ActiveStatuses, c.status) {
			active++
		}
		if c.status == "ended" || c.status == "marked_complete" {
			certs++
		}
		if in(rules.FundedTypes, c.funding) && c.status == "bamboohr_confirmed" {
			accountability++
		}
		if c.status == "completed_closed" {
			completed++
		}
	}
	remaining := v.allocation - committed - accounted
	if remaining < 0 {
		remaining = 0
	}
	share := func(n int64) string {
		if v.allocation == 0 {
			return "0% of allocation"
		}
		return strconv.Itoa(pyRound(float64(n)/float64(v.allocation)*100)) + "% of allocation"
	}
	pending := func(n int) string {
		if n == 0 {
			return "All up to date"
		}
		return "Action required"
	}
	l := rules.MetricLabels
	metrics := []*screensv1.PageMetric{
		{Label: l[0], Value: money(v.currency, v.allocation), Note: "FY " + v.fy},
		{Label: l[1], Value: money(v.currency, committed), Helper: share(committed)},
		{Label: l[2], Value: money(v.currency, accounted), Helper: share(accounted)},
		{Label: l[3], Value: money(v.currency, remaining), Helper: share(remaining)},
		{Label: l[4], Value: strconv.Itoa(active), Note: "In progress"},
		{Label: l[5], Value: strconv.Itoa(certs), Note: pending(certs)},
		{Label: l[6], Value: strconv.Itoa(accountability), Note: pending(accountability)},
		{Label: l[7], Value: strconv.Itoa(completed), Note: "This FY"},
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
		Title: "Learning plan context", Metrics: metrics}}}
}

// currentStatuses are the statuses get_page looks for first.
var currentStatuses = []string{"in_progress", "ended", "marked_complete", "certificate_uploaded",
	"bamboohr_confirmed", "accountability_submitted", "awaiting_hr_signoff"}

// current is get_page's "current course".
func (v *view) current() *course {
	for i := range v.rows {
		if in(currentStatuses, v.rows[i].status) {
			return &v.rows[i]
		}
	}
	for i := range v.rows {
		if in(rules.ActiveStatuses, v.rows[i].status) {
			return &v.rows[i]
		}
	}
	for i := range v.rows {
		if v.rows[i].status != "draft" && !in(rules.ClosedStatuses, v.rows[i].status) {
			return &v.rows[i]
		}
	}
	return nil
}

// progressStatuses are the statuses whose card counts the days gone.
var progressStatuses = []string{"in_progress", "ended", "marked_complete", "certificate_uploaded",
	"bamboohr_confirmed", "accountability_submitted", "awaiting_hr_signoff", "completed_closed"}

func nextAction(status string) string {
	if l, ok := rules.NextActions[status]; ok {
		return l
	}
	return "View"
}

// courseCard is My Current Course (_course_card and the card's template).
func (v *view) courseCard(c *course) *screensv1.PageBlock {
	if c == nil {
		return panel("My Current Course", nil,
			text("Request Professional Development support to start tracking a course here."),
			links(drawer("Request Professional Development", "/my-professional-development/request")))
	}
	total := max(1, days(c.start, c.end))
	elapsed := max(0, min(total, days(c.start, v.today)))
	pct := 0
	if in(progressStatuses, c.status) {
		pct = pyRound(float64(elapsed) / float64(total) * 100)
	}
	pct = min(100, pct)
	tone := "plain"
	if c.status == "ended" || c.status == "marked_complete" {
		tone = "caution"
	}
	category := "None"
	if c.category != nil {
		category = *c.category
	}
	items := []*screensv1.PagePanelItem{
		text(c.name), text(c.institution), text(courseType(c.kind)), text(category),
		text(fmt.Sprintf("%s – %s · %d days", day(c.start), day(c.end), total)),
		text("Progress"), text(strconv.Itoa(pct) + "%"),
	}
	if c.status == "marked_complete" || c.status == "certificate_uploaded" {
		items = append(items, text("Proof of completion"), text("Upload your certificate or transcript for this course."))
		if docs := v.documents[c.id]; len(docs) > 0 {
			list := []*screensv1.PageLink{}
			for _, d := range docs {
				badge := "Uploaded"
				switch d.status {
				case "returned":
					badge = "Returned"
				case "verified":
					badge = "Verified"
				}
				kind := d.kind
				if l, ok := rules.DocumentTypes[d.kind]; ok {
					kind = l
				}
				list = append(list, &screensv1.PageLink{Text: fmt.Sprintf("%s %s · %s %s", d.name, kind, localDay(d.created), badge)})
			}
			items = append(items, links(list...))
		}
	}
	items = append(items, text("Next: "+nextAction(c.status)), links(drawer("Open course →", requestHref(c.id))))
	return panel("My Current Course", []*screensv1.PageBadge{{Text: statusLabel(c.status), Tone: tone}}, items...)
}

// tracker is the Course Progress Tracker (_timeline).
func (v *view) tracker(c *course) *screensv1.PageBlock {
	if c == nil {
		return panel("Course Progress Tracker", nil,
			text("Your course progress tracker appears once you submit a Professional Development request."))
	}
	idx, ok := rules.StepIndex[c.status]
	if !ok {
		idx = -1
	}
	dates := map[int]*time.Time{0: c.submitted, 1: c.supervisor, 2: c.hr, 4: c.enrolled, 7: c.bamboo,
		8: c.accountability, 9: c.signedOff, 10: c.signedOff}
	if at, ok := v.uploaded[c.id]; ok {
		dates[6] = &at
	}
	blocked := c.status == "returned_by_supervisor" || c.status == "returned_by_hr" || c.status == "rejected" || c.status == "cancelled"
	items := []*screensv1.PagePanelItem{}
	for i, label := range rules.TimelineSteps {
		items = append(items, text(label))
		if d := dates[i]; d != nil {
			items = append(items, text(localDay(*d)))
			continue
		}
		active := !(blocked && i >= idx) && !(i < idx || (i == idx && c.status == "completed_closed")) && i == idx
		if active {
			items = append(items, text("In progress"))
		}
	}
	return panel("Course Progress Tracker", nil, items...)
}

type action struct{ id, title, description, button string }

// nextActions is _next_actions: at most four.
func (v *view) nextActions() *screensv1.PageBlock {
	list := []action{}
	for _, r := range v.rows {
		switch r.status {
		case "returned_by_supervisor", "returned_by_hr":
			list = append(list, action{r.id, "Fix Returned Request", r.name + " was returned — review the note and resubmit.", "Review & Fix"})
		case "marked_complete":
			list = append(list, action{r.id, "Upload Certificate", "Upload your completion certificate for " + r.name + ".", "Upload Now"})
		case "certificate_uploaded":
			list = append(list, action{r.id, "BambooHR Upload", "Upload certificate to BambooHR and confirm here for " + r.name + ".", "Confirm Upload"})
		case "bamboohr_confirmed":
			if in(rules.FundedTypes, r.funding) {
				list = append(list, action{r.id, "Submit Accountability", "Submit receipts and accountability for " + r.name + ".", "Submit Now"})
			} else {
				list = append(list, action{r.id, "Awaiting HR Sign-Off", r.name + " is ready for HR sign-off.", "View"})
			}
		case "accountability_submitted":
			if r.netsuite == "" {
				list = append(list, action{r.id, "Enter Expense ID", "Enter NetSuite Expense ID after accountability for " + r.name + ".", "Enter ID"})
			}
		}
	}
	if len(list) > 4 {
		list = list[:4]
	}
	if len(list) == 0 {
		return panel("Next Actions", nil, text("You're fully up to date on certificates, BambooHR uploads and accountability."))
	}
	items := []*screensv1.PagePanelItem{}
	for _, a := range list {
		items = append(items, text("1"), text(a.title), text(a.description), links(drawer(a.button, requestHref(a.id))))
	}
	return panel("Next Actions", nil, items...)
}

type reminder struct {
	id, label string
	date      time.Time
	daysLeft  int
}

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

// reminders is _upcoming_reminders: the six soonest.
func (v *view) reminders() *screensv1.PageBlock {
	list := []reminder{}
	add := func(r course, label string, when time.Time, left int) {
		list = append(list, reminder{r.id, label, when, left})
	}
	for _, r := range v.rows {
		switch r.status {
		case "returned_by_supervisor", "returned_by_hr":
			when := utcDate(r.updated)
			add(r, "“"+r.name+"” was returned — fix and resubmit", when, -days(when, v.today))
		case "enrollment_confirmed":
			if n := days(v.today, r.start); n >= 0 && n <= 7 {
				add(r, fmt.Sprintf("“%s” starts in %d day%s", r.name, n, plural(n)), r.start, n)
			}
		case "in_progress":
			if n := days(v.today, r.end); n >= 0 && n <= 14 {
				add(r, fmt.Sprintf("“%s” ends in %d day%s", r.name, n, plural(n)), r.end, n)
			}
		case "ended":
			n := days(r.end, v.today)
			add(r, fmt.Sprintf("Mark “%s” complete — %d day%s overdue", r.name, n, plural(n)), r.end, -n)
		case "marked_complete":
			since := r.end
			if r.markedComplete != nil {
				since = utcDate(*r.markedComplete)
			}
			if n := days(since, v.today); n >= 3 {
				add(r, fmt.Sprintf("Upload certificate for “%s” — %d days since completion", r.name, n), since, -n)
			}
		case "certificate_uploaded":
			when := utcDate(r.updated)
			if n := days(when, v.today); n >= 3 {
				add(r, fmt.Sprintf("Confirm BambooHR upload for “%s” — %d days pending", r.name, n), when, -n)
			}
		case "bamboohr_confirmed":
			if !in(rules.FundedTypes, r.funding) {
				continue
			}
			when := utcDate(r.updated)
			if n := days(when, v.today); n >= 3 {
				add(r, fmt.Sprintf("Submit accountability for “%s” — %d days pending", r.name, n), when, -n)
			}
		}
	}
	sort.SliceStable(list, func(i, j int) bool { return list[i].daysLeft < list[j].daysLeft })
	if len(list) > 6 {
		list = list[:6]
	}
	if len(list) == 0 {
		return panel("Upcoming Reminders", nil,
			text("You'll see start dates, certificate and accountability deadlines here as they approach."))
	}
	out := []*screensv1.PageLink{}
	for _, r := range list {
		out = append(out, drawer(r.label+" "+day(r.date), requestHref(r.id)))
	}
	return panel("Upcoming Reminders", nil, links(out...))
}

// initials is the avatar_initials filter.
func initials(name string) string {
	parts := strings.Fields(name)
	switch {
	case len(parts) >= 2:
		return strings.ToUpper(string([]rune(parts[0])[:1]) + string([]rune(parts[len(parts)-1])[:1]))
	case len(parts) == 1:
		r := []rune(parts[0])
		return strings.ToUpper(string(r[:min(2, len(r))]))
	}
	return "ED"
}

// messagesPanel is Messages from HR.
func (v *view) messagesPanel() *screensv1.PageBlock {
	if len(v.messages) == 0 {
		return panel("Messages from HR", nil,
			text("Messages from HR about your Professional Development requests will appear here."))
	}
	out := []*screensv1.PageLink{}
	for _, m := range v.messages {
		name, ok := v.senderNames[m.sender]
		if !ok {
			name = "Edify System"
		}
		href := "/messages"
		if m.context != "" {
			href += "?thread=" + m.context
		}
		out = append(out, &screensv1.PageLink{Text: initials(name), Href: href, Caption: name + " " + m.body})
	}
	return panel("Messages from HR", nil, links(out...))
}

func (v *view) quickActions(c *course) *screensv1.PageBlock {
	message := "/messages?context_type=professional_development"
	if c != nil {
		message += "&context_id=" + c.id
	}
	return panel("Quick Actions", nil, text("View PD Policy & Guidelines"), links(
		drawer("My PD Allocation History", "/my-professional-development/allocation-history"),
		&screensv1.PageLink{Text: "Download PD Report", Href: "/my-professional-development/export?fy=" + v.fy},
		&screensv1.PageLink{Text: "Message HR", Href: message},
	))
}

// courses is My Courses: its tabs and table, or its empty state.
func (v *view) courses() []*screensv1.PageBlock {
	if len(v.rows) == 0 {
		return []*screensv1.PageBlock{panel("My Courses", nil,
			text("Use Request Professional Development above to submit your first course for this financial year."))}
	}
	var progress, completed, cancelled int
	for _, r := range v.rows {
		if !in(rules.ClosedStatuses, r.status) && r.status != "draft" {
			progress++
		}
		switch r.status {
		case "completed_closed":
			completed++
		case "rejected", "cancelled", "withdrawn":
			cancelled++
		}
	}
	chip := func(value, label string, n int) *screensv1.PageChip {
		return &screensv1.PageChip{Value: value, Label: fmt.Sprintf("%s (%d)", label, n)}
	}
	chips := &screensv1.PageChips{Name: "tab", Value: "all", Chips: []*screensv1.PageChip{
		chip("all", "All", len(v.rows)), chip("in_progress", "In Progress", progress),
		chip("completed", "Completed", completed), chip("cancelled", "Cancelled", cancelled)}}
	col := func(label string, numeric bool) *screensv1.PageColumn {
		return &screensv1.PageColumn{Label: label, Numeric: numeric}
	}
	table := &screensv1.PageTable{Columns: []*screensv1.PageColumn{col("Course", false), col("Institution", false),
		col("Type", false), col("Start", false), col("End", false), col("Status", false), col("Funding Used", false),
		col("Next Action", true)}}
	cell := func(t string) *screensv1.PageCell { return &screensv1.PageCell{Text: t} }
	for _, r := range v.rows {
		funding := money(r.currency, r.requested)
		if r.requested == 0 {
			funding = r.currency + " 0"
			if r.funding == rules.SelfFunded {
				funding = "Self-Funded"
			}
		}
		table.Rows = append(table.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(r.name), cell(r.institution), cell(courseType(r.kind)), cell(day(r.start)), cell(day(r.end)),
			{Text: statusLabel(r.status), Tone: "primary", Badge: true}, cell(funding), cell(nextAction(r.status) + " →"),
		}})
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Section{Section: "My Courses"}},
		{Kind: &screensv1.PageBlock_Chips{Chips: chips}},
		{Kind: &screensv1.PageBlock_Table{Table: table}},
	}
}

// policy is the PD Policy & Guidelines dialog.
func policy() *screensv1.PageDialog {
	lines := []string{
		"Every eligible employee uses this same request, approval and tracking workflow — there is no separate process by role.",
		"No manager may approve their own request, and HR never signs off or approves its own staff's requests — an independent reviewer is always assigned.",
		"No course can be marked complete without completion evidence, and no funded course can be closed without both accountability and a NetSuite Expense ID.",
		"A certificate is not considered complete until it is uploaded to Edify and confirmed in BambooHR.",
		"Requests that exceed your remaining PD fund require a documented exception reason and additional approval.",
		"Professional Development funding is a dedicated ledger — it is never routed through the school-activity budget workflow.",
	}
	ls := []*screensv1.PageLink{}
	for _, l := range lines {
		ls = append(ls, &screensv1.PageLink{Text: l})
	}
	return &screensv1.PageDialog{Key: "showPolicy", Title: "PD Policy & Guidelines",
		Blocks: []*screensv1.PageBlock{panel("PD Policy & Guidelines", nil, links(ls...), text("Got it"))}}
}
