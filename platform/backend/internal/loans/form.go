// Package loans is the School Loan Application Portal: a public form a school
// fills in without an account, the referral it becomes, its delivery to the
// one lender the school chose, and the tracking Edify staff and that lender
// do afterwards. Its records live in the Go-owned schema school_loans; the
// Partner Directory, the School Directory and the existing loan workflow
// are only ever read.
package loans

import (
	"errors"
	"net/mail"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"
)

// Purpose is one loan purpose the form offers: a stable code stored with
// the label the school saw.
type Purpose struct {
	Code  string
	Label string
}

// Purposes are the brief's suggested loan purposes, in the order the form
// lists them.
var Purposes = []Purpose{
	{"classroom_construction", "Classroom Construction"},
	{"infrastructure_improvement", "School Infrastructure Improvement"},
	{"school_equipment", "School Equipment"},
	{"teaching_learning_materials", "Teaching and Learning Materials"},
	{"school_furniture", "School Furniture"},
	{"working_capital", "Working Capital"},
	{"school_transport", "School Transport"},
	{"ict_edtech", "ICT and Educational Technology"},
	{"sanitation_water", "Sanitation and Water Facilities"},
	{"other", "Other"},
}

// Religions are the voluntary answers to the optional religion question.
// The answer is never sent to a lender and never used in a decision.
var Religions = []Purpose{
	{"christian_catholic", "Christian – Catholic"},
	{"christian_anglican", "Christian – Anglican"},
	{"christian_pentecostal", "Christian – Pentecostal / Born Again"},
	{"christian_sda", "Christian – Seventh-day Adventist"},
	{"christian_other", "Christian – other"},
	{"muslim", "Muslim"},
	{"other", "Another religion"},
	{"prefer_not_to_say", "Prefer not to say"},
}

func find(list []Purpose, code string) (Purpose, bool) {
	for _, item := range list {
		if item.Code == code {
			return item, true
		}
	}
	return Purpose{}, false
}

// Limits on what the form accepts.
const (
	maxUGX           = 999_999_999_999
	maxLearners      = 50_000
	maxTermMonths    = 120
	maxNameLength    = 300
	maxPlaceLength   = 120
	maxDetailsLength = 2000
	maxOtherLength   = 200
)

// Input is a validated application as the school submitted it.
type Input struct {
	SchoolName     string
	DirectorName   string
	DirectorPhone  string // E.164
	DirectorEmail  string
	Religion       string // a Religions code, or empty
	District       string
	SubCounty      string
	Parish         string
	Village        string
	Boys           int
	Girls          int
	FeesCollected  int64 // UGX, average actually collected per term
	Purpose        Purpose
	PurposeOther   string
	PurposeDetails string
	Requested      int64 // UGX
	TermMonths     int   // 0 when not given
	PartnerID      string
	IdempotencyKey string
	InviteToken    string
}

// TotalEnrollment is boys plus girls; it is never typed in.
func (i Input) TotalEnrollment() int { return i.Boys + i.Girls }

// Problems maps a form field to what is wrong with it; "form" is the form
// as a whole.
type Problems map[string]string

var (
	idempotencyPattern = regexp.MustCompile(`^[0-9a-f]{32}$`)
	partnerPattern     = regexp.MustCompile(`^[a-z0-9]{1,64}$`)
)

