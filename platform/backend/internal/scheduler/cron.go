package scheduler

// Each job fires when the existing scheduler fires it (apps.realtime.registry
// JOB_REGISTRY cron_kwargs, copied verbatim into schedules.json), read as
// APScheduler's CronTrigger reads them in settings.TIME_ZONE: a field larger
// than the smallest one given is every value, a smaller one its minimum, so
// {"day_of_week": "fri", "hour": 6} is Fridays at 06:00:00 Kampala time.

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"slices"
	"strconv"
	"strings"
	"time"
)

//go:embed schedules.json
var schedulesJSON []byte

// Cron is one job's firing times; a nil field is every value.
type Cron struct {
	minutes, hours, days, weekdays []int
	zone                           *time.Location
}

var weekdayNames = map[string]int{"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 0}

// parseField is one CronTrigger field: an int, "*", "*/n", "a,b" or a
// weekday name, over the field's range.
func parseField(v any, lo, hi int, names map[string]int) ([]int, error) {
	switch x := v.(type) {
	case float64:
		return []int{int(x)}, nil
	case string:
		if x == "*" {
			return nil, nil
		}
		if step, ok := strings.CutPrefix(x, "*/"); ok {
			n, err := strconv.Atoi(step)
			if err != nil || n <= 0 {
				return nil, fmt.Errorf("scheduler: bad step %q", x)
			}
			var out []int
			for i := lo; i <= hi; i += n {
				out = append(out, i)
			}
			return out, nil
		}
		var out []int
		for _, part := range strings.Split(x, ",") {
			part = strings.TrimSpace(part)
			if n, ok := names[part]; ok {
				out = append(out, n)
				continue
			}
			n, err := strconv.Atoi(part)
			if err != nil {
				return nil, fmt.Errorf("scheduler: bad cron value %q", x)
			}
			out = append(out, n)
		}
		slices.Sort(out)
		return out, nil
	}
	return nil, fmt.Errorf("scheduler: bad cron value %v", v)
}

// ParseCron is CronTrigger(**kwargs) in zone.
func ParseCron(kwargs map[string]any, zone *time.Location) (Cron, error) {
	c := Cron{zone: zone}
	var err error
	field := func(name string, lo, hi int, names map[string]int) ([]int, bool, error) {
		v, ok := kwargs[name]
		if !ok {
			return nil, false, nil
		}
		out, err := parseField(v, lo, hi, names)
		return out, true, err
	}
	var hasMinute, hasHour, hasDay, hasWeekday bool
	if c.minutes, hasMinute, err = field("minute", 0, 59, nil); err != nil {
		return c, err
	}
	if c.hours, hasHour, err = field("hour", 0, 23, nil); err != nil {
		return c, err
	}
	if c.days, hasDay, err = field("day", 1, 31, nil); err != nil {
		return c, err
	}
	if c.weekdays, hasWeekday, err = field("day_of_week", 0, 6, weekdayNames); err != nil {
		return c, err
	}
	// Fields below the smallest one given take their minimum.
	if !hasMinute && (hasHour || hasDay || hasWeekday) {
		c.minutes = []int{0}
	}
	if !hasHour && (hasDay || hasWeekday) {
		c.hours = []int{0}
	}
	return c, nil
}

func matches(set []int, v int) bool { return set == nil || slices.Contains(set, v) }

// Next is the first firing time after t (to the minute, second zero).
func (c Cron) Next(t time.Time) time.Time {
	local := t.In(c.zone).Truncate(time.Minute).Add(time.Minute)
	// A year of minutes bounds the search; every schedule here fires far
	// more often than that.
	for i := 0; i < 366*24*60; i++ {
		if matches(c.minutes, local.Minute()) && matches(c.hours, local.Hour()) && matches(c.days, local.Day()) &&
			matches(c.weekdays, int(local.Weekday())) {
			return local
		}
		local = local.Add(time.Minute)
	}
	return time.Time{}
}

// djangoSchedules are the registry's schedules by job name.
func djangoSchedules(zone *time.Location) (map[string]Cron, error) {
	var raw map[string]map[string]any
	if err := json.Unmarshal(schedulesJSON, &raw); err != nil {
		return nil, err
	}
	out := make(map[string]Cron, len(raw))
	for name, kwargs := range raw {
		c, err := ParseCron(kwargs, zone)
		if err != nil {
			return nil, fmt.Errorf("%s: %w", name, err)
		}
		out[name] = c
	}
	return out, nil
}
