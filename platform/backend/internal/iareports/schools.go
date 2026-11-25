package iareports

// School briefs (schools_drawer, schools_release →
// reports.release_school_briefs): one school version per school, each handed
// to the school's account owner as an action to share on a visit.

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iapages"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	briefIssueType   = "impact_findings_share"
	briefDueDays     = 30
	eventSchoolBrief = "ia.report.school_brief"
)

// BriefURL is reports.brief_url.
func BriefURL(release string) string { return "/impact-briefs/" + release + "/" }

// storedSnapshot is a report's frozen evidence as stored, numbers as written.
func storedSnapshot(ctx context.Context, q schooldirectory.Querier, id string) (map[string]any, string, error) {
	var raw []byte
	var hash string
	if err := q.QueryRow(ctx, `SELECT evidence_snapshot::text, snapshot_hash FROM impact_report WHERE id = $1`, id).Scan(&raw, &hash); err != nil {
		return nil, "", fmt.Errorf("iareports: the frozen evidence: %w", err)
	}
	d := json.NewDecoder(strings.NewReader(string(raw)))
	d.UseNumber()
	var snapshot map[string]any
	if err := d.Decode(&snapshot); err != nil {
		return nil, "", fmt.Errorf("iareports: reading the frozen evidence: %w", err)
	}
	return snapshot, hash, nil
}

// mayReleaseSchools is can_release_schools.
func (r Reports) mayReleaseSchools(ctx context.Context, q schooldirectory.Querier, p auth.Principal, x *report) (bool, error) {
	if x.status != "released" {
		return false, nil
	}
	var reviewer string
	if err := q.QueryRow(ctx, `SELECT COALESCE(reviewed_by_id, '') FROM impact_report WHERE id = $1`, x.id).Scan(&reviewer); err != nil {
		return false, fmt.Errorf("iareports: the report's reviewer: %w", err)
	}
	if reviewer == p.UserID {
		return true, nil
	}
	return isCountryCD(ctx, q, p, x.country)
}

// schoolsDrawer is schools_drawer.
func (r Reports) schoolsDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	x, err := r.visible(ctx, r.DB, p, id, false)
	if err != nil || x == nil {
		if err == nil {
			err = errNoReport
		}
		return nil, err
	}
	may, err := r.mayReleaseSchools(ctx, r.DB, p, x)
	if err != nil {
		return nil, err
	}
	if !may {
		return emptyDrawer("Release school briefs", x.title,
			"The report's reviewer or the Country Director releases school briefs, after the leadership release."), nil
	}
	snapshot, _, err := storedSnapshot(ctx, r.DB, id)
	if err != nil {
		return nil, err
	}
	rows, err := r.DB.Query(ctx, `SELECT school_id FROM impact_report_release WHERE report_id = $1 AND audience = 'school'`, id)
	if err != nil {
		return nil, fmt.Errorf("iareports: the released briefs: %w", err)
	}
	released, err := pgx.CollectRows(rows, pgx.RowTo[*string])
	if err != nil {
		return nil, fmt.Errorf("iareports: the released briefs: %w", err)
	}
	done := map[string]bool{}
	for _, s := range released {
		if s != nil {
			done[*s] = true
		}
	}
	seen, options := map[string]string{}, [][2]string{}
	for _, raw := range list(snapshot["rows"]) {
		row := object(raw)
		school := str(row["school_id"])
		if school == "" {
			continue
		}
		if _, ok := seen[school]; !ok {
			name := str(row["school"])
			if name == "" {
				name = school
			}
			seen[school] = name
			options = append(options, [2]string{school, name})
		}
	}
	sort.SliceStable(options, func(i, j int) bool { return strings.ToLower(options[i][1]) < strings.ToLower(options[j][1]) })
	open := []*screensv1.DrawerOption{}
	values := []string{}
	for _, o := range options {
		if !done[o[0]] {
			open = append(open, &screensv1.DrawerOption{Value: o[0], Label: o[1]})
			values = append(values, o[0])
		}
	}
	if len(open) == 0 {
		return emptyDrawer("Release school briefs", x.title, "Every school in the report's evidence already has its brief."), nil
	}
	return &screensv1.PageDrawer{Title: "Release school briefs", Subtitle: x.title, HasRequired: true, SubmitLabel: "Release briefs",
		CancelLabel: "Cancel", CanSubmit: true, Items: []*screensv1.DrawerItem{
			note("Each school's account owner receives an action to share the brief on a visit and record what the school said."),
			// A multiselect: the feed's reader takes it for one select, so Go
			// draws the list the web shows (a deliberate difference, doc 189).
			field(&screensv1.DrawerField{Name: "schools", Label: "Schools", Kind: "checklist", Required: true,
				Value: strings.Join(values, ","), Options: open}),
		}}, nil
}

type releasedBrief struct{ release, recipient, school string }

