package iapages

import (
	"context"
	"fmt"
	"net/url"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

// PartnerEvidencePath is Partner Evidence, the queue of partner work
// submitted straight to IA.
const PartnerEvidencePath = "/ia/partner-evidence/"

// partnerPageParam is the queue table's pager.
const partnerPageParam = "partner_evidence_queue_rows_page"

// partnerWork is one partner activity awaiting IA, with what its row shows.
type partnerWork struct {
	ID, Kind, School, SchoolID, Cluster, Partner, Officer, Profile string
	Submitted                                                      *time.Time
	Held                                                           []string
}

// partnerEvidence is ia_partner_evidence_queue_view: the partner work in
// reach awaiting IA, the longest waiting first, the first QUEUE_PAGE_SIZE of
// it, each with its evidence against what it must carry. The export
// download stays with the existing application (the feed never passes its
// key).
func (s *Service) partnerEvidence(ctx context.Context, p auth.Principal, query url.Values, where string, args []any) (*screensv1.GetPageResponse, bool, error) {
	args = append(args, rules.QueuePageSize)
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT a.id, a.activity_type, COALESCE(a.school_id, ''), COALESCE(sc.name, ''), COALESCE(c.name, ''),
  COALESCE(pa.name, ''), COALESCE(pu.name, ''), COALESCE(a.evidence_profile_snapshot, ''), a.submitted_to_ia_at,
  ARRAY(SELECT DISTINCT e.kind FROM evidence_record e WHERE e.activity_id = a.id AND NOT e.quarantined ORDER BY 1),
  count(*) OVER ()
FROM activity a LEFT JOIN school sc ON sc.id = a.school_id LEFT JOIN cluster c ON c.id = a.cluster_id
LEFT JOIN partner pa ON pa.id = a.assigned_partner_id LEFT JOIN "user" pu ON pu.id = pa.user_id
WHERE a.id IN (SELECT a.id FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id
               WHERE a.deleted_at IS NULL AND a.delivery_type = 'partner' AND a.status = 'awaiting_ia_verification' AND %s)
ORDER BY a.submitted_to_ia_at LIMIT $%d`, where, len(args)), args...)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the partner queue: %w", err)
	}
	total := 0
	work, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (partnerWork, error) {
		var w partnerWork
		err := r.Scan(&w.ID, &w.Kind, &w.SchoolID, &w.School, &w.Cluster, &w.Partner, &w.Officer, &w.Profile, &w.Submitted, &w.Held, &total)
		return w, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the partner queue: %w", err)
	}
	return partnerPage(p, work, total, s.now().In(zone), query), true, nil
}

// requiredKinds is required_kinds_for_activity: by the activity's evidence
// profile, else by its type.
func requiredKinds(w partnerWork) []string {
	if kinds, ok := rules.ProfileRequiredEvidence[w.Profile]; ok {
		return kinds
	}
	return rules.RequiredEvidence[w.Kind]
}

// evidenceLabel is how many of the required kinds it holds, or how many
// files where nothing is required, and whether that is complete.
func evidenceLabel(w partnerWork) (string, bool) {
	needed := requiredKinds(w)
	if len(needed) == 0 {
		return strconv.Itoa(len(w.Held)) + " file(s)", len(w.Held) > 0
	}
	met := 0
	for _, k := range needed {
		for _, h := range w.Held {
			if h == k {
				met++
				break
			}
		}
	}
	return strconv.Itoa(met) + "/" + strconv.Itoa(len(needed)) + " required", met == len(needed)
}

func partnerPage(p auth.Principal, work []partnerWork, total int, now time.Time, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Verification", Title: "Partner Evidence",
		Description: "Partner submissions come directly to IA — review each against its plan, then Return it for correction or Complete it with its Salesforce entry.",
		Actions:     exportActions(p, PartnerEvidencePath, query)}
	t := &screensv1.PageTable{}
	for _, c := range []string{"School ID", "School / Activity", "Partner", "Activity", "Submitted", "Evidence", "Salesforce", "Payment"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	t.Columns = append(t.Columns, &screensv1.PageColumn{Label: "Action", Numeric: true})
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if len(work) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "Nothing awaiting review — partner submissions land here the moment they are sent."}}}}
		return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: PartnerEvidencePath}
	}
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	number, pages := closedschools.PageOf(query.Get(partnerPageParam), len(work), returnedPageSize)
	for _, w := range work[(number-1)*returnedPageSize : min(number*returnedPageSize, len(work))] {
		review := "/ia/partner-evidence/" + w.ID + "/"
		// {% school_code %} is a token the feed never fills: read empty.
		code := "—"
		if w.SchoolID != "" {
			code = ""
		}
		where := "Field work"
		switch {
		case w.SchoolID != "":
			where = w.School
		case w.Cluster != "":
			where = w.Cluster
		}
		partner := w.Partner
		if partner == "" {
			partner = "—"
		}
		submitted := "—"
		if w.Submitted != nil {
			// submitted_to_ia_at.date(): the day in UTC, as the view takes it.
			u := w.Submitted.UTC()
			day := time.Date(u.Year(), u.Month(), u.Day(), 0, 0, 0, 0, time.UTC)
			submitted = day.Format("02 Jan 2006")
			if age := int(today.Sub(day).Hours() / 24); age != 0 {
				submitted += " (" + strconv.Itoa(age) + "d)"
			}
		}
		kind, ok := rules.ActivityTypes[w.Kind]
		if !ok {
			kind = w.Kind
		}
		label, complete := evidenceLabel(w)
		tone := "warning"
		if complete {
			tone = "success"
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: code},
			{Text: closedschools.Collapse(where), Href: review},
			{Text: closedschools.Collapse(partner + w.Officer)},
			{Text: kind},
			{Text: submitted},
			{Text: label, Tone: tone},
			{Text: "Pending", Tone: "neutral"},
			{Text: "Not Yet Eligible", Tone: "neutral"},
			{Actions: []*screensv1.PageAction{{Key: "button", Label: "Review", Primary: true, Enabled: true, Href: review}}},
		}})
	}
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel(partnerPageParam, number, pages, len(work), returnedPageSize, query, rules.QueryKeysNotPassed))
	}
	if total > len(work) {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{
			Text: "Showing the " + strconv.Itoa(len(work)) + " oldest of " + strconv.Itoa(total) + " — clear these to see the rest."}}}}}})
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: PartnerEvidencePath}
}
