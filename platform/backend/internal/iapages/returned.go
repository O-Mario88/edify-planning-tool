package iapages

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// ReturnedPath is Returned Activities.
const ReturnedPath = "/ia/returned/"

// returnedPageSize is {% paginate returned "page" %}'s page.
const returnedPageSize = 50

// returned is ia_returned_view: the live activities in reach that IA returned,
// the last changed first, each with the reasons its verification gave.
func (s *Service) returned(ctx context.Context, p auth.Principal, query url.Values, where string, args []any) (*screensv1.GetPageResponse, bool, error) {
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT a.id, a.activity_type, a.school_id, sc.name, a.responsible_staff_id, a.updated_at,
       COALESCE((SELECT string_agg(r.reason, ', ') FROM ia_verification v JOIN ia_returned_reason r ON r.verification_id = v.id
                 WHERE v.activity_id = a.id), '')
FROM activity a LEFT JOIN school sc ON sc.id = a.school_id
WHERE a.id IN (SELECT a.id FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
               WHERE a.deleted_at IS NULL AND a.status = 'returned_by_ia' AND %s)
ORDER BY a.updated_at DESC`, where), args...)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the returned activities: %w", err)
	}
	type item struct {
		id, kind, reasons string
		school, name      *string
		staff             *string
		at                time.Time
	}
	items, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (item, error) {
		var it item
		err := r.Scan(&it.id, &it.kind, &it.school, &it.name, &it.staff, &it.at, &it.reasons)
		return it, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the returned activities: %w", err)
	}
	ids := []string{}
	for _, it := range items {
		ids = append(ids, deref(it.staff))
	}
	names, err := staffNames(ctx, s.db, ids)
	if err != nil {
		return nil, true, err
	}
	header := &screensv1.PageHeader{Eyebrow: "Verification", Title: "Returned Activities",
		Description: "Work sent back for correction, the reasons given, and whether it has come back yet."}
	if len(items) == 0 {
		return &screensv1.GetPageResponse{Header: header, WebPath: ReturnedPath, Blocks: []*screensv1.PageBlock{
			{Kind: &screensv1.PageBlock_Empty{Empty: "Work sent back for correction appears here with the reasons given."}}}}, true, nil
	}
	links := slices.Contains(rules.SchoolProfileRoles, p.ActiveRole)
	t := &screensv1.PageTable{}
	for _, c := range []string{"Activity ID", "School ID", "School / Cluster", "CCEO / Staff", "Return Reason(s)", "Date Returned", "Resubmitted?"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	t.Columns = append(t.Columns, &screensv1.PageColumn{Label: "Actions", Numeric: true})
	number, pages := closedschools.PageOf(query.Get("page"), len(items), returnedPageSize)
	for _, it := range items[(number-1)*returnedPageSize : min(number*returnedPageSize, len(items))] {
		kind, ok := rules.ActivityTypes[it.kind]
		if !ok {
			kind = it.kind
		}
		// {% school_code %} writes a token the response middleware fills in,
		// which the feed's render never runs: the app reads it empty.
		code := "—"
		school := &screensv1.PageCell{Text: "Cluster"}
		if s := deref(it.school); s != "" {
			code = ""
			school = &screensv1.PageCell{Text: deref(it.name)}
			if links && school.Text != "" {
				school.Href = "/schools/" + url.PathEscape(s)
			}
		}
		owner, ok := names[deref(it.staff)]
		if !ok {
			owner = deref(it.staff)
			if owner == "" {
				owner = "Unassigned"
			}
		}
		reasons := it.reasons
		if reasons == "" {
			reasons = "None Specified"
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: closedschools.Collapse("#" + it.id[:min(8, len(it.id))] + " " + kind)},
			{Text: code}, school, {Text: owner}, {Text: reasons},
			{Text: it.at.In(zone).Format("Jan 02, 2006 15:04")},
			{Text: "Awaiting CCEO", Tone: "primary", Badge: true},
			{Actions: []*screensv1.PageAction{{Key: "button", Label: "Inspect", Primary: true, Enabled: true, Href: "/ia/verification/" + it.id + "/"}}},
		}})
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel("page", number, pages, len(items), returnedPageSize, query, rules.QueryKeysNotPassed))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: ReturnedPath}, true, nil
}
