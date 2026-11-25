package iapages

import (
	"context"
	"fmt"
	"math"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// AnalyticsPath is Verification Analytics: verification quality as a
// pattern rather than a record.
const AnalyticsPath = "/ia/analytics/"

// analyticsWindows are the windows (days) the page offers; any other asks
// for the default.
var analyticsWindows = []int{30, 90, 180, 365}

const defaultAnalyticsWindow = 90

// rateRow is one submitter's or partner's decisions.
type rateRow struct {
	name                string
	submitted, returned int
	rate                int
}

// verifierRow is one verifier's turnaround and sample accuracy.
type verifierRow struct {
	name     string
	verified int
	avgHours *float64
	within24 int
	sampled  int
	accuracy *int
}

// trendRow is one local month's decisions.
type trendRow struct {
	month               string
	decisions, returned int
	rate                int
}

// reasonRow is one return reason's count.
type reasonRow struct {
	reason string
	count  int
	share  int
}

// analyticsData is verification_analytics' answer, as far as the page reads
// it.
type analyticsData struct {
	window              int
	decisions, returned int
	rate                int
	reasons             []reasonRow
	trend               []trendRow
	submitters          []rateRow
	partners            []rateRow
	verifiers           []verifierRow
	lines               []decisionLine
}

// analyticsWindow is the view's window: digits naming one of the offered
// windows, else the default.
func analyticsWindow(raw string) int {
	raw = strings.TrimSpace(raw)
	if raw == "" || strings.Trim(raw, "0123456789") != "" {
		return defaultAnalyticsWindow
	}
	n, err := strconv.Atoi(raw)
	if err != nil || !slices.Contains(analyticsWindows, n) {
		return defaultAnalyticsWindow
	}
	return n
}

// pct is percentage_or_zero: round(n / d * 100), ties to even, and 0 when
// there is nothing to be a share of.
func pct(n, d int) int {
	if d == 0 {
		return 0
	}
	return int(math.RoundToEven(float64(n) / float64(d) * 100))
}

// round1 is round(x, 1).
func round1(x float64) float64 { return schooldirectory.PyRound1(x) }

// hours is _hours: the time from start to end in hours to one place, or nil
// without both.
func hours(start *time.Time, end time.Time) *float64 {
	if start == nil {
		return nil
	}
	h := round1(float64(end.Sub(*start).Microseconds()) / 1e6 / 3600)
	return &h
}

// floatText is str() of a rounded float: ".0" on a whole number.
func floatText(x float64) string {
	s := strconv.FormatFloat(x, 'f', -1, 64)
	if !strings.ContainsAny(s, ".eEIN") {
		s += ".0"
	}
	return s
}

// analytics is ia_verification_analytics_view.
func (s *Service) analytics(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	window := analyticsWindow(query.Get("window"))
	data, err := s.verificationAnalytics(ctx, p, window)
	if err != nil {
		return nil, true, err
	}
	return analyticsPage(data, query), true, nil
}

type decisionRow struct {
	verification, decision, decidedBy string
	decidedAt                         time.Time
	staff, partner                    string
	// For the export (export_rows): the work and its school.
	activityID, activityType, schoolCode string
	schoolName                           *string
	submittedToIA                        *time.Time
}

// decisionLine is one of verification_analytics' rows, as export_rows
// writes it.
type decisionLine struct {
	decidedAt, activityID, schoolCode, school, activityType string
	submitter, partner, decision, reasons, verifier         string
	turnaround                                              *float64
}

// verificationAnalytics is apps.activities.verification_analytics
// .verification_analytics: the window's decisions on live activities in the
// reader's country, their return reasons, each submitter's and partner's
// return rate, the monthly trend, and each verifier's turnaround (from the
// verification history) and sample accuracy (from the checked samples).
func (s *Service) verificationAnalytics(ctx context.Context, p auth.Principal, window int) (analyticsData, error) {
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return analyticsData{}, fmt.Errorf("iapages: resolving the reader's scope: %w", err)
	}
	since := now.Add(-time.Duration(window) * 24 * time.Hour)
	args := []any{since}
	inCountry := "TRUE"
	if scope.CountryScope && scope.Country != "" {
		args = append(args, scope.CountryIDs())
		inCountry = schoolprofile.ActivityInCountry(len(args))
	}
	reach := `SELECT a.id FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id WHERE a.deleted_at IS NULL AND ` + inCountry

	decisions, err := s.analyticsDecisions(ctx, reach, args)
	if err != nil {
		return analyticsData{}, err
	}
	verificationIDs := make([]string, 0, len(decisions))
	for _, d := range decisions {
		verificationIDs = append(verificationIDs, d.verification)
	}
	reasonsBy, err := s.returnReasons(ctx, verificationIDs)
	if err != nil {
		return analyticsData{}, err
	}

	type counter struct{ submitted, returned int }
	submitters, partners := map[string]*counter{}, map[string]*counter{}
	var submitterOrder, partnerOrder []string
	bump := func(m map[string]*counter, order *[]string, key string, returned bool) {
		c, ok := m[key]
		if !ok {
			c = &counter{}
			m[key] = c
			*order = append(*order, key)
		}
		c.submitted++
		if returned {
			c.returned++
		}
	}
	reasonCounts := map[string]int{}
	var reasonOrder []string
	months := map[string]*counter{}
	var verifierIDs []string
	addVerifier := func(id string) {
		if !slices.Contains(verifierIDs, id) {
			verifierIDs = append(verifierIDs, id)
		}
	}
	returnedTotal := 0
	for _, d := range decisions {
		returned := d.decision == "RETURN"
		key := d.staff
		if key == "" {
			key = "—"
		}
		bump(submitters, &submitterOrder, key, returned)
		if d.partner != "" {
			bump(partners, &partnerOrder, d.partner, returned)
		}
		month := d.decidedAt.In(zone).Format("2006-01")
		if months[month] == nil {
			months[month] = &counter{}
		}
		months[month].submitted++
		if returned {
			returnedTotal++
			months[month].returned++
			reasons := reasonsBy[d.verification]
			if len(reasons) == 0 {
				reasons = []string{"Unspecified"}
			}
			for _, r := range reasons {
				if _, ok := reasonCounts[r]; !ok {
					reasonOrder = append(reasonOrder, r)
				}
				reasonCounts[r]++
			}
		}
		addVerifier(d.decidedBy)
	}

	staffIDs := slices.Clone(submitterOrder)
	staff, err := staffNames(ctx, s.db, staffIDs)
	if err != nil {
		return analyticsData{}, err
	}
	partnerNames, err := livePartnerNames(ctx, s.db, partnerOrder)
	if err != nil {
		return analyticsData{}, err
	}

	turnaround, err := s.verifierTurnaround(ctx, reach, args, addVerifier)
	if err != nil {
		return analyticsData{}, err
	}
	accuracy, err := s.sampleAccuracy(ctx, reach, args, addVerifier)
	if err != nil {
		return analyticsData{}, err
	}
	verifierNames, err := accountNames(ctx, s.db, verifierIDs)
	if err != nil {
		return analyticsData{}, err
	}

	rateRows := func(order []string, m map[string]*counter, names map[string]string) []rateRow {
		out := make([]rateRow, 0, len(order))
		for _, key := range order {
			c := m[key]
			name, ok := names[key]
			if !ok {
				name = key
			}
			out = append(out, rateRow{name: name, submitted: c.submitted, returned: c.returned, rate: pct(c.returned, c.submitted)})
		}
		slices.SortStableFunc(out, func(a, b rateRow) int {
			if a.rate != b.rate {
				return b.rate - a.rate
			}
			if a.submitted != b.submitted {
				return b.submitted - a.submitted
			}
			return strings.Compare(a.name, b.name)
		})
		return out
	}

	verifiers := make([]verifierRow, 0, len(verifierIDs))
	for _, id := range verifierIDs {
		name, ok := verifierNames[id]
		if !ok {
			name = id
		}
		hrs := turnaround[id]
		v := verifierRow{name: name, verified: len(hrs)}
		if len(hrs) > 0 {
			sum, within := 0.0, 0
			for _, h := range hrs {
				sum += h
				if h <= 24 {
					within++
				}
			}
			avg := round1(sum / float64(len(hrs)))
			v.avgHours = &avg
			v.within24 = pct(within, len(hrs))
		}
		if acc, ok := accuracy[id]; ok {
			v.sampled = acc.submitted
			a := pct(acc.returned, acc.submitted)
			v.accuracy = &a
		}
		verifiers = append(verifiers, v)
	}
	slices.SortStableFunc(verifiers, func(a, b verifierRow) int {
		if a.verified != b.verified {
			return b.verified - a.verified
		}
		return strings.Compare(a.name, b.name)
	})

	monthKeys := make([]string, 0, len(months))
	for m := range months {
		monthKeys = append(monthKeys, m)
	}
	slices.Sort(monthKeys)
	trend := make([]trendRow, 0, len(monthKeys))
	for _, m := range monthKeys {
		c := months[m]
		trend = append(trend, trendRow{month: m, decisions: c.submitted, returned: c.returned, rate: pct(c.returned, c.submitted)})
	}
	reasons := make([]reasonRow, 0, len(reasonOrder))
	for _, r := range reasonOrder {
		reasons = append(reasons, reasonRow{reason: r, count: reasonCounts[r], share: pct(reasonCounts[r], returnedTotal)})
	}
	slices.SortStableFunc(reasons, func(a, b reasonRow) int { return b.count - a.count })

	lines := make([]decisionLine, 0, len(decisions))
	for _, d := range decisions {
		key := d.staff
		if key == "" {
			key = "—"
		}
		submitter, ok := staff[key]
		if !ok {
			submitter = key
		}
		verifier, ok := verifierNames[d.decidedBy]
		if !ok {
			verifier = d.decidedBy
		}
		school := "Cluster-wide"
		if d.schoolName != nil {
			school = *d.schoolName
		}
		decision := "Verified"
		if d.decision == "RETURN" {
			decision = "Returned"
		}
		lines = append(lines, decisionLine{
			decidedAt: d.decidedAt.In(zone).Format("2006-01-02 15:04"), activityID: d.activityID, schoolCode: d.schoolCode,
			school: school, activityType: myplan.TypeLabel(d.activityType), submitter: submitter,
			partner: partnerNames[d.partner], decision: decision, reasons: strings.Join(reasonsBy[d.verification], "; "),
			verifier: verifier, turnaround: hours(d.submittedToIA, d.decidedAt),
		})
	}
	return analyticsData{
		lines:  lines,
		window: window, decisions: len(decisions), returned: returnedTotal, rate: pct(returnedTotal, len(decisions)),
		reasons: reasons, trend: trend,
		submitters: rateRows(submitterOrder, submitters, staff),
		partners:   rateRows(partnerOrder, partners, partnerNames),
		verifiers:  verifiers,
	}, nil
}

