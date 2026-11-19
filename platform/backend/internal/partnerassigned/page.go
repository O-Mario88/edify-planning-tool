// Package partnerassigned is the partner's intake queues and portal lists
// (portal.go: /partner/schools, /partner/activities, /partner/assignments):
// Assigned Schools
// (/partner/assigned-schools), the school-based work Edify handed to the
// organisation, and Assigned Activities (/partner/assigned-activities), its
// cluster and group work, each awaiting the partner's Schedule-or-Return
// decision, as the existing pages draw them
// (apps.frontend.views.partner_views._assigned_intake and
// pages/partner/assigned_list.html) and the app's feed reads them. The
// decisions stay with their drawers.
//
// The feed reads a row's Decision cell as its buttons' words, so the visit
// gate that greys Schedule out does not change the answer. A queue holding
// an assignment written before its catalogue item was pinned is passed on:
// the existing page saves that item as it reads it (_ensure_assignment_item),
// and the gateway does not write on a read.
//
// The doors, statuses, labels and limits are exported to rules.json by
// `manage.py export_partner_assigned_rules`;
// apps/partners/test_partner_assigned_rules_export.py fails when the two
// differ.
package partnerassigned

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"
	"unicode"

	_ "time/tzdata" // the assigned day is Nairobi's wherever the gateway runs

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The two queues.
const (
	SchoolsPath    = "/partner/assigned-schools"
	ActivitiesPath = "/partner/assigned-activities"
)

