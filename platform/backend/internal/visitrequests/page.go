package visitrequests

import (
	"context"
	"fmt"
	"net/url"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// Path is the page.
const Path = "/planning/visit-requests"

const (
	// mineLimit is requests_by's limit.
	mineLimit     = 50
	minePageParam = "visit_requests_mine_page"
	minePageSize  = 50

	requesterLead = "Visits you scheduled into another person’s schools, and what their owners decided. " +
		"A visit takes effect on your plan and budget once approved."
	ownerLead     = "Visits other staff have asked to make to your schools. Approve them onto their plan, or decline with a reason."
	noRequests    = "Schedule a visit from Planning; at a school someone else owns it appears here while they decide."
	nothingToDo   = "When someone asks to visit one of your schools, the request appears here."
	unknownOwner  = "the school's owner"
	unknownAsker  = "A staff member"
	declinedLabel = "rejected"
)

// Service builds the page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// request is one visit request.
type request struct {
	id, kind, status, note, person string
	schoolID, schoolName, district string
	districtID                     string
	planned                        *time.Time
}

// ownerIDs is scoping.owner_ids: both ids a person's work is filed under.
func ownerIDs(p auth.Principal) []string {
	out := []string{}
	for _, id := range []string{p.UserID, p.StaffProfileID} {
		if id != "" {
			out = append(out, id)
		}
	}
	return out
}

// readRequests is pending_for_owner (mine false) or requests_by (mine
// true), each with the other side's name: the requester's by either id
// space, the owner's by staff profile.
func (s *Service) readRequests(ctx context.Context, ids []string, mine bool) ([]request, error) {
	where := `a.status = $2 AND a.approval_owner_id = ANY($1)`
	// The name, "" for none: the default is written in Go.
	person := `(SELECT NULLIF(u.name, '') FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
    WHERE sp.id = a.responsible_staff_id OR sp.user_id = a.responsible_staff_id ORDER BY sp.id LIMIT 1)`
	order, limit := `a.planned_date ASC, a.created_at ASC`, ""
	args := []any{ids, rules.Awaiting}
	if mine {
		where = `a.responsible_staff_id = ANY($1) AND a.approval_owner_id <> ''`
		person = `(SELECT NULLIF(u.name, '') FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
    WHERE sp.id = a.approval_owner_id)`
		order, limit = `a.created_at DESC`, fmt.Sprintf(" LIMIT %d", mineLimit)
		args = args[:1]
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, a.activity_type, a.status, a.owner_decision_note, COALESCE(`+person+`, ''),
  COALESCE(s.id, ''), COALESCE(s.name, ''), COALESCE(d.name, ''), COALESCE(d.id, ''), a.planned_date
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN district d ON d.id = s.district_id
WHERE a.deleted_at IS NULL AND `+where+`
ORDER BY `+order+limit, args...)
	if err != nil {
		return nil, fmt.Errorf("visitrequests: reading the requests: %w", err)
	}
	defer rows.Close()
	out := []request{}
	for rows.Next() {
		var r request
		if err := rows.Scan(&r.id, &r.kind, &r.status, &r.note, &r.person, &r.schoolID, &r.schoolName, &r.district,
			&r.districtID, &r.planned); err != nil {
			return nil, fmt.Errorf("visitrequests: reading a request: %w", err)
		}
		if r.person == "" {
			r.person = unknownAsker
			if mine {
				r.person = unknownOwner
			}
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// Build answers the page; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	d, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	if !d.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	ids := ownerIDs(p)
	pending, mine := []request{}, []request{}
	if len(ids) > 0 {
		var err error
		if pending, err = s.readRequests(ctx, ids, false); err != nil {
			return nil, true, err
		}
		if mine, err = s.readRequests(ctx, ids, true); err != nil {
			return nil, true, err
		}
	}
	// Read from the rows, not only the role: a request already filed by a
	// role that no longer files them still waits on its owner.
	requester := len(mine) > 0 || d.Requester
	lead := ownerLead
	if requester {
		lead = requesterLead
	}
	blocks := []*screensv1.PageBlock{}
	if requester {
		blocks = append(blocks, section("Your requests"))
		blocks = append(blocks, mineBlocks(mine, d, query)...)
	}
	if !requester || len(pending) > 0 {
		blocks = append(blocks, section("Awaiting your decision"))
		blocks = append(blocks, pendingBlocks(pending)...)
	}
	header := &screensv1.PageHeader{Eyebrow: "My Work", Title: "Visit Requests", Description: lead,
		Badges: []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}, true, nil
}

func section(title string) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: title}}
}

func textPanel(title, subtitle string, lines ...string) *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{}
	for _, l := range lines {
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: l}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Subtitle: subtitle,
		Badges: []*screensv1.PageBadge{}, Items: items}}}
}

// day is a date as "j M Y".
func day(t *time.Time) string {
	if t == nil {
		return "—"
	}
	return t.Format("2 Jan 2006")
}

// pendingBlocks are the owner's cards, as the feed reads them: who asks to
// visit which school, the kind, the day and the district. The decision forms
// are the existing application's.
func pendingBlocks(pending []request) []*screensv1.PageBlock {
	if len(pending) == 0 {
		return []*screensv1.PageBlock{textPanel("", "", nothingToDo)}
	}
	out := []*screensv1.PageBlock{}
	for _, r := range pending {
		school := "your school"
		if r.schoolID != "" {
			school = r.schoolName
		}
		line := calendarpage.ActivityTypeLabel(r.kind)
		if r.planned != nil {
			line += " • " + day(r.planned)
		}
		if r.schoolID != "" && r.districtID != "" {
			line += " • " + r.district
		}
		out = append(out, textPanel(r.person+" asks to visit "+school, line))
	}
	return out
}

// mineBlocks are the requester's own requests and what became of each.
func mineBlocks(mine []request, d role, query url.Values) []*screensv1.PageBlock {
	if len(mine) == 0 {
		return []*screensv1.PageBlock{textPanel("", "", noRequests)}
	}
	t := &screensv1.PageTable{Columns: []*screensv1.PageColumn{{Label: "School ID"}, {Label: "School"}, {Label: "Date"},
		{Label: "Owner asked"}, {Label: "Decision"}}}
	page := tablepager.Paginate(len(mine), minePageSize, query, minePageParam)
	for _, r := range mine[page.Start:page.End] {
		// The School ID is written in after the page is drawn; the feed
		// reads its place as empty.
		code, school := "—", &screensv1.PageCell{Text: "—" + calendarpage.ActivityTypeLabel(r.kind)}
		if r.schoolID != "" {
			code = ""
			school.Text = r.schoolName + calendarpage.ActivityTypeLabel(r.kind)
			if d.OpenSchool {
				school.Href = "/schools/" + r.schoolID
			}
		}
		decision := "Approved" + r.note
		switch r.status {
		case rules.Awaiting:
			decision = "Awaiting approval"
		case declinedLabel:
			decision = "Declined" + r.note
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: code}, school, {Text: day(r.planned)},
			{Text: r.person}, {Text: decision}}})
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pager := tablepager.Panel(len(mine), minePageSize, query, minePageParam); pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks
}
