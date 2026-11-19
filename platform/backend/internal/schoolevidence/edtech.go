package schoolevidence

import (
	"context"
	"fmt"
	"math"
	"net/url"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
)

const (
	edtech = "edtech"
	check  = "check"
	// checksShown is how many of the year's checks the checks table lists.
	checksShown = 50
)

// verdict is who recorded a record, its state and the reader's row action.
type verdict struct {
	recordedBy, status, reason, country string
	recorder                            *string
}

const verdictColumns = `x.recorded_by_user_id, x.verification_status, COALESCE(x.return_reason, ''), COALESCE(x.country, ''),
  (SELECT u.name FROM "user" u WHERE u.id = x.recorded_by_user_id AND u.deleted_at IS NULL)`

func (v *verdict) targets() []any {
	return []any{&v.recordedBy, &v.status, &v.reason, &v.country, &v.recorder}
}

// cells are the register's "Recorded by" and "Status" cells and its row
// action (_row_actions): Verify when the reader may verify it, else Open.
func (v *verdict) cells(ctx context.Context, r *reader, kind, id string) ([]*screensv1.PageCell, error) {
	recorder := "Staff member"
	if v.recorder != nil {
		recorder = *v.recorder
	}
	status := label(rules.Statuses, v.status)
	if v.status == "returned" && v.reason != "" {
		status += ": " + v.reason
	}
	open := "Open"
	if v.status == "pending" {
		may, err := r.reviewer.May(ctx, v.recordedBy, v.country)
		if err != nil {
			return nil, err
		}
		if may {
			open = "Verify"
		}
	}
	return []*screensv1.PageCell{cell(recorder, ""), cell(status, ""), action(open, Path+kind+"/"+id+"/")}, nil
}

func action(label, drawer string) *screensv1.PageCell {
	return &screensv1.PageCell{Actions: []*screensv1.PageAction{{Key: "button", Label: label, Primary: true, Enabled: true,
		Href: drawer, Drawer: true}}}
}

func technology(quantity int, asset string) string {
	return strconv.Itoa(quantity) + " × " + choice(rules.AssetTypes, asset)
}

// choice is the label of value among choices, or nothing for none of them.
func choice(choices [][2]string, value string) string {
	for _, c := range choices {
		if c[0] == value {
			return c[1]
		}
	}
	return ""
}

// edtechTab is _edtech_tab: each confirmed deployment with its latest
// confirmed check, the register of deployments, and the year's checks.
func (s *Service) edtechTab(ctx context.Context, r *reader, query url.Values) (tabContent, error) {
	asset := query.Get("asset_type")
	if choice(rules.AssetTypes, asset) == "" {
		asset = ""
	}
	c := tabContent{recordLabel: "Record deployment", record: edtech,
		description: "What each school received for teaching and learning, and whether it works and is used: " +
			"the latest confirmed check of each confirmed deployment. Deployment is delivery, not impact; " +
			"use is the first sign it reaches learners."}
	f := &screensv1.PageFilter{Name: "asset_type", Caption: "Technology", Value: asset,
		Options: []*screensv1.PageFilterOption{{Label: "Every technology"}}}
	for _, a := range rules.AssetTypes {
		f.Options = append(f.Options, &screensv1.PageFilterOption{Value: a[0], Label: a[1]})
	}
	c.filters = append(c.filters, f)
	summary, err := s.edtechSummary(ctx, r, asset, query)
	if err != nil {
		return tabContent{}, err
	}
	register, err := s.deployments(ctx, r, asset, query)
	if err != nil {
		return tabContent{}, err
	}
	checks, err := s.checks(ctx, r)
	if err != nil {
		return tabContent{}, err
	}
	c.tables = append(append(summary, register...), checks...)
	return c, nil
}

