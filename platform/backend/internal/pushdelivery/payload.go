package pushdelivery

import (
	"strings"
	"time"
	"unicode"
)

// bodyChars is BODY_CHARS: what a phone shows of the body.
const bodyChars = 240

// notice is what a message is made of.
type notice struct {
	id, title, body, category, priority string
	told                                time.Time // last_reminded_at, else created_at
}

// pythonISO is datetime.isoformat() of an aware time read back in UTC.
func pythonISO(t time.Time) string {
	t = t.UTC()
	if t.Nanosecond()/int(time.Microsecond) == 0 {
		return t.Format("2006-01-02T15:04:05") + "+00:00"
	}
	return t.Format("2006-01-02T15:04:05.000000") + "+00:00"
}

// shownBody is payload_for's body: whitespace collapsed, cut at 240
// characters with an ellipsis.
func shownBody(body string) string {
	shown := strings.Join(strings.FieldsFunc(body, unicode.IsSpace), " ")
	runes := []rune(shown)
	if len(runes) > bodyChars {
		shown = strings.TrimRightFunc(string(runes[:bodyChars-1]), unicode.IsSpace) + "…"
	}
	return shown
}

// openURL is open_url: the address that marks the notice read and goes on.
func openURL(id string) string { return "/notifications/" + id + "/open" }

// payloadFor is payload_for, in its key order.
func payloadFor(n notice) orderedObject {
	return orderedObject{
		{"id", n.id}, {"title", n.title}, {"body", shownBody(n.body)}, {"url", openURL(n.id)},
		{"tag", "edify-" + n.id}, {"category", n.category}, {"priority", n.priority}, {"at", pythonISO(n.told)},
	}
}

// field is one payload value by name.
func (o orderedObject) field(name string) any {
	for _, f := range o {
		if f.name == name {
			return f.value
		}
	}
	return nil
}
