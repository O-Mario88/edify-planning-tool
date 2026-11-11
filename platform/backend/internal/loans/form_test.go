package loans

import (
	"net/url"
	"strings"
	"testing"
)

func validForm() url.Values {
	return url.Values{
		"school_name":     {"St. Mary's Primary School"},
		"director_name":   {"Grace Nakato"},
		"director_phone":  {"0772 123 456"},
		"director_email":  {""},
		"district":        {"Mukono"},
		"sub_county":      {"Goma"},
		"parish":          {"Seeta"},
		"village":         {"Namilyango"},
		"boys":            {"210"},
		"girls":           {"190"},
		"fees_collected":  {"UGX 12,500,000"},
		"purpose":         {"classroom_construction"},
		"requested":       {"40,000,000"},
		"partner":         {"cmw9lender"},
		"consent":         {"yes"},
		"idempotency_key": {"0123456789abcdef0123456789abcdef"},
	}
}

func TestAValidFormParses(t *testing.T) {
	input, problems := ParseForm(validForm())
	if len(problems) != 0 {
		t.Fatalf("problems: %v", problems)
	}
	if input.Boys != 210 || input.Girls != 190 || input.TotalEnrollment() != 400 {
		t.Fatalf("enrollment: %+v", input)
	}
	if input.FeesCollected != 12_500_000 || input.Requested != 40_000_000 {
		t.Fatalf("amounts: fees %d requested %d", input.FeesCollected, input.Requested)
	}
	if input.DirectorPhone != "+256772123456" {
		t.Fatalf("phone %q", input.DirectorPhone)
	}
	if input.Purpose.Code != "classroom_construction" || input.Purpose.Label != "Classroom Construction" {
		t.Fatalf("purpose %+v", input.Purpose)
	}
	if input.Religion != "" || input.TermMonths != 0 {
		t.Fatalf("optional fields should be empty: %+v", input)
	}
}

func TestRequiredFieldsAreRefusedWhenEmpty(t *testing.T) {
	for _, field := range []string{
		"school_name", "director_name", "director_phone", "district", "sub_county", "parish",
		"village", "boys", "girls", "fees_collected", "purpose", "requested", "partner", "consent",
	} {
		t.Run(field, func(t *testing.T) {
			form := validForm()
			form.Set(field, "  ")
			_, problems := ParseForm(form)
			if problems[field] == "" {
				t.Fatalf("an empty %s was accepted (problems %v)", field, problems)
			}
		})
	}
}

func TestEnrollmentTakesNonNegativeWholeNumbersOnly(t *testing.T) {
	for value, accepted := range map[string]bool{
		"0": true, "1,250": true, " 75 ": true,
		"-1": false, "12.5": false, "ten": false, "1e3": false, "99999999": false,
	} {
		form := validForm()
		form.Set("boys", value)
		_, problems := ParseForm(form)
		if (problems["boys"] == "") != accepted {
			t.Errorf("boys %q: accepted=%v, problems %v", value, problems["boys"] == "", problems)
		}
	}
}

func TestUGXAmountsAreParsedExactly(t *testing.T) {
	cases := map[string]int64{
		"1500000":        1_500_000,
		"1,500,000":      1_500_000,
		"1 500 000":      1_500_000,
		"UGX 1,500,000":  1_500_000,
		"ugx1,500,000/=": 1_500_000,
		"Shs. 2,000,000": 2_000_000,
		"999999999999":   999_999_999_999,
		"40,000,000.00":  40_000_000,
	}
	for raw, want := range cases {
		got, err := ParseUGX(raw)
		if err != nil || got != want {
			t.Errorf("ParseUGX(%q) = %d, %v; want %d", raw, got, err, want)
		}
	}
	for _, raw := range []string{"", "1,500,000.50", "-5000", "1.5m", "12,34,5", "abc", "10000000000000"} {
		if got, err := ParseUGX(raw); err == nil {
			t.Errorf("ParseUGX(%q) = %d, want an error", raw, got)
		}
	}
}

func TestRequestedAmountMustBePositiveButFeesMayBeZero(t *testing.T) {
	form := validForm()
	form.Set("requested", "0")
	form.Set("fees_collected", "0")
	_, problems := ParseForm(form)
	if problems["requested"] == "" {
		t.Fatal("a zero requested amount was accepted")
	}
	if problems["fees_collected"] != "" {
		t.Fatalf("zero fees collected was refused: %s", problems["fees_collected"])
	}
}

