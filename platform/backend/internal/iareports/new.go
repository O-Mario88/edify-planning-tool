package iareports

// Start an impact report (impact_report_views.report_new_drawer and
// report_create → reports.create_report).

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// NewPath is the Start an impact report drawer.
const NewPath = PagePath + "new"

const (
	newTitle     = "Start an impact report"
	authorOnly   = "Only Impact Assessment writes impact reports."
	draftSaved   = "Draft saved. Add recommendations, then submit it for review."
	noCountryYet = "Your staff profile has no country, so nobody can be named to review the report. Ask HR to record your country first."
)

func field(f *screensv1.DrawerField) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Field{Field: f}}
}

func note(text string) *screensv1.DrawerItem {
	return &screensv1.DrawerItem{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: text, Tone: "info"}}}
}

// emptyDrawer is _drawer with only its empty note.
func emptyDrawer(title, subtitle, empty string) *screensv1.PageDrawer {
	return &screensv1.PageDrawer{Title: title, Subtitle: subtitle, HasRequired: true, CancelLabel: "Cancel",
		Items: []*screensv1.DrawerItem{note(empty)}}
}

// reportValues are a report's fields as the form shows them.
type reportValues struct {
	title, fy, start, end, project, methodology, findings, limitations string
	areas                                                              []string
}

// reportFields is _report_fields as the feed reads them.
func (r Reports) reportFields(ctx context.Context, p auth.Principal, v reportValues) ([]*screensv1.DrawerItem, error) {
	projects, err := r.projectOptions(ctx, p)
	if err != nil {
		return nil, err
	}
	fyOptions := []*screensv1.DrawerOption{}
	for _, o := range schooldirectory.FYOptions(r.now()) {
		fyOptions = append(fyOptions, &screensv1.DrawerOption{Value: o, Label: "FY" + o})
	}
	areas := []*screensv1.DrawerOption{}
	for _, pr := range Programme {
		areas = append(areas, &screensv1.DrawerOption{Value: pr[0], Label: pr[1]})
	}
	items := []*screensv1.DrawerItem{
		field(&screensv1.DrawerField{Name: "title", Label: "Title", Kind: "text", Required: true, MaxLength: proto.Int32(200), Value: v.title}),
		field(&screensv1.DrawerField{Name: "fy", Label: "Financial year", Kind: "select", Required: true, Value: v.fy, Options: fyOptions}),
		field(&screensv1.DrawerField{Name: "period_start", Label: "Period start", Kind: "date", Value: v.start}),
		field(&screensv1.DrawerField{Name: "period_end", Label: "Period end", Kind: "date", Value: v.end}),
		// A multiselect: the feed's reader takes it for one select, so Go
		// draws the list the web shows (a deliberate difference, doc 189).
		field(&screensv1.DrawerField{Name: "programme_areas", Label: "Programme areas", Kind: "checklist",
			Value: strings.Join(v.areas, ","), Options: areas}),
	}
	if len(projects) > 0 {
		options := []*screensv1.DrawerOption{{Label: "Every project enrolment in scope"}}
		chosen := ""
		for _, pr := range projects {
			options = append(options, &screensv1.DrawerOption{Value: pr[0], Label: pr[1]})
			if pr[0] == v.project {
				chosen = v.project
			}
		}
		items = append(items, field(&screensv1.DrawerField{Name: "project", Label: "Special project cohort", Kind: "select",
			Value: chosen, Options: options}))
	}
	for _, t := range [][3]string{{"methodology", "Methodology", v.methodology}, {"findings", "Findings", v.findings},
		{"limitations", "Limitations", v.limitations}} {
		items = append(items, field(&screensv1.DrawerField{Name: t[0], Label: t[1], Kind: "textarea", MaxLength: proto.Int32(10000), Value: t[2]}))
	}
	return items, nil
}

// newDrawer is report_new_drawer.
func (r Reports) newDrawer(ctx context.Context, p auth.Principal, project string) (*screensv1.PageDrawer, error) {
	if !mayAuthor(p) {
		return emptyDrawer(newTitle, "Impact Reports", authorOnly), nil
	}
	items, err := r.reportFields(ctx, p, reportValues{fy: schooldirectory.OperationalFY(r.now()), project: project})
	if err != nil {
		return nil, err
	}
	return &screensv1.PageDrawer{Title: newTitle, Subtitle: "Draft · you add recommendations on the report page",
		HasRequired: true, SubmitLabel: "Save draft", CancelLabel: "Cancel", CanSubmit: true,
		Items: append([]*screensv1.DrawerItem{note("Nothing is frozen until you submit; a second officer reviews it before anyone reads it.")},
			items...)}, nil
}

// create is reports.create_report.
func (r Reports) create(ctx context.Context, p auth.Principal, values map[string]string) (Saved, error) {
	if !mayAuthor(p) {
		return Saved{}, refuse(authorOnly)
	}
	country, err := profileCountry(ctx, r.DB, p)
	if err != nil {
		return Saved{}, err
	}
	if country == "" {
		return Saved{}, refuse(noCountryYet)
	}
	f, err := r.clean(ctx, p, values)
	if err != nil {
		return Saved{}, err
	}
	id, now := cuid.New(), r.now()
	err = pgx.BeginTxFunc(ctx, r.DB, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `INSERT INTO impact_report (id, created_at, updated_at, author_id, author_role, review_basis,
  review_note, country, fy, period_start, period_end, programme_areas, title, status, methodology, findings, limitations,
  evidence_snapshot, snapshot_hash, version, project_id)
VALUES ($1, $2, $2, $3, $4, '', '', $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, '{}', '', 1, $15)`,
			id, now, p.UserID, p.ActiveRole, country, f.fy, f.periodStart, f.periodEnd, f.areas, f.title, statusDraft,
			f.methodology, f.findings, f.limitations, f.projectID); err != nil {
			return fmt.Errorf("iareports: saving the draft: %w", err)
		}
		_, err := audit.Append(ctx, tx, reportAudit("ia.report.started", id, p, country, 1, statusDraft, "", nil), now)
		return err
	})
	if err != nil {
		return Saved{}, err
	}
	return Saved{Message: draftSaved, ReportID: id}, nil
}

// reportAudit is reports._audit's row.
func reportAudit(action, id string, p auth.Principal, country string, version int, status, hash string, extra map[string]any) audit.Entry {
	payload := map[string]any{"country": country, "version": version, "status": status, "snapshot_hash": nil}
	if hash != "" {
		payload["snapshot_hash"] = hash
	}
	for k, v := range extra {
		payload[k] = v
	}
	return audit.Entry{Action: action, SubjectKind: audit.Text("ImpactReport"), SubjectID: audit.Text(id),
		ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true, Payload: payload}
}
