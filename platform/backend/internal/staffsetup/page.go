// Package staffsetup is the Staff Setup Queue
// (/admin-panel/staff-setup-queue): the operating schools whose uploaded
// owner is not matched to a registered member of staff yet, each with the
// staff it may be matched to, as the existing page draws it
// (apps.frontend.views.extended_views.admin_staff_setup_queue_view and
// pages/admin/staff_setup_queue.html) and the app's feed reads it. Matching
// and ignoring stay with the existing application.
//
// The doors, link roles, statuses and limits are exported to rules.json by
// `manage.py export_staff_setup_queue_rules`;
// apps/schools/test_staff_setup_queue_rules_export.py fails when the two
// differ.
package staffsetup

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"slices"
	"strings"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/admin-panel/staff-setup-queue"

const (
	pageParam = "unmatched_schools_page"
	emptyLine = "No unmatched school records currently in queue. Data integrity is clean!"
)

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	PageRoles            []string `json:"page_roles"`
	SchoolProfileRoles   []string `json:"school_profile_roles"`
	DistrictProfileRoles []string `json:"district_profile_roles"`
	PendingStatuses      []string `json:"pending_statuses"`
	OperatingStatuses    []string `json:"operating_statuses"`
	PageSize             int      `json:"page_size"`
	QueryKeysNotPassed   []string `json:"query_keys_not_passed"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.PageRoles) == 0 || len(r.PendingStatuses) == 0 || len(r.OperatingStatuses) == 0 || r.PageSize == 0 {
		panic(fmt.Sprintf("staffsetup: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// Service answers the page from the existing database.
type Service struct{ db schooldirectory.Querier }

// NewService is the page over db.
func NewService(db schooldirectory.Querier) *Service { return &Service{db: db} }

// school is one school waiting for its owner.
type school struct {
	ID, Name, RawOwner, District, DistrictID, Region string
}

// staff is one live member of staff the school may be matched to.
type staff struct{ Name, Email string }

// Build answers the queue; every other path is not this page's.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	rows, err := s.db.Query(ctx, `
SELECT s.id, s.name, COALESCE(s.account_owner_name_raw, ''), COALESCE(d.name, ''), COALESCE(d.id, ''), COALESCE(r.name, '')
FROM school s LEFT JOIN district d ON d.id = s.district_id LEFT JOIN region r ON r.id = s.region_id
WHERE s.deleted_at IS NULL AND s.operational_status = ANY($1) AND s.account_owner_status = ANY($2)
ORDER BY s.name`, rules.OperatingStatuses, rules.PendingStatuses)
	if err != nil {
		return nil, true, fmt.Errorf("staffsetup: reading the queue: %w", err)
	}
	schools, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (school, error) {
		var sc school
		err := r.Scan(&sc.ID, &sc.Name, &sc.RawOwner, &sc.District, &sc.DistrictID, &sc.Region)
		return sc, err
	})
	if err != nil {
		return nil, true, fmt.Errorf("staffsetup: reading the queue: %w", err)
	}
	var people []staff
	if len(schools) > 0 {
		// The view's StaffProfile query has no order: read the same join the
		// same way.
		rows, err := s.db.Query(ctx, `
SELECT u.name, u.email FROM staff_profile sp INNER JOIN "user" u ON u.id = sp.user_id WHERE sp.deleted_at IS NULL`)
		if err != nil {
			return nil, true, fmt.Errorf("staffsetup: reading the staff: %w", err)
		}
		if people, err = pgx.CollectRows(rows, func(r pgx.CollectableRow) (staff, error) {
			var st staff
			err := r.Scan(&st.Name, &st.Email)
			return st, err
		}); err != nil {
			return nil, true, fmt.Errorf("staffsetup: reading the staff: %w", err)
		}
	}
	return page(p, schools, people, query), true, nil
}

func collapse(text string) string { return closedschools.Collapse(text) }

// picker is the match form's select as the feed reads a cell holding it:
// every option's words in turn.
func picker(people []staff) string {
	parts := []string{"Select CCEO profile..."}
	for _, p := range people {
		parts = append(parts, p.Name+" ("+p.Email+")")
	}
	return collapse(strings.Join(parts, " "))
}

func row(p auth.Principal, sc school, pick string) *screensv1.PageRow {
	raw := sc.RawOwner
	if raw == "" {
		raw = "None Specified"
	}
	// school_identity: the School ID token (read empty, the feed never fills
	// it) and the name, a link for a reader who may open a school's profile.
	name := &screensv1.PageCell{Text: collapse(sc.Name + " Uploaded Owner: " + raw)}
	if slices.Contains(rules.SchoolProfileRoles, p.ActiveRole) && sc.Name != "" {
		name.Href = "/schools/" + url.PathEscape(sc.ID)
	}
	where := &screensv1.PageCell{Text: collapse(sc.District + " district / " + sc.Region + " region")}
	if slices.Contains(rules.DistrictProfileRoles, p.ActiveRole) && sc.District != "" && sc.DistrictID != "" {
		where.Href = "/districts/" + url.PathEscape(sc.DistrictID)
	}
	return &screensv1.PageRow{Cells: []*screensv1.PageCell{
		name, where,
		{Text: "Pending Link", Tone: "primary", Badge: true},
		{Text: pick},
		{Text: "Match Ignore"},
	}}
}

func page(p auth.Principal, schools []school, people []staff, query url.Values) *screensv1.GetPageResponse {
	t := &screensv1.PageTable{}
	for _, c := range []string{"School Record Name", "District / Region", "Status", "Link to Registered Staff"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	t.Columns = append(t.Columns, &screensv1.PageColumn{Label: "Resolve", Numeric: true})
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if len(schools) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: emptyLine}}}}
	} else {
		pick := picker(people)
		number, pages := closedschools.PageOf(query.Get(pageParam), len(schools), rules.PageSize)
		for _, sc := range schools[(number-1)*rules.PageSize : min(number*rules.PageSize, len(schools))] {
			t.Rows = append(t.Rows, row(p, sc, pick))
		}
		if pages > 1 {
			blocks = append(blocks, closedschools.PagerPanel(pageParam, number, pages, len(schools), rules.PageSize, query, rules.QueryKeysNotPassed))
		}
	}
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{Eyebrow: "Administration", Title: "Staff Setup Queue",
			Description: "Resolve raw staff name mappings from onboarding data to match registered CCEOs"},
		Blocks: blocks, WebPath: Path,
	}
}
