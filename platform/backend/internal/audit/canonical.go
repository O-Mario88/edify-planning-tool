// Package audit appends rows to the existing hash-chained audit_log, exactly
// as the existing application does (apps/audit/services.py,
// apps/core/audit_hash.py), so one chain holds both systems' events and the
// existing verifier (verify_chain) checks rows written here like its own.
package audit

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
)

// Entry is one audit row's business fields: the part the chain hashes.
// Optional fields are pointers so "absent" (null) and "empty" stay distinct,
// as they are in the existing hash.
type Entry struct {
	Action        string
	SubjectKind   *string
	SubjectID     *string
	ActorID       *string
	ActorRole     *string
	Success       bool
	Reason        *string
	IPAddress     *string
	UserAgent     *string
	CorrelationID *string
	// Payload is nil, or a JSON-shaped value: map[string]any, []any, string,
	// bool, an integer, an integral float, or nil.
	Payload any
}

// Text returns a pointer to s, or nil when s is empty — the way the existing
// callers pass an absent value.
func Text(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// StableStringify is the existing stable_stringify: JSON with object keys
// sorted, no whitespace, and non-ASCII characters written as themselves.
func StableStringify(value any) (string, error) {
	var out strings.Builder
	if err := stringify(&out, value); err != nil {
		return "", err
	}
	return out.String(), nil
}

func stringify(out *strings.Builder, value any) error {
	switch v := value.(type) {
	case nil:
		out.WriteString("null")
	case bool:
		if v {
			out.WriteString("true")
		} else {
			out.WriteString("false")
		}
	case string:
		writeString(out, v)
	case *string:
		if v == nil {
			out.WriteString("null")
		} else {
			writeString(out, *v)
		}
	case int:
		out.WriteString(strconv.Itoa(v))
	case int64:
		out.WriteString(strconv.FormatInt(v, 10))
	case float64:
		return writeFloat(out, v)
	case []any:
		return writeList(out, v)
	case map[string]any:
		return writeObject(out, v)
	default:
		return fmt.Errorf("audit: %T cannot be hashed into the chain", value)
	}
	return nil
}

func writeList(out *strings.Builder, items []any) error {
	out.WriteByte('[')
	for i, item := range items {
		if i > 0 {
			out.WriteByte(',')
		}
		if err := stringify(out, item); err != nil {
			return err
		}
	}
	out.WriteByte(']')
	return nil
}

func writeObject(out *strings.Builder, object map[string]any) error {
	keys := make([]string, 0, len(object))
	for key := range object {
		keys = append(keys, key)
	}
	// Byte order of UTF-8 is code point order, which is Python's order.
	sort.Strings(keys)
	out.WriteByte('{')
	for i, key := range keys {
		if i > 0 {
			out.WriteByte(',')
		}
		writeString(out, key)
		out.WriteByte(':')
		if err := stringify(out, object[key]); err != nil {
			return err
		}
	}
	out.WriteByte('}')
	return nil
}

// writeFloat matches Python for an integral float (printed as an integer).
// A fractional value is refused rather than risk a repr() the existing
// verifier would print differently; the sign-in payloads hold integers only.
func writeFloat(out *strings.Builder, v float64) error {
	if math.IsNaN(v) || math.IsInf(v, 0) || v != math.Trunc(v) || math.Abs(v) >= 1e15 {
		return fmt.Errorf("audit: the number %v is not supported in a payload", v)
	}
	out.WriteString(strconv.FormatInt(int64(v), 10))
	return nil
}

// writeString is the existing _json_escape.
func writeString(out *strings.Builder, s string) {
	out.WriteByte('"')
	for _, r := range s {
		switch {
		case r == '"':
			out.WriteString(`\"`)
		case r == '\\':
			out.WriteString(`\\`)
		case r == '\n':
			out.WriteString(`\n`)
		case r == '\r':
			out.WriteString(`\r`)
		case r == '\t':
			out.WriteString(`\t`)
		case r < 0x20:
			fmt.Fprintf(out, `\u%04x`, r)
		default:
			out.WriteRune(r)
		}
	}
	out.WriteByte('"')
}

// Canonical is the existing canonical_audit: the hashed form of an entry.
func Canonical(e Entry) (string, error) {
	return StableStringify([]any{
		e.Action, e.SubjectKind, e.SubjectID, e.ActorID, e.ActorRole, e.Success,
		e.Reason, e.IPAddress, e.UserAgent, e.CorrelationID, e.Payload,
	})
}

// ChainHash is the existing chain_hash: sha256 of the previous hash, a line
// break and the canonical form, as lowercase hex.
func ChainHash(prevHash, canonical string) string {
	sum := sha256.Sum256([]byte(prevHash + "\n" + canonical))
	return hex.EncodeToString(sum[:])
}
