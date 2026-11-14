package iapages

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// SamplesPath is Sample Checks, the second look at a share of verified work.
const SamplesPath = "/ia/samples/"

const samplesPageParam = "samples_page"

// sample is one drawn sample with what its row shows.
type sample struct {
	ID, Subject, Method, Status, Note, Verifier string
	Checker                                     *string
	CheckedAt                                   *time.Time
	SampledAt                                   time.Time
	ActivityID, ActivityType                    string
	SSAID, SSASchoolID                          string
	SSADate                                     *time.Time
	SchoolName                                  *string
	Excluded                                    bool
}

// samples is ia_samples_view: the samples in the reader's reach (activities
// in their country, SSA records of the schools an analytics surface lets
// them read), filtered by outcome and record when one of the known values is
// asked, by status then newest drawn, a page at a time. The grading menu and
// forms in each row's last cell are not read by the feed, so who may grade a
// sample does not change the answer.
func (s *Service) samples(ctx context.Context, p auth.Principal, role Role, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return nil, true, fmt.Errorf("iapages: resolving the reader's scope: %w", err)
	}
	args := []any{}
	activityReach := "TRUE"
	if scope.CountryScope && scope.Country != "" {
		args = append(args, scope.Country)
		activityReach = schoolprofile.ActivityInCountry(len(args))
	}
	schoolReach := schooldirectory.AnalyticsReach(scope, &args)
	status := query.Get("status")
	if !slices.Contains([]string{"pending", "confirmed", "disputed"}, status) {
		status = ""
	}
	subject := query.Get("subject")
	if !slices.Contains([]string{"activity", "ssa_record"}, subject) {
		subject = ""
	}
	where := fmt.Sprintf(`(v.activity_id IN (SELECT a.id FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id WHERE %s)
  OR r.school_id IN (SELECT s.id FROM school s WHERE %s))`, activityReach, schoolReach)
	if status != "" {
		args = append(args, status)
		where += fmt.Sprintf(" AND v.status = $%d", len(args))
	}
	if subject != "" {
		args = append(args, subject)
		where += fmt.Sprintf(" AND v.subject_type = $%d", len(args))
	}
	const from = `FROM ia_verification_sample v LEFT JOIN activity a ON a.id = v.activity_id LEFT JOIN ssa_record r ON r.id = v.ssa_record_id `
	var total int
	if err := s.db.QueryRow(ctx, `SELECT count(*) `+from+`WHERE `+where, args...).Scan(&total); err != nil {
		return nil, true, fmt.Errorf("iapages: counting the samples: %w", err)
	}
	number, pages := closedschools.PageOf(query.Get(samplesPageParam), total, rules.SamplePageSize)
	pageArgs := append(append([]any{}, args...), rules.SamplePageSize, (number-1)*rules.SamplePageSize)
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT v.id, v.subject_type, v.method, v.status, v.outcome_note, v.original_verifier, v.checked_by, v.checked_at, v.sampled_at,
  COALESCE(v.activity_id, ''), COALESCE(a.activity_type, ''), COALESCE(v.ssa_record_id, ''), COALESCE(r.school_id, ''), r.date_of_ssa,
  CASE WHEN v.subject_type = 'ssa_record' AND v.ssa_record_id IS NOT NULL THEN rs.name ELSE asch.name END,
  EXISTS (SELECT 1 FROM ia_verification_history h WHERE h.activity_id = v.activity_id AND NOT h.analytics_included)
