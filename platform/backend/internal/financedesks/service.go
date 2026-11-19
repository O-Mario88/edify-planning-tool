package financedesks

import (
	"context"
	"math"
	"net/url"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/calendarpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// pageSize is table_pagination's rows a page.
const pageSize = 50

// Service builds the desks.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the desks over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// desk is one desk page's builder.
type desk func(s *Service, ctx context.Context, d role, query url.Values) (*screensv1.GetPageResponse, error)

// desks are the pages this package answers, by path.
var desks = map[string]desk{
	"/accounts/accountability":    (*Service).accountability,
	"/accounts/advances":          (*Service).advances,
	"/accounts/audit-log":         (*Service).auditLog,
	"/accounts/blocked":           (*Service).blocked,
	"/accounts/budget-amendments": (*Service).budgetAmendments,
	"/accounts/cleared":           (*Service).cleared,
	"/accounts/returned":          (*Service).returned,
	"/accounts/variance-review":   (*Service).varianceReview,
	"/accounts/weekly-requests":   (*Service).weeklyRequests,
}

// Build answers path for p. served is false for a path this package does
// not answer, a role it has no rules for, and a reading it hands on.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	path = strings.TrimSuffix(path, "/")
	build, ok := desks[path]
	if !ok {
		return nil, false, nil
	}
	d, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, false, nil
	}
	if !d.Desks[path] {
		return nil, true, pagegate.ErrNotAvailable
	}
	page, err := build(s, ctx, d, query)
	if err == errHandOn {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	page.WebPath = path
	return page, true, nil
}

// errHandOn is a desk's answer for a reading Go does not draw.
var errHandOn = handOn{}

type handOn struct{}

func (handOn) Error() string { return "financedesks: handed on" }

// header is a desk's page header.
func header(eyebrow, title, description string) *screensv1.PageHeader {
	return &screensv1.PageHeader{Eyebrow: eyebrow, Title: title, Description: description,
		Badges: []*screensv1.PageBadge{}, Actions: []*screensv1.PageAction{}}
}

// page is a desk's answer.
func page(h *screensv1.PageHeader, blocks ...*screensv1.PageBlock) *screensv1.GetPageResponse {
	return &screensv1.GetPageResponse{Header: h, Blocks: blocks, Tabs: []*screensv1.PageTab{}, Dialogs: []*screensv1.PageDialog{}}
}

// table is a desk's table of rows, fifty a page: with none, its one row
// is the empty state, which the feed also reads as the table's empty
// message. The pager follows the table when there is more than a page.
func table(columns []*screensv1.PageColumn, rows []*screensv1.PageRow, empty, param string, query url.Values) []*screensv1.PageBlock {
	t := &screensv1.PageTable{Columns: columns}
	if len(rows) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: empty}}}}
		t.EmptyMessage = empty
	} else {
		p := tablepager.Paginate(len(rows), pageSize, query, param)
		t.Rows = rows[p.Start:p.End]
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pager := tablepager.Panel(len(rows), pageSize, query, param); pager != nil {
		blocks = append(blocks, pager)
	}
	return blocks
}

// columns are a table's headings; numeric ones are right-aligned.
func columns(labels []string, numeric ...string) []*screensv1.PageColumn {
	out := make([]*screensv1.PageColumn, len(labels))
	for i, l := range labels {
		out[i] = &screensv1.PageColumn{Label: l}
		for _, n := range numeric {
			if n == l {
				out[i].Numeric = true
			}
		}
	}
	return out
}

func cell(text string) *screensv1.PageCell { return &screensv1.PageCell{Text: text} }

// badge is a cell drawn as one pill: the plain pill reads "primary".
func badge(text string) *screensv1.PageCell {
	return &screensv1.PageCell{Text: text, Tone: "primary", Badge: true}
}

// school is school_link: the name opens the profile for a role that may.
func school(d role, id, name string) *screensv1.PageCell {
	c := cell(name)
	if d.OpenSchool && id != "" {
		c.Href = "/schools/" + id
	}
	return c
}

// detail is the activity's finance detail page.
func detail(activityID string) string { return "/accounts/activities/" + activityID + "/" }

// menu is a row's Actions menu holding one link.
func menu(label, href string) *screensv1.PageCell {
	return &screensv1.PageCell{Actions: []*screensv1.PageAction{{Key: "menu", Label: label, Href: href, Enabled: true}}}
}

// button is a row's own primary link.
func button(label, href string) *screensv1.PageCell {
	return &screensv1.PageCell{Actions: []*screensv1.PageAction{{Key: "button", Label: label, Href: href, Enabled: true, Primary: true}}}
}

// short is slice:":8".
func short(id string) string {
	r := []rune(id)
	if len(r) > 8 {
		r = r[:8]
	}
	return string(r)
}

// whole is f"{value:,.0f}": rounded half to even, with thousands commas.
func whole(v float64) string {
	return closedschools.Comma(int64(math.RoundToEven(v)))
}

// ugx is frontend_filters.ugx.
func ugx(v float64) string { return "UGX " + whole(v) }

// local is a moment in the deployment's time zone, as Django's date
// filter prints it.
func local(t time.Time) time.Time { return t.In(calendarpage.Location()) }

// joined is the feed's reading of a cell holding several parts: their
// words, one space apart.
func joined(parts ...string) string {
	var kept []string
	for _, p := range parts {
		if p = strings.TrimSpace(p); p != "" {
			kept = append(kept, p)
		}
	}
	return strings.Join(kept, " ")
}
