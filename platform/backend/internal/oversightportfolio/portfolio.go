package oversightportfolio

import (
	"cmp"
	"math"
	"slices"

	"golang.org/x/text/cases"
)

// casefold is Python's str.casefold, the key the portfolio sorts names by.
func casefold(s string) string { return cases.Fold().String(s) }

// officerGroup is portfolio_service.OfficerGroup: one CCEO's schools under
// their lead, and the ones the planning filter lists.
type officerGroup struct {
	key, name string
	schools   []school
	visible   []school
}

func (o officerGroup) count() int { return len(o.schools) }

func (o officerGroup) planned() int {
	n := 0
	for _, s := range o.schools {
		if s.planned() {
			n++
		}
	}
	return n
}

// pageParam is OfficerGroup.page_param: the officer's own page parameter.
func (o officerGroup) pageParam() string {
	safe := []rune{}
	for _, r := range o.key {
		if isAlnum(r) {
			safe = append(safe, r)
		} else {
			safe = append(safe, '_')
		}
	}
	trimmed := string(safe)
	for len(trimmed) > 0 && trimmed[0] == '_' {
		trimmed = trimmed[1:]
	}
	for len(trimmed) > 0 && trimmed[len(trimmed)-1] == '_' {
		trimmed = trimmed[:len(trimmed)-1]
	}
	if trimmed == "" {
		trimmed = "officer"
	}
	return "portfolio_" + trimmed + "_page"
}

// leadGroup is portfolio_service.LeadGroup: a Programme Lead's column.
type leadGroup struct {
	key, name string
	officers  []*officerGroup
}

func (l leadGroup) count() (n int) {
	for _, o := range l.officers {
		n += o.count()
	}
	return n
}

func (l leadGroup) planned() (n int) {
	for _, o := range l.officers {
		n += o.planned()
	}
	return n
}

func (l leadGroup) budget() (n int64) {
	for _, o := range l.officers {
		for _, s := range o.schools {
			n += s.budget
		}
	}
	return n
}

// share is round(100 * part / whole) as Python rounds it (half to even on
// the float), or nil with nothing to divide.
func share(part, whole int) *int {
	if whole == 0 {
		return nil
	}
	n := int(math.RoundToEven(100 * float64(part) / float64(whole)))
	return &n
}

// totals is portfolio_service._totals.
type totals struct {
	schools, planned, activities, leads, officers int
	budget                                        int64
}

func totalsOf(rows []school) totals {
	t := totals{schools: len(rows)}
	leads, officers := map[string]bool{}, map[[2]string]bool{}
	for _, r := range rows {
		if r.planned() {
			t.planned++
		}
		t.activities += r.activities
		t.budget += r.budget
		leads[r.leadID] = true
		officers[[2]string{r.leadID, r.officerID}] = true
	}
	t.leads, t.officers = len(leads), len(officers)
	return t
}

// leadOption is one entry of _lead_options.
type leadOption struct {
	id, name string
	count    int
}

// leadOptions is _lead_options: every lead holding a school in the rows,
// with how many, the unassigned column last.
func leadOptions(rows []school) []leadOption {
	out := []leadOption{}
	at := map[[2]string]int{}
	for _, r := range rows {
		key := [2]string{r.leadID, r.leadName}
		if i, ok := at[key]; ok {
			out[i].count++
			continue
		}
		at[key] = len(out)
		out = append(out, leadOption{id: r.leadID, name: r.leadName, count: 1})
	}
	slices.SortStableFunc(out, func(a, b leadOption) int {
		return cmp.Or(boolCmp(a.id == rules.NoLeadKey, b.id == rules.NoLeadKey), cmp.Compare(casefold(a.name), casefold(b.name)))
	})
	return out
}

// districtOption is one district the rows sit in.
type districtOption struct{ id, name string }

// districtOptions is country_portfolio's districts: each (id, name) once, by
// name.
func districtOptions(rows []school) []districtOption {
	out := []districtOption{}
	seen := map[districtOption]bool{}
	for _, r := range rows {
		d := districtOption{r.districtID, r.district}
		if r.districtID == "" || seen[d] {
			continue
		}
		seen[d] = true
		out = append(out, d)
	}
	slices.SortStableFunc(out, func(a, b districtOption) int { return cmp.Compare(a.name, b.name) })
	return out
}

func boolCmp(a, b bool) int {
	switch {
	case a == b:
		return 0
	case a:
		return 1
	}
	return -1
}

// group is portfolio_service._group: rows into lead columns of officers,
// listing the rows planned asks for; an officer with nothing listed and a
// lead with no officer left are dropped.
func group(rows []school, planned string) []*leadGroup {
	leads := []*leadGroup{}
	leadAt := map[string]*leadGroup{}
	officerAt := map[[2]string]*officerGroup{}
	for _, r := range rows {
		lead := leadAt[r.leadID]
		if lead == nil {
			lead = &leadGroup{key: r.leadID, name: r.leadName}
			leadAt[r.leadID] = lead
			leads = append(leads, lead)
		}
		key := [2]string{r.leadID, r.officerID}
		officer := officerAt[key]
		if officer == nil {
			officer = &officerGroup{key: r.officerID, name: r.officerName}
			officerAt[key] = officer
			lead.officers = append(lead.officers, officer)
		}
		officer.schools = append(officer.schools, r)
		if shown(r, planned) {
			officer.visible = append(officer.visible, r)
		}
	}
	out := []*leadGroup{}
	for _, lead := range leads {
		kept := []*officerGroup{}
		for _, o := range lead.officers {
			if len(o.visible) > 0 {
				kept = append(kept, o)
			}
		}
		slices.SortStableFunc(kept, func(a, b *officerGroup) int {
			return cmp.Or(boolCmp(a.key == rules.UnassignedKey, b.key == rules.UnassignedKey), cmp.Compare(casefold(a.name), casefold(b.name)))
		})
		lead.officers = kept
		if len(kept) > 0 {
			out = append(out, lead)
		}
	}
	slices.SortStableFunc(out, func(a, b *leadGroup) int {
		return cmp.Or(boolCmp(a.key == rules.NoLeadKey, b.key == rules.NoLeadKey), cmp.Compare(casefold(a.name), casefold(b.name)))
	})
	return out
}

func shown(r school, planned string) bool {
	switch planned {
	case "planned":
		return r.planned()
	case "unplanned":
		return !r.planned()
	}
	return true
}

// portfolio is what country_portfolio and _portfolio_context hand the
// template.
type portfolio struct {
	leads     []*leadGroup
	options   []leadOption
	districts []districtOption
	totals    totals
}

// build is country_portfolio over rows read for the district asked for.
func build(rows []school, programLead, planned string) portfolio {
	p := portfolio{totals: totalsOf(rows), districts: districtOptions(rows), options: leadOptions(rows)}
	if programLead != "" && programLead != "all" && programLead != "All" {
		kept := []school{}
		for _, r := range rows {
			if r.leadID == programLead {
				kept = append(kept, r)
			}
		}
		rows = kept
	}
	p.leads = group(rows, planned)
	return p
}
