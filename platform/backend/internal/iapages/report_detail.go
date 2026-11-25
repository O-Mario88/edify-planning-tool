package iapages

// One impact report's page (impact_report_views.report_detail,
// pages/ia/impact_reports_detail.html) as the feed reads it, for a draft:
// its words, recommendations, releases and history. A report that has been
// submitted carries frozen evidence and releases Go does not draw yet, and a
// correction names the version it corrects: those are handed on.

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageheader"
)

var reportDetailPath = regexp.MustCompile(`^/ia/impact-reports/([A-Za-z0-9]{1,30})/$`)

// reportActionLabels are reports.ACTION_LABELS.
var reportActionLabels = map[string]string{
	"ia.report.started": "Draft started", "ia.report.updated": "Draft edited",
	"ia.report.recommendation_added": "Recommendation added", "ia.report.recommendation_removed": "Recommendation removed",
	"ia.report.submitted": "Submitted for review (evidence frozen)", "ia.report.withdrawn": "Withdrawn",
	"ia.report.reviewed": "Reviewed", "ia.report.returned": "Returned to the author",
	"ia.report.correction_started": "Correction started as a new version", "ia.report.superseded": "Superseded by a newer version",
	"ia.report.released": "Released", "ia.report.donor_requested": "Donor version requested",
	"ia.report.donor_released": "Donor version approved and released", "ia.report.donor_declined": "Donor version declined",
	"ia.report.recommendation_responded": "Country Director responded to a recommendation",
	"ia.report.school_brief_shared":      "School brief shared with the school", "ia.report.annex_downloaded": "Evidence annex downloaded",
	"ia.report.release_downloaded": "Released version downloaded",
}

var recommendationLabels = map[string]string{
	"proposed": "Proposed", "accepted": "Accepted", "rejected": "Rejected", "deferred": "Deferred",
	"in_progress": "In progress", "done": "Done",
}

var actionOwnerLabels = map[string]string{
	"CountryDirector": "Country Director", "Program Lead": "Programme Lead", "RegionalProgramLead": "Regional Lead for CCE",
	"BusinessTransformationOfficer": "Business Transformation", "ImpactAssessment": "Impact Assessment",
}

// pageReport is what a report's page reads of it.
type pageReport struct {
	report
	project, methodology, findings, limitations string
	basis, reviewNote, snapshotHash             string
	submitted, reviewed                         *time.Time
	snapshot                                    []byte
	supersedes                                  bool
}

var reviewBasisLabels = map[string]string{"peer_ia": "Reviewed by a second IA officer", "cd_fallback": "Acknowledged by the Country Director"}

func dashCell(t string) *screensv1.PageCell {
	if t == "" {
		t = "—"
	}
	return &screensv1.PageCell{Text: t}
}

func dayTime(t time.Time) string { return t.In(zone).Format("2 Jan 2006 15:04") }

// reportRights are detail_rights' answers the page draws.
type reportRights struct {
	author, edit, withdraw, review, releaseLeadership, correct, annex, summaryOnly bool
	// releaseSchools is can_release_schools and can_request_donor; respond is
	// the Country Director's answer to each recommendation.
	releaseSchools, respond bool
}

