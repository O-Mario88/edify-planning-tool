package targets

// Status is team_status_for: the pace-aware state of a share against the
// share the period expects.
func Status(pct *int, pace int, started, assigned bool) (string, string) {
	if !assigned {
		return "Not Assigned", "neutral"
	}
	if !started {
		return "Not Started", "neutral"
	}
	p := 0
	if pct != nil {
		p = *pct
	}
	switch {
	case p > 100:
		return "Exceeded", "success"
	case p == 100:
		return "Complete", "success"
	}
	gap := pace - p
	switch {
	case gap <= rules.Bands.OnTrack:
		return "On Track", "success"
	case gap <= rules.Bands.Slight:
		return "Slightly Behind", "warning"
	case gap <= rules.Bands.HighRisk:
		return "High Risk", "danger"
	}
	return "Critical", "danger"
}

// Display is team_status_display: the five states the pages show.
func Display(status, tone string) (string, string) {
	switch status {
	case "Slightly Behind", "High Risk":
		return "Needs Attention", "warning"
	case "Not Started":
		return "Upcoming", "info"
	}
	return status, tone
}