const (
	pageParam = "assigned_list_rows_page"
	emptyLine = "Nothing awaiting your decision — new assignments appear here."
)

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	PageRoles          map[string][]string `json:"page_roles"`
	QueueStatuses      []string            `json:"queue_statuses"`
	QueueLimit         int                 `json:"queue_limit"`
	ClusterScopeTypes  []string            `json:"cluster_scope_types"`
	PurposeLabels      map[string]string   `json:"purpose_labels"`
	PartnerRoleBridge  bool                `json:"partner_role_bridge"`
	PageSize           int                 `json:"page_size"`
	QueryKeysNotPassed []string            `json:"query_keys_not_passed"`
	// The Evidence page: the activity labels, the statuses that are
	// completed work, and how many uploads and missing ones it lists.
	ActivityTypes         map[string]string `json:"activity_types"`
	CompletedWorkStatuses []string          `json:"completed_work_statuses"`
	EvidenceLimit         int               `json:"evidence_limit"`
	MissingEvidenceLimit  int               `json:"missing_evidence_limit"`
	// Completed Work & Payments: the statuses it lists, how many, and who
	// may open a school's or a cluster's profile from it.
	CompletedStatuses []string            `json:"completed_statuses"`
	CompletedLimit    int                 `json:"completed_limit"`
	ProfileLinkRoles  map[string][]string `json:"profile_link_roles"`
	// The portal's lists (portal.go).
	CalledOffStatuses []string `json:"called_off_statuses"`
	AwaitingStatuses  []string `json:"awaiting_statuses"`
	LogLimit          int      `json:"log_limit"`
	AssignmentsLimit  int      `json:"assignments_limit"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.PageRoles) != 7 || r.LogLimit == 0 || r.AssignmentsLimit == 0 || len(r.AwaitingStatuses) == 0 || r.CompletedLimit == 0 || len(r.CompletedWorkStatuses) == 0 || len(r.QueueStatuses) == 0 || r.QueueLimit == 0 || r.PageSize == 0 {
		panic(fmt.Sprintf("partnerassigned: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("partnerassigned: " + err.Error())
	}
	return z
}()

const (
	rolePartnerAdmin = "PartnerAdmin"
	rolePartnerFO    = "PartnerFieldOfficer"
	roleAdmin        = "Admin"
)

// Service answers both queues from the existing database.
type Service struct{ db schooldirectory.Querier }

// NewService is the queues over db.
func NewService(db schooldirectory.Querier) *Service { return &Service{db: db} }

// assignment is one queued hand-over with what its row shows.
type assignment struct {
	ID, Status, Expected, PurposeCode, Purpose string
	SchoolID, Code, School, District, Phone    string
	Contact, Address, ClusterID, Cluster       string
	Item                                       *string
	HasItem                                    bool
	CreatedAt                                  time.Time
}

// Build answers the two queues; every other path is not theirs.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	roles, ok := rules.PageRoles[path]
	if !ok {
		return nil, false, nil
	}
	if !slices.Contains(roles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	partners, err := s.partnerIDs(ctx, p)
	if err != nil {
		return nil, true, err
	}
	if path == EvidencePath {
		return s.evidence(ctx, partners)
	}
	if path == PortalSchoolsPath || path == PortalActivitiesPath || path == PortalAssignmentsPath {
		return s.portal(ctx, p, path, partners, query)
	}
	if path == CompletedPath {
		return s.completed(ctx, p, partners, query)
	}
	member, schools, err := s.teamMember(ctx, p)
	if err != nil {
		return nil, true, err
	}
	rows, err := s.queue(ctx, partners, member, schools)
	if err != nil {
		return nil, true, err
	}
	schoolScoped := path == SchoolsPath
	kept := []assignment{}
	for _, a := range rows {
		if isSchoolScoped(a) == schoolScoped {
			if !a.HasItem {
				// _ensure_assignment_item saves the item on this read.
				return nil, false, nil
			}
			kept = append(kept, a)
		}
	}
	return page(path, schoolScoped, !member, kept, query), true, nil
}

// PartnerIDs is apps.core.scoping.resolve_partner_ids: the organisation the
// reader acts as, for the other pages a partner login reads.
func PartnerIDs(ctx context.Context, db schooldirectory.Querier, p auth.Principal) ([]string, error) {
	return (&Service{db: db}).partnerIDs(ctx, p)
}

// IsTeamMember is member_scope.is_team_member: a partner login that is a
// roster entry's own and does not lead its team.
func IsTeamMember(ctx context.Context, db schooldirectory.Querier, p auth.Principal) (bool, error) {
	member, _, err := (&Service{db: db}).teamMember(ctx, p)
	return member, err
}

// partnerIDs is resolve_partner_ids: the organisation whose login this is,
// else the one a team member's login belongs to (partner roles only), else
// the first partner under the demo role-bridge, else none.
func (s *Service) partnerIDs(ctx context.Context, p auth.Principal) ([]string, error) {
	var id string
	err := s.db.QueryRow(ctx, `SELECT id FROM partner WHERE user_id = $1 AND active_status ORDER BY created_at LIMIT 1`, p.UserID).Scan(&id)
	if err == nil {
		return []string{id}, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return nil, fmt.Errorf("partnerassigned: reading the reader's organisation: %w", err)
	}
	if p.ActiveRole == rolePartnerAdmin || p.ActiveRole == rolePartnerFO {
		err := s.db.QueryRow(ctx, `
SELECT m.partner_id FROM partner_member m JOIN partner pa ON pa.id = m.partner_id
WHERE m.user_id = $1 AND m.active AND pa.active_status LIMIT 1`, p.UserID).Scan(&id)
		if err == nil {
			return []string{id}, nil
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return nil, fmt.Errorf("partnerassigned: reading the reader's membership: %w", err)
		}
	}
	if rules.PartnerRoleBridge {
		err := s.db.QueryRow(ctx, `SELECT id FROM partner WHERE active_status ORDER BY created_at LIMIT 1`).Scan(&id)
		if err == nil {
			return []string{id}, nil
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return nil, fmt.Errorf("partnerassigned: reading the first partner: %w", err)
		}
	}
	return nil, nil
}

// teamMember is member_scope.team_member: a partner login that is a roster
// entry's own and does not lead its team, with the schools given to it.
func (s *Service) teamMember(ctx context.Context, p auth.Principal) (bool, []string, error) {
	if p.ActiveRole != rolePartnerAdmin && p.ActiveRole != rolePartnerFO {
		return false, nil, nil
	}
	var memberID, partnerID, partnerUser string
	err := s.db.QueryRow(ctx, `
