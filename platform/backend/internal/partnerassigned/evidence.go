package partnerassigned

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// EvidencePath is the partner's Evidence page.
const EvidencePath = "/partner/evidence"

// upload is one evidence record as Recent Uploads lists it.
type upload struct {
	School      *string
	At          time.Time
	Quarantined bool
}

// missing is completed partner work with no evidence.
type missing struct {
	ID, Type string
	School   *string
}

// evidence is partner_evidence_view: the newest uploads on the partner's
// live activities, and its completed work that has none, newest first.
func (s *Service) evidence(ctx context.Context, partners []string) (*screensv1.GetPageResponse, bool, error) {
	if partners == nil {
		partners = []string{}
	}
	rows, err := s.db.Query(ctx, `
SELECT s.name, e.created_at, e.quarantined FROM evidence_record e
JOIN activity a ON a.id = e.activity_id LEFT JOIN school s ON s.id = a.school_id
WHERE a.assigned_partner_id = ANY($1) AND a.deleted_at IS NULL
ORDER BY e.created_at DESC LIMIT $2`, partners, rules.EvidenceLimit)
	if err != nil {
		return nil, true, fmt.Errorf("partnerassigned: reading the uploads: %w", err)
	}
	uploads, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (upload, error) {
		var u upload
		err := r.Scan(&u.School, &u.At, &u.Quarantined)
		return u, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("partnerassigned: reading the uploads: %w", err)
	}
	rows, err = s.db.Query(ctx, `
SELECT a.id, a.activity_type, s.name FROM activity a LEFT JOIN school s ON s.id = a.school_id
WHERE a.assigned_partner_id = ANY($1) AND a.status = ANY($2) AND a.deleted_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM evidence_record e WHERE e.activity_id = a.id)
ORDER BY a.created_at DESC LIMIT $3`, partners, rules.CompletedWorkStatuses, rules.MissingEvidenceLimit)
	if err != nil {
		return nil, true, fmt.Errorf("partnerassigned: reading the work missing evidence: %w", err)
	}
	pending, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (missing, error) {
		var m missing
		err := r.Scan(&m.ID, &m.Type, &m.School)
		return m, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("partnerassigned: reading the work missing evidence: %w", err)
	}
	return evidencePage(uploads, pending), true, nil
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

// schoolOr is the school's name, or what the row says without one. A name
// is a link only for a reader who may open profiles, and the feed reads a
// link in a line as its words.
func schoolOr(name *string, without string) string {
	if name == nil {
		return without
	}
	return closedschools.Collapse(*name)
}

// evidencePage is pages/partner/evidence.html as the feed reads it.
func evidencePage(uploads []upload, pending []missing) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Partner Portal", Title: "Evidence",
		Description: "Uploads for your completed activities — work without evidence cannot be verified or paid."}
	blocks := []*screensv1.PageBlock{}
	if len(pending) > 0 {
		noun := "activities"
		if len(pending) == 1 {
			noun = "activity"
		}
		items := []*screensv1.PagePanelItem{}
		for _, m := range pending {
			kind, ok := rules.ActivityTypes[m.Type]
			if !ok {
				kind = m.Type
			}
			items = append(items, text(closedschools.Collapse(schoolOr(m.School, "Activity")+" · "+kind)),
				&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
					{Text: "Upload Evidence", Href: "/activities/" + m.ID + "/evidence", Drawer: true}}}}})
		}
		blocks = append(blocks,
			&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
				text(strconv.Itoa(len(pending)) + " completed " + noun + " missing evidence")}}}},
			&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: items}}})
	}
	recent := []*screensv1.PagePanelItem{}
	for _, u := range uploads {
		state := "Received"
		if u.Quarantined {
			state = "Quarantined"
		}
		recent = append(recent, text(schoolOr(u.School, "Activity")), text(u.At.In(zone).Format("02 Jan 2006 15:04")), text(state))
	}
	if len(recent) == 0 {
		recent = append(recent, text("Evidence you upload for completed activities will appear here."))
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Recent Uploads", Items: recent}}})
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: EvidencePath}
}