// deployments is the register of deployments, newest first, 50 a page.
func (s *Service) deployments(ctx context.Context, r *reader, asset string, query url.Values) ([]*screensv1.PageBlock, error) {
	args := append([]any{}, r.args...)
	arg := func(v any) string {
		args = append(args, v)
		return "$" + strconv.Itoa(len(args))
	}
	where := "x.deleted_at IS NULL AND " + r.schools + " AND x.fy = " + arg(r.fy)
	if r.status != "" {
		where += " AND x.verification_status = " + arg(r.status)
	}
	if asset != "" {
		where += " AND x.asset_type = " + arg(asset)
	}
	from := ` FROM impact_edtech_deployment x JOIN school s ON s.id = x.school_id WHERE ` + where
	var total int
	if err := s.db.QueryRow(ctx, `SELECT count(*)`+from, args...).Scan(&total); err != nil {
		return nil, fmt.Errorf("schoolevidence: counting the deployments: %w", err)
	}
	number, pages := closedschools.PageOf(query.Get("register_page"), total, pageSize)
	limit, offset := arg(pageSize), arg((number-1)*pageSize)
	rows, err := s.db.Query(ctx, `SELECT x.id, s.name, x.asset_type, x.quantity, x.deployed_on, x.funding, x.learners_with_access, `+
		verdictColumns+from+` ORDER BY x.deployed_on DESC, x.created_at DESC LIMIT `+limit+` OFFSET `+offset, args...)
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the deployments: %w", err)
	}
	type deployment struct {
		id, school, asset, funding string
		quantity                   int
		deployed                   time.Time
		access                     *int
		v                          verdict
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (deployment, error) {
		var d deployment
		err := row.Scan(append([]any{&d.id, &d.school, &d.asset, &d.quantity, &d.deployed, &d.funding, &d.access}, d.v.targets()...)...)
		return d, err
	})
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the deployments: %w", err)
	}
	cells := [][]*screensv1.PageCell{}
	for _, d := range list {
		tail, err := d.v.cells(ctx, r, edtech, d.id)
		if err != nil {
			return nil, err
		}
		cells = append(cells, append([]*screensv1.PageCell{
			cell(d.school, ""), cell(technology(d.quantity, d.asset), ""), cell(d.deployed.Format("2 Jan 2006"), ""),
			cell(choice(rules.Funding, d.funding), ""), cell(num(d.access, ""), ""),
		}, tail...))
	}
	return table("Deployments", []string{"School", "Technology", "Deployed", "Funding", "Learners with access", "Recorded by", "Status"},
		cells, len(cells) > 0, total, number, pages, "register_page", "No EdTech deployments recorded",
		"Record the technology a school received, its funding and who has access.", query), nil
}

// checks is the year's checks of use, newest first (up to 50).
func (s *Service) checks(ctx context.Context, r *reader) ([]*screensv1.PageBlock, error) {
	args := append([]any{}, r.args...)
	arg := func(v any) string {
		args = append(args, v)
		return "$" + strconv.Itoa(len(args))
	}
	where := "x.deleted_at IS NULL AND " + r.schools + " AND x.fy = " + arg(r.fy)
	if r.status != "" {
		where += " AND x.verification_status = " + arg(r.status)
	}
	rows, err := s.db.Query(ctx, `SELECT x.id, s.name, d.quantity, d.asset_type, x.checked_on, x.units_functional, x.teachers_using, x.learners_using, `+
		verdictColumns+` FROM impact_edtech_check x JOIN school s ON s.id = x.school_id JOIN impact_edtech_deployment d ON d.id = x.deployment_id
WHERE `+where+` ORDER BY x.checked_on DESC, x.created_at DESC LIMIT `+arg(checksShown), args...)
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the checks: %w", err)
	}
	type checkRow struct {
		id, school, asset  string
		quantity, working  int
		checked            time.Time
		teachers, learners *int
		v                  verdict
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (checkRow, error) {
		var c checkRow
		err := row.Scan(append([]any{&c.id, &c.school, &c.quantity, &c.asset, &c.checked, &c.working, &c.teachers, &c.learners}, c.v.targets()...)...)
		return c, err
	})
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the checks: %w", err)
	}
	cells := [][]*screensv1.PageCell{}
	for _, c := range list {
		tail, err := c.v.cells(ctx, r, check, c.id)
		if err != nil {
			return nil, err
		}
		cells = append(cells, append([]*screensv1.PageCell{
			cell(c.school, ""), cell(technology(c.quantity, c.asset), ""), cell(c.checked.Format("2 Jan 2006"), ""),
			cell(strconv.Itoa(c.working), ""), cell(num(c.teachers, ""), ""), cell(num(c.learners, ""), ""),
		}, tail...))
	}
	return table("Checks of use", []string{"School", "Deployment", "Checked", "Units working", "Teachers using", "Learners using",
		"Recorded by", "Status"}, cells, len(cells) > 0, len(cells), 1, 1, "checks_page", "No checks recorded this year",
		"Record a check from a confirmed deployment above.", nil), nil
}

