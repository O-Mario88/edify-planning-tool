package closedschools

import (
	"math"
	"strconv"
	"strings"
	"unicode"

	"golang.org/x/text/unicode/norm"
)

// pySpace is Python's str.isspace for one character: Unicode white space and
// the four information separators.
func pySpace(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) }

// collapse is the feed's reading of a text: its whitespace run together.
func collapse(text string) string { return strings.Join(strings.FieldsFunc(text, pySpace), " ") }

// strip is Python's str.strip().
func strip(text string) string { return strings.TrimFunc(text, pySpace) }

// truncateChars is Django's |truncatechars: the text in composed form, cut
// to length characters with an ellipsis as the last of them when it is
// longer; combining marks are not counted.
func truncateChars(text string, length int) string {
	if length <= 0 {
		return ""
	}
	text = norm.NFC.String(text)
	keep := length - 1 // the ellipsis is one of the characters
	shown, end := 0, -1
	for i, r := range text {
		if norm.NFC.PropertiesString(string(r)).CCC() != 0 {
			continue
		}
		shown++
		if end < 0 && shown > keep {
			end = i
		}
		if shown > length {
			return text[:max(end, 0)] + "…"
		}
	}
	return text
}

// slug is the feed's key for a header button: its label in lower case, every
// run of anything but a–z and 0–9 an underscore.
func slug(label string) string {
	var b strings.Builder
	gap := false
	// Python lowers a dotted capital I to an i and a combining dot.
	for _, r := range strings.ToLower(strings.ReplaceAll(label, "İ", "i̇")) {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') {
			if gap && b.Len() > 0 {
				b.WriteByte('_')
			}
			gap = false
			b.WriteRune(r)
			continue
		}
		gap = true
	}
	return b.String()
}

// pyQuote is urllib.parse.quote(text, safe="").
func pyQuote(text string) string {
	var b strings.Builder
	for i := 0; i < len(text); i++ {
		c := text[i]
		switch {
		case c >= 'a' && c <= 'z', c >= 'A' && c <= 'Z', c >= '0' && c <= '9', strings.IndexByte("_.-~", c) >= 0:
			b.WriteByte(c)
		default:
			b.WriteString("%" + strings.ToUpper(strconv.FormatInt(int64(c)+0x100, 16)[1:]))
		}
	}
	return b.String()
}

// thousands is |intcomma for a whole number written in digits.
func thousands(digits string) string {
	sign := ""
	if strings.HasPrefix(digits, "-") {
		sign, digits = "-", digits[1:]
	}
	for i := len(digits) - 3; i > 0; i -= 3 {
		digits = digits[:i] + "," + digits[i:]
	}
	return sign + digits
}

func comma(n int64) string { return thousands(strconv.FormatInt(n, 10)) }

// pyInt is Python's int() of a query value: surrounding whitespace, a sign,
// and underscores between digits allowed. A number too long to hold is the
// largest there is, which a page number is clamped from either way.
func pyInt(text string) (int, bool) {
	s := strip(text)
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
	s = strings.ReplaceAll(s, "_", "")
	for i := 0; i < len(s); i++ {
		if s[i] < '0' || s[i] > '9' {
			return 0, false
		}
	}
	n, err := strconv.Atoi(s)
	if err != nil {
		n = math.MaxInt
	}
	return sign * n, true
}