// releaseSchools is reports.release_school_briefs.
func (r Reports) releaseSchools(ctx context.Context, p auth.Principal, id string, values map[string]string) (Saved, error) {
	wanted := ticked(values["schools"])
	if len(wanted) == 0 {
		return Saved{}, refuse("Choose at least one school.")
	}
	now := r.now()
	today := kampalaDay(now)
	var x *report
	released := []releasedBrief{}
	err := pgx.BeginTxFunc(ctx, r.DB, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		var err error
		if x, err = r.visible(ctx, tx, p, id, true); err != nil {
			return err
		}
		if x == nil {
			return refuse("That impact report is not in your country.")
		}
		if x.status != "released" {
			return refuse("School briefs follow the leadership release; release the report first.")
		}
		may, err := r.mayReleaseSchools(ctx, tx, p, x)
		if err != nil {
			return err
		}
		if !may {
			return refuse("The report's reviewer or the Country Director releases school briefs.")
		}
		snapshot, hash, err := storedSnapshot(ctx, tx, id)
		if err != nil {
			return err
		}
		if err := r.withPeople(ctx, tx, id, snapshot); err != nil {
			return err
		}
		inReport := map[string]bool{}
		for _, raw := range list(snapshot["rows"]) {
			inReport[str(object(raw)["school_id"])] = true
		}
		for _, s := range wanted {
			if !inReport[s] {
				return refuse("Choose schools the report's evidence covers.")
			}
		}
		narrative := map[string]string{"methodology": x.methodology, "findings": x.findings, "limitations": x.limitations}
		period := iapages.PeriodLabel(x.fy, x.start, x.end)
		for _, school := range wanted {
			var name, ownerUser, ownerRole string
			var ownerActive, exists bool
			err := tx.QueryRow(ctx, `SELECT s.name, COALESCE(u.id, ''), COALESCE(u.active_role, ''), COALESCE(u.is_active, false),
  EXISTS (SELECT 1 FROM impact_report_release r WHERE r.report_id = $2 AND r.audience = 'school' AND r.school_id = s.id)
FROM school s LEFT JOIN staff_profile sp ON sp.id = s.account_owner_id AND sp.deleted_at IS NULL
LEFT JOIN "user" u ON u.id = sp.user_id WHERE s.id = $1 AND s.deleted_at IS NULL`, school, id).
				Scan(&name, &ownerUser, &ownerRole, &ownerActive, &exists)
			if err == pgx.ErrNoRows {
				continue
			}
			if err != nil {
				return fmt.Errorf("iareports: a school to brief: %w", err)
			}
			if exists || ownerUser == "" || !ownerActive {
				continue
			}
			payload, err := json.Marshal(schoolPayload(snapshot, school, name, narrative))
			if err != nil {
				return fmt.Errorf("iareports: the school's brief: %w", err)
			}
			release, action := cuid.New(), cuid.New()
			if _, err := tx.Exec(ctx, `INSERT INTO impact_report_release (id, created_at, updated_at, audience, redaction_profile,
  rendered_payload, status, requested_by_id, approved_by_id, approved_at, released_by_id, released_at, revoked_reason, report_id, school_id)
VALUES ($1, $2, $2, 'school', 'school', $3::jsonb, 'released', $4, $4, $2, $4, $2, '', $5, $6)`, release, now, string(payload), p.UserID, id, school); err != nil {
				return fmt.Errorf("iareports: releasing the school's brief: %w", err)
			}
			if _, err := tx.Exec(ctx, `INSERT INTO team_action (created_at, updated_at, id, condition_key, issue_type, severity, school_id, fy,
  sender_id, sender_role, recipient_id, recipient_role, requested_action, workflow_route, message, priority, due_date, state, detected_at,
  blocked_reason, resolved_by_system, manual_resolution_reason, returned_reason, reminder_count)
VALUES ($1, $1, $2, $3, $4, 'normal', $5, $6, $7, $8, $9, $10, 'Share impact findings with the school', $11, $12, 'normal', $13, 'open', $1,
  '', false, '', '', 0)`, now, action, "impact_brief:"+release, briefIssueType, school, x.fy, p.UserID, p.ActiveRole, ownerUser, ownerRole,
				BriefURL(release), x.title+" ("+period+"): share the school's brief on your next visit and record what the school said.",
				today.AddDate(0, 0, briefDueDays)); err != nil {
				return fmt.Errorf("iareports: the brief's action: %w", err)
			}
			if _, err := audit.Append(ctx, tx, reportAudit("ia.report.released", id, p, x.country, x.version, x.status, hash,
				map[string]any{"audience": redactionSchool, "release_id": release, "school_id": school, "team_action_id": action}), now); err != nil {
				return err
			}
			released = append(released, releasedBrief{release: release, recipient: ownerUser, school: name})
		}
		return nil
	})
	if err != nil {
		return Saved{}, err
	}
	for _, b := range released {
		title := "Share impact findings with " + b.school
		if len([]rune(title)) > 200 {
			title = string([]rune(title)[:200])
		}
		if err := activities.SendNotices(ctx, r.DB, r.Push, r.Live, r.Logger, r.now(), b.release, "", activities.Origin{},
			activities.Notice{Title: title, Body: "Impact Assessment's brief for the school is ready to share on your next visit.",
				Event: eventSchoolBrief, Category: "ia", ContextType: "ImpactReportRelease", Priority: "normal"},
			[]activities.NoticeTo{{UserID: b.recipient, Route: BriefURL(b.release), Label: "Open School Brief"}}); err != nil && r.Logger != nil {
			r.Logger.Warn("iareports: the account owner was not told", "release", b.release, "err", err)
		}
	}
	plural := "s"
	if len(released) == 1 {
		plural = ""
	}
	return Saved{Message: fmt.Sprintf("%d school brief%s released to account owners.", len(released), plural), ReportID: id}, nil
}

// withPeople is reports.snapshot_with_people: the snapshot's people plus
// the author's and reviewer's names, for the scrub.
func (r Reports) withPeople(ctx context.Context, q schooldirectory.Querier, id string, snapshot map[string]any) error {
	rows, err := q.Query(ctx, `SELECT COALESCE(u.name, '') FROM impact_report r JOIN "user" u ON u.id IN (r.author_id, r.reviewed_by_id)
WHERE r.id = $1`, id)
	if err != nil {
		return fmt.Errorf("iareports: the report's people: %w", err)
	}
	names, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return fmt.Errorf("iareports: the report's people: %w", err)
	}
	people := list(snapshot["people"])
	for _, n := range names {
		people = append(people, n)
	}
	snapshot["people"] = people
	return nil
}
