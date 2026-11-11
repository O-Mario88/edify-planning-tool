package loans

import (
	"bytes"
	"net/url"
	"strings"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
)

func testPages(t *testing.T) *Public {
	t.Helper()
	public, err := NewPublic(nil, DeriveKeys("test-secret"), config.Loans{}, NewLimiter(nil), nil, time.Now)
	if err != nil {
		t.Fatalf("NewPublic: %v", err)
	}
	return public
}

func renderPage(t *testing.T, public *Public, name string, data any) string {
	t.Helper()
	var out bytes.Buffer
	if err := public.pages.ExecuteTemplate(&out, name, data); err != nil {
		t.Fatalf("rendering %s: %v", name, err)
	}
	return out.String()
}

func TestTheFormShowsEverySectionAndOnlyEligibleLenders(t *testing.T) {
	public := testPages(t)
	html := renderPage(t, public, "apply.html", formPage{
		page:      page{Title: "Apply", Version: "v"},
		Values:    url.Values{},
		Problems:  Problems{},
		Lenders:   []Lender{{PartnerID: "p1", Name: "Kampala School Finance", Description: "Loans for schools"}},
		Purposes:  Purposes,
		Religions: Religions,
		Districts: []Place{{ID: "d1", Name: "Mukono"}},
		Total:     "—",
	})
	for _, want := range []string{
		"School information", "School location", "School enrollment", "Financial information",
		"Loan request", "Declaration and consent", "Kampala School Finance", `value="p1"`,
		"Total enrollment", "actually collects in one term", `<option value="Mukono">`,
		`name="consent" value="yes" required`,
	} {
		if !strings.Contains(html, want) {
			t.Errorf("the form lacks %q", want)
		}
	}
	if strings.Contains(html, "checked") {
		t.Error("something on the form is pre-ticked; consent must never be")
	}
	if strings.Contains(html, `value="d1"`) {
		t.Error("an internal place id reached the public page")
	}
}

func TestAFormWithProblemsListsThemAndMarksTheFields(t *testing.T) {
	public := testPages(t)
	html := renderPage(t, public, "apply.html", formPage{
		page: page{Title: "Apply", Version: "v"}, Values: url.Values{"school_name": {"<script>x</script>"}},
		Problems:    Problems{"boys": "Enter the number of boys as a whole number, such as 120."},
		ProblemList: []problemItem{{Field: "boys", Message: "Enter the number of boys as a whole number, such as 120."}},
		Lenders:     []Lender{{PartnerID: "p1", Name: "L"}}, Total: "—",
	})
	if !strings.Contains(html, `href="#boys"`) || !strings.Contains(html, `aria-invalid="true"`) {
		t.Fatal("the problem is not linked or marked")
	}
	if strings.Contains(html, "<script>x</script>") {
		t.Fatal("a submitted value was not escaped")
	}
}

func TestWithNoLenderTheFormSaysSoAndCannotBeSubmitted(t *testing.T) {
	public := testPages(t)
	html := renderPage(t, public, "apply.html", formPage{page: page{Version: "v"}, Values: url.Values{}, Total: "—"})
	if !strings.Contains(html, "Applications are paused") || !strings.Contains(html, `id="submit-button" disabled`) {
		t.Fatal("an empty lender list must pause the form")
	}
}

func TestTheReceiptNeverClaimsMoreThanHappened(t *testing.T) {
	queued := progressOf(Receipt{LenderName: "L", Status: StatusSubmitted, DeliveryStatus: DeliveryQueued})
	if strings.Contains(queued, "has sent") || strings.Contains(queued, "L has received") {
		t.Fatalf("a queued application claims delivery: %q", queued)
	}
	sent := progressOf(Receipt{LenderName: "L", Status: StatusAwaitingReceipt, DeliveryStatus: DeliverySent})
	if !strings.Contains(sent, "not yet confirmed receipt") {
		t.Fatalf("a sent application claims receipt: %q", sent)
	}
	failed := progressOf(Receipt{LenderName: "L", Status: StatusSubmitted, DeliveryStatus: DeliveryFailed})
	if strings.Contains(failed, "has sent") {
		t.Fatalf("a failed delivery claims it was sent: %q", failed)
	}
}

func TestTheReceiptPageShowsTheReference(t *testing.T) {
	public := testPages(t)
	html := renderPage(t, public, "receipt.html", receiptPage{
		page:    page{Version: "v"},
		Receipt: Receipt{Reference: "EDL-7K3Q-X9MZ", SchoolName: "Seeta High", LenderName: "L"},
		Fresh:   true, StatusLabel: "Submitted", DeliveryLabel: "Waiting to be sent", Progress: "p",
	})
	for _, want := range []string{"Your Loan Application Has Been Received", "EDL-7K3Q-X9MZ", "Seeta High", "Waiting to be sent"} {
		if !strings.Contains(html, want) {
			t.Errorf("the receipt lacks %q", want)
		}
	}
}

func TestFormStampsAreSignedAndTimed(t *testing.T) {
	keys := DeriveKeys("k")
	shown := time.Unix(1_800_000_000, 0)
	stamp := keys.FormStamp(shown)
	if age, ok := keys.StampAge(stamp, shown.Add(10*time.Second)); !ok || age != 10*time.Second {
		t.Fatalf("age %v ok %v", age, ok)
	}
	if _, ok := DeriveKeys("other").StampAge(stamp, shown); ok {
		t.Fatal("a stamp signed with another key was accepted")
	}
	if _, ok := keys.StampAge("1800000000.forged", shown); ok {
		t.Fatal("a forged stamp was accepted")
	}
}

func TestReceiptTokensAreStablePerSubmission(t *testing.T) {
	keys := DeriveKeys("k")
	if keys.ReceiptToken("a", "k1") != keys.ReceiptToken("a", "k1") || keys.ReceiptToken("a", "k1") == keys.ReceiptToken("a", "k2") {
		t.Fatal("receipt tokens must repeat for the same submission and differ otherwise")
	}
	reference, err := NewReference()
	if err != nil || len(reference) != 13 || !strings.HasPrefix(reference, "EDL-") || strings.ContainsAny(reference[4:], "ILOU") {
		t.Fatalf("reference %q %v", reference, err)
	}
}

func TestTheLimiterStopsABurst(t *testing.T) {
	now := time.Unix(0, 0)
	limiter := NewLimiter(func() time.Time { return now })
	for index := 0; index < 3; index++ {
		if !limiter.Allow("k", 3, time.Minute) {
			t.Fatalf("request %d refused", index)
		}
	}
	if limiter.Allow("k", 3, time.Minute) {
		t.Fatal("the fourth request was allowed")
	}
	now = now.Add(time.Minute)
	if !limiter.Allow("k", 3, time.Minute) {
		t.Fatal("a new window was refused")
	}
}

func TestNoTemplateNeedsInlineStyleOrScript(t *testing.T) {
	// The pages' Content-Security-Policy allows only this site's own
	// stylesheet and script; an inline one would silently not work.
	entries, err := webFiles.ReadDir("web/templates")
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		raw, err := webFiles.ReadFile("web/templates/" + entry.Name())
		if err != nil {
			t.Fatal(err)
		}
		text := string(raw)
		if strings.Contains(text, "style=") || strings.Contains(text, "<script>") || strings.Contains(text, " onclick") {
			t.Errorf("%s holds an inline style or script", entry.Name())
		}
	}
}
