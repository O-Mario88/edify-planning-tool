package country

import (
	"fmt"
	"time"
)

// EthiopianDate is a date on the Ethiopian (Ge'ez) 13-month calendar:
// 12 months of 30 days (Meskerem..Nehase) plus Pagume (5 days, or 6 in a
// leap year when Year % 4 == 3).
type EthiopianDate struct {
	Year  int
	Month int // 1..13
	Day   int // 1..30 (1..6 for month 13)
}

var ethiopianMonthsEN = [13]string{
	"Meskerem", "Tikimt", "Hidar", "Tahsas", "Tir", "Yekatit",
	"Megabit", "Miazia", "Ginbot", "Sene", "Hamle", "Nehase", "Pagume",
}

var ethiopianMonthsAM = [13]string{
	"መስከረም", "ጥቅምት", "ኅዳር", "ታኅሣሥ", "ጥር", "የካቲት",
	"መጋቢት", "ሚያዝያ", "ግንቦት", "ሰኔ", "ሐምሌ", "ነሐሴ", "ጳጉሜ",
}

// ethiopicEpochJDN is the Dershowitz & Reingold 0-based Ethiopic epoch
// (JDN 1723856, one 365-day year before Meskerem 1, Year 1 = JDN 1724221),
// aligning Ethiopian leap years (year % 4 == 3) with r == 1460.
const ethiopicEpochJDN = 1723856

// gregorianToJDN converts a proleptic Gregorian date to its Julian Day Number.
func gregorianToJDN(y, m, d int) int {
	a := (14 - m) / 12
	yy := y + 4800 - a
	mm := m + 12*a - 3
	return d + (153*mm+2)/5 + 365*yy + yy/4 - yy/100 + yy/400 - 32045
}

// jdnToGregorian converts a Julian Day Number to a Gregorian (y, m, d).
func jdnToGregorian(jdn int) (int, time.Month, int) {
	a := jdn + 32044
	b := (4*a + 3) / 146097
	c := a - (146097*b)/4
	d := (4*c + 3) / 1461
	e := c - (1461*d)/4
	m := (5*e + 2) / 153
	day := e - (153*m+2)/5 + 1
	month := m + 3 - 12*(m/10)
	year := 100*b + d - 4800 + m/10
	return year, time.Month(month), day
}

// ToEthiopian converts a Gregorian time.Time (by its calendar date) into an
// EthiopianDate.
func ToEthiopian(t time.Time) EthiopianDate {
	jdn := gregorianToJDN(t.Year(), int(t.Month()), t.Day())
	delta := jdn - ethiopicEpochJDN
	r := delta % 1461
	if r < 0 {
		r += 1461
	}
	n := (r % 365) + 365*(r/1460)
	cycles := (delta - r) / 1461
	year := 4*cycles + r/365 - r/1460
	month := n/30 + 1
	day := n%30 + 1
	return EthiopianDate{Year: year, Month: month, Day: day}
}

// ToGregorian converts an EthiopianDate back to a UTC Gregorian midnight time.
func (e EthiopianDate) ToGregorian() time.Time {
	jdn := ethiopicEpochJDN + 365*e.Year + e.Year/4 + 30*(e.Month-1) + (e.Day - 1)
	y, m, d := jdnToGregorian(jdn)
	return time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
}

// Format returns a human-readable Ethiopian date in English or Amharic ("am").
func (e EthiopianDate) Format(locale string) string {
	if e.Month < 1 || e.Month > 13 {
		return fmt.Sprintf("%04d-%02d-%02d EC", e.Year, e.Month, e.Day)
	}
	if locale == "am" {
		return fmt.Sprintf("%s %d, %d ዓ.ም", ethiopianMonthsAM[e.Month-1], e.Day, e.Year)
	}
	return fmt.Sprintf("%s %d, %d EC", ethiopianMonthsEN[e.Month-1], e.Day, e.Year)
}

// FormatInCalendar formats t for a country's configured calendar ("ethiopian"
// or "gregorian").
func FormatInCalendar(t time.Time, calendar, locale string) string {
	if calendar == "ethiopian" {
		return ToEthiopian(t).Format(locale)
	}
	return t.Format("2 Jan 2006")
}
