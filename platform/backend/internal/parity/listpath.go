package parity

import (
	"encoding/json"
	"strconv"
	"strings"
)

// segment is one step of a field path: a key, or an index.
type segment struct {
	key   string
	index int
}

// parsePath reads ".blocks[3].table.rows" into its steps.
func parsePath(path string) []segment {
	out := []segment{}
	for _, part := range strings.Split(strings.TrimPrefix(path, "."), ".") {
		name, rest, _ := strings.Cut(part, "[")
		if name != "" {
			out = append(out, segment{key: name, index: -1})
		}
		for rest != "" {
			n, after, _ := strings.Cut(rest, "]")
			i, err := strconv.Atoi(n)
			if err != nil {
				return nil
			}
			out = append(out, segment{index: i})
			rest = strings.TrimPrefix(after, "[")
		}
	}
	return out
}

// listAt is the list at path in a decoded answer, and a way to replace it.
func listAt(root any, path string) ([]any, func([]any), bool) {
	steps := parsePath(path)
	if len(steps) == 0 {
		return nil, nil, false
	}
	parent := root
	for _, st := range steps[:len(steps)-1] {
		switch v := parent.(type) {
		case map[string]any:
			parent = v[st.key]
		case []any:
			if st.index < 0 || st.index >= len(v) {
				return nil, nil, false
			}
			parent = v[st.index]
		default:
			return nil, nil, false
		}
	}
	last := steps[len(steps)-1]
	m, ok := parent.(map[string]any)
	if !ok || last.index >= 0 {
		return nil, nil, false
	}
	list, ok := m[last.key].([]any)
	if !ok {
		return nil, nil, false
	}
	return list, func(l []any) { m[last.key] = l }, true
}

// AcceptReordered compares each reordered field of a and b (Go's answer and
// the existing one, decoded) as a whole: when the entry accepts it, Go's
// list is replaced by the existing one, so its items compare equal, and the
// accepted difference is returned.
func (l *List) AcceptReordered(answer Answer, goRoot, oldRoot any) []Accepted {
	out := []Accepted{}
	for _, field := range l.ReorderedFields(answer) {
		mine, set, ok := listAt(goRoot, field)
		old, _, ok2 := listAt(oldRoot, field)
		if !ok || !ok2 {
			continue
		}
		a, _ := json.Marshal(mine)
		b, _ := json.Marshal(old)
		d := Diff{Field: field, Go: string(a), Existing: string(b), Text: "  " + field + ": the same rows in another order"}
		if e, ok := l.Match(answer, d); ok {
			set(old)
			out = append(out, Accepted{Diff: d, Entry: e.ID})
		}
	}
	return out
}
