package iareports

// Edit a draft (impact_report_views.report_edit_drawer and report_update →
// reports.update_report), and add a recommendation to it
// (recommendation_new_drawer, recommendation_create → add_recommendation).

import (
	"context"
	"fmt"
	"slices"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// ActionOwners are findings.ACTION_OWNER_ROLES, in their order.
var ActionOwners = [][2]string{
	{"CountryDirector", "Country Director"}, {"Program Lead", "Programme Lead"},
	{"RegionalProgramLead", "Regional Lead for CCE"}, {"BusinessTransformationOfficer", "Business Transformation"},
	{"ImpactAssessment", "Impact Assessment"},
}

var errNoReport = &Refusal{Message: "This drawer is not available.", NotFound: true}

// editDrawer is report_edit_drawer.
func (r Reports) editDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	x, err := r.visible(ctx, r.DB, p, id, false)
	if err != nil || x == nil {
		if err == nil {
			err = errNoReport
		}
		return nil, err
	}
	if !x.canEdit(p) {
		return emptyDrawer("Edit impact report", x.title,
			"Only the author edits a draft; a submitted report is corrected as a new version."), nil
	}
	items, err := r.reportFields(ctx, p, reportValues{title: x.title, fy: x.fy, start: isoDay(x.start), end: isoDay(x.end),
		project: x.project, methodology: x.methodology, findings: x.findings, limitations: x.limitations, areas: x.areas})
	if err != nil {
		return nil, err
	}
	return &screensv1.PageDrawer{Title: "Edit impact report", Subtitle: "Draft · version " + strconv.Itoa(x.version),
		HasRequired: true, SubmitLabel: "Save draft", CancelLabel: "Cancel", CanSubmit: true, Items: items}, nil
}

// update is reports.update_report.
func (r Reports) update(ctx context.Context, p auth.Principal, id string, values map[string]string) (Saved, error) {
	f, err := r.clean(ctx, p, values)
	if err != nil {
		return Saved{}, err
	}
	now := r.now()
	err = pgx.BeginTxFunc(ctx, r.DB, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		x, err := r.ownDraft(ctx, tx, p, id)
		if err != nil {
			return err
		}
		project := ""
		if f.projectID != nil {
			project = *f.projectID
		}
		changed := []any{}
		for _, c := range []struct {
			key      string
			was, now any
		}{
			{"title", x.title, f.title}, {"fy", x.fy, f.fy}, {"period_start", isoDay(x.start), isoDay(f.periodStart)},
			{"period_end", isoDay(x.end), isoDay(f.periodEnd)}, {"programme_areas", fmt.Sprint(x.areas), fmt.Sprint(f.areas)},
			{"project_id", x.project, project}, {"methodology", x.methodology, f.methodology},
			{"findings", x.findings, f.findings}, {"limitations", x.limitations, f.limitations},
		} {
			if c.was != c.now {
				changed = append(changed, c.key)
			}
		}
		if _, err := tx.Exec(ctx, `UPDATE impact_report SET title = $2, fy = $3, period_start = $4, period_end = $5,
  programme_areas = $6, project_id = $7, methodology = $8, findings = $9, limitations = $10, updated_at = $11 WHERE id = $1`,
			id, f.title, f.fy, f.periodStart, f.periodEnd, f.areas, f.projectID, f.methodology, f.findings, f.limitations, now); err != nil {
			return fmt.Errorf("iareports: saving the draft: %w", err)
		}
		_, err = audit.Append(ctx, tx, reportAudit("ia.report.updated", id, p, x.country, x.version, x.status, "",
			map[string]any{"changed": changed}), now)
		return err
	})
	if err != nil {
		return Saved{}, err
	}
	return Saved{Message: "Draft saved.", ReportID: id}, nil
}

// recommendationDrawer is recommendation_new_drawer.
func (r Reports) recommendationDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	x, err := r.visible(ctx, r.DB, p, id, false)
	if err != nil || x == nil {
		if err == nil {
			err = errNoReport
		}
		return nil, err
	}
	if !x.canEdit(p) {
		return emptyDrawer("Add a recommendation", x.title, "Only the author adds recommendations, while the report is a draft."), nil
	}
	owners := []*screensv1.DrawerOption{}
	for _, o := range ActionOwners {
		owners = append(owners, &screensv1.DrawerOption{Value: o[0], Label: o[1]})
	}
	return &screensv1.PageDrawer{Title: "Add a recommendation", Subtitle: x.title, HasRequired: true,
		SubmitLabel: "Add recommendation", CancelLabel: "Cancel", CanSubmit: true, Items: []*screensv1.DrawerItem{
			field(&screensv1.DrawerField{Name: "text", Label: "Recommendation", Kind: "textarea", Required: true, MaxLength: proto.Int32(4000)}),
			field(&screensv1.DrawerField{Name: "owner_role", Label: "Who should act on it", Kind: "select", Required: true,
				Value: owners[0].GetValue(), Options: owners}),
			field(&screensv1.DrawerField{Name: "due_date", Label: "Due by", Kind: "date", Required: true}),
		}}, nil
}

// addRecommendation is reports.add_recommendation.
func (r Reports) addRecommendation(ctx context.Context, p auth.Principal, id string, values map[string]string) (Saved, error) {
	words, err := text(values, "text", "Recommendation", true, 4000)
	if err != nil {
		return Saved{}, err
	}
	owner := strings.TrimSpace(values["owner_role"])
	if !slices.ContainsFunc(ActionOwners, func(o [2]string) bool { return o[0] == owner }) {
		return Saved{}, refuse("Say who should act on the recommendation.")
	}
	due, err := day(values, "due_date", "Due date")
	if err != nil {
		return Saved{}, err
	}
	if due == nil {
		return Saved{}, refuse("Give the recommendation a due date.")
	}
	now, recommendation := r.now(), cuid.New()
	err = pgx.BeginTxFunc(ctx, r.DB, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		x, err := r.ownDraft(ctx, tx, p, id)
		if err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `INSERT INTO impact_report_recommendation (id, created_at, updated_at, text, owner_role, due_date,
  status, response, report_id) VALUES ($1, $2, $2, $3, $4, $5, 'proposed', '', $6)`, recommendation, now, words, owner, *due, id); err != nil {
			return fmt.Errorf("iareports: saving the recommendation: %w", err)
		}
		_, err = audit.Append(ctx, tx, reportAudit("ia.report.recommendation_added", id, p, x.country, x.version, x.status, "",
			map[string]any{"recommendation_id": recommendation, "owner_role": owner}), now)
		return err
	})
	if err != nil {
		return Saved{}, err
	}
	return Saved{Message: "Recommendation added.", ReportID: id}, nil
}
