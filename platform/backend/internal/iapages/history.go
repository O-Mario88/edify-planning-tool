package iapages

import (
	"context"
	"fmt"
	"net/url"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// HistoryPath is Verification History.
const HistoryPath = "/ia/history/"

// history is ia_history_view: every verification of a live activity in
// reach, the latest first, each with its school (else "Cluster-wide") and
// cluster, partner, owner, verifier (an account's name, else the id as
// stored) and whether it counts in analytics; 50 a page.
func (s *Service) history(ctx context.Context, p auth.Principal, query url.Values, where string, args []any) (*screensv1.GetPageResponse, bool, error) {
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT a.id, a.activity_type, a.school_id, sc.name, cl.name, p.name, a.responsible_staff_id,
       h.verified_by, vu.name, h.verified_at, h.analytics_included
FROM ia_verification_history h JOIN activity a ON a.id = h.activity_id
LEFT JOIN school sc ON sc.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
LEFT JOIN partner p ON p.id = a.assigned_partner_id
LEFT JOIN "user" vu ON vu.id = h.verified_by AND vu.deleted_at IS NULL
WHERE h.activity_id IN (SELECT a.id FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
                        WHERE a.deleted_at IS NULL AND %s)
ORDER BY h.verified_at DESC`, where), args...)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the verification history: %w", err)
	}
	type entry struct {
		id, kind, verifiedBy                        string
		school, schoolName, cluster, partner, staff *string
		verifier                                    *string
		at                                          time.Time
		included                                    bool
	}
	entries, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (entry, error) {
		var e entry
		err := r.Scan(&e.id, &e.kind, &e.school, &e.schoolName, &e.cluster, &e.partner, &e.staff,
			&e.verifiedBy, &e.verifier, &e.at, &e.included)
		return e, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the verification history: %w", err)
	}
	ids := []string{}
	for _, e := range entries {
		ids = append(ids, deref(e.staff))
	}
	names, err := staffNames(ctx, s.db, ids)
	if err != nil {
		return nil, true, err
	}
	header := &screensv1.PageHeader{Eyebrow: "Verification", Title: "Verification History", Actions: exportActions(p, HistoryPath, query),
		Description: "Every activity certified by Impact Assessment, newest first, with who verified it and when."}
	if len(entries) == 0 {
		return &screensv1.GetPageResponse{Header: header, WebPath: HistoryPath, Blocks: []*screensv1.PageBlock{
			{Kind: &screensv1.PageBlock_Empty{Empty: "Certified activities appear here as Impact Assessment verifies them."}}}}, true, nil
	}
	t := &screensv1.PageTable{}
	for _, c := range []string{"Activity", "School ID", "School / Cluster", "Partner", "Staff", "Verified by", "Verified", "In analytics"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	t.Columns = append(t.Columns, &screensv1.PageColumn{Label: "Actions", Numeric: true})
	number, pages := closedschools.PageOf(query.Get("page"), len(entries), returnedPageSize)
	for _, e := range entries[(number-1)*returnedPageSize : min(number*returnedPageSize, len(entries))] {
		kind, ok := rules.ActivityTypes[e.kind]
		if !ok {
			kind = e.kind
		}
		code, place := "—", "Cluster-wide"
		if deref(e.school) != "" {
			code, place = "", deref(e.schoolName)
		}
		if c := deref(e.cluster); c != "" {
			place += " " + c
		}
		partner := &screensv1.PageCell{Text: "—"}
		if p := deref(e.partner); p != "" {
			partner = &screensv1.PageCell{Text: p, Tone: "primary", Badge: true}
		}
		owner, ok := names[deref(e.staff)]
		if !ok {
			owner = deref(e.staff)
			if owner == "" {
				owner = "Unassigned"
			}
		}
		verifier := e.verifiedBy
		if e.verifier != nil {
			verifier = *e.verifier
		}
		included := &screensv1.PageCell{Text: "Excluded"}
		if e.included {
			included = &screensv1.PageCell{Text: "Certified", Tone: "primary", Badge: true}
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: closedschools.Collapse("#" + e.id[:min(8, len(e.id))] + " " + kind)},
			{Text: code}, {Text: closedschools.Collapse(place)}, partner, {Text: owner}, {Text: verifier},
			{Text: e.at.In(zone).Format("Jan 02, 2006 15:04")}, included,
			{Actions: []*screensv1.PageAction{
				{Key: "menu", Label: "Workspace", Enabled: true, Href: "/ia/verification/" + e.id + "/"},
				{Key: "menu", Label: "View audit timeline", Enabled: true, Href: "/activities/" + e.id + "/timeline/"},
			}},
		}})
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel("page", number, pages, len(entries), returnedPageSize, query, rules.QueryKeysNotPassed))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: HistoryPath}, true, nil
}
