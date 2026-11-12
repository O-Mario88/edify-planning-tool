package clusteroversight

import (
	"math"
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The existing page's arithmetic and wording are Python's; these are its
// operations, so a figure rounds and reads here as it does there.

// pyRound is round(x, digits): correctly rounded from the exact binary
// value, ties to even.
func pyRound(x float64, digits int) float64 {
	v, _ := strconv.ParseFloat(strconv.FormatFloat(x, 'f', digits, 64), 64)
	return v
}

// pyRoundInt is round(x) of a float: to the nearest whole number, ties to
// even.
func pyRoundInt(x float64) int { return int(math.RoundToEven(x)) }

// pySum is sum() of floats.
func pySum(values []float64) float64 { return schooldirectory.PySum(values) }

// mean is sum(values) / len(values); the caller has checked there are some.
func mean(values []float64) float64 { return pySum(values) / float64(len(values)) }

// fixed is f"{x:.{digits}f}".
func fixed(x float64, digits int) string { return strconv.FormatFloat(x, 'f', digits, 64) }

// floatStr is str() of a float the page has rounded: the shortest text that
// reads back as it, with ".0" on a whole number.
func floatStr(x float64) string {
	s := strconv.FormatFloat(x, 'f', -1, 64)
	if !strings.ContainsAny(s, ".eEIN") {
		s += ".0"
	}
	return s
}

// signed is workspace.signed: a plus before a rise, the figure to digits
// places, and its suffix.
func signed(value float64, digits int, suffix string) string {
	plus := ""
	if value > 0 {
		plus = "+"
	}
	return plus + fixed(value, digits) + suffix
}

// commas is f"{n:,}".
func commas(n int) string {
	s := strconv.Itoa(n)
	sign := ""
	if n < 0 {
		sign, s = "-", s[1:]
	}
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	return sign + s
}

func replaceUnderscores(s string) string { return strings.ReplaceAll(s, "_", " ") }

// pyTitle is str.title(): each run of letters starts with a capital and
// continues in lower case.
func pyTitle(s string) string {
	out := strings.Builder{}
	inWord := false
	for _, r := range s {
		switch {
		case !unicode.IsLetter(r):
			inWord = false
			out.WriteRune(r)
		case inWord:
			out.WriteRune(unicode.ToLower(r))
		default:
			inWord = true
			out.WriteRune(unicode.ToTitle(r))
		}
	}
	return out.String()
}

// collapse is the feed's reading of a text: its whitespace run together.
func collapse(text string) string { return strings.Join(strings.Fields(text), " ") }

// plural is the page's f"{n} cluster{” if n == 1 else 's'}".
func plural(n int, word string) string {
	if n == 1 {
		return strconv.Itoa(n) + " " + word
	}
	return strconv.Itoa(n) + " " + word + "s"
}

// A day is a date as "2026-04-22", or "" for none; days in this form sort
// as dates, and none sorts first, as the page's `held_on or date.min` does.

// daysBetween is (end - start).days.
func daysBetween(start, end string) (int, bool) {
	from, err1 := time.Parse(time.DateOnly, start)
	to, err2 := time.Parse(time.DateOnly, end)
	if err1 != nil || err2 != nil {
		return 0, false
	}
	return int(math.Round(to.Sub(from).Hours() / 24)), true
}
