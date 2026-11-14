package iaframework

import (
	"context"
	"fmt"
	"regexp"
	"slices"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageheader"
)

func label(choices map[string]string, value string) string {
	if l, ok := choices[value]; ok {
		return l
	}
	return value
}

func statusLabel(value string) string {
	for _, s := range rules.DefinitionStatuses {
		if s[0] == value {
			return s[1]
		}
	}
	return value
}

func isDefinitionStatus(value string) bool {
	return slices.ContainsFunc(rules.DefinitionStatuses, func(s [2]string) bool { return s[0] == value })
}

// names is _names: each account's name, any account.
func (s *Service) names(ctx context.Context, ids []string) (map[string]string, error) {
	out := map[string]string{}
	keep := []string{}
	for _, id := range ids {
		if id != "" {
			keep = append(keep, id)
		}
	}
	if len(keep) == 0 {
		return out, nil
	}
	rows, err := s.db.Query(ctx, `SELECT id, name FROM "user" WHERE id = ANY($1)`, keep)
	if err != nil {
		return nil, fmt.Errorf("iaframework: reading names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, err
		}
		out[id] = name
	}
	return out, rows.Err()
}

// authorCountries is _author_countries: each author's People record's
// country.
func (s *Service) authorCountries(ctx context.Context, ids []string) (map[string]string, error) {
	out := map[string]string{}
	rows, err := s.db.Query(ctx, `SELECT user_id, COALESCE(country, '') FROM staff_profile WHERE user_id = ANY($1) AND deleted_at IS NULL`, ids)
	if err != nil {
		return nil, fmt.Errorf("iaframework: reading the authors' countries: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, country string
		if err := rows.Scan(&id, &country); err != nil {
			return nil, err
		}
		out[id] = country
	}
	return out, rows.Err()
}

// definition is an outcome area or indicator version.
type definition struct {
	id, name, status, author, reviewer, country, key string
	version                                          int
	level, source, area                              string
	domains                                          []string
}

// definitions is definitions_register: every version of the kind, newest
// first within its code or key, filtered to a known status.
func (s *Service) definitions(ctx context.Context, kind, status string) ([]definition, map[string]string, map[string]string, error) {
	var sql string
	args := []any{}
	if kind == "area" {
		sql = `SELECT a.id, a.name, a.status, COALESCE(a.author_id, ''), COALESCE(a.reviewed_by_id, ''), '', a.code, a.version, '', '', '',
  COALESCE((SELECT array_agg(d.intervention) FROM impact_outcome_area_domain d WHERE d.area_id = a.id), '{}')
FROM impact_outcome_area a WHERE TRUE`
	} else {
		args = append(args, rules.LoanPurposeKeyPrefix)
		sql = `SELECT i.id, i.name, i.status, COALESCE(i.author_id, ''), COALESCE(i.reviewed_by_id, ''), COALESCE(i.country, ''), i.key, i.version,
  i.level, i.source, COALESCE(o.name, ''), '{}'::varchar[]
FROM impact_indicator_definition i LEFT JOIN impact_outcome_area o ON o.id = i.outcome_area_id WHERE i.key NOT LIKE $1 || '%'`
	}
	alias := map[string]string{"area": "a", "indicator": "i"}[kind]
	if isDefinitionStatus(status) {
		args = append(args, status)
		sql += fmt.Sprintf(" AND %s.status = $%d", alias, len(args))
	}
	order := map[string]string{"area": " ORDER BY a.code, a.version DESC", "indicator": " ORDER BY i.key, i.version DESC"}[kind]
	rows, err := s.db.Query(ctx, sql+order, args...)
	if err != nil {
		return nil, nil, nil, fmt.Errorf("iaframework: reading the definitions: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (definition, error) {
		var d definition
		return d, r.Scan(&d.id, &d.name, &d.status, &d.author, &d.reviewer, &d.country, &d.key, &d.version, &d.level, &d.source, &d.area, &d.domains)
	})
	if err != nil {
		return nil, nil, nil, fmt.Errorf("iaframework: reading the definitions: %w", err)
	}
	authors, people := []string{}, []string{}
	for _, d := range list {
		authors = append(authors, d.author)
		people = append(people, d.author, d.reviewer)
	}
	countries, err := s.authorCountries(ctx, authors)
	if err != nil {
		return nil, nil, nil, err
	}
	names, err := s.names(ctx, people)
	if err != nil {
		return nil, nil, nil, err
	}
	return list, countries, names, nil
}

func nameOr(names map[string]string, id string) string {
	if n, ok := names[id]; ok {
		return n
	}
	return "—"
}

// definitionActions are a definition row's Open, Submit and Review.
func definitionActions(ctx context.Context, r reader, res *resolver, d definition, country, open, singular string) (*screensv1.PageCell, error) {
	pairs := [][2]string{{"Open", Path + open + "/" + d.id + "/"}}
	if r.author && slices.Contains(rules.PendingDefinitionStatuses, d.status) && d.author == r.id {
		pairs = append(pairs, [2]string{"Submit", Path + singular + "/" + d.id + "/submit"})
	}
	if d.status == "in_review" {
		ok, err := res.may(ctx, d.author, country)
		if err != nil {
			return nil, err
		}
		if ok {
			pairs = append(pairs, [2]string{"Review", Path + singular + "/" + d.id + "/review"})
		}
	}
	return actions(pairs...), nil
}

func (s *Service) areasTab(ctx context.Context, r reader, res *resolver, status string) (tab, error) {
	list, countries, names, err := s.definitions(ctx, "area", status)
	if err != nil {
		return tab{}, err
	}
	t := tab{title: "Outcome areas", columns: []string{"Outcome area", "SSA domains (proxy)", "Version", "Status", "Written by", "Reviewed by"},
		emptyTitle:  "No outcome areas defined",
		emptyBody:   "An outcome area names a dimension of transformation Edify measures and the SSA domains read as its school-level proxy.",
		filters:     []*screensv1.PageFilter{choice("status", "Status", "Every status", status, rules.DefinitionStatuses)},
		description: "The long-term change in partner schools Edify exists for. SSA domains are school-level proxies for each area, never proof of it on their own."}
	for _, d := range list {
		domains := []string{}
		for _, i := range d.domains {
			domains = append(domains, label(rules.InterventionAbbreviations, i))
		}
		act, err := definitionActions(ctx, r, res, d, countries[d.author], "areas", "area")
		if err != nil {
			return tab{}, err
		}
		t.rows = append(t.rows, []*screensv1.PageCell{
			cell(d.name), cell(strings.Join(domains, ", ")), cell("v" + strconv.Itoa(d.version)), cell(statusLabel(d.status)),
			cell(nameOr(names, d.author)), cell(nameOr(names, d.reviewer)), act,
		})
	}
	if r.author {
		t.actions = []*screensv1.PageAction{pageheader.Drawer("New outcome area", Path+"areas/new", false)}
		var missing bool
		if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM unnest($1::varchar[]) c WHERE c NOT IN (SELECT code FROM impact_outcome_area))`, rules.ProposedAreaCodes).Scan(&missing); err != nil {
			return tab{}, fmt.Errorf("iaframework: reading the proposed areas: %w", err)
		}
		if missing {
			t.noticeTone = "info"
			t.notice = "Three outcome areas are proposed for review: spiritual formation (CB, WOG), educational quality (LE, TE, LSHIP) and sustainability (FH, GR, ENR). Draft them, adjust the definitions, and submit each for a second officer's review."
		}
	}
	return t, nil
}

func (s *Service) indicatorsTab(ctx context.Context, r reader, res *resolver, status string) (tab, error) {
	list, countries, names, err := s.definitions(ctx, "indicator", status)
	if err != nil {
		return tab{}, err
	}
	t := tab{title: "Indicators", columns: []string{"Indicator", "Level", "Outcome area", "Source", "Version", "Scope", "Status", "Reviewed by"},
		emptyTitle:  "No indicators defined",
		emptyBody:   "Each indicator states what is counted, over which population and denominator, from which baseline, how often, and what it cannot show.",
		filters:     []*screensv1.PageFilter{choice("status", "Status", "Every status", status, rules.DefinitionStatuses)},
		description: "Measures of success, versioned append-only: a changed definition is a new version, so earlier results keep the definition they were measured by."}
	for _, d := range list {
		country := d.country
		if country == "" {
			country = countries[d.author]
		}
		act, err := definitionActions(ctx, r, res, d, country, "indicators", "indicator")
		if err != nil {
			return tab{}, err
		}
		scope := d.country
		if scope == "" {
			scope = "All countries"
		}
		t.rows = append(t.rows, []*screensv1.PageCell{
			cell(d.name), cell(label(rules.Levels, d.level)), cell(d.area), cell(label(rules.Sources, d.source)),
			cell("v" + strconv.Itoa(d.version)), cell(scope), cell(statusLabel(d.status)), cell(nameOr(names, d.reviewer)), act,
		})
	}
	if r.author {
		t.actions = []*screensv1.PageAction{pageheader.Drawer("New indicator", Path+"indicators/new", false)}
	}
	return t, nil
}

var nonSlug = regexp.MustCompile(`[^a-z0-9]+`)

// slug is framework._slug.
func slug(text string) string {
	out := strings.Trim(nonSlug.ReplaceAllString(strings.ToLower(text), "-"), "-")
	if len(out) > 80 {
		out = out[:80]
	}
	return out
}

func (s *Service) purposesTab(ctx context.Context, r reader, res *resolver) (tab, error) {
	t := tab{title: "Loan purposes", columns: []string{"Loan purpose", "Kind", "Impact indicators", "Verification", "Follow-up", "Countries", "Status"},
		emptyTitle: "No active loan purposes", emptyBody: "Loan purposes are created through the lending purpose request.",
		notice:      "A new purpose keeps its own route (lending partner request, BT review, IA definition, Country Director approval). For a purpose already in use, IA defines its measurement here and a second reviewer approves it.",
		description: "What each lending purpose is measured by: impact indicators, the evidence required, how it is verified and when it is followed up."}
	type purpose struct {
		id, code, label, verification string
		edtech, complete              bool
		followUp                      int
		indicators, countries         []string
	}
	rows, err := s.db.Query(ctx, `SELECT id, code, label, COALESCE(verification_method, ''), is_edtech, measurement_profile_complete, follow_up_days,
  impact_indicators, applicable_countries FROM bt_loan_purpose WHERE active ORDER BY label`)
	if err != nil {
		return tab{}, fmt.Errorf("iaframework: reading the loan purposes: %w", err)
	}
	purposes, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (purpose, error) {
		var p purpose
		return p, row.Scan(&p.id, &p.code, &p.label, &p.verification, &p.edtech, &p.complete, &p.followUp, &p.indicators, &p.countries)
	})
	if err != nil {
		return tab{}, fmt.Errorf("iaframework: reading the loan purposes: %w", err)
	}
	keys := make([]string, len(purposes))
	for i, p := range purposes {
		keys[i] = slug(rules.LoanPurposeKeyPrefix + p.code)
	}
	type record struct {
		id, key, status, author, country string
		version                          int
	}
	rows, err = s.db.Query(ctx, `SELECT DISTINCT ON (key) id, key, status, COALESCE(author_id, ''), COALESCE(country, ''), version FROM impact_indicator_definition
WHERE key = ANY($1) ORDER BY key, version DESC`, keys)
	if err != nil {
		return tab{}, fmt.Errorf("iaframework: reading the purposes' definitions: %w", err)
	}
	records, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (record, error) {
		var x record
		return x, row.Scan(&x.id, &x.key, &x.status, &x.author, &x.country, &x.version)
	})
	if err != nil {
		return tab{}, fmt.Errorf("iaframework: reading the purposes' definitions: %w", err)
	}
	latest := map[string]record{}
	authors := []string{}
	for _, x := range records {
		latest[x.key] = x
		authors = append(authors, x.author)
	}
	countries, err := s.authorCountries(ctx, authors)
	if err != nil {
		return tab{}, err
	}
	for i, p := range purposes {
		applicable := []string{}
		for _, c := range p.countries {
			if c != "" {
				applicable = append(applicable, c)
			}
		}
		state := "Measurement not defined"
		if p.complete {
			state = "Defined"
		}
		rec, has := latest[keys[i]]
		if has && rec.status != "approved" {
			state += " · v" + strconv.Itoa(rec.version) + " " + strings.ToLower(statusLabel(rec.status))
		}
		pairs := [][2]string{}
		inCountry := len(applicable) == 0 || r.country == "" || slices.Contains(applicable, r.country)
		if r.author && inCountry {
			pairs = append(pairs, [2]string{"Define measurement", Path + "purposes/" + p.id + "/"})
		}
		if has && rec.status == "in_review" {
			country := rec.country
			if country == "" {
				country = countries[rec.author]
			}
			ok, err := res.may(ctx, rec.author, country)
			if err != nil {
				return tab{}, err
			}
			if ok {
				pairs = append(pairs, [2]string{"Review", Path + "indicator/" + rec.id + "/review"})
			}
		}
		if has && r.author && slices.Contains(rules.PendingDefinitionStatuses, rec.status) && rec.author == r.id {
			pairs = append(pairs, [2]string{"Submit", Path + "indicator/" + rec.id + "/submit"})
		}
		kind := "Lending"
		if p.edtech {
			kind = "EdTech"
		}
		countriesText := strings.Join(applicable, ", ")
		if countriesText == "" {
			countriesText = "All countries"
		}
		t.rows = append(t.rows, []*screensv1.PageCell{
			cell(p.label), cell(kind), cell(strings.Join(p.indicators, ", ")), cell(p.verification),
			cell(strconv.Itoa(p.followUp) + " days"), cell(countriesText), cell(state), actions(pairs...),
		})
	}
	return t, nil
}
