// Command clusterctl migrates the Cluster Leader Portal's own schema,
// cluster_leadership, on a development, test or staging database. It is the
// only code that applies those migrations; the gateway never does.
//
//	EDIFY_ENV=development \
//	EDIFY_MIGRATE_DATABASE_URL=postgresql://localhost:5432/edify_gorn_dev \
//	  clusterctl migrate --confirm-database=edify_gorn_dev
//
//	clusterctl status   # the applied version beside the one this build needs
//
// It refuses production (EDIFY_ENV=production), a URL the production guard
// refuses, and a database other than the one --confirm-database names.
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

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterlead/schema"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/dbguard"
)

const (
	envMigrateURL = "EDIFY_MIGRATE_DATABASE_URL"
	runTimeout    = 2 * time.Minute
)

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "clusterctl:", err)
		os.Exit(1)
	}
}

func run(args []string) error {
	if len(args) == 0 {
		return errors.New("usage: clusterctl migrate --confirm-database=NAME | clusterctl status")
	}
	command, rest := args[0], args[1:]
	flags := flag.NewFlagSet(command, flag.ContinueOnError)
	confirm := flags.String("confirm-database", "", "the database name the run is meant for")
	if err := flags.Parse(rest); err != nil {
		return err
	}

	cfg, err := config.LoadGuard(os.Getenv)
	if err != nil {
		return err
	}
	dsn := os.Getenv(envMigrateURL)
	if dsn == "" {
		return fmt.Errorf("%s is required (DATABASE_URL is never read)", envMigrateURL)
	}
	if _, err := dbguard.CheckDSN(dbguard.PolicyFrom(cfg), dsn); err != nil {
		return err
	}

	ctx, cancel := context.WithTimeout(context.Background(), runTimeout)
	defer cancel()
	conn, err := pgx.Connect(ctx, dsn)
	if err != nil {
		// The connection error can echo the URL; name the variable instead.
		return fmt.Errorf("connecting with %s failed", envMigrateURL)
	}
	defer func() { _ = conn.Close(context.Background()) }()

	switch command {
	case "status":
		version, err := schema.Version(ctx, conn)
		if err != nil {
			return err
		}
		fmt.Printf("%s: applied version %d, this build needs %d\n", schema.Name, version, schema.Required())
		return nil
	case "migrate":
		applied, err := schema.Apply(ctx, conn, *confirm)
		for _, migration := range applied {
			fmt.Printf("applied %04d %s\n", migration.Version, migration.Name)
		}
		if err != nil {
			return err
		}
		if len(applied) == 0 {
			fmt.Printf("%s is up to date (version %d)\n", schema.Name, schema.Required())
		}
		return nil
	default:
		return fmt.Errorf("unknown command %q (migrate or status)", command)
	}
}