func (s *Service) rightsOf(ctx context.Context, p auth.Principal, x pageReport) (reportRights, error) {
	r := reportRights{summaryOnly: p.ActiveRole == roleRVP}
	r.author = x.author == p.UserID && p.ActiveRole == roleIA
	r.edit = r.author && x.status == "draft"
	r.withdraw = r.author && (x.status == "draft" || x.status == "submitted")
	country, err := s.profileCountry(ctx, p)
	if err != nil {
		return r, err
	}
	if x.status == "submitted" && p.UserID != x.author && x.country != "" && country == x.country {
		switch p.ActiveRole {
		case roleIA:
			r.review = true
		case roleCD:
			var others bool
			if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id
WHERE 'ImpactAssessment' = ANY(u.roles) AND u.is_active AND u.deleted_at IS NULL AND sp.country = $1 AND sp.deleted_at IS NULL
  AND u.id <> $2)`, x.country, x.author).Scan(&others); err != nil {
				return r, fmt.Errorf("iapages: the country's officers: %w", err)
			}
			r.review = !others
		}
	}
	r.releaseLeadership = x.status == "reviewed" && x.reviewer == p.UserID
	countryCD := p.ActiveRole == roleCD && x.country != "" && country == x.country
	r.releaseSchools = x.status == "released" && (x.reviewer == p.UserID || countryCD)
	r.respond = x.status == "released" && countryCD
	correctable := x.status == "returned" || x.status == "reviewed" || x.status == "released" ||
		(x.status == "withdrawn" && x.submitted != nil)
	r.correct = correctable && p.ActiveRole == roleIA && x.country != "" && country == x.country
	if r.correct {
		var open bool
		if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM impact_report WHERE supersedes_id = $1
  AND status IN ('draft', 'submitted', 'returned'))`, x.id).Scan(&open); err != nil {
			return r, fmt.Errorf("iapages: the report's open correction: %w", err)
		}
		r.correct = !open
	}
	r.annex = x.status != "draft" && !r.summaryOnly && (p.ActiveRole == roleIA || p.ActiveRole == roleCD || p.ActiveRole == roleAdm) &&
		slices.Contains(rules.ExportRoles, p.ActiveRole)
	return r, nil
}

