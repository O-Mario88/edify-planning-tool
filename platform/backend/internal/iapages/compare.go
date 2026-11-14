package iapages

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// ComparePath is Evidence Compare: an activity's plan beside what the field
// submitted.
const ComparePath = "/ia/compare/"

// leadVerifiedSQL is lead_verified_q over activity `a`: staff-delivered
// work owned by someone a Programme Lead verifies (a CCEO, a lead, or anyone
// a lead supervises), its arguments at $n and $n+1.
func leadVerifiedSQL(n int) string {
	return fmt.Sprintf(`(a.delivery_type IS DISTINCT FROM 'partner' AND a.responsible_staff_id IN (
  SELECT x FROM (SELECT sp.id, sp.user_id FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
    WHERE sp.deleted_at IS NULL AND (u.roles && $%[1]d::varchar[] OR EXISTS (
      SELECT 1 FROM staff_supervisor_assignment l JOIN staff_profile sv ON sv.id = l.supervisor_id JOIN "user" su ON su.id = sv.user_id
      WHERE l.supervisee_id = sp.id AND sv.deleted_at IS NULL AND su.roles @> ARRAY[$%[2]d::varchar]))) lv,
  LATERAL (VALUES (lv.id), (lv.user_id)) AS ids(x) WHERE x IS NOT NULL))`, n, n+1)
}

// waiting is one activity in the picker.
type waiting struct {
	id, kind string
	school   *string
}

// compared is the chosen activity as the comparison reads it.
type compared struct {
	id, kind, intervention, salesforce   string
	schoolID, school, clusterID, cluster *string
	planned                              *time.Time
	scheduled                            *time.Time
	teachers, leaders                    int
}

// evidenceFile is one unquarantined upload.
type evidenceFile struct {
	id, name, kind string
	size           *int64
}

// schoolSSA is the school's latest SSA record, when it has one.
type schoolSSA struct {
	found   bool
	average *float64
}

// compare is ia_compare_view. An activity asked for outside the reader's
// reach is not found.
func (s *Service) compare(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	where, args, err := reach(ctx, s.db, p, s.now(), nil)
	if err != nil {
		return nil, true, err
	}
	const from = `FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id `
	wargs := append(append([]any{}, args...), rules.LeadVerifiedRoles, rules.LeadRole)
	rows, err := s.db.Query(ctx, `SELECT a.id, a.activity_type, s.name `+from+`
WHERE `+where+` AND a.deleted_at IS NULL AND a.status = 'awaiting_ia_verification' AND NOT COALESCE(`+leadVerifiedSQL(len(args)+1)+`, FALSE)
ORDER BY a.created_at, a.id`, wargs...)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the activities awaiting verification: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (waiting, error) {
		var w waiting
		return w, r.Scan(&w.id, &w.kind, &w.school)
	})
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the activities awaiting verification: %w", err)
	}
	id := query.Get("activity_id")
	if id == "" && len(list) > 0 {
		id = list[0].id
	}
	if id == "" {
		return comparePage(p, list, nil, nil, schoolSSA{}), true, nil
	}
	var c compared
	aargs := append(append([]any{}, args...), id)
	err = s.db.QueryRow(ctx, fmt.Sprintf(`SELECT a.id, a.activity_type, COALESCE(a.focus_intervention, ''), COALESCE(a.salesforce_activity_id, ''),
  s.id, s.name, cl.id, cl.name, a.planned_date, a.scheduled_date, COALESCE(a.teachers_attended, 0), COALESCE(a.leaders_attended, 0)
%sWHERE %s AND a.id = $%d AND a.deleted_at IS NULL`, from, where, len(aargs)), aargs...).Scan(
		&c.id, &c.kind, &c.intervention, &c.salesforce, &c.schoolID, &c.school, &c.clusterID, &c.cluster, &c.planned, &c.scheduled, &c.teachers, &c.leaders)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, pagegate.ErrNotAvailable
	}
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the activity: %w", err)
	}
	rows, err = s.db.Query(ctx, `SELECT id, COALESCE(original_name, ''), kind, file_size FROM evidence_record
WHERE activity_id = $1 AND NOT quarantined ORDER BY created_at DESC`, c.id)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the evidence: %w", err)
	}
	files, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (evidenceFile, error) {
		var f evidenceFile
		return f, r.Scan(&f.id, &f.name, &f.kind, &f.size)
	})
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the evidence: %w", err)
	}
	var ssa schoolSSA
	if c.schoolID != nil {
		err := s.db.QueryRow(ctx, `SELECT TRUE, average_score FROM ssa_record WHERE school_id = $1 AND deleted_at IS NULL
ORDER BY date_of_ssa DESC NULLS LAST LIMIT 1`, *c.schoolID).Scan(&ssa.found, &ssa.average)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return nil, true, fmt.Errorf("iapages: reading the school's SSA: %w", err)
		}
	}
	return comparePage(p, list, &c, files, ssa), true, nil
}

