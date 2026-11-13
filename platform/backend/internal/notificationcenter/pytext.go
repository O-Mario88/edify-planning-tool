package notificationcenter

import (
	"math"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"
)

// pyTitle is Python's str.title(): a letter after a cased letter is lower
// case, any other letter title case.
func pyTitle(s string) string {
	var b strings.Builder
	previousCased := false
	for _, r := range s {
		if previousCased {
			b.WriteRune(unicode.ToLower(r))
		} else {
			b.WriteRune(unicode.ToTitle(r))
		}
		previousCased = unicode.IsUpper(r) || unicode.IsLower(r) || unicode.IsTitle(r)
	}
	return b.String()
}

var (
	apostrophe  = regexp.MustCompile(`[a-z]'[A-Z]`)
	digitLetter = regexp.MustCompile(`\d[A-Z]`)
)

// djangoTitle is Django's |title: str.title(), then a letter after an
// apostrophe and one after a digit kept lower case.
func djangoTitle(s string) string {
	t := apostrophe.ReplaceAllStringFunc(pyTitle(s), strings.ToLower)
	return digitLetter.ReplaceAllStringFunc(t, strings.ToLower)
}

// pageAsked is the page the address asks for, read as the existing pager
// reads it (`max(1, int(raw or 1))`, a value int() refuses being 1). A
// number past int32 stands for "beyond the last page".
func pageAsked(raw string) int {
	text := strings.TrimSpace(raw)
	if text == "" {
		return 1
	}
	sign := 1
	switch text[0] {
	case '+':
		text = text[1:]
	case '-':
		sign, text = -1, text[1:]
	}
	// int() takes single underscores between digits ("1_0" is 10).
	if text == "" || text[0] == '_' || text[len(text)-1] == '_' || strings.Contains(text, "__") {
		return 1
	}
	digits := strings.ReplaceAll(text, "_", "")
	for _, r := range digits {
		if r < '0' || r > '9' {
			return 1
		}
	}
	n, err := strconv.ParseInt(digits, 10, 64)
	if err != nil || n > math.MaxInt32 {
		n = math.MaxInt32
	}
	if sign < 0 || n < 1 {
		return 1
	}
	return int(n)
}

// likeContains is Django's icontains pattern on PostgreSQL: the value with
// its LIKE wildcards and backslashes escaped, between two %.
func likeContains(value string) string {
	escaped := strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`).Replace(value)
	return "%" + escaped + "%"
}

// eastAfrica is the existing application's TIME_ZONE (Africa/Nairobi).
var eastAfrica = loadZone("Africa/Nairobi")

func loadZone(name string) *time.Location {
	zone, err := time.LoadLocation(name)
	if err != nil {
		// Three hours east of UTC, all year, since 1960.
		return time.FixedZone("EAT", 3*60*60)
	}
	return zone
}

// createdLabel is `created_at|date:"M j, Y H:i"` in the application's time
// zone ("Nov 3, 2026 14:05").
func createdLabel(at time.Time) string {
	return at.In(eastAfrica).Format("Jan 2, 2006 15:04")
}

// pageWindow is apps.core.pagination.make_pagination_window(current, total,
// window_size=1), the shared table pager's page numbers, 0 for a gap.
func pageWindow(current, total int) []int32 {
	const windowSize = 1
	pages := []int32{}
	if total <= 7 {
		for p := 1; p <= total; p++ {
			pages = append(pages, int32(p)) //nolint:gosec // page numbers
		}
		return pages
	}
	pages = append(pages, 1)
	if current-windowSize > 2 {
		pages = append(pages, 0)
		for p := current - windowSize; p < current; p++ {
			pages = append(pages, int32(p)) //nolint:gosec // page numbers
		}
	} else {
		for p := 2; p < current; p++ {
			pages = append(pages, int32(p)) //nolint:gosec // page numbers
		}
	}
	if current != 1 {
		pages = append(pages, int32(current)) //nolint:gosec // page numbers
	}
	if current+windowSize < total-1 {
		for p := current + 1; p <= current+windowSize; p++ {
			pages = append(pages, int32(p)) //nolint:gosec // page numbers
		}
		pages = append(pages, 0)
	} else {
		for p := current + 1; p < total; p++ {
			pages = append(pages, int32(p)) //nolint:gosec // page numbers
		}
	}
	if pages[len(pages)-1] != int32(total) { //nolint:gosec // page numbers
		pages = append(pages, int32(total)) //nolint:gosec // page numbers
	}
	return pages
}
