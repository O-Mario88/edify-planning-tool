package projectspage

import "time"

// DjangoDateTime is a date-time as a template's default rendering writes it
// (DATETIME_FORMAT "N j, Y, P", en-us): "Nov. 19, 2026, 8:55 a.m.", "noon".
// The Admin Panel's Audit Log prints its times so.
func DjangoDateTime(t time.Time) string { return djangoDateTime(t) }