// filesize is |filesizeformat, its non-breaking space read as a space.
func filesize(n *int64) string {
	b := int64(0)
	if n != nil {
		b = *n
	}
	switch {
	case b == 1:
		return "1 byte"
	case b < 1024:
		return strconv.FormatInt(b, 10) + " bytes"
	}
	v := float64(b)
	units := []string{"KB", "MB", "GB", "TB", "PB"}
	for i, u := range units {
		v /= 1024
		if v < 1024 || i == len(units)-1 {
			return strconv.FormatFloat(round1(v), 'f', 1, 64) + " " + u
		}
	}
	return ""
}

func linkItem(text, href string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{{Text: text, Href: href}}}}}
}

func heading(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: t}}
}

func titled(title string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Items: items}}}
}

// comparePage is pages/ia/compare_evidence.html as the feed reads it. The
// school check's "MATCHED" sits in a span the feed does not read.
func comparePage(p auth.Principal, list []waiting, act *compared, files []evidenceFile, ssa schoolSSA) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Verification", Title: "Evidence Compare", BackLabel: "Back to Verification Queue", BackHref: "/ia/verification/",
		Description: "The plan beside the evidence: what was scheduled for a school and what the field submitted, side by side."}
	kindLabel := func(k string) string {
		if l, ok := rules.ActivityTypes[k]; ok {
			return l
		}
		return k
	}
	picker := []*screensv1.PagePanelItem{}
	if len(list) == 0 {
		picker = append(picker, text("No pending activities"))
	} else {
		links := &screensv1.PageLinks{}
		for _, w := range list {
			school := "Cluster-wide"
			if w.school != nil && *w.school != "" {
				school = *w.school
			}
			links.Links = append(links.Links, &screensv1.PageLink{Text: "#" + w.id[:min(8, len(w.id))], Href: ComparePath + "?activity_id=" + w.id,
				Caption: closedschools.Collapse(school + " · " + kindLabel(w.kind))})
		}
		picker = append(picker, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: links}})
	}
	blocks := []*screensv1.PageBlock{titled("Awaiting Verification", picker...)}
	if act == nil {
		blocks = append(blocks, titled("", text("Please select an activity from the side panel to begin side-by-side comparison.")))
		return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: ComparePath}
	}
	school := text("Cluster-wide")
	if act.schoolID != nil {
		name := closedschools.Collapse(*act.school)
		if slices.Contains(rules.SchoolProfileRoles, p.ActiveRole) {
			school = linkItem(name, "/schools/"+*act.schoolID)
		} else {
			school = text(name)
		}
	}
	cluster := text("No Cluster")
	if act.clusterID != nil {
		cluster = linkItem(closedschools.Collapse(*act.cluster), "/clusters/"+*act.clusterID)
	}
	intervention := "None"
	if act.intervention != "" {
		intervention = act.intervention
		if l, ok := rules.InterventionLabels[act.intervention]; ok {
			intervention = l
		}
	}
	planned, executed := "N/A", "N/A"
	if act.planned != nil {
		planned = act.planned.Format(time.DateOnly)
	}
	if act.scheduled != nil {
		executed = act.scheduled.In(zone).Format(time.DateOnly)
	}
	salesforce := act.salesforce
	if salesforce == "" {
		salesforce = "Unlinked"
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title:  "Plan Parameters vs Field Submission",
		Badges: []*screensv1.PageBadge{{Text: "Activity: #" + act.id, Tone: "plain"}},
		Items: []*screensv1.PagePanelItem{
			heading("Plan Targets"), text("Target School:"), school, text("Target Cluster:"), cluster,
			text("Intervention:"), text(intervention), text("Planned Date:"), text(planned),
			heading("Field Execution Actuals"), text("Execution School:"), school, text("Execution Cluster:"), cluster,
			text("Salesforce Activity ID:"), text(closedschools.Collapse(salesforce)), text("Execution Date:"), text(executed),
		}}}})
	uploads := []*screensv1.PagePanelItem{}
	for _, f := range files {
		uploads = append(uploads, text(closedschools.Collapse(f.name)), text(f.kind+" • "+filesize(f.size)),
			linkItem("Download File", "/api/evidence/"+f.id+"/file?download=1"))
	}
	if len(uploads) == 0 {
		uploads = append(uploads, text("No evidence documents uploaded."))
	}
	blocks = append(blocks, titled("Uploaded Evidence Document List", uploads...))
	// The planned day against the scheduled moment's date (UTC, as the
	// template's .date reads it); with no scheduled moment they never match.
	variance := "Deviation Flagged"
	if act.planned != nil && act.scheduled != nil && act.scheduled.UTC().Format(time.DateOnly) == act.planned.Format(time.DateOnly) {
		variance = "0 days variance"
	}
	score := "SSA Required"
	switch {
	case ssa.found && ssa.average == nil:
		score = "None Average"
	case ssa.found:
		score = floatText(*ssa.average) + " Average"
	}
	blocks = append(blocks, titled("Compliance Variance Analysis",
		text("School Identity Validation"), text("Scheduled Date Overlap"), text(variance),
		text("Headcount Attendance Verification"), text("T: "+strconv.Itoa(act.teachers)+" • L: "+strconv.Itoa(act.leaders)),
		text("SSA Score Integrity"), text(score)),
		titled("", heading("Ready to certify this activity?"),
			text("Enter the workspace checklist to approve this outcome or return it for correction."),
			linkItem("Review Workspace", "/ia/verification/"+act.id+"/")))
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: ComparePath}
}
