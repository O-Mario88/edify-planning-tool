package schoolprofile

import (
	"strconv"
	"strings"
	"time"
	_ "time/tzdata" // the page's dates are Kampala's wherever the gateway runs
)

// kampala is the existing TIME_ZONE ("Africa/Nairobi"), in which a template
// prints a stored moment.
var kampala = func() *time.Location {
	zone, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		return time.FixedZone("EAT", 3*60*60)
	}
	return zone
}()

// shortest is a float's shortest round-trip decimal, as Python's repr
// writes it in the range a score or a coordinate lives in.
func shortest(x float64) string {
	return strconv.FormatFloat(x, 'f', -1, 64)
}

// pyFloat is a template printing a float: Python's str(6.0) is "6.0".
func pyFloat(x float64) string {
	s := shortest(x)
	if !strings.ContainsAny(s, ".eEn") {
		s += ".0"
	}
	return s
}

// floatformat is Django's |floatformat:n for a float: its repr, rounded half
// up to n places (Decimal.quantize(ROUND_HALF_UP)), always n places shown.
func floatformat(x float64, n int) string {
	s := shortest(x)
	negative := strings.HasPrefix(s, "-")
	s = strings.TrimPrefix(s, "-")
	whole, frac, _ := strings.Cut(s, ".")
	for len(frac) <= n {
		frac += "0"
	}
	digits := []byte(whole + frac[:n])
	if frac[n] >= '5' {
		i := len(digits) - 1
		for ; i >= 0; i-- {
			if digits[i] == '9' {
				digits[i] = '0'
				continue
			}
			digits[i]++
			break
		}
		if i < 0 {
			digits = append([]byte{'1'}, digits...)
		}
	}
	cut := len(digits) - n
	out := string(digits[:cut])
	if n > 0 {
		out += "." + string(digits[cut:])
	}
	if negative && strings.Trim(out, "0.") != "" {
		out = "-" + out
	}
	return out
}

// jMY is Django's |date:"j M Y" ("9 Nov 2026") of a calendar day.
func jMY(day time.Time) string {
	return strconv.Itoa(day.Day()) + " " + day.Format("Jan 2006")
}

// dMY is Django's |date:"d M Y" ("09 Nov 2026").
func dMY(day time.Time) string { return day.Format("02 Jan 2006") }

// localJMY is |date:"j M Y" of a stored moment, read on Kampala's clock.
func localJMY(moment time.Time) string { return jMY(moment.In(kampala)) }