// ParseForm validates a submitted form. Every problem is reported at once,
// so the school fixes them in one pass.
func ParseForm(values url.Values) (Input, Problems) {
	problems := Problems{}
	text := func(field, label string, limit int, required bool) string {
		value := strings.Join(strings.Fields(values.Get(field)), " ")
		switch {
		case value == "" && required:
			problems[field] = "Enter the " + label + "."
		case utf8.RuneCountInString(value) > limit:
			problems[field] = "Keep the " + label + " to " + strconv.Itoa(limit) + " characters."
		}
		return value
	}
	input := Input{
		SchoolName:     text("school_name", "school's name", maxNameLength, true),
		DirectorName:   text("director_name", "director's full name", maxNameLength, true),
		District:       text("district", "district", maxPlaceLength, true),
		SubCounty:      text("sub_county", "sub-county", maxPlaceLength, true),
		Parish:         text("parish", "parish", maxPlaceLength, true),
		Village:        text("village", "village", maxPlaceLength, true),
		PurposeDetails: strings.TrimSpace(values.Get("purpose_details")),
		InviteToken:    strings.TrimSpace(values.Get("invite")),
	}
	if utf8.RuneCountInString(input.PurposeDetails) > maxDetailsLength {
		problems["purpose_details"] = "Keep the details to 2,000 characters."
	}

	if raw := strings.TrimSpace(values.Get("director_phone")); raw == "" {
		problems["director_phone"] = "Enter the director's phone number."
	} else if phone, err := NormalizePhone(raw); err != nil {
		problems["director_phone"] = err.Error()
	} else {
		input.DirectorPhone = phone
	}
	if raw := strings.TrimSpace(values.Get("director_email")); raw != "" {
		address, err := mail.ParseAddress(raw)
		if err != nil || address.Address != raw || len(raw) > 254 {
			problems["director_email"] = "Enter an email address like name@example.org, or leave it blank."
		} else {
			input.DirectorEmail = strings.ToLower(raw)
		}
	}
	if raw := strings.TrimSpace(values.Get("religion")); raw != "" {
		if _, ok := find(Religions, raw); !ok {
			problems["religion"] = "Choose one of the answers, or leave it blank."
		} else {
			input.Religion = raw
		}
	}

	input.Boys = count(values, "boys", "number of boys", problems)
	input.Girls = count(values, "girls", "number of girls", problems)
	input.FeesCollected = amount(values, "fees_collected", "average fees collected per term", false, problems)
	input.Requested = amount(values, "requested", "loan amount", true, problems)

	if purpose, ok := find(Purposes, strings.TrimSpace(values.Get("purpose"))); !ok {
		if strings.TrimSpace(values.Get("purpose")) == "" {
			problems["purpose"] = "Choose the loan purpose."
		} else {
			problems["purpose"] = "Choose one of the listed purposes."
		}
	} else {
		input.Purpose = purpose
		if purpose.Code == "other" {
			input.PurposeOther = text("purpose_other", "short description of the purpose", maxOtherLength, true)
		}
	}
	if raw := strings.TrimSpace(values.Get("term_months")); raw != "" {
		months, err := strconv.Atoi(raw)
		if err != nil || months < 1 || months > maxTermMonths {
			problems["term_months"] = "Enter a repayment period from 1 to 120 months, or leave it blank."
		} else {
			input.TermMonths = months
		}
	}

	input.PartnerID = strings.TrimSpace(values.Get("partner"))
	switch {
	case input.PartnerID == "":
		problems["partner"] = "Choose the lending partner you would like to apply to."
	case !partnerPattern.MatchString(input.PartnerID):
		problems["partner"] = "Choose one of the listed lending partners."
	}
	if values.Get("consent") != "yes" {
		problems["consent"] = "Tick the declaration to confirm it before submitting."
	}
	input.IdempotencyKey = strings.TrimSpace(values.Get("idempotency_key"))
	if !idempotencyPattern.MatchString(input.IdempotencyKey) {
		problems["form"] = "This form has expired. Reload the page and submit it again."
	}
	return input, problems
}

func count(values url.Values, field, label string, problems Problems) int {
	raw := strings.ReplaceAll(strings.TrimSpace(values.Get(field)), ",", "")
	if raw == "" {
		problems[field] = "Enter the " + label + " (0 if none)."
		return 0
	}
	value, err := strconv.Atoi(raw)
	if err != nil || value < 0 || value > maxLearners || strings.ContainsAny(raw, "+-") {
		problems[field] = "Enter the " + label + " as a whole number, such as 120."
		return 0
	}
	return value
}

func amount(values url.Values, field, label string, positive bool, problems Problems) int64 {
	raw := strings.TrimSpace(values.Get(field))
	if raw == "" {
		problems[field] = "Enter the " + label + " in UGX."
		return 0
	}
	value, err := ParseUGX(raw)
	switch {
	case err != nil:
		problems[field] = err.Error()
	case positive && value == 0:
		problems[field] = "Enter a " + label + " above UGX 0."
	}
	return value
}

