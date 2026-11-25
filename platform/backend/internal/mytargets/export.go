package mytargets

import (
	"bytes"
	"context"
	"encoding/csv"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/targets"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/workbook"
)

// Export is my_targets_export_view: the reader's targets for the year as
// CSV, a heading line naming them, then each agreed priority's months,
// quarters and year (MyTargetQueryService.export_rows). The existing view
// rebuilds the ledger first; Go reads it as the page does (targets.Prepare
// answers a dirty mark in memory), writing nothing. handled is false for a
// reader the page hands on.
func (s *Service) Export(ctx context.Context, p auth.Principal, query url.Values) (string, []byte, bool, error) {
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return "", nil, true, pagegate.ErrNotAvailable
	}
	if p.InActingAppointment {
		return "", nil, false, nil
	}
	now := s.now()
	fy := strings.TrimSpace(query.Get("fy"))
	if fy == "" {
		fy = operationalFY(targets.Day(now.In(local)))
	}
	person := targets.Person{UserID: p.UserID, StaffID: p.StaffProfileID}
	roster, err := targets.Prepare(ctx, s.db, []targets.Person{person}, fy, nil)
	if errors.Is(err, targets.ErrHandOn) {
		return "", nil, false, nil
	}
	if err != nil {
		return "", nil, true, err
	}
	var name, email string
	if err := s.db.QueryRow(ctx, `SELECT COALESCE(name, ''), COALESCE(email, '') FROM "user" WHERE id = $1`, p.UserID).
		Scan(&name, &email); err != nil {
		return "", nil, true, fmt.Errorf("mytargets: reading the reader's name: %w", err)
	}
	var buf bytes.Buffer
	w := csv.NewWriter(&buf)
	w.UseCRLF = true
	write := func(cells ...string) {
		for i, c := range cells {
			cells[i] = workbook.SpreadsheetText(c)
		}
		_ = w.Write(cells)
	}
	write("My Targets — "+name, "FY "+fy, "Generated "+now.UTC().Format("2006-01-02 15:04")+" by "+email)
	write("Performance Priority", "Period", "Target", "Achieved", "%")
	tg, ach := roster.Targets(person), roster.Achieved(person)
	line := func(label, period string, t, a int) {
		pct := ""
		if t != 0 {
			pct = strconv.Itoa(round(float64(a) / float64(t) * 100))
		}
		write(label, period, strconv.Itoa(t), strconv.Itoa(a), pct)
	}
	for _, a := range roster.Areas(person) {
		for m := 1; m <= 12; m++ {
			line(a.Label, targets.MonthLabel(fy, m), tg[a.Key][m-1], ach[a.Key][m-1])
		}
		for _, q := range []string{"Q1", "Q2", "Q3", "Q4"} {
			months := targets.MonthsOfQuarter(q)
			line(a.Label, q, sum(tg[a.Key], months), sum(ach[a.Key], months))
		}
		line(a.Label, "FY Cumulative", sum(tg[a.Key], through(12)), sum(ach[a.Key], through(12)))
	}
	w.Flush()
	return "my_targets_" + fy + ".csv", buf.Bytes(), true, w.Error()
}
