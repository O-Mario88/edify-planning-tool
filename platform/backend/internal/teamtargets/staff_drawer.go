package teamtargets

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/mytargets"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
)

// notInTeam is _team_member_or_none's refusal.
const notInTeam = "Not in your supervised team."

// perAreaPage is the drawer table's page size (TABLE_PAGE_SIZE): more
// priorities than that page, which Go does not draw.
const perAreaPage = 50

// StaffDrawer is team_targets_staff_drawer_view: one supervised member's
// month (the month asked for, else this month in the current year and the
// first in any other), each priority with where its work stands.
func StaffDrawer(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string, now time.Time) (*screensv1.PageDrawer, error) {
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, &RefusedError{Refusal}
	}
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	team, err := supervisedUsers(ctx, db, p, scope)
	if err != nil {
		return nil, err
	}
	staff := strings.TrimSpace(q["staff"])
	i := slices.IndexFunc(team, func(m Member) bool { return m.UserID == staff })
	if i < 0 {
		return nil, &RefusedError{notInTeam}
	}
	m := team[i]
	l := now.In(kampala)
	today := time.Date(l.Year(), l.Month(), l.Day(), 0, 0, 0, 0, time.UTC)
	current := strconv.Itoa(l.Year())
	if l.Month() >= time.October {
		current = strconv.Itoa(l.Year() + 1)
	}
	fy, month, ok := staffPeriod(q, current, today)
	if !ok {
		return nil, ErrHandOn
	}
	person := targets.Person{UserID: m.UserID, StaffID: m.StaffID}
	roster, err := targets.Prepare(ctx, db, []targets.Person{person}, fy, nil)
	if err != nil {
		return nil, err
	}
	member := roster.TeamMember(person, month, fy == current, today, nil)
	if len(member.PerArea) > perAreaPage {
		return nil, ErrHandOn
	}
	districts, sf, err := staffFacts(ctx, db, m, fy)
	if err != nil {
		return nil, err
	}
	start, end := targets.MonthRange(fy, month)
	ids := []string{m.UserID}
	if m.StaffID != "" {
		ids = append(ids, m.StaffID)
	}
	rows := []*screensv1.PageRow{}
	for _, pa := range member.PerArea {
		c, err := mytargets.CountPipeline(ctx, db, ids, m.UserID, fy, pa.Key, start, end)
		if err != nil {
			return nil, err
		}
		cells := []string{fmt.Sprintf("%s w%d%%", pa.Label, pa.Weight), strconv.Itoa(pa.Target), strconv.Itoa(pa.Achieved),
			strconv.Itoa(c.Scheduled), strconv.Itoa(c.PendingSF), strconv.Itoa(c.IAPending), strconv.Itoa(c.Returned), pctText(pa.Pct)}
		row := &screensv1.PageRow{}
		for _, t := range cells {
			row.Cells = append(row.Cells, &screensv1.PageCell{Text: t})
		}
		rows = append(rows, row)
	}
	columns := []*screensv1.PageColumn{}
	for _, label := range []string{"Priority", "Tgt", "Valid", "Scheduled", "SF ID missing", "PL pending", "Returned", "%"} {
		columns = append(columns, &screensv1.PageColumn{Label: label})
	}
	label := targets.MonthLabel(fy, month)
	fact := func(l, v string) *screensv1.PageFact { return &screensv1.PageFact{Label: l, Value: v} }
	items := []*screensv1.DrawerItem{
		{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: []*screensv1.PageFact{
			fact("Monthly target", strconv.Itoa(member.MonthTarget)), fact("Valid achieved", strconv.Itoa(member.MonthAchieved)),
			// The second line under Achievement (the expected pace) is not
			// read by the feed.
			fact("Achievement", pctText(member.MonthPct)), fact("Status", member.Status)}}}},
		{Kind: &screensv1.DrawerItem_Heading{Heading: "Performance priorities — " + label}},
		{Kind: &screensv1.DrawerItem_Block{Block: &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Columns: columns, Rows: rows}}}}},
		text("Valid = executed, evidenced, with an Activity SF ID and the Programme Lead's verification, credited to the month the work happened. Provisional work is never counted."),
		text(fmt.Sprintf("Districts: %s · SF ID compliance %d%%", districts, sf)),
	}
	return &screensv1.PageDrawer{Title: m.Name, Subtitle: label, HasRequired: true, CancelLabel: "Cancel", Items: items}, nil
}

// staffPeriod is the view's year and month: the year asked for (else the
// current one) and a month 1 to 12 (else this month in the current year and
// the first in another). ok is false for a year Go does not read as Django
// would (anything but four digits) and a month holding anything but ASCII.
func staffPeriod(q map[string]string, current string, today time.Time) (string, int, bool) {
	fy := strings.TrimSpace(q["fy"])
	if fy == "" {
		fy = current
	}
	if len(fy) != 4 || strings.Trim(fy, "0123456789") != "" {
		return "", 0, false
	}
	raw := strings.TrimSpace(q["month"])
	for _, r := range raw {
		if r >= 0x80 {
			// A Unicode digit is a digit to str.isdigit() but not to int().
			return "", 0, false
		}
	}
	if n, err := strconv.Atoi(raw); err == nil && strings.Trim(raw, "0123456789") == "" && n >= 1 && n <= 12 {
		return fy, n, true
	}
	if fy == current {
		return fy, targets.MonthOfFY(today, fy), true
	}
	return fy, 1, true
}

func pctText(p *int) string {
	if p == nil {
		return "—"
	}
	return strconv.Itoa(*p) + "%"
}

// staffFacts are the view's backfilled portfolio fields: the first two
// districts (by name) of the member's assigned schools, and the share of
// their completed staff work owing an Activity SF ID that carries one (100
// with none owed).
func staffFacts(ctx context.Context, db schooldirectory.Querier, m Member, fy string) (string, int, error) {
	names := []string{}
	if m.StaffID != "" {
		rows, err := db.Query(ctx, `SELECT DISTINCT d.name FROM staff_school_assignment a JOIN school s ON s.id = a.school_id
			JOIN district d ON d.id = s.district_id WHERE a.staff_id = $1`, m.StaffID)
		if err != nil {
			return "", 0, fmt.Errorf("teamtargets: the member's districts: %w", err)
		}
		defer rows.Close()
		for rows.Next() {
			var n string
			if err := rows.Scan(&n); err != nil {
				return "", 0, err
			}
			names = append(names, n)
		}
		if err := rows.Err(); err != nil {
			return "", 0, err
		}
	}
	sort.Strings(names)
	label := strings.Join(names[:min(2, len(names))], ", ")
	if label == "" {
		label = "—"
	}
	ids := []string{m.UserID}
	if m.StaffID != "" {
		ids = append(ids, m.StaffID)
	}
	var total, given int
	if err := db.QueryRow(ctx, `SELECT count(*), count(*) FILTER (WHERE COALESCE(salesforce_activity_id, '') <> '') FROM activity
		WHERE responsible_staff_id = ANY($1) AND fy = $2 AND activity_type = ANY($3) AND status = ANY($4)
		AND deleted_at IS NULL AND delivery_type IS DISTINCT FROM 'partner'`, ids, fy, rules.SFRequiredTypes, rules.CompletedStatuses).Scan(&total, &given); err != nil {
		return "", 0, fmt.Errorf("teamtargets: the member's SF ID compliance: %w", err)
	}
	sf := 100
	if total > 0 {
		sf = pyRound(float64(given) / float64(total) * 100)
	}
	return label, sf, nil
}
