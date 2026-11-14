package platformhealth

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/jackc/pgx/v5"
)

// slowQuery is the round trip past which the database reads as slow.
const slowQuery = 200 * time.Millisecond

// sealingBacklog is how long an unsealed audit row may wait before it
// reads as a backlog: rows are sealed the moment their transaction commits.
const sealingBacklog = 5 * time.Minute

func failed(label string, err error) check {
	return check{label: label, value: "Could not be read", meta: err.Error(), tone: bad}
}

func (s *Service) database(ctx context.Context) ([]check, bool) {
	start := time.Now()
	var version, name, role, readOnly string
	var tls *bool
	err := s.db.QueryRow(ctx, `
SELECT current_setting('server_version'), current_database(), current_user, current_setting('default_transaction_read_only'),
       (SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid())`).Scan(&version, &name, &role, &readOnly, &tls)
	took := time.Since(start)
	if err != nil {
		return []check{failed("Connection", err)}, false
	}
	latency := check{label: "Round trip", value: took.Round(time.Millisecond).String(), tone: good}
	if took > slowQuery {
		latency.tone = warn
	}
	ro := check{label: "Read-only by default", meta: "Saves open their own read-write transactions", value: "Yes", tone: good}
	if readOnly != "on" {
		ro.value, ro.tone = "No: the gateway's sessions can write", bad
	}
	encrypted := check{label: "Encrypted (TLS)", value: "Yes", tone: good}
	if tls == nil || !*tls {
		encrypted.value, encrypted.tone = "No", bad
		if s.facts.Env == "development" || s.facts.Env == "test" {
			encrypted.tone = warn
			encrypted.meta = "Allowed on a developer's machine only"
		}
	}
	out := []check{
		{label: "Connection", meta: "PostgreSQL " + version, value: name + " as " + role, tone: good},
		latency, ro, encrypted,
	}
	if s.probe.Pool != nil {
		st := s.probe.Pool()
		tone := good
		if st.Max > 0 && st.Acquired >= st.Max {
			tone = warn
		}
		out = append(out, check{label: "Connection pool", meta: fmt.Sprintf("%d idle", st.Idle),
			value: fmt.Sprintf("%d in use of %d (%d open)", st.Acquired, st.Max, st.Total), tone: tone})
	}
	return out, true
}

func (s *Service) ownedSchemas(ctx context.Context, reachable bool) ([]check, int) {
	names := make([]string, 0, len(s.schemas))
	for name := range s.schemas {
		names = append(names, name)
	}
	sort.Strings(names)
	out, ready := []check{}, 0
	for _, name := range names {
		spec := s.schemas[name]
		need := spec.Required()
		if !reachable {
			out = append(out, check{label: name, value: "Not checked", meta: "The database cannot be reached", tone: bad})
			continue
		}
		have, err := spec.Version(ctx, s.db)
		if err != nil {
			out = append(out, failed(name, err))
			continue
		}
		c := check{label: name, meta: fmt.Sprintf("Migration %d of %d", have, need), value: "Ready", tone: good}
		switch {
		case have == need:
			if err := spec.Ready(ctx, s.db); err != nil {
				c.value, c.meta, c.tone = "Not ready", err.Error(), bad
			} else {
				ready++
			}
		case have == 0:
			c.value, c.tone = "Not created: its pages are passed on", bad
		case have < need:
			c.value, c.tone = "Behind: run schemactl migrate", bad
		default:
			c.value, c.tone = "Ahead of this build", warn
		}
		out = append(out, c)
	}
	return out, ready
}

