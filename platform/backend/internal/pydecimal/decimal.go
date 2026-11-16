// Package pydecimal is Python's decimal.Decimal as the existing application
// computes with it and Django prints it: a coefficient and an exponent,
// kept through addition, multiplication, division and quantize exactly as
// the default context (28 significant digits, ROUND_HALF_EVEN) keeps them,
// so a figure Go prints reads digit for digit as the template's ("12.00",
// "2", "0.05"; a zero divided by "20.00" is 0E+2, printed "0").
package pydecimal

import (
	"fmt"
	"math/big"
	"strings"
)

// precision is the default context's significant digits.
const precision = 28

var (
	ten  = big.NewInt(10)
	zero = big.NewInt(0)
)

// Decimal is coefficient × 10^exponent.
type Decimal struct {
	c *big.Int
	e int
}

// Zero is Decimal(0).
func Zero() Decimal { return Decimal{c: new(big.Int)} }

// Int is Decimal(n).
func Int(n int64) Decimal { return Decimal{c: big.NewInt(n)} }

// Parse reads a Decimal's text as PostgreSQL's numeric::text or Python's
// str() writes it ("12.00", "-0.5", "1E+2").
func Parse(s string) (Decimal, error) {
	s = strings.TrimSpace(s)
	exp := 0
	if i := strings.IndexAny(s, "eE"); i >= 0 {
		if _, err := fmt.Sscan(s[i+1:], &exp); err != nil {
			return Decimal{}, fmt.Errorf("pydecimal: %q is not a number", s)
		}
		s = s[:i]
	}
	if i := strings.IndexByte(s, '.'); i >= 0 {
		exp -= len(s) - i - 1
		s = s[:i] + s[i+1:]
	}
	c, ok := new(big.Int).SetString(s, 10)
	if !ok {
		return Decimal{}, fmt.Errorf("pydecimal: %q is not a number", s)
	}
	return Decimal{c: c, e: exp}, nil
}

// MustParse is Parse for a literal.
func MustParse(s string) Decimal {
	d, err := Parse(s)
	if err != nil {
		panic(err)
	}
	return d
}

func (d Decimal) coef() *big.Int {
	if d.c == nil {
		return zero
	}
	return d.c
}

func pow10(n int) *big.Int { return new(big.Int).Exp(ten, big.NewInt(int64(n)), nil) }

// aligned is both coefficients at the smaller exponent.
func aligned(a, b Decimal) (*big.Int, *big.Int, int) {
	e := min(a.e, b.e)
	ac := new(big.Int).Mul(a.coef(), pow10(a.e-e))
	bc := new(big.Int).Mul(b.coef(), pow10(b.e-e))
	return ac, bc, e
}

func digits(c *big.Int) int {
	if c.Sign() == 0 {
		return 1
	}
	return len(new(big.Int).Abs(c).String())
}

// rounded is c × 10^e held to the context's precision.
func rounded(c *big.Int, e int) Decimal {
	n := digits(c)
	if n <= precision {
		return Decimal{c: c, e: e}
	}
	drop := n - precision
	return Decimal{c: roundHalfEven(c, pow10(drop)), e: e + drop}
}

// roundHalfEven is c / div rounded half to even.
func roundHalfEven(c, div *big.Int) *big.Int {
	q, r := new(big.Int).QuoRem(c, div, new(big.Int))
	twice := new(big.Int).Mul(new(big.Int).Abs(r), big.NewInt(2))
	switch twice.Cmp(div) {
	case 1:
		q.Add(q, big.NewInt(int64(c.Sign())))
	case 0:
		if q.Bit(0) == 1 {
			q.Add(q, big.NewInt(int64(c.Sign())))
		}
	}
	return q
}

// Add is a + b.
func (d Decimal) Add(b Decimal) Decimal {
	ac, bc, e := aligned(d, b)
	return rounded(ac.Add(ac, bc), e)
}

// Sub is a - b.
func (d Decimal) Sub(b Decimal) Decimal {
	ac, bc, e := aligned(d, b)
	return rounded(ac.Sub(ac, bc), e)
}

