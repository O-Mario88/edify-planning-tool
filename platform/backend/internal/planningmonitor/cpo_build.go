package planningmonitor

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
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// cpoReadFilters is service.read_filters: the page's filters from its query,
// old period links keeping their meaning and anything unknown dropped.
func cpoReadFilters(q map[string]string, today time.Time) cpoFilters {
	get := func(name string) string { return strings.TrimSpace(q[name]) }
	operational := strconv.Itoa(cpoOperationalFY(today))
	fy := get("fy")
	if fy == "" || strings.IndexFunc(fy, func(r rune) bool { return r < '0' || r > '9' }) >= 0 {
		fy = operational
	}
	month := 0
	if m, err := strconv.Atoi(get("month")); err == nil && m >= 1 && m <= 12 && strings.IndexFunc(get("month"), func(r rune) bool { return r < '0' || r > '9' }) < 0 {
		month = m
	}
	quarter := strings.ToUpper(get("quarter"))
	if !slices.Contains([]string{"Q1", "Q2", "Q3", "Q4"}, quarter) {
		quarter = ""
	}
	period := strings.ToLower(get("period"))
	if !slices.Contains([]string{"fy", "quarter", "month", "week"}, period) {
		switch {
		case month > 0:
			period = "month"
		case quarter != "":
			period = "quarter"
		default:
			period = "fy"
		}
	}
	week := get("week")
	if period == "quarter" && quarter == "" {
		quarter = "Q" + strconv.Itoa((int(today.Month())+2)%12/3+1)
	}
	if period == "month" && month == 0 {
		month = int(today.Month())
	}
	if period == "week" && week == "" {
		y, w := today.ISOWeek()
		week = fmt.Sprintf("%04d-W%02d", y, w)
	}
	pick := func(name string, allowed [][2]string) string {
		v := get(name)
		if allowed != nil && !slices.ContainsFunc(allowed, func(o [2]string) bool { return o[0] == v }) {
			return ""
		}
		if v == "all" || v == "All" {
			return ""
		}
		return v
	}
	page := rules.CountryOversight.Page
	f := cpoFilters{fy: fy, period: period, region: pick("region", nil), district: pick("district", nil),
		programLead: pick("program_lead", nil), cceo: pick("cceo", nil), schoolType: pick("school_type", page.TypeOptions),
		channel: pick("channel", page.ChannelOptions), partner: pick("partner", nil),
		clusterStatus: pick("cluster_status", page.ClusterOptions), planningStatus: pick("planning_status", page.StatusOptions)}
	if f.schoolType == "" && pick("family", nil) == "core_family" {
		f.schoolType = "core"
	}
	switch period {
	case "quarter":
		f.quarter = quarter
	case "month":
		f.month = month
	case "week":
		f.week = week
	}
	return f
}

// cpoNames is service._names: the names of the records a dataset names.
func cpoNames(ctx context.Context, db schooldirectory.Querier, table string, ids []string) ([]cpoOption, error) {
	if len(ids) == 0 {
		return nil, nil
	}
	rows, err := db.Query(ctx, `SELECT id, name FROM `+table+` WHERE id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: %s names: %w", table, err)
	}
	defer rows.Close()
	names := map[string]string{}
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, err
		}
		names[id] = name
	}
	return sortedOptions(names), rows.Err()
}

// cpoOptions is country_oversight_views._filter_options.
func cpoOptions(ctx context.Context, db schooldirectory.Querier, snap *cpoSnapshot, today time.Time) (cpoPageOptions, error) {
	o := cpoPageOptions{}
	last := max(cpoOperationalFY(today)+1, 2027)
	for y := 2025; y <= last; y++ {
		o.years = append(o.years, strconv.Itoa(y))
	}
	partners, regions, districts := map[string]bool{}, map[string]bool{}, map[string]bool{}
	for _, s := range snap.data.schools {
		for p := range s.partners {
			if p != "" {
				partners[p] = true
			}
		}
		regions[s.regionID] = true
		districts[s.districtID] = true
	}
	keys := func(m map[string]bool) []string {
		out := []string{}
		for k := range m {
			if k != "" {
				out = append(out, k)
			}
		}
		return out
	}
	var err error
	if o.partners, err = cpoNames(ctx, db, "partner", keys(partners)); err != nil {
		return o, err
	}
	if o.regions, err = cpoNames(ctx, db, "region", keys(regions)); err != nil {
		return o, err
	}
	if o.districts, err = cpoNames(ctx, db, "district", keys(districts)); err != nil {
		return o, err
	}
	o.leads = pairs(snap.leads)
	type owner struct{ key, name, lead, kind string }
	byKey, order := map[string]owner{}, []string{}
	put := func(w owner) {
		if _, ok := byKey[w.key]; !ok {
			order = append(order, w.key)
		}
		byKey[w.key] = w
	}
	for _, r := range snap.roster {
		put(owner{r.key, r.name, r.leadKey, ownerKind(r.key, r.role)})
	}
	dataKeys := []string{}
	for k := range snap.data.owners {
		dataKeys = append(dataKeys, k)
	}
	sort.Strings(dataKeys)
	for _, k := range dataKeys {
		d := snap.data.owners[k]
		put(owner{d.key, d.name, d.leadKey, ownerKind(d.key, d.role)})
	}
	owners := []owner{}
	for _, k := range order {
		if w := byKey[k]; w.kind != "unassigned" {
			owners = append(owners, w)
		}
	}
	sort.SliceStable(owners, func(i, j int) bool { return strings.ToLower(owners[i].name) < strings.ToLower(owners[j].name) })
	for _, w := range owners {
		if snap.filters.programLead == "" || w.lead == snap.filters.programLead {
			label := w.name
			if w.kind == "pl_personal" {
				label += " (Programme Lead)"
			}
			o.owners = append(o.owners, cpoOption{w.key, label})
		}
	}
	return o, nil
}

// CountryOversightPage is the planning-coverage dashboard as the existing
// page draws it (coverage_page and page.html, read by the feed): the lens
// tabs, the filters, the cards, the school types, the four charts, the
// drill-down and the open follow-ups.
func CountryOversightPage(ctx context.Context, db schooldirectory.Querier, p auth.Principal, q map[string]string,
	now time.Time) ([]*screensv1.PageBlock, error) {
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	l := now.In(cpoLocation)
	today := date(l.Year(), l.Month(), l.Day())
	f := cpoReadFilters(q, today)
	snap, err := buildCPOSnapshot(ctx, db, scope, f, today)
	if err != nil {
		return nil, err
	}
	options, err := cpoOptions(ctx, db, snap, today)
	if err != nil {
		return nil, err
	}
	country, err := cpoCountry(ctx, db, scope)
	if err != nil {
		return nil, err
	}
	count, items, err := cpoFollowUps(ctx, db, f.fy, cpoLocation)
	if err != nil {
		return nil, err
	}
	reader := cpoReaderFor(p.ActiveRole, slices.Contains(rules.CountryOversight.Page.ExportRoles, p.ActiveRole))
	blocks := []*screensv1.PageBlock{cpoLensTabs(), cpoFilterBlock(f, options)}
	blocks = append(blocks, cpoNotices(snap)...)
	blocks = append(blocks, cpoCards(snap))
	blocks = append(blocks, cpoTypeBlocks(snap)...)
	blocks = append(blocks, cpoChartBlocks(snap)...)
	blocks = append(blocks, drillBlocks(snap, country, reader, count)...)
	blocks = append(blocks, followUpsPanel(f.query(nil), reader, count, items)...)
	return blocks, nil
}