func (s *Service) waiting(ctx context.Context, reachable bool, now time.Time) []check {
	if !reachable {
		return []check{{label: "Work waiting", value: "Not checked", meta: "The database cannot be reached", tone: bad}}
	}
	out := []check{}
	var tail *int64
	var sealedAt *time.Time
	if err := s.db.QueryRow(ctx, `SELECT seq, created_at FROM audit_log WHERE seq IS NOT NULL ORDER BY seq DESC LIMIT 1`).Scan(&tail, &sealedAt); err != nil && !errors.Is(err, pgx.ErrNoRows) {
		out = append(out, failed("Audit chain", err))
	} else {
		c := check{label: "Audit chain", value: "Empty", tone: good}
		if tail != nil {
			c.value = fmt.Sprintf("%d rows sealed", *tail)
			if sealedAt != nil {
				c.meta = "Last sealed " + since(now.Sub(*sealedAt)) + " ago"
			}
		}
		out = append(out, c)
	}
	var unsealed int
	var oldest *time.Time
	if err := s.db.QueryRow(ctx, `SELECT count(*), min(created_at) FROM audit_log WHERE seq IS NULL`).Scan(&unsealed, &oldest); err != nil {
		out = append(out, failed("Audit rows waiting to be sealed", err))
	} else {
		c := check{label: "Audit rows waiting to be sealed", value: fmt.Sprint(unsealed), tone: good}
		if unsealed > 0 && oldest != nil {
			c.meta = "Oldest " + since(now.Sub(*oldest)) + " old"
			if now.Sub(*oldest) > sealingBacklog {
				c.tone = bad
			}
		}
		out = append(out, c)
	}
	var marks int
	var marked *time.Time
	if err := s.db.QueryRow(ctx, `SELECT count(*), min(marked_at) FROM target_ledger_dirty`).Scan(&marks, &marked); err != nil {
		out = append(out, failed("Target ledgers to rebuild", err))
	} else {
		c := check{label: "Target ledgers to rebuild", meta: "Their readers are passed on until the existing application rebuilds them",
			value: fmt.Sprint(marks), tone: good}
		if marks > 0 {
			c.tone = warn
			if marked != nil {
				c.meta = "Oldest marked " + since(now.Sub(*marked)) + " ago; their readers are passed on until the existing application rebuilds them"
			}
		}
		out = append(out, c)
	}
	var costs int
	if err := s.db.QueryRow(ctx, `SELECT count(*) FROM daily_visit_costs_to_follow`).Scan(&costs); err != nil {
		out = append(out, failed("Costs to settle after Go saves", err))
	} else {
		c := check{label: "Costs to settle after Go saves", meta: "Priced by the existing application after a Go save commits", value: fmt.Sprint(costs), tone: good}
		if costs > 0 {
			c.tone = warn
		}
		out = append(out, c)
	}
	return out
}

func (s *Service) dependencies(ctx context.Context) []check {
	out := []check{}
	switch s.facts.RoutingProvider {
	case "", "none":
		out = append(out, check{label: "Road routing", value: "None: straight-line distances only", tone: warn})
	case "osrm":
		c := check{label: "Road routing", meta: "OSRM at " + s.facts.OSRMURL, value: "Reachable", tone: good}
		if s.probe.Reach != nil {
			if err := s.probe.Reach(ctx, s.facts.OSRMURL); err != nil {
				c.value, c.tone = "Unreachable: road legs fall back to straight lines", bad
			}
		}
		out = append(out, c)
	default:
		out = append(out, check{label: "Road routing", value: "Google Routes", meta: "Not probed: each call is billed"})
	}
	if s.facts.AnalyticsAddr == "" {
		out = append(out, check{label: "Analytics worker", value: "Not configured", meta: "Pages that need it are passed on", tone: warn})
	} else {
		c := check{label: "Analytics worker", meta: s.facts.AnalyticsAddr, value: "Reachable", tone: good}
		if s.probe.Reach != nil {
			if err := s.probe.Reach(ctx, "tcp://"+s.facts.AnalyticsAddr); err != nil {
				c.value, c.tone = "Unreachable", bad
			}
		}
		out = append(out, c)
	}
	mail := check{label: "Mail", value: "Configured", tone: good}
	switch {
	case s.facts.DevMailbx:
		mail.value, mail.meta = "Written to files", "A developer's mailbox, not sent"
	case !s.facts.MailConfigured:
		mail.value, mail.tone = "Not configured: account mail is not sent", warn
	}
	return append(out, mail)
}
