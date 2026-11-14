// Package platformhealth is Go's own health page (/platform-health): the
// gateway (its environment, build and uptime, the saves it makes), its
// database connection (reachability, latency, the pool, the read-only
// session and TLS), the schemas Go owns (each migrated to the version this
// build needs), the audit chain's tail and the rows still waiting to be
// sealed, the target ledgers marked for rebuilding (whose readers Go passes
// on), the costs Django still has to settle after a Go save, and the
// routing provider and analytics worker it depends on.
//
// The existing application keeps its own System Health, which checks
// Django itself (owner, 2026-11-14: "Build Go platform health now"). This
// page reads and never writes; it opens to whoever may open System Health,
// exported to rules.json by `manage.py export_platform_health_rules`.
package platformhealth

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"runtime"
	"runtime/debug"
	"slices"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ownedschema"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page Go answers.
const Path = "/platform-health"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	PageRoles []string `json:"page_roles"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.PageRoles) == 0 {
		panic(fmt.Sprintf("platformhealth: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// Facts are what the gateway was started with.
type Facts struct {
	Env, Release              string
	Started                   time.Time
	GoSaves                   []string
	ExistingApp               bool
	RoutingProvider, OSRMURL  string
	AnalyticsAddr             string
	MailConfigured, DevMailbx bool
}

// PoolStat is the pool's state (pgxpool.Stat's figures).
type PoolStat struct {
	Total, Acquired, Idle, Max int32
}

// Probe answers the checks that are not a query: the pool's figures and
// whether an address answers.
type Probe struct {
	Pool  func() PoolStat
	Reach func(ctx context.Context, rawURL string) error
}

// Service answers Platform Health.
type Service struct {
	db      schooldirectory.Querier
	facts   Facts
	probe   Probe
	schemas map[string]ownedschema.Spec
	now     func() time.Time
}

// NewService is the page over db, with the gateway's facts, its probes and
// the schemas it owns.
func NewService(db schooldirectory.Querier, facts Facts, probe Probe, schemas map[string]ownedschema.Spec, now func() time.Time) *Service {
	return &Service{db: db, facts: facts, probe: probe, schemas: schemas, now: now}
}

// check is one line of a section.
type check struct{ label, meta, value, tone string }

const (
	good = "success"
	warn = "warning"
	bad  = "danger"
)

// Build answers /platform-health; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, _ url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	now := s.now()
	gateway := s.gateway(now)
	database, reachable := s.database(ctx)
	schemas, ready := s.ownedSchemas(ctx, reachable)
	work := s.waiting(ctx, reachable, now)
	deps := s.dependencies(ctx)

	problems := 0
	for _, section := range [][]check{gateway, database, schemas, work, deps} {
		for _, c := range section {
			if c.tone == bad {
				problems++
			}
		}
	}
	dbValue, dbTone := "Reachable", good
	if !reachable {
		dbValue, dbTone = "Unreachable", bad
	}
	readyTone := good
	if ready < len(s.schemas) {
		readyTone = bad
	}
	problemTone := good
	if problems > 0 {
		problemTone = bad
	}
	strip := &screensv1.PageStrip{Title: "Platform at a glance", Metrics: []*screensv1.PageMetric{
		{Label: "Database", Value: dbValue, Tone: dbTone},
		{Label: "Go schemas ready", Value: fmt.Sprintf("%d of %d", ready, len(s.schemas)), Tone: readyTone},
		{Label: "Problems", Value: fmt.Sprint(problems), Tone: problemTone},
		{Label: "Up for", Value: since(now.Sub(s.facts.Started))},
	}}
	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Strip{Strip: strip}},
		section("Gateway", "This process: what it is and what it does in Go.", gateway),
		section("Database", "The gateway's own connection, read-only by default.", database),
		section("Schemas Go owns", "Each migrated (by schemactl, never by the gateway) to the version this build reads.", schemas),
		section("Work waiting", "Rows the platform still has to finish, and readers Go passes on.", work),
		section("Dependencies", "Services the gateway calls.", deps),
	}
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{Eyebrow: "Go platform", Title: "Platform Health",
			Description: "The Go gateway's own health. Checks of the existing application stay on System Health."},
		Blocks:  blocks,
		WebPath: Path,
	}, true, nil
}

func section(title, subtitle string, checks []check) *screensv1.PageBlock {
	rows := []*screensv1.PageDataRow{}
	for _, c := range checks {
		rows = append(rows, &screensv1.PageDataRow{Label: c.label, Meta: c.meta, Value: c.value, Tone: c.tone})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: title, Subtitle: subtitle,
		Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: rows}}}}}}}
}

// since is a duration in the largest whole units: "3 days 4 hours".
func since(d time.Duration) string {
	if d < time.Minute {
		return "under a minute"
	}
	days, hours, minutes := int(d.Hours())/24, int(d.Hours())%24, int(d.Minutes())%60
	switch {
	case days > 0:
		return fmt.Sprintf("%s %s", plural(days, "day"), plural(hours, "hour"))
	case hours > 0:
		return fmt.Sprintf("%s %s", plural(hours, "hour"), plural(minutes, "minute"))
	}
	return plural(minutes, "minute")
}

func plural(n int, word string) string {
	if n == 1 {
		return fmt.Sprintf("1 %s", word)
	}
	return fmt.Sprintf("%d %ss", n, word)
}

func (s *Service) gateway(now time.Time) []check {
	build, revision := "unknown", ""
	if info, ok := debug.ReadBuildInfo(); ok {
		for _, setting := range info.Settings {
			switch setting.Key {
			case "vcs.revision":
				revision = setting.Value
				if len(revision) > 12 {
					revision = revision[:12]
				}
			case "vcs.modified":
				if setting.Value == "true" {
					revision += " (modified)"
				}
			}
		}
		build = info.GoVersion
	}
	if build == "unknown" {
		build = runtime.Version()
	}
	release := s.facts.Release
	if release == "" {
		release = revision
	}
	saves := "None: every save goes to the existing application"
	if len(s.facts.GoSaves) > 0 {
		saves = strings.Join(s.facts.GoSaves, ", ")
	}
	existing, existingTone := "Connected", good
	if !s.facts.ExistingApp {
		existing, existingTone = "Not configured: pages Go does not build are unavailable", warn
	}
	return []check{
		{label: "Environment", value: s.facts.Env},
		{label: "Release", meta: "Go " + strings.TrimPrefix(build, "go"), value: dashIf(release)},
		{label: "Started", meta: since(now.Sub(s.facts.Started)) + " ago", value: s.facts.Started.Format("2 Jan 2006 15:04 MST")},
		{label: "Saves made in Go", value: saves},
		{label: "Existing application", meta: "Pages and saves Go hands on", value: existing, tone: existingTone},
	}
}

func dashIf(s string) string {
	if strings.TrimSpace(s) == "" {
		return "—"
	}
	return s
}
