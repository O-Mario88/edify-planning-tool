package parity

import (
	"encoding/json"
	"fmt"
	"slices"
)

// RowPair is a row only the existing application's copy holds and a row
// only Go's holds that differ only as intended.
type RowPair struct {
	Existing, Go string
	Accepted     []Accepted
}

// PairRows pairs, for one table of a save scenario (a.Question is the
// table), each row only the existing copy holds with a row only Go's copy
// holds when the two are the same in every column but those whose two
// values an entry accepts (Field is the column). Rows are JSON objects, as
// cmd/shadow prints them. Rows left unpaired still differ.
func (l *List) PairRows(a Answer, onlyExisting, onlyGo []string) (pairs []RowPair, restExisting, restGo []string) {
	used := make([]bool, len(onlyGo))
	for _, old := range onlyExisting {
		paired := false
		for j, row := range onlyGo {
			if used[j] {
				continue
			}
			if accepted, ok := l.rowsDifferAsIntended(a, old, row); ok {
				used[j], paired = true, true
				pairs = append(pairs, RowPair{Existing: old, Go: row, Accepted: accepted})
				break
			}
		}
		if !paired {
			restExisting = append(restExisting, old)
		}
	}
	for j, row := range onlyGo {
		if !used[j] {
			restGo = append(restGo, row)
		}
	}
	return pairs, restExisting, restGo
}

// rowsDifferAsIntended says whether every column the two rows differ in is
// accepted by an entry, and at least one differs.
func (l *List) rowsDifferAsIntended(a Answer, existingRow, goRow string) ([]Accepted, bool) {
	var old, mine map[string]any
	if json.Unmarshal([]byte(existingRow), &old) != nil || json.Unmarshal([]byte(goRow), &mine) != nil {
		return nil, false
	}
	columns := []string{}
	for c := range old {
		columns = append(columns, c)
	}
	for c := range mine {
		if _, ok := old[c]; !ok {
			columns = append(columns, c)
		}
	}
	slices.Sort(columns)
	accepted := []Accepted{}
	for _, c := range columns {
		ov, inOld := old[c]
		gv, inGo := mine[c]
		if inOld && inGo && valueText(ov) == valueText(gv) {
			continue
		}
		if !inOld || !inGo {
			return nil, false
		}
		d := Diff{Field: c, Existing: valueText(ov), Go: valueText(gv)}
		d.Text = fmt.Sprintf("  %s.%s: go %s, existing %s", a.Question, c, d.Go, d.Existing)
		e, ok := l.Match(a, d)
		if !ok {
			return nil, false
		}
		accepted = append(accepted, Accepted{Diff: d, Entry: e.ID})
	}
	return accepted, len(accepted) > 0
}

// valueText is a column's value as text: a string as it is, anything else
// as JSON ("null", "3", "true", "[1,2]").
func valueText(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	raw, _ := json.Marshal(v)
	return string(raw)
}
