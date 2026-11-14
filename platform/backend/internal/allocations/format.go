package allocations

import (
	"math/big"
	"strconv"
	"strings"
)

// FloatFormat is Django's |floatformat:places for a Decimal: a negative
// places shows a whole number bare and anything else to |places| digits,
// rounded half up.
func FloatFormat(d *big.Rat, places int) string {
	if d == nil {
		return ""
	}
	if places < 0 && d.IsInt() {
		return d.Num().String()
	}
	p := places
	if p < 0 {
		p = -p
	}
	scale := new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(p)), nil)
	scaled := new(big.Rat).Mul(d, new(big.Rat).SetInt(scale))
	// Half up: away from zero at the half.
	num, den := new(big.Int).Abs(scaled.Num()), scaled.Denom()
	q, r := new(big.Int).QuoRem(num, den, new(big.Int))
	if new(big.Int).Mul(r, big.NewInt(2)).Cmp(den) >= 0 {
		q.Add(q, big.NewInt(1))
	}
	s := q.String()
	if p > 0 {
		if len(s) <= p {
			s = strings.Repeat("0", p-len(s)+1) + s
		}
		s = s[:len(s)-p] + "." + s[len(s)-p:]
	}
	if scaled.Sign() < 0 && strings.Trim(s, "0.") != "" {
		s = "-" + s
	}
	return s
}

// FloatFormatFloat is |floatformat on a float (through its repr).
func FloatFormatFloat(f float64, places int) string {
	d, _ := new(big.Rat).SetString(strconv.FormatFloat(f, 'g', -1, 64))
	return FloatFormat(d, places)
}

// Repr is Python's str() of a float: the shortest form that reads back,
// a whole number with ".0".
func Repr(f float64) string {
	s := strconv.FormatFloat(f, 'f', -1, 64)
	if !strings.ContainsAny(s, ".eE") {
		s += ".0"
	}
	return s
}

// Meter is components/meter.html (meta=True) as the feed reads it: the
// value, then the line under it.
func Meter(p *Progress) string {
	if p == nil {
		return "— Not linked to the plan yet — define which activities count towards it."
	}
	if !p.HasWork && p.Completed == 0 && p.Planned == 0 {
		value, meta := "Nothing planned", "No FY"+p.Year+" activity counts towards this yet."
		if !p.Started {
			value, meta = "Not started", "FY"+p.Year+" has not started — nothing is planned into it yet."
		}
		if p.Target != nil {
			meta += " Target " + FloatFormat(p.Target, -2) + " " + p.Unit + "."
		}
		return value + " " + meta
	}
	counts := strconv.FormatInt(p.Completed, 10) + " done · " + strconv.FormatInt(p.Planned, 10) + " planned"
	value := counts
	if p.Pct != nil {
		value = FloatFormatFloat(*p.Pct, 0) + "%"
	}
	meta := counts
	if p.Target != nil {
		meta += " · of " + FloatFormat(p.Target, -2) + " " + p.Unit
	} else {
		meta += " " + p.Unit + " · no target yet — define the metric to get a percentage"
	}
	if p.Verified != nil {
		meta += " · " + FloatFormat(p.Verified, -2) + " verified"
	}
	return value + " " + meta
}