// Mul is a × b.
func (d Decimal) Mul(b Decimal) Decimal {
	return rounded(new(big.Int).Mul(d.coef(), b.coef()), d.e+b.e)
}

// Div is a / b as the default context divides: an exact quotient at the
// exponent nearest the ideal (a's less b's), else 28 significant digits.
// Division by zero is the caller's to prevent.
func (d Decimal) Div(b Decimal) Decimal {
	ideal := d.e - b.e
	if d.coef().Sign() == 0 {
		return Decimal{c: new(big.Int), e: ideal}
	}
	// Scale the dividend so the quotient carries at least precision+1 digits.
	shift := max(0, precision+1-(digits(d.coef())-digits(b.coef())))
	num := new(big.Int).Mul(d.coef(), pow10(shift))
	q, r := new(big.Int).QuoRem(num, b.coef(), new(big.Int))
	e := ideal - shift
	if r.Sign() == 0 {
		// Exact: shed trailing zeros down to the ideal exponent.
		for e < ideal {
			m := new(big.Int)
			nq, _ := new(big.Int).QuoRem(q, ten, m)
			if m.Sign() != 0 {
				break
			}
			q, e = nq, e+1
		}
		return rounded(q, e)
	}
	// Inexact: round the true quotient to the precision.
	exact := new(big.Rat).SetFrac(num, b.coef())
	n := digits(q)
	drop := n - precision
	if drop <= 0 {
		return Decimal{c: q, e: e}
	}
	div := new(big.Rat).SetInt(pow10(drop))
	scaled := new(big.Rat).Quo(exact, div)
	c := roundRat(scaled)
	return rounded(c, e+drop)
}

// roundRat is r rounded half to even.
func roundRat(r *big.Rat) *big.Int {
	return roundHalfEven(new(big.Int).Mul(r.Num(), big.NewInt(1)), r.Denom())
}

// Quantize is quantize(Decimal(10) ** exp), ROUND_HALF_EVEN.
func (d Decimal) Quantize(exp int) Decimal {
	if d.e >= exp {
		return Decimal{c: new(big.Int).Mul(d.coef(), pow10(d.e-exp)), e: exp}
	}
	return Decimal{c: roundHalfEven(d.coef(), pow10(exp-d.e)), e: exp}
}

// Cmp compares the values.
func (d Decimal) Cmp(b Decimal) int {
	ac, bc, _ := aligned(d, b)
	return ac.Cmp(bc)
}

// Sign is -1, 0 or 1.
func (d Decimal) Sign() int { return d.coef().Sign() }

// Max is Python's max(a, b): the first of two equal values.
func Max(a, b Decimal) Decimal {
	if b.Cmp(a) > 0 {
		return b
	}
	return a
}

// Min is Python's min(a, b): the first of two equal values.
func Min(a, b Decimal) Decimal {
	if b.Cmp(a) < 0 {
		return b
	}
	return a
}

// Rat is the exact value.
func (d Decimal) Rat() *big.Rat {
	r := new(big.Rat).SetInt(d.coef())
	if d.e >= 0 {
		return r.Mul(r, new(big.Rat).SetInt(pow10(d.e)))
	}
	return r.Quo(r, new(big.Rat).SetInt(pow10(-d.e)))
}

// Float64 is float(d).
func (d Decimal) Float64() float64 {
	f, _ := d.Rat().Float64()
	return f
}

// String is format(d, "f"), which Django's template prints a Decimal as.
func (d Decimal) String() string {
	c := d.coef()
	neg := c.Sign() < 0
	s := new(big.Int).Abs(c).String()
	switch {
	case d.e >= 0:
		if c.Sign() != 0 {
			s += strings.Repeat("0", d.e)
		}
	default:
		places := -d.e
		if len(s) <= places {
			s = strings.Repeat("0", places-len(s)+1) + s
		}
		s = s[:len(s)-places] + "." + s[len(s)-places:]
	}
	if neg {
		return "-" + s
	}
	return s
}
