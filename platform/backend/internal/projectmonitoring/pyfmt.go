package projectmonitoring

import (
	"errors"
	"strconv"
	"strings"
	"time"
	"unicode"
)

// errUnread is data this piece cannot answer exactly; the page is passed on
// to the existing application rather than guessed.
var errUnread = errors.New("projectmonitoring: data this piece does not read")

// pyRound is round(x, digits): correctly rounded from the exact binary
// value, ties to even.
func pyRound(x float64, digits int) float64 {
	v, _ := strconv.ParseFloat(strconv.FormatFloat(x, 'f', digits, 64), 64)
	return v
}

// floatStr is str() of a float: the shortest text that reads back as it,
// with ".0" on a whole number.
func floatStr(x float64) string {
	s := strconv.FormatFloat(x, 'f', -1, 64)
	if !strings.ContainsAny(s, ".eEIN") {
		s += ".0"
	}
	return s
}

// intcomma is Django's |intcomma of an int.
func intcomma(n int) string {
	s := strconv.Itoa(n)
	neg := strings.HasPrefix(s, "-")
	s = strings.TrimPrefix(s, "-")
	var b strings.Builder
	for i, r := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteRune(r)
	}
	if neg {
		return "-" + b.String()
	}
	return b.String()
}

// dayLabel is Django's |date:"j M Y".
func dayLabel(t time.Time) string { return t.Format("2 Jan 2006") }

// pyTitle is str.title(): each run of letters starts upper case and goes on
// lower case.
func pyTitle(s string) string {
	var b strings.Builder
	prev := false
	for _, r := range s {
		if unicode.IsLetter(r) {
			if prev {
				b.WriteRune(unicode.ToLower(r))
			} else {
				b.WriteRune(unicode.ToUpper(r))
			}
			prev = true
			continue
		}
		prev = false
		b.WriteRune(r)
	}
	return b.String()
}

// plural is Django's |pluralize: "s" unless the count is one.
func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}
