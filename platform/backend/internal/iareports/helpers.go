package iareports

import (
	"encoding/json"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iaredaction"
)

const (
	suppressed      = iaredaction.Suppressed
	redactionSchool = "school"
)

// str is a stored snapshot value as text.
func str(v any) string {
	switch x := v.(type) {
	case nil:
		return ""
	case string:
		return x
	case json.Number:
		return x.String()
	}
	b, _ := json.Marshal(v)
	return string(b)
}

func object(v any) map[string]any {
	m, _ := v.(map[string]any)
	if m == nil {
		return map[string]any{}
	}
	return m
}

func getOr(m map[string]any, key string, fallback any) any {
	if v, ok := m[key]; ok {
		return v
	}
	return fallback
}
