// Command countryctl seeds Edify Global's country registry on a development,
// test or staging database: the countries (UG Active; KE, RW, ET Draft),
// Uganda's settings as the platform runs today, and every existing school
// and account mapped to Uganda (internal/country SeedLegacy), and Uganda's
// levels of administrative units with every existing unit mapped in by id
// (SeedGeography). It writes only country_registry's tables and reads only
// the existing school, account and geography rows. Run again, it adds only
// what is missing. reconcile-geography only reads: it compares every
// existing geography table with the registry one to one.
//
//	EDIFY_ENV=development \
//	EDIFY_MIGRATE_DATABASE_URL=postgresql://localhost:5432/edify_gorn_dev \
//	  countryctl seed-legacy --confirm-database=edify_gorn_dev
//
// It refuses production (EDIFY_ENV=production), a URL the production guard
// refuses, a database other than the one --confirm-database names, and a
// database whose country_registry is not migrated to this build's version.
// DATABASE_URL is never read.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	countryschema "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country/schema"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/dbguard"
)

const (
	envURL     = "EDIFY_MIGRATE_DATABASE_URL"
	runTimeout = 2 * time.Minute
	seededBy   = "countryctl"
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "countryctl:", err)
		os.Exit(1)
	}
}

func run(args []string) error {
	if len(args) == 0 || (args[0] != "seed-legacy" && args[0] != "seed-templates" && args[0] != "reconcile-geography") {
		return errors.New("usage: countryctl seed-legacy|seed-templates|reconcile-geography --confirm-database=NAME")
	}
	flags := flag.NewFlagSet(args[0], flag.ContinueOnError)
	confirm := flags.String("confirm-database", "", "the database name the run is meant for")
	if err := flags.Parse(args[1:]); err != nil {
		return err
	}
	cfg, err := config.LoadGuard(os.Getenv)
	if err != nil {
		return err
	}
	dsn := os.Getenv(envURL)
	if dsn == "" {
		return fmt.Errorf("%s is required (DATABASE_URL is never read)", envURL)
	}
	if _, err := dbguard.CheckDSN(dbguard.PolicyFrom(cfg), dsn); err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), runTimeout)
	defer cancel()
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		// The connection error can echo the URL; name the variable instead.
		return fmt.Errorf("connecting with %s failed", envURL)
	}
	defer func() { _ = conn.Close(context.Background()) }()
	if *confirm == "" || *confirm != conn.Config().Database {
		return fmt.Errorf("--confirm-database must name the database the URL opens (%q)", conn.Config().Database)
	}
	version, err := countryschema.Spec.Version(ctx, conn)
	if err != nil {
		return err
	}
	if version != countryschema.Spec.Required() {
		return fmt.Errorf("country_registry is at version %d, this build needs %d: run schemactl migrate first",
			version, countryschema.Spec.Required())
	}
	if args[0] == "reconcile-geography" {
		return reconcileGeography(ctx, conn, *confirm)
	}
	tx, err := conn.Begin(ctx)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback(context.Background()) }()
	if args[0] == "seed-templates" {
		tpls, err := country.SeedExpansionTemplates(ctx, tx, seededBy)
		if err != nil {
			return err
		}
		if err := tx.Commit(ctx); err != nil {
			return err
		}
		fmt.Printf("seeded expansion templates on %s: %d country configs, %d admin levels\n", *confirm, tpls.Configs, tpls.Levels)
		return nil
	}
	seeded, err := country.SeedLegacy(ctx, tx, seededBy)
	if err != nil {
		return err
	}
	geography, err := country.SeedGeography(ctx, tx, seededBy)
	if err != nil {
		return err
	}
	if err := tx.Commit(ctx); err != nil {
		return err
	}
	fmt.Printf("seeded %s: %d countries, %d settings, %d names, %d schools, %d memberships, %d role sources, %d partners, %d unit levels, %d units\n", *confirm,
		seeded.Countries, seeded.Settings, seeded.Aliases, seeded.Schools, seeded.Memberships, seeded.RolesSources, seeded.Partners,
		geography.Types, geography.Units)
	return nil
}

// reconcileGeography prints how every existing geography table stands
// against the registry, one line a table, and fails when any is not mapped
// one to one. It only reads.
func reconcileGeography(ctx context.Context, conn *pgx.Conn, database string) error {
	levels, err := country.Reconcile(ctx, conn)
	if err != nil {
		return err
	}
	apart := 0
	for _, l := range levels {
		mark := "ok"
		if !l.Reconciled() {
			mark, apart = "APART", apart+1
		}
		fmt.Printf("%-10s %-5s existing %6d  mapped %6d  renamed %d  moved %d  unmapped %v\n",
			l.Table, mark, l.Existing, l.Mapped, l.Renamed, l.Moved, l.Unmapped)
	}
	if apart > 0 {
		return fmt.Errorf("%s: %d geography tables are not mapped one to one", database, apart)
	}
	fmt.Printf("%s: geography reconciled one to one\n", database)
	return nil
}