func (s *Service) reportDetail(ctx context.Context, p auth.Principal, role Role, id string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	args := []any{}
	reach, err := s.reportReach(ctx, p, &args)
	if err != nil {
		return nil, true, err
	}
	args = append(args, id)
	var x pageReport
	err = s.db.QueryRow(ctx, fmt.Sprintf(`SELECT r.id, r.title, r.status, r.author_id, COALESCE(r.reviewed_by_id, ''), r.country, r.fy,
  r.period_start, r.period_end, COALESCE(r.programme_areas, '{}'), r.version, COALESCE(pr.name, ''), r.methodology, r.findings,
  r.limitations, r.supersedes_id IS NOT NULL, r.evidence_snapshot::text, r.submitted_at, r.reviewed_at, r.review_basis, r.review_note, r.snapshot_hash
FROM impact_report r LEFT JOIN project pr ON pr.id = r.project_id WHERE (%s) AND r.id = $%d`, reach, len(args)), args...).
		Scan(&x.id, &x.title, &x.status, &x.author, &x.reviewer, &x.country, &x.fy, &x.start, &x.end, &x.programmes, &x.version,
			&x.project, &x.methodology, &x.findings, &x.limitations, &x.supersedes, &x.snapshot, &x.submitted, &x.reviewed,
			&x.basis, &x.reviewNote, &x.snapshotHash)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the report: %w", err)
	}
	frozen := string(x.snapshot) != "{}" && len(x.snapshot) > 0
	// Released reports (their releases), corrections (the version they
	// correct), reports with a newer version and the RVP's donor reading are
	// the existing page's still.
	if frozen && p.ActiveRole == roleRVP {
		return nil, false, nil
	}
	// A donor version (its approval and its RVP reading) is the existing
	// page's still; the leadership release and school briefs are drawn here.
	var other bool
	if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM impact_report_release WHERE report_id = $1 AND audience = 'donor')`, id).Scan(&other); err != nil {
		return nil, true, fmt.Errorf("iapages: the report's releases: %w", err)
	}
	if other {
		return nil, false, nil
	}
	notes, err := s.versionNotes(ctx, reach, args[:len(args)-1:len(args)-1], x)
	if err != nil {
		return nil, true, err
	}
	rights, err := s.rightsOf(ctx, p, x)
	if err != nil {
		return nil, true, err
	}
	header := &screensv1.PageHeader{Title: x.title,
		Description: reportStatusLabel(x.status) + " · version " + strconv.Itoa(x.version) + " · " + x.country}
	path := ReportsPath + id + "/"
	if rights.edit {
		header.Actions = append(header.Actions, pageheader.Drawer("Edit draft", path+"edit", false),
			&screensv1.PageAction{Key: "submit_for_review", Label: "Submit for review", Enabled: true})
	}
	if rights.withdraw {
		header.Actions = append(header.Actions, &screensv1.PageAction{Key: "withdraw", Label: "Withdraw", Enabled: true})
	}
	if rights.review {
		header.Actions = append(header.Actions, pageheader.Drawer("Review", path+"review", false))
	}
	if rights.releaseLeadership {
		header.Actions = append(header.Actions, &screensv1.PageAction{Key: pageheader.Key("Release to country leadership"),
			Label: "Release to country leadership", Enabled: true})
	}
	if rights.releaseSchools {
		header.Actions = append(header.Actions, pageheader.Drawer("Release school briefs", path+"release/schools", false),
			pageheader.Drawer("Request donor version", path+"release/donor", false))
	}
	if rights.correct {
		header.Actions = append(header.Actions, &screensv1.PageAction{Key: pageheader.Key("Start a correction"), Label: "Start a correction", Enabled: true})
	}
	if rights.annex {
		header.Actions = append(header.Actions, pageheader.Link("Download evidence annex", path+"annex.csv"))
	}
	blocks := workspaceStrip(role)
	if x.status == "returned" && x.reviewNote != "" {
		blocks = append(blocks, titled("", text("Returned by the reviewer: "+x.reviewNote)))
	}
	blocks = append(blocks, notes...)
	facts, err := s.reportFacts(ctx, x)
	if err != nil {
		return nil, true, err
	}
	blocks = append(blocks, titled("The report", paired(facts)...))
	if !rights.summaryOnly {
		if rights.edit {
			blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
				Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
					{Text: "Add recommendation", Href: path + "recommendations/new", Drawer: true}}}}}}}}})
		}
		table, err := s.recommendationTable(ctx, x, rights)
		if err != nil {
			return nil, true, err
		}
		blocks = append(blocks, titled("Recommendations"), table)
	}
	if frozen {
		evidence, err := frozenEvidence(x, query)
		if err != nil {
			return nil, true, err
		}
		blocks = append(blocks, evidence...)
	} else {
		blocks = append(blocks, titled("Evidence", text("The evidence is taken by the server, in your scope, the moment the report is submitted — the project cohort in the period, school change with its evidence grades, learning, discipleship and EdTech evidence, mapping versions, verified loan conclusions and approved findings — and never changes afterwards.")))
	}
	releases, err := s.releaseTable(ctx, x, query)
	if err != nil {
		return nil, true, err
	}
	blocks = append(blocks, releases...)
	if !rights.summaryOnly {
		table, err := s.historyTable(ctx, x)
		if err != nil {
			return nil, true, err
		}
		blocks = append(blocks, titled("History"), table)
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: path}, true, nil
}

// emptyTable is impact_reports_table.html with no rows, as the feed reads
// its empty state.
func emptyTable(title, empty, body string) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{EmptyMessage: empty,
		Rows: []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: title + " " + empty + " " + body}}}}}}}
}

func (s *Service) reportFacts(ctx context.Context, x pageReport) ([]string, error) {
	names := map[string]string{}
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(name, '') FROM "user" WHERE id = ANY($1)`, []string{x.author, x.reviewer})
	if err != nil {
		return nil, fmt.Errorf("iapages: the report's people: %w", err)
	}
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			rows.Close()
			return nil, fmt.Errorf("iapages: the report's people: %w", err)
		}
		names[id] = name
	}
	rows.Close()
	author := names[x.author]
	submitted, reviewed := "", ""
	if x.submitted != nil {
		submitted = dayTime(*x.submitted)
	}
	if x.reviewer != "" {
		at := ""
		if x.reviewed != nil {
			at = dayTime(*x.reviewed)
		}
		reviewed = names[x.reviewer] + " · " + reviewBasisLabels[x.basis] + " · " + at
	}
	fy := ""
	if x.fy != "" {
		fy = "FY" + x.fy
	}
	project := x.project
	if project == "" {
		project = "Every project enrolment in scope"
	}
	areas := []string{}
	for _, a := range x.programmes {
		label := a
		if l, ok := rules.ReportProgrammes[a]; ok {
			label = l
		}
		areas = append(areas, label)
	}
	programmes := strings.Join(areas, ", ")
	if programmes == "" {
		programmes = "Across programmes"
	}
	items := []string{}
	for _, f := range [][2]string{{"Country", x.country}, {"Period", periodLabel(x.report)}, {"Financial year", fy},
		{"Special project", project}, {"Programme areas", programmes}, {"Author", author}, {"Submitted", submitted},
		{"Reviewed by", reviewed}} {
		if f[1] != "" {
			items = append(items, f[0], f[1])
		}
	}
	for _, f := range [][2]string{{"Methodology", x.methodology}, {"Findings", x.findings}, {"Limitations", x.limitations}} {
		value := f[1]
		if value == "" {
			value = "Not written yet"
		}
		items = append(items, f[0], linebreaksRead(value))
	}
	return items, nil
}

