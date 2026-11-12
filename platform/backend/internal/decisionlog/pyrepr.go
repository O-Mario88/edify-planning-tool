package decisionlog

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math/big"
	"strconv"
	"strings"
	"unicode"
)

// value is one JSON value of a payload as Python reads it (json.loads):
// keys in the order they are stored, numbers as int or float.
type value struct {
	kind   byte // 's' string, 'i' int, 'f' float, 'b' bool, 'n' null, 'l' list, 'd' dict
	str    string
	num    string
	flt    float64
	truth  bool
	items  []value
	keys   []string
	values []value
}

// decode reads a JSON document as Python reads it.
func decode(raw []byte) (value, error) {
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	return decodeValue(d)
}

func decodeValue(d *json.Decoder) (value, error) {
	token, err := d.Token()
	if err != nil {
		return value{}, err
	}
	switch t := token.(type) {
	case json.Delim:
		if t == '[' {
			v := value{kind: 'l'}
			for d.More() {
				item, err := decodeValue(d)
				if err != nil {
					return value{}, err
				}
				v.items = append(v.items, item)
			}
			_, err := d.Token()
			return v, err
		}
		v := value{kind: 'd'}
		for d.More() {
			key, err := d.Token()
			if err != nil {
				return value{}, err
			}
			item, err := decodeValue(d)
			if err != nil {
				return value{}, err
			}
			name, _ := key.(string)
			if i := indexOf(v.keys, name); i >= 0 {
				// A repeated key keeps its first place and its last value.
				v.values[i] = item
				continue
			}
			v.keys, v.values = append(v.keys, name), append(v.values, item)
		}
		_, err := d.Token()
		return v, err
	case string:
		return value{kind: 's', str: t}, nil
	case bool:
		return value{kind: 'b', truth: t}, nil
	case nil:
		return value{kind: 'n'}, nil
	case json.Number:
		text := t.String()
		if strings.ContainsAny(text, ".eE") {
			f, err := strconv.ParseFloat(text, 64)
			if err != nil {
				return value{}, err
			}
			return value{kind: 'f', flt: f}, nil
		}
		n, ok := new(big.Int).SetString(text, 10)
		if !ok {
			return value{}, fmt.Errorf("decisionlog: a number that is not one: %q", text)
		}
		return value{kind: 'i', num: n.String()}, nil
	}
	return value{}, fmt.Errorf("decisionlog: an unknown JSON token %v", token)
}

func indexOf(list []string, s string) int {
	for i, x := range list {
		if x == s {
			return i
		}
	}
	return -1
}

// get is dict.get: the value under key, and whether there is one.
func (v value) get(key string) (value, bool) {
	if v.kind != 'd' {
		return value{}, false
	}
	if i := indexOf(v.keys, key); i >= 0 {
		return v.values[i], true
	}
	return value{}, false
}

// truthy is Python's truth of the value.
func (v value) truthy() bool {
	switch v.kind {
	case 's':
		return v.str != ""
	case 'i':
		return v.num != "0"
	case 'f':
		return v.flt != 0
	case 'b':
		return v.truth
	case 'l':
		return len(v.items) > 0
	case 'd':
		return len(v.keys) > 0
	}
	return false
}

// pyStr is str(value).
func (v value) pyStr() string {
	if v.kind == 's' {
		return v.str
	}
	return v.pyRepr()
}

// pyRepr is repr(value).
func (v value) pyRepr() string {
	switch v.kind {
	case 's':
		return pyReprString(v.str)
	case 'i':
		return v.num
	case 'f':
		return pyReprFloat(v.flt)
	case 'b':
		if v.truth {
			return "True"
		}
		return "False"
	case 'l':
		parts := make([]string, len(v.items))
		for i, item := range v.items {
			parts[i] = item.pyRepr()
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case 'd':
		parts := make([]string, len(v.keys))
		for i, key := range v.keys {
			parts[i] = pyReprString(key) + ": " + v.values[i].pyRepr()
		}
		return "{" + strings.Join(parts, ", ") + "}"
	}
	return "None"
}

// pyReprFloat is repr(float): the shortest digits that read back, in
// positional form between 1e-4 and 1e16 and with ".0" when whole.
func pyReprFloat(f float64) string {
	switch {
	case f != f:
		return "nan"
	case f > 1.7976931348623157e308:
		return "inf"
	case f < -1.7976931348623157e308:
		return "-inf"
	}
	sci := strconv.FormatFloat(f, 'e', -1, 64) // -d.ddde±XX
	mantissa, exp, _ := strings.Cut(sci, "e")
	e, _ := strconv.Atoi(exp)
	if e < -4 || e >= 16 {
		sign := "+"
		if e < 0 {
			sign, e = "-", -e
		}
		return fmt.Sprintf("%se%s%02d", mantissa, sign, e)
	}
	text := strconv.FormatFloat(f, 'f', -1, 64)
	if !strings.Contains(text, ".") {
		text += ".0"
	}
	return text
}

// pyReprString is repr(str): single quotes unless the text holds one and no
// double quote; backslash escapes for the quote, the backslash, the three
// white-space controls and anything else that does not print.
func pyReprString(s string) string {
	quote := byte('\'')
	if strings.Contains(s, "'") && !strings.Contains(s, `"`) {
		quote = '"'
	}
	var b strings.Builder
	b.WriteByte(quote)
	for _, r := range s {
		switch {
		case r == rune(quote) || r == '\\':
			b.WriteByte('\\')
			b.WriteRune(r)
		case r == '\t':
			b.WriteString(`\t`)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == ' ' || (unicode.IsPrint(r) && r != ' ' && r != '­'):
			b.WriteRune(r)
		case r < 0x100:
			fmt.Fprintf(&b, `\x%02x`, r)
		case r < 0x10000:
			fmt.Fprintf(&b, `\u%04x`, r)
		default:
			fmt.Fprintf(&b, `\U%08x`, r)
		}
	}
	b.WriteByte(quote)
	return b.String()
}

// capitalize is str.capitalize: the first character in title case, the rest
// in lower case.
func capitalize(s string) string {
	for i, r := range s {
		return string(unicode.ToTitle(r)) + strings.ToLower(s[i+len(string(r)):])
	}
	return s
}
