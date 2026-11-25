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
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
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

// draftReport is what the draft page reads of its report.
type draftReport struct {
	report
	project, methodology, findings, limitations string
	supersedes                                  bool
	snapshot                                    bool
}

func dashCell(t string) *screensv1.PageCell {
	if t == "" {
		t = "—"
	}
	return &screensv1.PageCell{Text: t}
}

func dayTime(t time.Time) string { return t.In(zone).Format("2 Jan 2006 15:04") }

func (s *Service) reportDetail(ctx context.Context, p auth.Principal, role Role, id string) (*screensv1.GetPageResponse, bool, error) {
	args := []any{}
	reach, err := s.reportReach(ctx, p, &args)
	if err != nil {
		return nil, true, err
	}
	args = append(args, id)
	var x draftReport
	err = s.db.QueryRow(ctx, fmt.Sprintf(`SELECT r.id, r.title, r.status, r.author_id, COALESCE(r.reviewed_by_id, ''), r.country, r.fy,
  r.period_start, r.period_end, COALESCE(r.programme_areas, '{}'), r.version, COALESCE(pr.name, ''), r.methodology, r.findings,
  r.limitations, r.supersedes_id IS NOT NULL, r.evidence_snapshot <> '{}'::jsonb
FROM impact_report r LEFT JOIN project pr ON pr.id = r.project_id WHERE (%s) AND r.id = $%d`, reach, len(args)), args...).
		Scan(&x.id, &x.title, &x.status, &x.author, &x.reviewer, &x.country, &x.fy, &x.start, &x.end, &x.programmes, &x.version,
			&x.project, &x.methodology, &x.findings, &x.limitations, &x.supersedes, &x.snapshot)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the report: %w", err)
	}
	if x.status != "draft" || x.snapshot || x.supersedes {
		return nil, false, nil
	}
	var successor bool
	sargs := append(args[:len(args)-1:len(args)-1], id)
	if err := s.db.QueryRow(ctx, fmt.Sprintf(`SELECT EXISTS (SELECT 1 FROM impact_report r WHERE (%s) AND r.supersedes_id = $%d)`,
		reach, len(sargs)), sargs...).Scan(&successor); err != nil {
		return nil, true, fmt.Errorf("iapages: the report's successor: %w", err)
	}
	if successor {
		return nil, false, nil
	}
	author := x.author == p.UserID && p.ActiveRole == roleIA
	header := &screensv1.PageHeader{Title: x.title,
		Description: reportStatusLabel(x.status) + " · version " + strconv.Itoa(x.version) + " · " + x.country}
	if author {
		header.Actions = []*screensv1.PageAction{
			pageheader.Drawer("Edit draft", ReportsPath+id+"/edit", false),
			{Key: "submit_for_review", Label: "Submit for review", Enabled: true},
			{Key: "withdraw", Label: "Withdraw", Enabled: true},
		}
	}
	blocks := workspaceStrip(role)
	facts, err := s.reportFacts(ctx, x)
	if err != nil {
		return nil, true, err
	}
	blocks = append(blocks, titled("The report", facts...))
	summaryOnly := p.ActiveRole == roleRVP
	if !summaryOnly {
		if author {
			blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
				Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
					{Text: "Add recommendation", Href: ReportsPath + id + "/recommendations/new", Drawer: true}}}}}}}}})
		}
		table, err := s.recommendationTable(ctx, x, author)
		if err != nil {
			return nil, true, err
		}
		blocks = append(blocks, titled("Recommendations"), table)
	}
	blocks = append(blocks,
		titled("Evidence", text("The evidence is taken by the server, in your scope, the moment the report is submitted — the project cohort in the period, school change with its evidence grades, learning, discipleship and EdTech evidence, mapping versions, verified loan conclusions and approved findings — and never changes afterwards.")),
		titled("Releases"), emptyTable(x.title, "Not released",
			"A reviewed report is released to country leadership first, then school briefs and the donor version."))
	if !summaryOnly {
		table, err := s.historyTable(ctx, x)
		if err != nil {
			return nil, true, err
		}
		blocks = append(blocks, titled("History"), table)
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: ReportsPath + id + "/"}, true, nil
}

