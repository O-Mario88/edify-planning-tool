package iapages

import (
	"context"
	"fmt"
	"net/url"
	"time"

	_ "time/tzdata" // the page's days are Nairobi's wherever the gateway runs

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// DuplicatesPath is Duplicate Review.
const DuplicatesPath = "/ia/duplicates/"

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("iapages: " + err.Error())
	}
	return z
}()

// Service builds the IA review pages.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// side is one activity of a flagged pair.
type side struct {
	id, kind, school, sfID, staff string
	planned                       *time.Time
}

type flag struct {
	reason   string
	flagged  time.Time
	activity side
	matching side
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

// Build answers path for p. served is false for a path this package does not
// answer.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != DuplicatesPath && path != ReturnedPath && path != HistoryPath && path != PartnerEvidencePath && path != SamplesPath && path != AnalyticsPath && path != StoriesPath {
		return nil, false, nil
	}
	role, ok := rules.Pages[path].Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	switch path {
	case SamplesPath:
		return s.samples(ctx, p, role, query)
	case AnalyticsPath:
		return s.analytics(ctx, p, query)
	case StoriesPath:
		return s.stories(ctx, p, role, query)
	}
	where, args, err := reach(ctx, s.db, p, s.now(), nil)
	if err != nil {
		return nil, true, err
	}
	switch path {
	case ReturnedPath:
		return s.returned(ctx, p, query, where, args)
	case PartnerEvidencePath:
		return s.partnerEvidence(ctx, p, query, where, args)
	case HistoryPath:
		return s.history(ctx, p, query, where, args)
	}
	// DuplicateActivity has no order of its own; the view reads it unordered.
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT d.reason, d.created_at,
       a.id, a.activity_type, sa.name, a.salesforce_activity_id, a.responsible_staff_id, a.planned_date,
       b.id, b.activity_type, sb.name, b.salesforce_activity_id, b.responsible_staff_id, b.planned_date
FROM ia_duplicate_activity d
JOIN activity b ON b.id = d.duplicate_of_id
JOIN activity a ON a.id = d.activity_id
LEFT JOIN school sa ON sa.id = a.school_id LEFT JOIN school sb ON sb.id = b.school_id
WHERE d.status = 'potential' AND d.activity_id IN (
  SELECT a.id FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id WHERE a.deleted_at IS NULL AND %s)`, where), args...)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the flagged duplicates: %w", err)
	}
	flags, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (flag, error) {
		var f flag
		var aSchool, bSchool, aSF, bSF, aStaff, bStaff *string
		err := r.Scan(&f.reason, &f.flagged,
			&f.activity.id, &f.activity.kind, &aSchool, &aSF, &aStaff, &f.activity.planned,
			&f.matching.id, &f.matching.kind, &bSchool, &bSF, &bStaff, &f.matching.planned)
		f.activity.school, f.activity.sfID, f.activity.staff = deref(aSchool), deref(aSF), deref(aStaff)
		f.matching.school, f.matching.sfID, f.matching.staff = deref(bSchool), deref(bSF), deref(bStaff)
		return f, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the flagged duplicates: %w", err)
	}
	ids := []string{}
	for _, f := range flags {
		ids = append(ids, f.activity.staff, f.matching.staff)
	}
	names, err := staffNames(ctx, s.db, ids)
	if err != nil {
		return nil, true, err
	}
	return duplicatesPage(flags, names), true, nil
}

func deref(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

// details is one side of the pair as the template writes it.
func details(heading string, a side, names map[string]string) []*screensv1.PagePanelItem {
	school := a.school
	if school == "" {
		school = "Cluster-wide"
	}
	planned := ""
	if a.planned != nil {
		planned = a.planned.Format(time.DateOnly)
	}
	owner, ok := names[a.staff]
	if !ok {
		owner = a.staff
		if owner == "" {
			owner = "Unassigned"
		}
	}
	sf := a.sfID
	if sf == "" {
		sf = "Unlinked"
	}
	kind, ok := rules.ActivityTypes[a.kind]
	if !ok {
		kind = a.kind
	}
	return []*screensv1.PagePanelItem{
		{Kind: &screensv1.PagePanelItem_Heading{Heading: heading}},
		text("Activity ID: #" + a.id[:min(8, len(a.id))]),
		text("Type: " + kind), text("School: " + school), text("Date: " + planned),
		text("Owner: " + owner), text("Salesforce ID: " + sf),
	}
}

// duplicatesPage is pages/ia/duplicate_review.html as the feed reads it: one
// card a flagged pair (the reason, when it was flagged, each side's details
// and the link to compare them), or the empty state.
func duplicatesPage(flags []flag, names map[string]string) *screensv1.GetPageResponse {
	blocks := []*screensv1.PageBlock{}
	for _, f := range flags {
		items := []*screensv1.PagePanelItem{text(f.reason), text("Flagged " + f.flagged.In(zone).Format("Jan 02, 2006"))}
		items = append(items, details("Submitted Activity Detail", f.activity, names)...)
		items = append(items, details("Matching Activity Detail", f.matching, names)...)
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
			{Text: "Compare Evidence side-by-side", Href: "/ia/compare/?activity_id=" + f.activity.id}}}}})
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: items}}})
	}
	if len(flags) == 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{Empty: "Possible duplicates appear here when two records look like the same work."}})
	}
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{Eyebrow: "Verification", Title: "Duplicate Review",
			Description: "Activities flagged as possible duplicates — same school, date, staff and type, a repeated Salesforce ID, " +
				"or the same evidence uploaded twice. Decide each one."},
		Blocks: blocks, WebPath: DuplicatesPath,
	}
}
