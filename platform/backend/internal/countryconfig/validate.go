package countryconfig

import (
	"errors"
	"fmt"
	"regexp"
	"slices"
	"strings"
	"time"
	_ "time/tzdata" // a country's time zone is checked wherever the gateway runs
	"unicode/utf8"

	countriesv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/countries/v1"
)

const (
	maxLanguages  = 10
	maxMinorUnits = 3
	maxReason     = 500
)

var (
	countryCode  = regexp.MustCompile(`^[A-Z]{2}$`)
	languageCode = regexp.MustCompile(`^[a-z]{2,3}(-[A-Z]{2})?$`)
	currencyCode = regexp.MustCompile(`^[A-Z]{3}$`)

	// dateFormats are the platform's existing notations (Django's), which
	// the clients already draw.
	dateFormats = []string{"j M Y", "d M Y", "j F Y", "d/m/Y", "m/d/Y", "d.m.Y", "Y-m-d"}
	// Dates are stored Gregorian; Ethiopian is shown beside them.
	calendarNames = []string{"gregorian", "ethiopian"}
)

// settings is a checked RecordCountryConfigRequest.
type settings struct {
	code, defaultLanguage, currency, timeZone, dateFormat string
	languages, calendars                                  []string
	minorUnits, fyStartMonth                              int
	// from is YYYY-MM-DD, or empty for today.
	from, reason string
}

// refusal is a request the reader can correct; its text is shown.
type refusal string

func (r refusal) Error() string { return string(r) }

// settingsOf checks a request field by field, before anything is read.
func settingsOf(r *countriesv1.RecordCountryConfigRequest) (settings, error) {
	s := settings{
		code: r.GetCountryCode(), defaultLanguage: r.GetDefaultLanguage(), currency: r.GetCurrencyCode(),
		timeZone: r.GetTimeZone(), dateFormat: r.GetDateFormat(),
		languages: r.GetLanguages(), calendars: r.GetCalendars(),
		minorUnits: int(r.GetCurrencyMinorUnits()), fyStartMonth: int(r.GetFyStartMonth()),
		from: strings.TrimSpace(r.GetEffectiveFrom()), reason: strings.TrimSpace(r.GetChangeReason()),
	}
	checks := []error{
		check(countryCode.MatchString(s.code), "country_code must be a two-letter code such as KE"),
		codes("languages", s.languages, maxLanguages, languageCode.MatchString),
		check(slices.Contains(s.languages, s.defaultLanguage), "default_language must be one of languages"),
		check(currencyCode.MatchString(s.currency), "currency_code must be an ISO 4217 code such as KES"),
		check(s.minorUnits >= 0 && s.minorUnits <= maxMinorUnits, "currency_minor_units must be 0 to 3"),
		zone(s.timeZone),
		check(slices.Contains(dateFormats, s.dateFormat), "date_format must be one of "+strings.Join(dateFormats, ", ")),
		codes("calendars", s.calendars, len(calendarNames), func(c string) bool { return slices.Contains(calendarNames, c) }),
		check(slices.Contains(s.calendars, "gregorian"), "calendars must include gregorian, the calendar dates are kept in"),
		check(s.fyStartMonth >= 1 && s.fyStartMonth <= 12, "fy_start_month must be 1 to 12"),
		day("effective_from", s.from),
		check(s.reason != "", "change_reason is required"),
		check(utf8.RuneCountInString(s.reason) <= maxReason, fmt.Sprintf("change_reason must be at most %d characters", maxReason)),
	}
	return s, errors.Join(checks...)
}

func check(ok bool, message string) error {
	if ok {
		return nil
	}
	return refusal(message)
}

// codes refuses an empty, over-long, repeated or malformed list.
func codes(field string, list []string, most int, valid func(string) bool) error {
	if len(list) == 0 || len(list) > most {
		return refusal(fmt.Sprintf("%s must hold 1 to %d entries", field, most))
	}
	seen := map[string]bool{}
	for _, item := range list {
		if !valid(item) || seen[item] {
			return refusal(fmt.Sprintf("%s holds %q, which is not allowed or repeated", field, item))
		}
		seen[item] = true
	}
	return nil
}

func zone(name string) error {
	if name == "" || name == "Local" {
		return refusal("time_zone must be an IANA zone such as Africa/Nairobi")
	}
	if _, err := time.LoadLocation(name); err != nil {
		return refusal(fmt.Sprintf("time_zone %q is not an IANA zone", name))
	}
	return nil
}

// day checks that field holds a YYYY-MM-DD date, or nothing.
func day(field, raw string) error {
	if raw == "" {
		return nil
	}
	if _, err := time.Parse(time.DateOnly, raw); err != nil {
		return refusal(field + " must be YYYY-MM-DD")
	}
	return nil
}