func TestPhoneNumbersAreNormalised(t *testing.T) {
	cases := map[string]string{
		"0772123456":      "+256772123456",
		"0772 123 456":    "+256772123456",
		"+256 772 123456": "+256772123456",
		"256772123456":    "+256772123456",
		"00256772123456":  "+256772123456",
		"(0772) 123-456":  "+256772123456",
		"+254 712 345678": "+254712345678",
	}
	for raw, want := range cases {
		got, err := NormalizePhone(raw)
		if err != nil || got != want {
			t.Errorf("NormalizePhone(%q) = %q, %v; want %q", raw, got, err, want)
		}
	}
	for _, raw := range []string{"12345", "07721234567890123", "phone", "0772-12a-456", "+0772123456"} {
		if got, err := NormalizePhone(raw); err == nil {
			t.Errorf("NormalizePhone(%q) = %q, want an error", raw, got)
		}
	}
}

func TestOtherPurposeNeedsADescription(t *testing.T) {
	form := validForm()
	form.Set("purpose", "other")
	_, problems := ParseForm(form)
	if problems["purpose_other"] == "" {
		t.Fatal("Other was accepted without a description")
	}
	form.Set("purpose_other", "Perimeter wall")
	input, problems := ParseForm(form)
	if len(problems) != 0 || input.PurposeOther != "Perimeter wall" || input.Purpose.Label != "Other" {
		t.Fatalf("problems %v input %+v", problems, input)
	}
}

func TestAnUnknownPurposeOrReligionIsRefused(t *testing.T) {
	form := validForm()
	form.Set("purpose", "holiday")
	form.Set("religion", "anything")
	_, problems := ParseForm(form)
	if problems["purpose"] == "" || problems["religion"] == "" {
		t.Fatalf("problems %v", problems)
	}
}

func TestReligionIsOptionalAndVoluntary(t *testing.T) {
	form := validForm()
	form.Set("religion", "prefer_not_to_say")
	input, problems := ParseForm(form)
	if len(problems) != 0 || input.Religion != "prefer_not_to_say" {
		t.Fatalf("problems %v religion %q", problems, input.Religion)
	}
}

func TestEmailIsOptionalButMustBeValid(t *testing.T) {
	form := validForm()
	form.Set("director_email", "grace@example.org")
	if input, problems := ParseForm(form); len(problems) != 0 || input.DirectorEmail != "grace@example.org" {
		t.Fatalf("problems %v", problems)
	}
	form.Set("director_email", "Grace <grace@example.org>")
	if _, problems := ParseForm(form); problems["director_email"] == "" {
		t.Fatal("a display-name address was accepted")
	}
	form.Set("director_email", "not-an-email")
	if _, problems := ParseForm(form); problems["director_email"] == "" {
		t.Fatal("a malformed address was accepted")
	}
}

func TestPreferredTermIsOptionalButBounded(t *testing.T) {
	form := validForm()
	form.Set("term_months", "24")
	if input, problems := ParseForm(form); len(problems) != 0 || input.TermMonths != 24 {
		t.Fatalf("problems %v", problems)
	}
	form.Set("term_months", "121")
	if _, problems := ParseForm(form); problems["term_months"] == "" {
		t.Fatal("a 121-month term was accepted")
	}
}

func TestConsentMustBeGivenExplicitly(t *testing.T) {
	form := validForm()
	form.Del("consent")
	if _, problems := ParseForm(form); problems["consent"] == "" {
		t.Fatal("a form without consent was accepted")
	}
}

func TestOverlongTextIsRefused(t *testing.T) {
	form := validForm()
	form.Set("school_name", strings.Repeat("a", 301))
	if _, problems := ParseForm(form); problems["school_name"] == "" {
		t.Fatal("a 301-character school name was accepted")
	}
}

func TestAMissingOrMalformedIdempotencyKeyIsRefused(t *testing.T) {
	form := validForm()
	form.Set("idempotency_key", "short")
	if _, problems := ParseForm(form); problems["form"] == "" {
		t.Fatal("a malformed idempotency key was accepted")
	}
}

func TestFormatUGXGroupsThousands(t *testing.T) {
	for value, want := range map[int64]string{0: "UGX 0", 950: "UGX 950", 1500000: "UGX 1,500,000", 40000000: "UGX 40,000,000"} {
		if got := FormatUGX(value); got != want {
			t.Errorf("FormatUGX(%d) = %q, want %q", value, got, want)
		}
	}
}
