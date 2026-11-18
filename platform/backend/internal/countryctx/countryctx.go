// Package countryctx carries the country a request is made in into the
// database session, so PostgreSQL's row-level security can keep a request
// to its country's rows as a second line behind the Go checks
// (docs/migration/80-multi-country-phase-0.md §23; owner, 2026-11-18:
// "enforce country isolation in both Go and the database").
//
// Every connection the gateway takes from its pool carries the session
// setting edify.read_countries:
//
//   - "*" — every country: the Admin, a regional role (§15), and work done
//     on the platform's own behalf (no signed-in caller: the public loan
//     form, token pages, workers, startup checks);
//   - a country code ("UG", "KE") — a signed-in caller working in that
//     country;
//   - "" — a signed-in caller who works in no Active country: no row of a
//     guarded table is theirs.
//
// The pool is shared by every request, so the setting is written each time
// a connection is taken out (PrepareConn) whenever it differs from what that
// connection last carried; a connection can never keep a previous request's
// country. Policies read it with current_setting('edify.read_countries',
// true).
package countryctx

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// Setting is the session setting the guarded tables' policies read.
const Setting = "edify.read_countries"

// Every is the setting's value for every country.
const Every = "*"

// customKey is where a connection remembers the value it carries.
const customKey = "edify.read_countries"

// Wanted is the value of Setting for the request ctx belongs to.
func Wanted(ctx context.Context) string {
	p, ok := auth.PrincipalFrom(ctx)
	switch {
	case !ok:
		return Every
	case p.ActiveRole == "Admin" || country.IsRegional(p.ActiveRole):
		return Every
	case p.Country == nil:
		return ""
	}
	return p.Country.Code
}

// Prepare is the pool's PrepareConn: it writes Setting on conn when the
// value the request wants differs from what conn carries.
func Prepare(ctx context.Context, conn *pgx.Conn) (bool, error) {
	want := Wanted(ctx)
	data := conn.PgConn().CustomData()
	if have, ok := data[customKey].(string); ok && have == want {
		return true, nil
	}
	if _, err := conn.Exec(ctx, `SELECT set_config($1, $2, false)`, Setting, want); err != nil {
		// The connection's state is unknown: let the pool discard it.
		delete(data, customKey)
		return false, fmt.Errorf("countryctx: setting the request's country: %w", err)
	}
	data[customKey] = want
	return true, nil
}

// Configure makes every connection of cfg carry its request's country.
func Configure(cfg *pgxpool.Config) {
	cfg.PrepareConn = Prepare
}
