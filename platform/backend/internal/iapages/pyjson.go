package iapages

// PythonJSON writes a snapshot as Django's JSONField stores it: a float is
// written as Python writes it (6.0, 0.75, 1e-05), an integer as an integer,
// so a stored score reads back the same on either side.

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strconv"
)

// PythonJSON is json.dumps of a snapshot built from maps, lists, strings,
// booleans, ints and float64s.
func PythonJSON(v any) ([]byte, error) {
	var out bytes.Buffer
	if err := writePy(&out, v); err != nil {
		return nil, err
	}
	return out.Bytes(), nil
}

func writePy(out *bytes.Buffer, v any) error {
	switch x := v.(type) {
	case nil:
		out.WriteString("null")
	case bool, string, int, int32, int64:
		b, err := json.Marshal(x)
		if err != nil {
			return err
		}
		out.Write(b)
	case float64:
		if math.IsNaN(x) || math.IsInf(x, 0) {
			return fmt.Errorf("iapages: %v cannot be stored", x)
		}
		out.WriteString(pyFloatRepr(x))
	case []any:
		out.WriteByte('[')
		for i, e := range x {
			if i > 0 {
				out.WriteString(", ")
			}
			if err := writePy(out, e); err != nil {
				return err
			}
		}
		out.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		out.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				out.WriteString(", ")
			}
			b, _ := json.Marshal(k)
			out.Write(b)
			out.WriteString(": ")
			if err := writePy(out, x[k]); err != nil {
				return err
			}
		}
		out.WriteByte('}')
	default:
		return fmt.Errorf("iapages: a %T cannot be stored in a snapshot", v)
	}
	return nil
}

// pyFloatRepr is Python's repr() of a finite float: the shortest digits
// that read back, fixed for a decimal exponent from -4 below 16, ".0" on an
// integral value.
func pyFloatRepr(x float64) string {
	if x == 0 {
		if math.Signbit(x) {
			return "-0.0"
		}
		return "0.0"
	}
	exp := int(math.Floor(math.Log10(math.Abs(x))))
	if exp < -4 || exp >= 16 {
		s := strconv.FormatFloat(x, 'e', -1, 64)
		mantissa, e, _ := cutE(s)
		n, _ := strconv.Atoi(e)
		sign := "+"
		if n < 0 {
			sign, n = "-", -n
		}
		return fmt.Sprintf("%se%s%02d", mantissa, sign, n)
	}
	s := strconv.FormatFloat(x, 'f', -1, 64)
	if !bytes.ContainsAny([]byte(s), ".") {
		s += ".0"
	}
	return s
}

func cutE(s string) (string, string, bool) {
	for i := 0; i < len(s); i++ {
		if s[i] == 'e' {
			return s[:i], s[i+1:], true
		}
	}
	return s, "0", false
}