// emptyTable is impact_reports_table.html with no rows, as the feed reads
// its empty state.
func emptyTable(title, empty, body string) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{EmptyMessage: empty,
		Rows: []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: title + " " + empty + " " + body}}}}}}}
}

func (s *Service) reportFacts(ctx context.Context, x draftReport) ([]*screensv1.PagePanelItem, error) {
	var author string
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(name, '') FROM "user" WHERE id = $1`, x.author).Scan(&author); err != nil &&
		!errors.Is(err, pgx.ErrNoRows) {
		return nil, fmt.Errorf("iapages: the report's author: %w", err)
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
	items := []*screensv1.PagePanelItem{}
	for _, f := range [][2]string{{"Country", x.country}, {"Period", periodLabel(x.report)}, {"Financial year", fy},
		{"Special project", project}, {"Programme areas", programmes}, {"Author", author}} {
		if f[1] != "" {
			items = append(items, text(f[0]), text(f[1]))
		}
	}
	for _, f := range [][2]string{{"Methodology", x.methodology}, {"Findings", x.findings}, {"Limitations", x.limitations}} {
		value := f[1]
		if value == "" {
			value = "Not written yet"
		}
		items = append(items, text(f[0]), text(linebreaksRead(value)))
	}
	return items, nil
}

// linebreaksRead is linebreaksbr's text. The feed's reader drops a value
// with line breaks altogether; Go keeps it with its breaks (a deliberate
// difference, as on the Verify form, doc 189).
func linebreaksRead(v string) string { return strings.ReplaceAll(v, "\r\n", "\n") }

func (s *Service) recommendationTable(ctx context.Context, x draftReport, author bool) (*screensv1.PageBlock, error) {
	rows, err := s.db.Query(ctx, `SELECT text, owner_role, due_date, status, response FROM impact_report_recommendation
WHERE report_id = $1 ORDER BY due_date, created_at`, x.id)
	if err != nil {
		return nil, fmt.Errorf("iapages: the recommendations: %w", err)
	}
	defer rows.Close()
	t := &screensv1.PageTable{}
	for rows.Next() {
		var words, owner, status, response string
		var due *time.Time
		if err := rows.Scan(&words, &owner, &due, &status, &response); err != nil {
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
		cells := []*screensv1.PageCell{dashCell(words), dashCell(forWhom), dashCell(dueBy), dashCell(label), dashCell(response)}
		if author {
			// Its Remove is a one-button form the feed does not read.
			cells = append(cells, &screensv1.PageCell{})
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells})
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iapages: the recommendations: %w", err)
	}
	if len(t.Rows) == 0 {
		body := "This report makes no recommendations."
		if author {
			body = "Add what should change, who acts and by when."
		}
		return emptyTable(x.title, "No recommendations", body), nil
	}
	for _, c := range []string{"Recommendation", "For", "Due by", "Status", "Country Director's response"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	if author {
		t.Columns = append(t.Columns, &screensv1.PageColumn{})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}, nil
}

func (s *Service) historyTable(ctx context.Context, x draftReport) (*screensv1.PageBlock, error) {
	rows, err := s.db.Query(ctx, `SELECT a.action, COALESCE(a.actor_id, ''), COALESCE(a.actor_role, ''), a.created_at,
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
		if err := rows.Scan(&action, &actorID, &actorRole, &at, &reason, &actor); err != nil {
			return nil, fmt.Errorf("iapages: a history row: %w", err)
		}
		if actorID == "" {
			actor = "System"
		}
		label := action
		if l, ok := reportActionLabels[action]; ok {
			label = l
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
