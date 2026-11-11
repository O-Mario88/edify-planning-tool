// Command schemactl migrates one of the gateway's Go-owned schemas on a
// development, test or staging database. It is the only code that applies
// their migrations; the gateway never does.
//
//	EDIFY_ENV=development \
//	EDIFY_MIGRATE_DATABASE_URL=postgresql://localhost:5432/edify_gorn_dev \
//	  schemactl migrate --schema=school_loans --confirm-database=edify_gorn_dev
//
//	schemactl status   # every schema's applied version beside the one this build needs
//
// It refuses production (EDIFY_ENV=production), a URL the production guard
// refuses, and a database other than the one --confirm-database names.
// DATABASE_URL is never read. (clusterctl remains for cluster_leadership.)
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	clusterschema "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterlead/schema"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/dbguard"
	loanschema "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/schema"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/ownedschema"
)

const (
	envMigrateURL = "EDIFY_MIGRATE_DATABASE_URL"
	runTimeout    = 2 * time.Minute
)

var schemas = map[string]ownedschema.Spec{
	clusterschema.Name: clusterschema.Spec,
	loanschema.Name:    loanschema.Spec,
}

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "schemactl:", err)
		os.Exit(1)
	}
}

func names() string {
	list := make([]string, 0, len(schemas))
	for name := range schemas {
		list = append(list, name)
	}
	sort.Strings(list)
	return strings.Join(list, ", ")
}

func run(args []string) error {
	if len(args) == 0 {
		return errors.New("usage: schemactl migrate --schema=NAME --confirm-database=NAME | schemactl status")
	}
	command, rest := args[0], args[1:]
	flags := flag.NewFlagSet(command, flag.ContinueOnError)
	confirm := flags.String("confirm-database", "", "the database name the run is meant for")
	chosen := flags.String("schema", "", "the schema to migrate: "+names())
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
		for _, name := range strings.Split(names(), ", ") {
			spec := schemas[name]
			version, err := spec.Version(ctx, conn)
			if err != nil {
				return err
			}
			fmt.Printf("%s: applied version %d, this build needs %d\n", name, version, spec.Required())
		}
		return nil
	case "migrate":
		spec, ok := schemas[*chosen]
		if !ok {
			return fmt.Errorf("--schema must be one of %s", names())
		}
		applied, err := spec.Apply(ctx, conn, *confirm)
		for _, migration := range applied {
			fmt.Printf("applied %s %04d %s\n", spec.Name, migration.Version, migration.Name)
		}
		if err != nil {
			return err
		}
		if len(applied) == 0 {
			fmt.Printf("%s is up to date (version %d)\n", spec.Name, spec.Required())
		}
		return nil
	default:
		return fmt.Errorf("unknown command %q (migrate or status)", command)
	}
}
