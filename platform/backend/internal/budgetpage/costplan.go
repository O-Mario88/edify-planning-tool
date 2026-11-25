package budgetpage

import (
	"context"
	"fmt"
	"strconv"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// CostPlanSheet is plan_export.budget_sheet's ledger as one sheet
// (services.cost_plan_sheet over budget_groups): the Activity cost plan of
// exactly these activities' own cost lines, laid out as the Budget page
// lays it out, under the period line given. title names the sheet.
func CostPlanSheet(ctx context.Context, db schooldirectory.Querier, title string, activityIDs []string, period string) (workbook.Sheet, error) {
	lines := []line{}
	if len(activityIDs) > 0 {
		rs, err := db.Query(ctx, `
		SELECT COALESCE(l.label, ''), COALESCE(l.line_item_type, ''), COALESCE(l.amount, 0), COALESCE(l.unit_cost, 0),
		       COALESCE(l.quantity, 0), `+ledgerColumns+`
		FROM activity_schedule_cost_line l
		JOIN activity a ON a.id = l.activity_id
		WHERE l.activity_id = ANY($1) AND a.deleted_at IS NULL
		ORDER BY l.planned_date, l.activity_id, l.id`, activityIDs)
		if err != nil {
			return workbook.Sheet{}, fmt.Errorf("budgetpage: reading the plan's cost lines: %w", err)
		}
		lines, err = pgx.CollectRows(rs, func(row pgx.CollectableRow) (line, error) {
			var l line
			err := row.Scan(&l.label, &l.lineItemType, &l.amount, &l.unitCost, &l.quantity,
				&l.activityID, &l.responsibleUser, &l.settingKey, &l.plannedDate, &l.partnerID,
				&l.activityType, &l.programmeType, &l.deliveryType,
				&l.teachers, &l.leaders, &l.others, &l.expected, &l.batchID)
			return l, err
		})
		if err != nil {
			return workbook.Sheet{}, fmt.Errorf("budgetpage: reading the plan's cost lines: %w", err)
		}
	}
	s := &Service{db: db}
	dayRates, err := s.dayRates(ctx, lines)
	if err != nil {
		return workbook.Sheet{}, err
	}
	sheet := costPlanSheet(groups(lines, dayRates), period)
	sheet.Title = title
	return sheet, nil
}

// costPlanSheet is cost_plan_sheet: the title and Grand total, the caption
// and period, then for each group a band, its headings, an item a row and
// its subtotal, and the Grand total last.
func costPlanSheet(gs []*group, period string) workbook.Sheet {
	c := rules.CostPlanSheet
	var total, staff int64
	for _, g := range gs {
		total += g.total
		staff += g.staffTotal
	}
	e, txt, num := workbook.Empty(), workbook.Text, workbook.Int
	rows := [][]workbook.Cell{
		{txt(c.Title), e, e, e, txt("Grand total"), num(total)},
		{txt(c.Caption)},
		{txt(period)},
		{},
	}
	styles := map[int]string{1: "title", 2: "caption", 3: "caption"}
	add := func(style string, cells ...workbook.Cell) {
		rows = append(rows, cells)
		if style != "" {
			styles[len(rows)] = style
		}
	}
	for _, g := range gs {
		n := len(g.activityIDs)
		word := "activities"
		if n == 1 {
			word = "activity"
		}
		add("band", txt(g.label+" · "+strconv.Itoa(n)+" "+word))
		headers := c.Headers[g.kind]
		if headers == nil {
			headers = c.Headers["standard"]
		}
		heads := make([]workbook.Cell, len(headers))
		for i, h := range headers {
			heads[i] = txt(h)
		}
		add("columns", heads...)
		sessions := g.kind == "meeting" || g.kind == "training"
		for _, r := range g.rows {
			count := len(r.dates)
			if sessions {
				count = len(r.activityIDs)
			}
			var people int64
			for _, p := range r.people {
				people += p
			}
			peopleCell := num(people)
			if people == 0 {
				peopleCell = txt("—")
			}
			staffCell := num(r.staffTotal)
			if r.vendorTotal != 0 && r.staffTotal == 0 {
				staffCell = txt("—")
			}
			add("", txt(r.item), num(int64(count)), peopleCell, num(r.rate), staffCell, num(r.total))
		}
		add("subtotal", txt(g.label+" subtotal"), e, e, e, num(g.staffTotal), num(g.total))
	}
	if len(gs) == 0 {
		add("caption", txt(c.Empty))
	}
	add("total", txt("Grand total"), e, e, e, num(staff), num(total))
	return workbook.Sheet{
		Title: c.Title, Rows: rows, RowStyles: styles,
		Widths:        []float64{44, 18, 18, 18, 20, 20},
		NumberFormats: map[int]string{4: c.Money, 5: c.Money, 6: c.Money},
		Align:         map[int]string{2: "center", 3: "center", 4: "right", 5: "right", 6: "right"},
		NoFilter:      true, NoFreeze: true,
	}
}
