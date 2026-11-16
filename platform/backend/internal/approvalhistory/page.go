// Package approvalhistory builds the Finance Approval History page
// (/accounts/approval-history/): every weekly fund request, latest week
// first, with who it belongs to, its owner confirmation, finance approval
// and disbursement stages and its status
// (apps.frontend.views.finance_operating_views.approval_history_view and
// pages/accounts/approval_history.html, as the existing feed reads them).
//
// It reads; it never writes. It hands the page on for a query it does not
// know. The doors and words are exported to rules.json by `manage.py
// export_approval_history_rules`; apps/fund_requests/
// test_approval_history_rules_export.py fails when the two differ.
package approvalhistory

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// PagePath is the page's path.
const PagePath = "/accounts/approval-history/"

const pageParam = "requests_page"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles map[string]struct {
		Page  bool            `json:"page"`
		Strip json.RawMessage `json:"strip"`
	} `json:"roles"`
	StatusInitialisms  map[string]string `json:"status_initialisms"`
	PageSize           int               `json:"page_size"`
	QueryKeysNotPassed []string          `json:"query_keys_not_passed"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("approvalhistory: reading rules.json: %v", err))
	}
	if len(r.Roles) == 0 || r.PageSize <= 0 || len(r.StatusInitialisms) == 0 {
		panic("approvalhistory: rules.json lacks the doors, the page size or the initialisms")
	}
	return r
}()

// Service builds the page.
type Service struct {
	db schooldirectory.Querier
}

// NewService returns the page's builder.
func NewService(db schooldirectory.Querier) *Service { return &Service{db: db} }

// request is one weekly fund request as the page shows it.
type request struct {
	week          time.Time
	amount        int64
	owner, status string
}

// Build answers /accounts/approval-history/.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != PagePath {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	for key := range query {
		if key != pageParam {
			return nil, false, nil
		}
	}
	if len(role.Strip) > 0 && string(role.Strip) != "null" {
		// No role that opens the page is shown a strip; one that is would
		// need it drawn.
		return nil, false, nil
	}
	rows, err := s.requests(ctx)
	if err != nil {
		return nil, true, err
	}
	h := &screensv1.PageHeader{Eyebrow: "Finance", Title: "Finance Approval History",
		Description: "Audit trail of fund requests routing through PL, CD, RVP, and accountant sign-off stages."}
	return &screensv1.GetPageResponse{Header: h, Blocks: blocks(rows, query), WebPath: PagePath}, true, nil
}

// requests is every weekly fund request, latest week first, with its
// owner's name (the owner's id when no account has it). The requests are
// read on their own, as the existing query reads them, so requests of the
// same week come in the same order.
func (s *Service) requests(ctx context.Context) ([]request, error) {
	rows, err := s.db.Query(ctx, `
SELECT week_start_date, total_amount, responsible_user, status FROM weekly_fund_request ORDER BY week_start_date DESC`)
	if err != nil {
		return nil, fmt.Errorf("approvalhistory: reading the weekly requests: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (request, error) {
		var r request
		err := row.Scan(&r.week, &r.amount, &r.owner, &r.status)
		return r, err
	})
	if err != nil {
		return nil, fmt.Errorf("approvalhistory: reading the weekly requests: %w", err)
	}
	ids := make([]string, 0, len(out))
	for _, r := range out {
		ids = append(ids, r.owner)
	}
	names := map[string]string{}
	nrows, err := s.db.Query(ctx, `SELECT id, name FROM "user" WHERE id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("approvalhistory: reading the owners: %w", err)
	}
	defer nrows.Close()
	for nrows.Next() {
		var id, name string
		if err := nrows.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("approvalhistory: reading the owners: %w", err)
		}
		names[id] = name
	}
	if err := nrows.Err(); err != nil {
		return nil, fmt.Errorf("approvalhistory: reading the owners: %w", err)
	}
	for i := range out {
		if name, ok := names[out[i].owner]; ok {
			out[i].owner = name
		}
	}
	return out, nil
}

func blocks(rows []request, query url.Values) []*screensv1.PageBlock {
	t := &screensv1.PageTable{}
	for _, c := range []string{"Fund Request / ID", "Submitted By", "Owner Confirmation", "Finance Approval", "Disbursement", "Status"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
	}
	t.Columns = append(t.Columns, &screensv1.PageColumn{Label: "Actions", Numeric: true})
	if len(rows) == 0 {
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No requests found in approval history."}}}}
		return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	}
	number, pages := closedschools.PageOf(query.Get(pageParam), len(rows), rules.PageSize)
	for _, r := range rows[(number-1)*rules.PageSize : min(number*rules.PageSize, len(rows))] {
		cells := []*screensv1.PageCell{
			{Text: fmt.Sprintf("Request: %s Amount: %d UGX", weekLabel(r.week), r.amount)},
			{Text: r.owner},
		}
		for _, state := range chain(r.status) {
			cells = append(cells, &screensv1.PageCell{Text: stateLabel(state)})
		}
		cells = append(cells, &screensv1.PageCell{Text: statusLabel(r.status)},
			&screensv1.PageCell{Actions: []*screensv1.PageAction{{Key: "button", Label: "Review Request", Primary: true,
				Enabled: true, Href: "/accounts/weekly-requests/"}}})
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: cells})
	}
	out := []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}
	if pages > 1 {
		out = append(out, closedschools.PagerPanel(pageParam, number, pages, len(rows), rules.PageSize, query, rules.QueryKeysNotPassed))
	}
	return out
}

// weekLabel is the date filter "Y-\WW": the calendar year, then the ISO week.
func weekLabel(d time.Time) string {
	_, week := d.ISOWeek()
	return strconv.Itoa(d.Year()) + "-W" + strconv.Itoa(week)
}

// chain is disbursement_dashboard_service._weekly_chain: the owner's
// confirmation, finance's approval and the disbursement, from the status.
func chain(status string) [3]string {
	owner, finance, disbursement := "approved", "not_started", "not_started"
	if status == "pending_responsible_confirmation" {
		owner = "pending"
	}
	switch status {
	case "confirmed_for_advance":
		finance = "pending"
	case "disbursed", "accounted":
		finance, disbursement = "approved", "done"
	case "returned_by_accountant", "returned":
		finance = "returned"
	}
	return [3]string{owner, finance, disbursement}
}

// stateLabel is the template's word for a stage's state.
func stateLabel(state string) string {
	switch state {
	case "approved":
		return "Approved"
	case "done":
		return "Disbursed"
	case "returned":
		return "Returned"
	case "held":
		return "Held"
	case "pending":
		return "Awaiting"
	case "not_required":
		return "Not required"
	}
	return "Not yet"
}

// statusLabel is the status_label filter: each word capitalised, the
// initialisms it knows written as they are.
func statusLabel(status string) string {
	words := strings.Fields(strings.NewReplacer("_", " ", "-", " ").Replace(status))
	for i, w := range words {
		w = strings.ToUpper(w[:1]) + strings.ToLower(w[1:])
		if fixed, ok := rules.StatusInitialisms[w]; ok {
			w = fixed
		}
		words[i] = w
	}
	return strings.Join(words, " ")
}
