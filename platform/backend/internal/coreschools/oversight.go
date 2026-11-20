package coreschools

import (
	"context"
	"fmt"
	"strconv"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
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
func (pg *page) oversightFacts(ctx context.Context, pks []string) (map[string]int, map[string]deliveryState, map[[2]string]string, error) {
	partners, err := counts(ctx, pg.db, `SELECT school_id, count(*) FROM partner_assignment
WHERE school_id = ANY($1) AND NOT COALESCE(status = ANY($2), FALSE) GROUP BY school_id`, pks, rules.PartnerReleased)
	if err != nil {
		return nil, nil, nil, err
	}
	rows, err := pg.db.Query(ctx, `SELECT school_id,
  count(*) FILTER (WHERE evidence_status IN ('', 'pending', 'not_uploaded')),
  count(*) FILTER (WHERE status = ANY($3) AND (salesforce_activity_id IS NULL OR salesforce_activity_id = '')),
  count(*) FILTER (WHERE status = 'awaiting_ia_verification'),
  count(*) FILTER (WHERE payment_status = 'pending')
FROM activity WHERE school_id = ANY($1) AND fy = $2 AND activity_type IN ('core_visit', 'core_training') AND deleted_at IS NULL
  AND status IS DISTINCT FROM 'cancelled' GROUP BY school_id`, pks, pg.fy, rules.CompletedStatuses)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("coreschools: reading the delivery chain: %w", err)
	}
	delivery := map[string]deliveryState{}
	for rows.Next() {
		var id string
		var d deliveryState
		if err := rows.Scan(&id, &d.evidence, &d.salesforce, &d.ia, &d.finance); err != nil {
			rows.Close()
			return nil, nil, nil, fmt.Errorf("coreschools: reading a delivery chain: %w", err)
		}
		delivery[id] = d
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, nil, nil, fmt.Errorf("coreschools: reading the delivery chain: %w", err)
	}
	sent := map[[2]string]string{}
	asks, err := pg.db.Query(ctx, `SELECT school_id, issue_type, state FROM team_action WHERE school_id = ANY($1) AND fy = $2
  AND state = ANY($3) AND issue_type = ANY($4)`, pks, pg.fy, rules.ActionActiveStates, rules.OversightBlockers)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("coreschools: reading the asks sent: %w", err)
	}
	defer asks.Close()
	for asks.Next() {
		var school, issue, state string
		if err := asks.Scan(&school, &issue, &state); err != nil {
			return nil, nil, nil, fmt.Errorf("coreschools: reading an ask sent: %w", err)
		}
		key := [2]string{school, issue}
		if _, twice := sent[key]; twice {
			// build_rows keeps whichever the database returned last.
			return nil, nil, nil, fmt.Errorf("two open asks about one school: %w", errPassOn)
		}
		sent[key] = state
	}
	return partners, delivery, sent, asks.Err()
}

// oversightBlocks is partials/core_schools/team_oversight.html as the feed
// reads it: the read-only table of the team's core schools on this page and
// its count, then the programme tables. Two open asks about one school and
// blocker hand on.
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
	t := &screensv1.PageTable{Title: fmt.Sprintf("Team Core Schools (%d)", len(pg.all)), Subtitle: "Read-Only Team Oversight"}
	if len(rows) == 0 {
		t.EmptyMessage = "Nothing to oversee here. No core schools in your team match these filters."
	} else {
		t.Columns = columnsOf("School ID", "School", "Responsible CCEO", "Assessment", "Visits", "Trainings", "Partner", "Delivery", "Blocker", "Action")
		for _, r := range rows {
			t.Rows = append(t.Rows, &screensv1.PageRow{Cells: oversightCells(r, partners[r.id], delivery[r.id], sent)})
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
func oversightCells(r row, partner int, d deliveryState, sent map[[2]string]string) []*screensv1.PageCell {
	// The school's ID as the web fills in its {% school_code %} tag.
	code := closedschools.SchoolCode(r.code)
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
	// The ask the blocker carries is a POST form, and "Nothing to ask" a
	// caption, neither of which the feed reads; an ask already sent is a
	// link to the sent actions.
	blocker, key := "No blocker", ""
	switch {
	case assessment != "Complete":
		blocker, key = "Assessment due", rules.OversightBlockers[0]
	case !r.packageComplete:
		blocker, key = "Package behind", rules.OversightBlockers[1]
	}
	action := &screensv1.PageCell{}
	if state, ok := sent[[2]string{r.id, key}]; ok && key != "" {
		label := rules.ActionStateLabels[state]
		if label == "" {
			label = state
		}
		action.Actions = []*screensv1.PageAction{{Key: "button", Label: "View Action · " + label, Primary: true, Enabled: true, Href: "/actions/sent"}}
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