// analyticsDecisions is the window's decisions in reach, newest first.
func (s *Service) analyticsDecisions(ctx context.Context, reach string, args []any) ([]decisionRow, error) {
	rows, err := s.db.Query(ctx, `
SELECT d.verification_id, d.decision, d.decided_by, d.decided_at, COALESCE(a.responsible_staff_id, ''), COALESCE(a.assigned_partner_id, ''),
       a.id, a.activity_type, COALESCE(sc.school_id, ''), sc.name, a.submitted_to_ia_at
FROM ia_verification_decision d JOIN ia_verification v ON v.id = d.verification_id JOIN activity a ON a.id = v.activity_id
LEFT JOIN school sc ON sc.id = a.school_id
WHERE d.decided_at >= $1 AND v.activity_id IN (`+reach+`)
ORDER BY d.decided_at DESC`, args...)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the verification decisions: %w", err)
	}
	defer rows.Close()
	var out []decisionRow
	for rows.Next() {
		var d decisionRow
		if err := rows.Scan(&d.verification, &d.decision, &d.decidedBy, &d.decidedAt, &d.staff, &d.partner,
			&d.activityID, &d.activityType, &d.schoolCode, &d.schoolName, &d.submittedToIA); err != nil {
			return nil, fmt.Errorf("iapages: reading the verification decisions: %w", err)
		}
		out = append(out, d)
	}
	return out, rows.Err()
}

