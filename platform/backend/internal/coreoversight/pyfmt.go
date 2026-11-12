package coreoversight

import (
	"math"
	"math/big"
	"strconv"
	"strings"
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

// floatStr is str() of a float the page has rounded: the shortest text that
// reads back as it, with ".0" on a whole number.
func floatStr(x float64) string {
	s := strconv.FormatFloat(x, 'f', -1, 64)
	if !strings.ContainsAny(s, ".eEIN") {
		s += ".0"
	}
	return s
}

// signedFloat is the template's {% if x > 0 %}+{% endif %}{{ x }}.
func signedFloat(x float64) string {
	if x > 0 {
		return "+" + floatStr(x)
	}
	return floatStr(x)
}

// signedInt is the same for a whole number.
func signedInt(n int) string {
	if n > 0 {
		return "+" + strconv.Itoa(n)
	}
	return strconv.Itoa(n)
}

// decimalOne is {{ d|floatformat:1 }} of a Decimal column's text: rounded
// half away from zero to one place, no sign on a zero.
func decimalOne(text string) string {
	d, ok := new(big.Rat).SetString(strings.TrimSpace(text))
	if !ok {
		return text
	}
	negative := d.Sign() < 0
	tenths := new(big.Rat).Mul(new(big.Rat).Abs(d), big.NewRat(10, 1))
	whole := new(big.Int).Quo(tenths.Num(), tenths.Denom())
	rest := new(big.Rat).Sub(tenths, new(big.Rat).SetInt(whole))
	if rest.Cmp(big.NewRat(1, 2)) >= 0 {
		whole.Add(whole, big.NewInt(1))
	}
	digits := whole.String()
	if len(digits) < 2 {
		digits = "0" + digits
	}
	out := digits[:len(digits)-1] + "." + digits[len(digits)-1:]
	if negative && whole.Sign() != 0 {
		out = "-" + out
	}
	return out
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

// pluralS is the template's |pluralize.
func pluralS(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}