SELECT m.id, m.partner_id, COALESCE(pa.user_id, '') FROM partner_member m JOIN partner pa ON pa.id = m.partner_id
WHERE m.user_id = $1 AND m.active AND pa.active_status LIMIT 1`, p.UserID).Scan(&memberID, &partnerID, &partnerUser)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil, nil
	}
	if err != nil {
		return false, nil, fmt.Errorf("partnerassigned: reading the reader's roster entry: %w", err)
	}
	// leads_team: the Admin, the organisation's own login, or its login as
	// Partner Admin.
	if p.ActiveRole == roleAdmin || partnerUser == p.UserID {
		return false, nil, nil
	}
	if p.ActiveRole == rolePartnerAdmin {
		own, err := s.partnerIDs(ctx, p)
		if err != nil {
			return false, nil, err
		}
		if slices.Contains(own, partnerID) {
			return false, nil, nil
		}
	}
	rows, err := s.db.Query(ctx, `SELECT school_id FROM partner_school_member WHERE member_id = $1`, memberID)
	if err != nil {
		return false, nil, fmt.Errorf("partnerassigned: reading the member's schools: %w", err)
	}
	schools, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return false, nil, fmt.Errorf("partnerassigned: reading the member's schools: %w", err)
	}
	if schools == nil {
		schools = []string{}
	}
	return true, schools, nil
}

// queue is the queued assignments of the reader's organisation (a team
// member's only at their schools), the newest first.
func (s *Service) queue(ctx context.Context, partners []string, member bool, schools []string) ([]assignment, error) {
	if len(partners) == 0 {
		return nil, nil
	}
	args := []any{partners, rules.QueueStatuses, rules.QueueLimit}
	narrow := ""
	if member {
		args = append(args, schools)
		narrow = " AND a.school_id = ANY($4)"
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, a.status, COALESCE(a.expected_activity_type, ''), COALESCE(a.purpose_of_visit, ''), COALESCE(a.purpose, ''),
  COALESCE(a.school_id, ''), COALESCE(sc.school_id, ''), COALESCE(sc.name, ''), COALESCE(d.name, ''), COALESCE(sc.school_phone, ''),
  COALESCE(NULLIF(sc.primary_contact_name, ''), sc.headteacher_name, ''), COALESCE(sc.shipping_address, ''),
  COALESCE(a.cluster_id, ''), COALESCE(cl.name, ''), ci.display_name, a.catalogue_item_id IS NOT NULL, a.created_at
FROM partner_assignment a
LEFT JOIN school sc ON sc.id = a.school_id LEFT JOIN district d ON d.id = sc.district_id
LEFT JOIN cluster cl ON cl.id = a.cluster_id LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
WHERE a.partner_id = ANY($1) AND a.status = ANY($2)`+narrow+`
ORDER BY a.created_at DESC LIMIT $3`, args...)
	if err != nil {
		return nil, fmt.Errorf("partnerassigned: reading the queue: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (assignment, error) {
		var a assignment
		err := r.Scan(&a.ID, &a.Status, &a.Expected, &a.PurposeCode, &a.Purpose, &a.SchoolID, &a.Code, &a.School, &a.District,
			&a.Phone, &a.Contact, &a.Address, &a.ClusterID, &a.Cluster, &a.Item, &a.HasItem, &a.CreatedAt)
		return a, err
	})
}

// isSchoolScoped is _assignment_is_school_scoped: one school is a School
// Visit; cluster or group scope is an Assigned Activity.
func isSchoolScoped(a assignment) bool {
	if a.ClusterID != "" || slices.Contains(rules.ClusterScopeTypes, a.Expected) {
		return false
	}
	return a.SchoolID != ""
}

