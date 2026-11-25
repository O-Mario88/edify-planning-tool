package notifymail

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// The golden files are Django's own rendering of templates/emails/
// notification.{txt,html} for the same context (render_to_string).
func TestTheEmailReadsAsDjangoRendersIt(t *testing.T) {
	cases := map[string]view{
		"sent": {RecipientName: "Grace", SenderName: "Peter O'Neil & Co", Title: `Visit <plan> "due"`,
			Body: "Line one\nLine two & more", ActionLabel: "Review", OpenURL: "https://app.example/notifications/n1/open",
			SettingsURL: "https://app.example/notifications/#delivery-settings", SentAt: "5 Nov 2026, 14:03"},
		"urgent": {RecipientName: "there", Title: "Overdue", ActionLabel: "Open in Edify",
			OpenURL:     "http://localhost:3000/notifications/n2/open",
			SettingsURL: "http://localhost:3000/notifications/#delivery-settings", SentAt: "9 Jan 2026, 08:00", Urgent: true},
	}
	for name, v := range cases {
		var text, html strings.Builder
		if err := textTemplate.Execute(&text, v); err != nil {
			t.Fatal(err)
		}
		if err := htmlTemplate.Execute(&html, escaped(v)); err != nil {
			t.Fatal(err)
		}
		for ext, got := range map[string]string{"txt": text.String(), "html": html.String()} {
			want, err := os.ReadFile(filepath.Join("testdata", name+"."+ext))
			if err != nil {
				t.Fatal(err)
			}
			if got != string(want) {
				t.Errorf("%s.%s differs from Django's rendering:\n--- go\n%q\n--- django\n%q", name, ext, got, want)
			}
		}
	}
}

func TestTheSubjectNamesOnlyTheKindOfThingWaiting(t *testing.T) {
	cases := []struct {
		n    notice
		want string
	}{
		{notice{category: "fund_requests"}, "Edify: a new fund requests notification"},
		{notice{category: "", actionRequired: true}, "Edify: a general item needs your action"},
		{notice{category: "planning", priority: "urgent"}, "Urgent: Edify: a new planning notification"},
	}
	for _, c := range cases {
		if got := subjectFor(c.n); got != c.want {
			t.Errorf("subjectFor = %q, want %q", got, c.want)
		}
	}
}