// linebreaksRead is linebreaksbr's text. The feed's reader drops a value
// with line breaks altogether; Go keeps it with its breaks (a deliberate
// difference, as on the Verify form, doc 189).
func linebreaksRead(v string) string { return strings.ReplaceAll(v, "\r\n", "\n") }

func (s *Service) recommendationTable(ctx context.Context, x pageReport, rights reportRights) (*screensv1.PageBlock, error) {
	rows, err := s.db.Query(ctx, `SELECT id, text, owner_role, due_date, status, response FROM impact_report_recommendation
WHERE report_id = $1 ORDER BY due_date, created_at`, x.id)
	if err != nil {
		return nil, fmt.Errorf("iapages: the recommendations: %w", err)
	}
	defer rows.Close()
	today := localDay(s.now())
	t := &screensv1.PageTable{}
	actions := rights.edit || rights.respond
	for rows.Next() {
		var id, words, owner, status, response string
		var due *time.Time
		if err := rows.Scan(&id, &words, &owner, &due, &status, &response); err != nil {
			return nil, fmt.Errorf("iapages: a recommendation: %w", err)
		}
		forWhom := owner
		if l, ok := actionOwnerLabels[owner]; ok {
			forWhom = l
		}
		dueBy := ""
		if due != nil {
			dueBy = due.Format("2 Jan 2006")
		}
		label := status
		if l, ok := recommendationLabels[status]; ok {
			label = l
		}
		open := status == "proposed" || status == "accepted" || status == "in_progress"
		if x.status == "released" && open && due != nil && due.Before(today) {
			label += " · overdue"
		}
		cells := []*screensv1.PageCell{dashCell(words), dashCell(forWhom), dashCell(dueBy), dashCell(label), dashCell(response)}
		switch {
		case rights.edit:
			// Its Remove is a one-button form the feed does not read.
			cells = append(cells, &screensv1.PageCell{})
		case rights.respond:
			verb := "Update"
			if status == "proposed" {
				verb = "Respond"
			}
			cells = append(cells, &screensv1.PageCell{Actions: []*screensv1.PageAction{{Key: "button", Label: verb, Primary: true, Enabled: true,
				Href: ReportsPath + x.id + "/recommendations/" + id + "/", Drawer: true}}})
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells})
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iapages: the recommendations: %w", err)
	}
	if len(t.Rows) == 0 {
		body := "This report makes no recommendations."
		if rights.edit {
			body = "Add what should change, who acts and by when."
		}
		return emptyTable(x.title, "No recommendations", body), nil
	}
	for _, c := range []string{"Recommendation", "For", "Due by", "Status", "Country Director's response"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	if actions {
		t.Columns = append(t.Columns, &screensv1.PageColumn{})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}, nil
}

var releaseStatusLabels = map[string]string{"pending_approval": "Awaiting approval", "approved": "Approved", "released": "Released", "revoked": "Revoked"}

