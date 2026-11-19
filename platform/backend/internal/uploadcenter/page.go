package uploadcenter

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	_ "time/tzdata" // an upload's time is read in Nairobi wherever the gateway runs

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// PagePath is the page's path.
const PagePath = "/uploads"

var ownQuery = []string{"tab", "status", "type", "q", "page"}

// tabs is TABS: every tab the page may show, in order.
var tabs = [][2]string{
	{"all", "All Authorized Uploads"},
	{"imports", "Structured Imports"},
	{"documents", "Policies and Manuals"},
	{"training", "Training Resources"},
	{"mine", "My Uploads"},
}

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("uploadcenter: " + err.Error())
	}
	return z
}()

// Service builds the page.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService returns the page's builder.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// Build answers /uploads and New Policy or Manual.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path == NewDocumentPath {
		doors := rules.Roles[p.ActiveRole]
		if !doors.NewPage {
			return nil, true, pagegate.ErrNotAvailable
		}
		training := query.Get("kind") == "training"
		if (training && !doors.TrainingCreate) || (!training && !doors.DocumentsCreate) {
			return nil, false, nil // the page redirects a reader without the kind's create permission
		}
		return newDocumentPage(training), true, nil
	}
	if path != PagePath {
		return nil, false, nil
	}
	doors, known := rules.Roles[p.ActiveRole]
	if !known || !doors.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	for key := range query {
		if !slices.Contains(ownQuery, key) {
			return nil, false, nil
		}
	}
	if len(doors.Actions) == 0 {
		return nil, false, nil
	}
	now := s.now().In(zone)
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	r := reader{userID: p.UserID, role: p.ActiveRole, slug: doors.Slug, doors: doors}
	err := s.db.QueryRow(ctx, `SELECT COALESCE((SELECT country FROM staff_profile WHERE user_id = $1 LIMIT 1), '')`, p.UserID).
		Scan(&r.country)
	if err != nil {
		return nil, true, fmt.Errorf("uploadcenter: reading the reader's country: %w", err)
	}
	nameOf, err := names(ctx, s.db)
	if err != nil {
		return nil, true, err
	}
	all, err := imports(ctx, s.db, r, nameOf)
	if err != nil {
		return nil, true, err
	}
	docs, err := documents(ctx, s.db, r, nameOf, today)
	if errors.Is(err, errHandOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	all = append(all, docs...)
	sort.SliceStable(all, func(i, j int) bool { return all[i].uploadedAt.After(all[j].uploadedAt) })

	tab := strings.TrimSpace(query.Get("tab"))
	if tab == "" {
		tab = "all"
	}
	shown := filter(all, tab, query, p.UserID, nameOf[p.UserID])
	page := 1
	if n, err := strconv.Atoi(strings.TrimSpace(query.Get("page"))); err == nil && n > 1 {
		page = n
	}
	if len(shown) > rules.PageSize {
		return nil, false, nil
	}
	window := shown
	if page > 1 {
		window = nil
	}

	overdue := 0
	if doors.ManageAcknowledgements {
		if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM document_acknowledgement
			WHERE state = 'pending' AND due_date < $1`, today).Scan(&overdue); err != nil {
			return nil, true, fmt.Errorf("uploadcenter: counting overdue signatures: %w", err)
		}
	}
	blocks := []*screensv1.PageBlock{quickActions(doors), strip(shown, doors, overdue), tabBlock(all, doors, tab),
		table(window)}
	if doors.AdminMenu {
		blocks = append(blocks, drawer(doors)...)
	}
	h := &screensv1.PageHeader{Eyebrow: "Files", Title: "Upload Center",
		Description: "Upload and manage school data, SSA files, policies, training resources and other organisational documents."}
	if doors.AdminMenu {
		h.Actions = []*screensv1.PageAction{{Key: "upload", Label: "Upload", Enabled: true}}
	}
	return &screensv1.GetPageResponse{Header: h, Blocks: blocks, WebPath: PagePath}, true, nil
}

// filter is UploadCenterService.get's narrowing: the tab, then the type,
// the status and the search.
func filter(all []row, tab string, query url.Values, me, myName string) []row {
	kind := strings.TrimSpace(query.Get("type"))
	status := strings.ToLower(strings.TrimSpace(query.Get("status")))
	search := strings.ToLower(strings.TrimSpace(query.Get("q")))
	out := []row{}
	for _, x := range all {
		switch {
		case tab == "mine" && x.uploadedBy != me && x.uploadedBy != myName,
			(tab == "imports" || tab == "documents" || tab == "training") && x.tab != tab,
			kind != "" && x.recordType != kind,
			status != "" && !strings.Contains(strings.ToLower(x.processing+" "+x.publication), status),
			search != "" && !strings.Contains(strings.ToLower(x.title+" "+x.context+" "+x.uploadedBy), search):
			continue
		}
		out = append(out, x)
	}
	return out
}

func links(ls ...*screensv1.PageLink) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: ls}}}
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func panel(title, subtitle string, items ...*screensv1.PagePanelItem) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title,
		Subtitle: subtitle, Items: items}}}
}

// quickActions is the "Start an upload" cards, read as links under their
// category.
func quickActions(doors Role) *screensv1.PageBlock {
	ls := []*screensv1.PageLink{}
	for _, a := range doors.Actions {
		ls = append(ls, &screensv1.PageLink{Text: a.ActionLabel, Href: a.Href, Caption: a.Category})
	}
	return panel("Start an upload", "Quick actions", links(ls...))
}

// strip is UploadCenterService.kpis over the rows shown: what awaits review,
// what is published and, for a reader who chases signatures, what is
// overdue everywhere.
func strip(shown []row, doors Role, overdue int) *screensv1.PageBlock {
	awaiting, published := 0, 0
	for _, x := range shown {
		if strings.Contains(strings.ToLower(x.next), "review") {
			awaiting++
		}
		if strings.ToLower(x.publication) == "published" {
			published++
		}
	}
	s := &screensv1.PageStrip{Title: "Upload context", Metrics: []*screensv1.PageMetric{
		{Label: rules.MetricLabels[0], Value: strconv.Itoa(awaiting), Href: "/uploads"},
		{Label: rules.MetricLabels[1], Value: strconv.Itoa(published), Href: "/uploads?tab=documents"},
	}}
	if doors.ManageAcknowledgements {
		s.Metrics = append(s.Metrics, &screensv1.PageMetric{Label: rules.MetricLabels[2], Value: strconv.Itoa(overdue),
			Href: "/policy-compliance?state=pending"})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: s}}
}

// tabBlock is visible_tabs: All, then each category with uploads behind it
// or that the reader may create, then My Uploads.
func tabBlock(all []row, doors Role, current string) *screensv1.PageBlock {
	present := map[string]bool{}
	for _, x := range all {
		present[x.tab] = true
	}
	present["documents"] = present["documents"] || doors.DocumentsCreate
	present["training"] = present["training"] || doors.TrainingCreate
	present["imports"] = present["imports"] || doors.SchoolUpload || doors.SSAUpload
	out := &screensv1.PageLinkTabs{}
	for _, t := range tabs {
		if t[0] != "all" && t[0] != "mine" && !present[t[0]] {
			continue
		}
		out.Tabs = append(out.Tabs, &screensv1.PageLinkTab{Label: t[1], Href: "?tab=" + t[0], Active: t[0] == current})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: out}}
}

// truncate is the truncatechars filter: past n characters, the first n-1
// and an ellipsis.
func truncate(s string, n int) string {
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	return string([]rune(s)[:n-1]) + "…"
}

func or(s, fallback string) string {
	if s == "" {
		return fallback
	}
	return s
}

// table is partials/documents/upload_table.html: the rows, or the words for
// none.
func table(rows []row) *screensv1.PageBlock {
	if len(rows) == 0 {
		return panel("", "", text("Nothing here yet"),
			text("This is a real result, not an error — no uploads in this category are visible to you."))
	}
	t := &screensv1.PageTable{}
	for _, c := range []string{"Title", "Type", "Owner", "Context", "Version", "Uploaded By", "Uploaded", "Status",
		"Preview", "Acknowledgement", "Next Action"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	for _, x := range rows {
		status := or(x.processing, or(x.publication, "—"))
		cells := []*screensv1.PageCell{
			{Text: truncate(x.title, 60), Href: x.route},
			{Text: label(rules.TypeLabels, x.recordType)},
			{Text: x.owner},
			{Text: truncate(x.context, 48)},
			{Text: or(x.version, "—")},
			{Text: or(x.uploadedBy, "—")},
			{Text: x.uploadedAt.In(zone).Format("02 Jan 15:04")},
			{Text: status},
			{Text: or(x.preview, "—")},
			{Text: or(x.acknowledgement, "—")},
			{Text: x.next, Href: x.route},
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

// drawer is the Admin's upload drawer: its heading, then each upload type's
// card.
func drawer(doors Role) []*screensv1.PageBlock {
	out := []*screensv1.PageBlock{panel("Choose an upload type", "Admin uploads")}
	for _, a := range doors.Actions {
		ls := []*screensv1.PageLink{{Text: a.ActionLabel, Href: a.Href}}
		if a.TemplateHref != "" {
			ls = append(ls, &screensv1.PageLink{Text: a.TemplateLabel, Href: a.TemplateHref})
		}
		out = append(out, panel(a.Title, "", text(a.Category), text(a.Description), links(ls...)))
	}
	return out
}