%sLEFT JOIN school rs ON rs.id = r.school_id LEFT JOIN school asch ON asch.id = a.school_id
WHERE %s ORDER BY v.status, v.sampled_at DESC LIMIT $%d OFFSET $%d`, from, where, len(pageArgs)-1, len(pageArgs)), pageArgs...)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the samples: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (sample, error) {
		var x sample
		err := r.Scan(&x.ID, &x.Subject, &x.Method, &x.Status, &x.Note, &x.Verifier, &x.Checker, &x.CheckedAt, &x.SampledAt,
			&x.ActivityID, &x.ActivityType, &x.SSAID, &x.SSASchoolID, &x.SSADate, &x.SchoolName, &x.Excluded)
		return x, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the samples: %w", err)
	}
	ids := []string{}
	for _, x := range list {
		ids = append(ids, x.Verifier)
		if x.Checker != nil {
			ids = append(ids, *x.Checker)
		}
	}
	names, err := accountNames(ctx, s.db, ids)
	if err != nil {
		return nil, true, err
	}
	return samplesPage(p, role, list, names, number, pages, total, status, subject, query), true, nil
}

// accountNames is each account id's name (any account, as the view reads
// them), for the verifiers and graders on the page.
func accountNames(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]string, error) {
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT id, name FROM "user" WHERE id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the verifiers' names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, err
		}
		out[id] = name
	}
	return out, rows.Err()
}

func isSSASample(x sample) bool { return x.Subject == "ssa_record" && x.SSAID != "" }

// outcome is the sample's outcome as the row words it.
func outcome(x sample) string {
	switch {
	case x.Status == "pending":
		return "Pending"
	case x.Status == "confirmed":
		return "Confirmed"
	case isSSASample(x):
		return "Disputed · SSA returned to its collector"
	case x.Excluded:
		return "Disputed · excluded from analytics until resolved"
	}
	return "Disputed · resolved"
}

func samplesPage(p auth.Principal, role Role, list []sample, names map[string]string, number, pages, total int,
	status, subject string, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Verification", Title: "Sample Checks",
		Description: "A second look at " + strconv.Itoa(rules.SampleSharePct) + "% of last week's verified activities and confirmed SSA records in your country, drawn every Monday. A verifier other than the original one confirms or disputes each; a disputed SSA returns to its collector and a disputed activity leaves analytics until the dispute is resolved."}
	if slices.Contains(rules.SampleDrawRoles, p.ActiveRole) {
		// The draw is a form's submit button: the feed reads it with no link.
		header.Actions = []*screensv1.PageAction{{Key: "draw_this_week_now", Label: "Draw this week now", Enabled: true}}
	}
	blocks := []*screensv1.PageBlock{}
	if role.Strip != nil {
		tabs := &screensv1.PageLinkTabs{Label: role.Strip.Label, Scrolls: role.Strip.Scrolls}
		for _, t := range role.Strip.Tabs {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: t.Label, Href: t.Href, Active: t.Active})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}})
	}
	blocks = append(blocks,
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Samples"}}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{
			{Name: "status", Value: status, Caption: "Outcome", Options: []*screensv1.PageFilterOption{
				{Value: "", Label: "All outcomes"}, {Value: "pending", Label: "Pending"}, {Value: "confirmed", Label: "Confirmed"}, {Value: "disputed", Label: "Disputed"}}},
			{Name: "subject", Value: subject, Caption: "Record", Options: []*screensv1.PageFilterOption{
				{Value: "", Label: "Activities and SSA"}, {Value: "activity", Label: "Verified activities"}, {Value: "ssa_record", Label: "Confirmed SSA"}}},
		}}}},
	)
	t := &screensv1.PageTable{}
	if len(list) == 0 {
		t.EmptyMessage = "No samples drawn yet"
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No samples drawn yet The first sample is drawn on Monday, or draw this week now."}}}}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
		return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: SamplesPath}
	}
	for _, c := range []string{"School ID", "School", "Record", "Original verifier", "Drawn", "Check", "Outcome", ""} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	for _, x := range list {
		school := "Cluster-wide"
		hasSchool := x.SchoolName != nil
		if hasSchool {
			school = *x.SchoolName
		}
		// {% school_code %}: the feed never fills the token, so a school's
		// ID reads empty; no school reads a dash.
		code := "—"
		if hasSchool {
			code = ""
		}
		var record, href string
		if isSSASample(x) {
			record = "Confirmed SSA"
			if x.SSADate != nil {
				record += " dated " + x.SSADate.In(zone).Format("2 Jan 2006")
			}
			href = "/schools/" + x.SSASchoolID + "#ssa-timeline"
		} else {
			record = "Activity"
			if x.ActivityID != "" {
				record = x.ActivityType
				if l, ok := rules.ActivityTypes[x.ActivityType]; ok {
					record = l
				}
				href = "/ia/verification/" + x.ActivityID + "/"
			}
		}
		verifier, ok := names[x.Verifier]
		if !ok {
			verifier = x.Verifier
		}
		text := outcome(x)
		if x.Note != "" {
			text += " · " + x.Note
		}
		if x.Checker != nil && *x.Checker != "" {
			if checker := names[*x.Checker]; checker != "" {
				text += " · by " + checker + ", "
				if x.CheckedAt != nil {
					text += x.CheckedAt.In(zone).Format("02 Jan")
				}
			}
		}
		method, ok := rules.SampleMethods[x.Method]
		if !ok {
			method = x.Method
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: code},
			{Text: closedschools.Collapse(school), Href: href},
			{Text: closedschools.Collapse(record)},
			{Text: closedschools.Collapse(verifier)},
			{Text: x.SampledAt.In(zone).Format("02 Jan 2006")},
			{Text: method},
			{Text: closedschools.Collapse(text)},
			{},
		}})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel(samplesPageParam, number, pages, total, rules.SamplePageSize, query, rules.QueryKeysNotPassed))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: SamplesPath}
}
