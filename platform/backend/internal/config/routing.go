package config

import (
	"fmt"
	"net/url"
	"strconv"
	"strings"
)

// Routing chooses where the Route Planner's road distances come from (owner,
// 2026-11-14: a map that needs no login). Map tiles need no configuration:
// they are keyless and drawn by the apps.
type Routing struct {
	// Provider is none, osrm or google. none (the default) answers with
	// straight-line distances only, labelled as such.
	Provider string
	// OSRMURL is the Edify-run OSRM server, e.g. http://127.0.0.1:5000.
	OSRMURL string
	// GoogleKey is a server key restricted to the Routes API; only read when
	// Provider is google.
	GoogleKey string
	// DailyLimit caps provider requests a day; past it the planner falls
	// back to straight-line distances.
	DailyLimit int
}

const (
	envRoutingProvider = "EDIFY_ROUTING_PROVIDER"
	envOSRMURL         = "EDIFY_OSRM_URL"
	envGoogleRoutesKey = "EDIFY_GOOGLE_ROUTES_KEY"
	envRoutingLimit    = "EDIFY_ROUTING_DAILY_LIMIT"

	defaultRoutingLimit = 20000
)

func loadRouting(getenv func(string) string) (Routing, error) {
	out := Routing{
		Provider:   strings.ToLower(firstNonEmpty(strings.TrimSpace(getenv(envRoutingProvider)), "none")),
		OSRMURL:    strings.TrimRight(strings.TrimSpace(getenv(envOSRMURL)), "/"),
		GoogleKey:  strings.TrimSpace(getenv(envGoogleRoutesKey)),
		DailyLimit: defaultRoutingLimit,
	}
	if raw := strings.TrimSpace(getenv(envRoutingLimit)); raw != "" {
		n, err := strconv.Atoi(raw)
		if err != nil || n < 1 {
			return Routing{}, fmt.Errorf("config: %s must be a whole number above 0", envRoutingLimit)
		}
		out.DailyLimit = n
	}
	switch out.Provider {
	case "none":
	case "osrm":
		u, err := url.Parse(out.OSRMURL)
		if out.OSRMURL == "" || err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
			return Routing{}, fmt.Errorf("config: %s=osrm needs %s, an http(s) address", envRoutingProvider, envOSRMURL)
		}
	case "google":
		if out.GoogleKey == "" {
			return Routing{}, fmt.Errorf("config: %s=google needs %s", envRoutingProvider, envGoogleRoutesKey)
		}
	default:
		return Routing{}, fmt.Errorf("config: %s must be none, osrm or google", envRoutingProvider)
	}
	return out, nil
}