// releaseTable is _release_rows under its title, for a report whose
// releases are the leadership one and its school briefs.
func (s *Service) releaseTable(ctx context.Context, x pageReport, query url.Values) ([]*screensv1.PageBlock, error) {
	rows, err := s.db.Query(ctx, `SELECT r.id, r.audience, r.status, COALESCE(sc.name, ''), COALESCE(q.name, ''), COALESCE(d.name, ''),
  r.released_at, COALESCE(a.state, ''), COALESCE(a.manual_resolution_reason, ''), a.id IS NOT NULL, COALESCE(ru.name, 'the account owner')
FROM impact_report_release r LEFT JOIN school sc ON sc.id = r.school_id
LEFT JOIN "user" q ON q.id = r.requested_by_id LEFT JOIN "user" d ON d.id = r.released_by_id
LEFT JOIN LATERAL (SELECT t.id, t.state, t.manual_resolution_reason, t.recipient_id FROM team_action t
  WHERE t.condition_key = 'impact_brief:' || r.id ORDER BY t.created_at DESC LIMIT 1) a ON TRUE
LEFT JOIN "user" ru ON ru.id = a.recipient_id
WHERE r.report_id = $1 ORDER BY r.audience, r.created_at`, x.id)
	if err != nil {
		return nil, fmt.Errorf("iapages: the report's releases: %w", err)
	}
	defer rows.Close()
	path := ReportsPath + x.id + "/releases/"
	list := [][]string{}
	actions := [][]*screensv1.PageAction{}
	for rows.Next() {
		var id, audience, status, school, requested, released, state, resolution, recipient string
		var at *time.Time
		var hasAction bool
		if err := rows.Scan(&id, &audience, &status, &school, &requested, &released, &at, &state, &resolution, &hasAction, &recipient); err != nil {
			return nil, fmt.Errorf("iapages: a release: %w", err)
		}
		label := status
		if l, ok := releaseStatusLabels[status]; ok {
			label = l
		}
		day := ""
		if at != nil {
			day = dayTime(*at)
		}
		buttons := []*screensv1.PageAction{{Label: "View", Enabled: true, Href: path + id + "/", Drawer: true}}
		if status == "released" && audience != "school" {
			buttons = append(buttons, &screensv1.PageAction{Label: "Download", Enabled: true, Href: path + id + "/download"})
		}
		if audience == "school" {
			buttons = append(buttons, &screensv1.PageAction{Label: "Open brief", Enabled: true, Href: "/impact-briefs/" + id + "/"})
		}
		key := "menu"
		if len(buttons) == 1 {
			key = "button"
			buttons[0].Primary = true
		}
		for _, b := range buttons {
			b.Key = key
		}
		shared := ""
		if hasAction {
			shared = "Waiting for " + recipient + " to share it"
			if state == "resolved" {
				shared = resolution
			}
		}
		list = append(list, []string{reportAudienceLabels[audience], school, label, requested, released, day, shared})
		actions = append(actions, buttons)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iapages: the report's releases: %w", err)
	}
	blocks := []*screensv1.PageBlock{titled("Releases")}
	if len(list) == 0 {
		return append(blocks, emptyTable(x.title, "Not released",
			"A reviewed report is released to country leadership first, then school briefs and the donor version.")), nil
	}
	size := 50
	number, pages := closedschools.PageOf(query.Get("releases_page"), len(list), size)
	t := &screensv1.PageTable{}
	for _, c := range []string{"Audience", "School", "Status", "Requested by", "Released by", "Released", "Follow-through", ""} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	for i := (number - 1) * size; i < min(number*size, len(list)); i++ {
		cells := []*screensv1.PageCell{}
		for _, c := range list[i] {
			cells = append(cells, dashCell(c))
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: append(cells, &screensv1.PageCell{Actions: actions[i]})})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel("releases_page", number, pages, len(list), size, query, rules.QueryKeysNotPassed))
	}
	return blocks, nil
}

var reportAudienceLabels = map[string]string{"leadership": "Country leadership", "school": "Partner school", "donor": "Donors"}