// returnReasons is each verification's returned reasons (ReturnedReason has
// no order of its own; the function reads them unordered).
func (s *Service) returnReasons(ctx context.Context, ids []string) (map[string][]string, error) {
	out := map[string][]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := s.db.Query(ctx, `SELECT verification_id, reason FROM ia_returned_reason WHERE verification_id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the return reasons: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, reason string
		if err := rows.Scan(&id, &reason); err != nil {
			return nil, fmt.Errorf("iapages: reading the return reasons: %w", err)
		}
		out[id] = append(out[id], reason)
	}
	return out, rows.Err()
}

// verifierTurnaround is each verifier's hours from submission to
// verification, for the window's history rows in reach with a submission
// time.
func (s *Service) verifierTurnaround(ctx context.Context, reach string, args []any, seen func(string)) (map[string][]float64, error) {
	rows, err := s.db.Query(ctx, `
SELECT h.verified_by, h.verified_at, a.submitted_to_ia_at
FROM ia_verification_history h JOIN activity a ON a.id = h.activity_id
WHERE h.verified_at >= $1 AND h.activity_id IN (`+reach+`)`, args...)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the verification history: %w", err)
	}
	defer rows.Close()
	out := map[string][]float64{}
	for rows.Next() {
		var by string
		var at time.Time
		var submitted *time.Time
		if err := rows.Scan(&by, &at, &submitted); err != nil {
			return nil, fmt.Errorf("iapages: reading the verification history: %w", err)
		}
		if h := hours(submitted, at); h != nil {
			out[by] = append(out[by], *h)
		}
		seen(by)
	}
	return out, rows.Err()
}

// sampleAccuracy is each original verifier's checked samples (submitted)
// and how many were confirmed (returned), for the window's checked samples
// of activities in reach.
func (s *Service) sampleAccuracy(ctx context.Context, reach string, args []any, seen func(string)) (map[string]struct{ submitted, returned int }, error) {
	rows, err := s.db.Query(ctx, `
SELECT v.original_verifier, v.status FROM ia_verification_sample v
WHERE v.sampled_at >= $1 AND v.activity_id IN (`+reach+`) AND v.status <> 'pending'`, args...)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the sample checks: %w", err)
	}
	defer rows.Close()
	out := map[string]struct{ submitted, returned int }{}
	for rows.Next() {
		var by, status string
		if err := rows.Scan(&by, &status); err != nil {
			return nil, fmt.Errorf("iapages: reading the sample checks: %w", err)
		}
		c := out[by]
		c.submitted++
		if status == "confirmed" {
			c.returned++
		}
		out[by] = c
		seen(by)
	}
	return out, rows.Err()
}

// livePartnerNames is _partner_names: each live partner's name.
func livePartnerNames(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]string, error) {
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT id, name FROM partner WHERE id = ANY($1) AND deleted_at IS NULL`, ids)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the partners' names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("iapages: reading the partners' names: %w", err)
		}
		out[id] = name
	}
	return out, rows.Err()
}