// percentage is apps.core.metrics.ratio.percentage: a whole percentage
// (Python's round, ties to even), or nil when there is nothing to be one of.
func percentage(n, d int) *int {
	if d == 0 {
		return nil
	}
	v := int(math.RoundToEven(float64(n) / float64(d) * 100))
	return &v
}

// edtechSummary is edtech_summary: every confirmed deployment in the
// reader's schools (any year, any state filter) with its latest confirmed
// check and its checks awaiting verification, by school then newest.
func (s *Service) edtechSummary(ctx context.Context, r *reader, asset string, query url.Values) ([]*screensv1.PageBlock, error) {
	args := append([]any{}, r.args...)
	where := "x.deleted_at IS NULL AND " + r.schools + " AND x.verification_status = 'confirmed'"
	if asset != "" {
		args = append(args, asset)
		where += " AND x.asset_type = $" + strconv.Itoa(len(args))
	}
	rows, err := s.db.Query(ctx, `SELECT x.id, s.name, x.asset_type, x.quantity, x.deployed_on, x.learners_with_access,
  k.checked_on, k.units_functional, k.teachers_using, k.learners_using,
  (SELECT count(*) FROM impact_edtech_check p WHERE p.deployment_id = x.id AND p.verification_status = 'pending' AND p.deleted_at IS NULL)
FROM impact_edtech_deployment x JOIN school s ON s.id = x.school_id
LEFT JOIN LATERAL (SELECT c.checked_on, c.units_functional, c.teachers_using, c.learners_using FROM impact_edtech_check c
  WHERE c.deployment_id = x.id AND c.verification_status = 'confirmed' AND c.deleted_at IS NULL
  ORDER BY c.checked_on DESC, c.created_at DESC LIMIT 1) k ON true
WHERE `+where+` ORDER BY s.name, x.deployed_on DESC`, args...)
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the deployments' latest checks: %w", err)
	}
	type summaryRow struct {
		id, school, asset           string
		quantity, pending           int
		deployed                    time.Time
		access                      *int
		checked                     *time.Time
		working, teachers, learners *int
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (summaryRow, error) {
		var x summaryRow
		err := row.Scan(&x.id, &x.school, &x.asset, &x.quantity, &x.deployed, &x.access, &x.checked, &x.working, &x.teachers,
			&x.learners, &x.pending)
		return x, err
	})
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the deployments' latest checks: %w", err)
	}
	record := rules.Roles[r.p.ActiveRole].Record
	number, pages := closedschools.PageOf(query.Get("summary_page"), len(list), pageSize)
	cells := [][]*screensv1.PageCell{}
	for _, x := range list[(number-1)*pageSize : min(number*pageSize, len(list))] {
		checked, working, teachers, learners := "Not checked yet", "Not measured", "Not measured", "Not measured"
		if x.checked != nil {
			checked = x.checked.Format("2 Jan 2006")
			units := 0
			if x.working != nil {
				units = *x.working
			}
			pct := "None"
			if p := percentage(units, x.quantity); p != nil {
				pct = strconv.Itoa(*p)
			}
			working = num(x.working, "") + " of " + strconv.Itoa(x.quantity) + " (" + pct + "%)"
			teachers = num(x.teachers, "")
			learners = num(x.learners, "")
			if x.access != nil && *x.access != 0 && x.learners != nil {
				learners = strconv.Itoa(*x.learners) + " of " + strconv.Itoa(*x.access)
			}
		}
		row := []*screensv1.PageCell{
			cell(x.school, ""), cell(technology(x.quantity, x.asset), ""), cell(x.deployed.Format("2 Jan 2006"), ""),
			cell(checked, ""), cell(working, ""), cell(teachers, ""), cell(learners, ""), cell(strconv.Itoa(x.pending), ""),
		}
		if record {
			row = append(row, action("Record check", Path+edtech+"/"+x.id+"/check"))
		}
		cells = append(cells, row)
	}
	return table("Deployments and their latest check", []string{"School", "Technology", "Deployed", "Latest check", "Working",
		"Teachers using", "Learners using", "Checks awaiting verification"}, cells, record && len(cells) > 0, len(list), number, pages,
		"summary_page", "No confirmed deployment", "Record a deployment; once confirmed, record checks of use.", query), nil
}
