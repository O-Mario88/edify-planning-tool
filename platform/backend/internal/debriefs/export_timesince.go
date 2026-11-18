package debriefs

import "time"

// Timesince is django.utils.timesince.timesince(d, now), as the debriefs
// page writes it: the two largest adjacent units between d and now.
func Timesince(d, now time.Time) string { return timesince(d, now) }
