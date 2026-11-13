package teamperformance

import (
	"math"
	"strconv"
	"strings"
)

// dash is a figure the records cannot give, never a zero.
const dash = "—"

// grouped is Python's f"{n:,}" of an integer.
func grouped(n int64) string {
	text := strconv.FormatInt(n, 10)
	sign := ""
	if strings.HasPrefix(text, "-") {
		sign, text = "-", text[1:]
	}
	for i := len(text) - 3; i > 0; i -= 3 {
		text = text[:i] + "," + text[i:]
	}
	return sign + text
}

// groupedFixed is Python's f"{x:,.1f}".
func groupedFixed(x float64, places int) string {
	text := strconv.FormatFloat(x, 'f', places, 64)
	sign := ""
	if strings.HasPrefix(text, "-") {
		sign, text = "-", text[1:]
	}
	whole, frac, _ := strings.Cut(text, ".")
	for i := len(whole) - 3; i > 0; i -= 3 {
		whole = whole[:i] + "," + whole[i:]
	}
	if frac != "" {
		return sign + whole + "." + frac
	}
	return sign + whole
}

// num is team_performance_tags.num: 1,234 for a count, one decimal place
// only where the figure has one; a dash for no figure.
func num(v *float64) string {
	if v == nil {
		return dash
	}
	if *v == math.Trunc(*v) && !math.IsInf(*v, 0) {
		return grouped(int64(*v))
	}
	return groupedFixed(*v, 1)
}

// pct is team_performance_tags.pct.
func pct(v *float64) string {
	if v == nil {
		return dash
	}
	return strings.Replace(groupedFixed(*v, 1)+"%", ".0%", "%", 1)
}

// signed is team_performance_tags.signed: +12 / −3 / 0.
func signed(v *float64) string {
	if v == nil {
		return dash
	}
	text := num(ptr(math.Abs(*v)))
	switch {
	case *v > 0:
		return "+" + text
	case *v < 0:
		return "−" + text
	}
	return "0"
}

func ptr(v float64) *float64 { return &v }

func fptr(n *int) *float64 {
	if n == nil {
		return nil
	}
	v := float64(*n)
	return &v
}

func iptr(n int) *int { return &n }

// pyRound is Python's round(x, places): the binary value rounded, half to
// even, as its shortest decimal says.
func pyRound(x float64, places int) float64 {
	v, _ := strconv.ParseFloat(strconv.FormatFloat(x, 'f', places, 64), 64)
	return v
}

// pyRoundInt is round(x) to a whole number, half to even.
func pyRoundInt(x float64) float64 { return math.RoundToEven(x) }

// share is report.pct: achieved as a share of target, one decimal place;
// nil with no figure or no target.
func share(achieved, target *float64) *float64 {
	if achieved == nil || target == nil || *target == 0 {
		return nil
	}
	v := pyRound(100.0**achieved / *target, 1)
	return &v
}

// variance is report._var.
func variance(achieved, target *float64) *float64 {
	if achieved == nil || target == nil {
		return nil
	}
	v := *achieved - *target
	return &v
}

// statusOf is report.status: the workbook's 100% / 75% rule.
func statusOf(s *float64, running bool) string {
	switch {
	case s == nil:
		return ""
	case *s >= 100:
		if running {
			return rules.StatusWords.OnTrack
		}
		return rules.StatusWords.Achieved
	case *s >= 75:
		return rules.StatusWords.Progressing
	}
	return rules.StatusWords.Attention
}

// fmtG is Python's f"{x:g}".
func fmtG(x float64) string { return strconv.FormatFloat(x, 'g', 6, 64) }
