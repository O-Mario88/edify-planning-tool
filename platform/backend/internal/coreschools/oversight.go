package coreschools

import (
	"context"
	"fmt"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// deliveryState is one school's delivery chain over its core visits and
// trainings of the year (CoreTeamOversightService.build_rows).
type deliveryState struct{ evidence, salesforce, ia, finance int }

// chips is the Delivery cell's flags, in the template's order.
func (d deliveryState) chips() []string {
	out := []string{}
	for _, c := range []struct {
		n    int
		word string
	}{{d.evidence, "evidence"}, {d.salesforce, "Salesforce"}, {d.ia, "IA"}, {d.finance, "finance"}} {
		if c.n > 0 {
			out = append(out, strconv.Itoa(c.n)+" "+c.word)
		}
	}
	return out
}

// oversightFacts are build_rows' three lookups over the page's schools: the
// partners supporting each, its delivery chain, and whether an ask has
// already been sent about any of them.
func (pg *page) oversightFacts(ctx context.Context, pks []string) (map[string]int, map[string]deliveryState, bool, error) {
	partners, err := counts(ctx, pg.db, `SELECT school_id, count(*) FROM partner_assignment
WHERE school_id = ANY($1) AND NOT COALESCE(status = ANY($2), FALSE) GROUP BY school_id`, pks, rules.PartnerReleased)
	if err != nil {
		return nil, nil, false, err
	}
	rows, err := pg.db.Query(ctx, `SELECT school_id,
  count(*) FILTER (WHERE evidence_status IN ('', 'pending', 'not_uploaded')),
  count(*) FILTER (WHERE status = ANY($3) AND (salesforce_activity_id IS NULL OR salesforce_activity_id = '')),
  count(*) FILTER (WHERE status = 'awaiting_ia_verification'),
  count(*) FILTER (WHERE payment_status = 'pending')
FROM activity WHERE school_id = ANY($1) AND fy = $2 AND activity_type IN ('core_visit', 'core_training') AND deleted_at IS NULL
  AND status IS DISTINCT FROM 'cancelled' GROUP BY school_id`, pks, pg.fy, rules.CompletedStatuses)
	if err != nil {
		return nil, nil, false, fmt.Errorf("coreschools: reading the delivery chain: %w", err)
	}
	delivery := map[string]deliveryState{}
	for rows.Next() {
		var id string
		var d deliveryState
		if err := rows.Scan(&id, &d.evidence, &d.salesforce, &d.ia, &d.finance); err != nil {
			rows.Close()
			return nil, nil, false, fmt.Errorf("coreschools: reading a delivery chain: %w", err)
		}
		delivery[id] = d
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, false, fmt.Errorf("coreschools: reading the delivery chain: %w", err)
	}
	var sent bool
	if err := pg.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM team_action WHERE school_id = ANY($1) AND fy = $2 AND state = ANY($3)
  AND issue_type = ANY($4))`, pks, pg.fy, rules.ActionActiveStates, rules.OversightBlockers).Scan(&sent); err != nil {
		return nil, nil, false, fmt.Errorf("coreschools: reading the asks sent: %w", err)
	}
	return partners, delivery, sent, nil
}

// oversightBlocks is partials/core_schools/team_oversight.html as the feed
// reads it: the read-only table of the team's core schools on this page and
// its count, then the programme tables. An ask already sent shows as a link
// the feed reads differently, and hands on.
func (pg *page) oversightBlocks(ctx context.Context) ([]*screensv1.PageBlock, error) {
	rows, err := pg.matrixRows(ctx, pg.shown)
	if err != nil {
		return nil, err
	}
	pks, _ := ids(pg.shown)
	partners, delivery, sent, err := pg.oversightFacts(ctx, pks)
	if err != nil {
		return nil, err
	}
	if sent {
		return nil, fmt.Errorf("an ask already sent: %w", errPassOn)
	}
	t := &screensv1.PageTable{Title: fmt.Sprintf("Team Core Schools (%d)", len(pg.all)), Subtitle: "Read-Only Team Oversight"}
	if len(rows) == 0 {
		t.EmptyMessage = "Nothing to oversee here No core schools in your team match these filters."
	} else {
		t.Columns = columnsOf("School ID", "School", "Responsible CCEO", "Assessment", "Visits", "Trainings", "Partner", "Delivery", "Blocker", "Action")
		for _, r := range rows {
			t.Rows = append(t.Rows, &screensv1.PageRow{Cells: oversightCells(r, partners[r.id], delivery[r.id])})
		}
		first := (pg.number-1)*pg.perPage + 1
		t.Footnote = fmt.Sprintf("Showing %d–%d of %d", first, first+len(pg.shown)-1, len(pg.all))
	}
	programme, err := pg.programme(ctx)
	if err != nil {
		return nil, err
	}
	return append([]*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Table{Table: t}}}, programme...), nil
}

// oversightCells is one school's row of the read-only table.
func oversightCells(r row, partner int, d deliveryState) []*screensv1.PageCell {
	code := ""
	if r.code == "" {
		code = "—"
	}
	district := r.districtName
	if district == "" {
		district = "—"
	}
	owner := &screensv1.PageCell{Text: r.staffName}
	if r.ownerID != "" {
		owner.Href = "/staff/" + r.ownerID
	}
	assessment := "Outstanding"
	if r.assessment == rules.AssessmentWords["confirmed"] {
		assessment = "Complete"
	}
	support := "—"
	if partner > 0 {
		support = strconv.Itoa(partner)
	}
	flags := strings.Join(d.chips(), " ")
	if flags == "" {
		flags = "Clear"
	}
	blocker, action := "No blocker", &screensv1.PageCell{Text: "Nothing to ask"}
	switch {
	case assessment != "Complete":
		blocker, action = "Assessment due", &screensv1.PageCell{}
	case !r.packageComplete:
		blocker, action = "Package behind", &screensv1.PageCell{}
	}
	return []*screensv1.PageCell{{Text: code}, {Text: r.name + " " + district, Href: "/schools/" + r.code}, owner, {Text: assessment},
		{Text: fmt.Sprintf("%d / %d", r.visits, r.visitsTarget)}, {Text: fmt.Sprintf("%d / %d", r.trainings, r.trainingsTarget)},
		{Text: support}, {Text: flags}, {Text: blocker}, action}
}

func columnsOf(labels ...string) []*screensv1.PageColumn {
	out := []*screensv1.PageColumn{}
	for _, l := range labels {
		out = append(out, &screensv1.PageColumn{Label: l})
	}
	return out
}