func (s *Service) historyTable(ctx context.Context, x pageReport) (*screensv1.PageBlock, error) {
	var first int64
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(min(seq), 0) FROM audit_log WHERE subject_kind = 'ImpactReport' AND subject_id = $1
  AND action = 'ia.report.released'`, x.id).Scan(&first); err != nil {
		return nil, fmt.Errorf("iapages: the report's first release: %w", err)
	}
	rows, err := s.db.Query(ctx, `SELECT a.seq, a.action, COALESCE(a.actor_id, ''), COALESCE(a.actor_role, ''), a.created_at,
  COALESCE(a.reason, ''), COALESCE(u.name, 'System')
FROM audit_log a LEFT JOIN "user" u ON u.id = a.actor_id
WHERE a.subject_kind = 'ImpactReport' AND a.subject_id = $1 ORDER BY a.created_at DESC LIMIT 50`, x.id)
	if err != nil {
		return nil, fmt.Errorf("iapages: the report's history: %w", err)
	}
	defer rows.Close()
	t := &screensv1.PageTable{}
	for rows.Next() {
		var action, actorID, actorRole, reason, actor string
		var at time.Time
		var seq int64
		if err := rows.Scan(&seq, &action, &actorID, &actorRole, &at, &reason, &actor); err != nil {
			return nil, fmt.Errorf("iapages: a history row: %w", err)
		}
		if actorID == "" {
			actor = "System"
		}
		label := action
		if l, ok := reportActionLabels[action]; ok {
			label = l
		}
		if action == "ia.report.released" {
			// Its payload's audience: the first release is the leadership
			// one, every later one a school brief (the page hands on a report
			// with a donor version).
			audience := "Partner school"
			if seq == first {
				audience = "Country leadership"
			}
			label += " · " + audience
		}
		if actorRole == "" {
			actorRole = "system"
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{dashCell(dayTime(at)), dashCell(label),
			dashCell(actor + " (" + actorRole + ")"), dashCell(reason)}})
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iapages: the report's history: %w", err)
	}
	if len(t.Rows) == 0 {
		return emptyTable(x.title, "No history", "Transitions and downloads are recorded here."), nil
	}
	for _, c := range []string{"When", "What", "Who", "Note"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}, nil
}

// versionNotes are the page's notes on its versions: the newer version that
// corrects it, and the version it corrects.
func (s *Service) versionNotes(ctx context.Context, reach string, args []any, x pageReport) ([]*screensv1.PageBlock, error) {
	out := []*screensv1.PageBlock{}
	note := func(words, linkText, href string) *screensv1.PageBlock {
		return titled("", &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: words}, Tone: "info",
			TextLinks: []*screensv1.PageLink{{Text: linkText, Href: href}}})
	}
	sargs := append(slices.Clone(args), x.id)
	var nextID, nextStatus string
	var nextVersion int
	err := s.db.QueryRow(ctx, fmt.Sprintf(`SELECT r.id, r.version, r.status FROM impact_report r WHERE (%s) AND r.supersedes_id = $%d
ORDER BY r.version DESC LIMIT 1`, reach, len(sargs)), sargs...).Scan(&nextID, &nextVersion, &nextStatus)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
	case err != nil:
		return nil, fmt.Errorf("iapages: the report's newer version: %w", err)
	default:
		v := strconv.Itoa(nextVersion)
		out = append(out, note("Version "+v+" corrects this report ("+nextStatus+"). Open version "+v, "Open version "+v, ReportsPath+nextID+"/"))
	}
	if !x.supersedes {
		return out, nil
	}
	var priorID, priorStatus string
	var priorVersion int
	if err := s.db.QueryRow(ctx, `SELECT p.id, p.version, p.status FROM impact_report r JOIN impact_report p ON p.id = r.supersedes_id
WHERE r.id = $1`, x.id).Scan(&priorID, &priorVersion, &priorStatus); err != nil {
		return nil, fmt.Errorf("iapages: the version it corrects: %w", err)
	}
	until := "is released"
	if priorStatus == "returned" || priorStatus == "withdrawn" {
		until = "is submitted"
	}
	v := strconv.Itoa(priorVersion)
	return append(out, note("This version corrects version "+v+", which stands until this one "+until+".", "version "+v, ReportsPath+priorID+"/")), nil
}