// pyTitle is str.title(): a letter after a cased letter is lowered, any
// other letter raised.
func pyTitle(s string) string {
	out := []rune{}
	cased := false
	for _, r := range s {
		if cased {
			out = append(out, unicode.ToLower(r))
		} else {
			out = append(out, unicode.ToTitle(r))
		}
		cased = unicode.IsUpper(r) || unicode.IsLower(r) || unicode.IsTitle(r)
	}
	return string(out)
}

// subtype is the catalogue item's name, else the recorded type in words.
func subtype(a assignment) string {
	if a.Item != nil {
		return *a.Item
	}
	return pyTitle(strings.ReplaceAll(a.Expected, "_", " "))
}

// purpose is the coded purpose's label, else the free-text reason, else "—".
func purpose(a assignment) string {
	if l, ok := rules.PurposeLabels[a.PurposeCode]; ok && l != "" {
		return l
	}
	if a.Purpose != "" {
		return a.Purpose
	}
	return "—"
}

func or(text, fallback string) string {
	if text == "" {
		return fallback
	}
	return text
}

func collapse(text string) string { return closedschools.Collapse(text) }

func page(path string, schoolScoped, canReturn bool, rows []assignment, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Field Work", Title: "Assigned Activities",
		Description: "Trainings, cluster meetings and other group work assigned to your organisation."}
	labels := []string{"Date Assigned", "Activity", "Cluster / Area", "Status"}
	if schoolScoped {
		header.Title = "Assigned Schools"
		header.Description = "Schools Edify has assigned to your organisation. Open one to review the brief, then Schedule it or Return it."
		labels = []string{"Date Assigned", "School ID", "School Name", "District", "Phone", "Primary Contact", "Shipping Address", "Assignment Purpose"}
	}
	t := &screensv1.PageTable{}
	for _, l := range labels {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: l})
	}
	t.Columns = append(t.Columns, &screensv1.PageColumn{Label: "Decision", Numeric: true})
	decision := "Schedule"
	if canReturn {
		decision = "Return Schedule"
	}
	blocks := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if len(rows) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: emptyLine}}}}
		return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: path}
	}
	number, pages := closedschools.PageOf(query.Get(pageParam), len(rows), rules.PageSize)
	for _, a := range rows[(number-1)*rules.PageSize : min(number*rules.PageSize, len(rows))] {
		day := &screensv1.PageCell{Text: a.CreatedAt.In(zone).Format("02 Jan 2006")}
		open := "/partner/assignments/" + a.ID
		var cells []*screensv1.PageCell
		if schoolScoped {
			cells = []*screensv1.PageCell{
				day,
				{Text: collapse(or(a.Code, "—"))},
				{Text: collapse(or(a.School, "School") + " " + subtype(a)), Href: open},
				{Text: collapse(or(a.District, "—"))},
				{Text: collapse(or(a.Phone, "—"))},
				{Text: collapse(or(a.Contact, "—"))},
				{Text: collapse(or(a.Address, "—"))},
				{Text: collapse(purpose(a))},
			}
		} else {
			area := &screensv1.PageCell{Text: collapse(or(a.District, "—"))}
			if a.ClusterID != "" {
				area = &screensv1.PageCell{Text: collapse(a.Cluster), Href: "/clusters/" + a.ClusterID}
			}
			status := "Awaiting Schedule"
			if a.Status == "returned" {
				status = "Returned"
			}
			cells = []*screensv1.PageCell{
				day,
				{Text: collapse(subtype(a)), Href: open},
				area,
				{Text: status, Tone: "primary", Badge: true},
			}
		}
		cells = append(cells, &screensv1.PageCell{Text: decision})
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells})
	}
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel(pageParam, number, pages, len(rows), rules.PageSize, query, rules.QueryKeysNotPassed))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: path}
}
