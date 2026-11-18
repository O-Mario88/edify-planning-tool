// Package pynum reads numbers from text as the existing application's
// Python does.
package pynum

import (
	"strconv"
	"strings"
)

// Int is Python's int() of a text: surrounding space, one sign and single
// underscores between digits allowed.
func Int(text string) (int, bool) {
	s := strings.TrimSpace(text)
	sign := 1
	if strings.HasPrefix(s, "+") || strings.HasPrefix(s, "-") {
		if s[0] == '-' {
			sign = -1
		}
		s = s[1:]
	}
	if s == "" || s[0] == '_' || s[len(s)-1] == '_' || strings.Contains(s, "__") {
		return 0, false
	}
	digits := strings.ReplaceAll(s, "_", "")
	if strings.ContainsAny(digits, "+-") {
		return 0, false
	}
	n, err := strconv.Atoi(digits)
	if err != nil {
		return 0, false
	}
	return sign * n, true
}