var (
	currencyWords = regexp.MustCompile(`(?i)^(ugx|ushs?\.?|shs?\.?)\s*`)
	grouped       = regexp.MustCompile(`^\d{1,3}(,\d{3})+$`)
	digitsOnly    = regexp.MustCompile(`^\d+$`)
	zeroFraction  = regexp.MustCompile(`\.0{1,2}$`)
	phoneFiller   = regexp.MustCompile(`[\s().-]`)
)

// ParseUGX reads an amount in Uganda shillings as written on a phone:
// "1,500,000", "UGX 1 500 000", "1,500,000/=". UGX has no cents in use, so a
// fraction other than .00 is refused rather than rounded.
func ParseUGX(raw string) (int64, error) {
	value := strings.TrimSpace(raw)
	value = currencyWords.ReplaceAllString(value, "")
	value = strings.TrimSuffix(strings.TrimSpace(value), "/=")
	value = strings.ReplaceAll(value, " ", "")
	value = zeroFraction.ReplaceAllString(value, "")
	if value == "" {
		return 0, errors.New("Enter the amount in UGX, such as 1,500,000.")
	}
	if strings.Contains(value, ".") {
		return 0, errors.New("Enter whole shillings, without cents.")
	}
	if strings.Contains(value, ",") {
		if !grouped.MatchString(value) {
			return 0, errors.New("Check the commas: write the amount like 1,500,000.")
		}
		value = strings.ReplaceAll(value, ",", "")
	}
	if !digitsOnly.MatchString(value) {
		return 0, errors.New("Enter the amount in figures, such as 1,500,000.")
	}
	number, err := strconv.ParseInt(value, 10, 64)
	if err != nil || number > maxUGX {
		return 0, errors.New("That amount is too large. Check the figure.")
	}
	return number, nil
}

// NormalizePhone returns a phone number in E.164 form. A Ugandan number may
// be written locally (0772 123456); any other needs its country code.
func NormalizePhone(raw string) (string, error) {
	value := phoneFiller.ReplaceAllString(strings.TrimSpace(raw), "")
	if strings.HasPrefix(value, "00") {
		value = "+" + value[2:]
	}
	invalid := errors.New("Enter a phone number such as 0772 123456, or with its country code, such as +256 772 123456.")
	switch {
	case strings.HasPrefix(value, "+"):
		digits := value[1:]
		if !digitsOnly.MatchString(digits) || len(digits) < 8 || len(digits) > 15 || digits[0] == '0' {
			return "", invalid
		}
		return value, nil
	case !digitsOnly.MatchString(value):
		return "", invalid
	case len(value) == 10 && value[0] == '0':
		return "+256" + value[1:], nil
	case len(value) == 12 && strings.HasPrefix(value, "256"):
		return "+" + value, nil
	case len(value) == 9 && value[0] == '7':
		return "+256" + value, nil
	default:
		return "", invalid
	}
}

// FormatUGX writes an amount the way the form and the tables show it.
func FormatUGX(value int64) string {
	digits := strconv.FormatInt(value, 10)
	sign := ""
	if value < 0 {
		sign, digits = "-", digits[1:]
	}
	var out strings.Builder
	for index, digit := range digits {
		if index > 0 && (len(digits)-index)%3 == 0 {
			out.WriteByte(',')
		}
		out.WriteRune(digit)
	}
	return "UGX " + sign + out.String()
}

// Cleaned returns values with only the fields the form defines, so a
// re-rendered form never echoes anything else.
func Cleaned(values url.Values) url.Values {
	kept := url.Values{}
	for _, field := range []string{
		"school_name", "director_name", "director_phone", "director_email", "religion",
		"district", "sub_county", "parish", "village", "boys", "girls", "fees_collected",
		"purpose", "purpose_other", "purpose_details", "requested", "term_months", "partner",
	} {
		if value := values.Get(field); value != "" {
			kept.Set(field, value)
		}
	}
	return kept
}
