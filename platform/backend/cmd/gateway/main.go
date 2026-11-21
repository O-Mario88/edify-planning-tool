// Command gateway is the Edify mobile-facing API gateway.
//
// It serves Protocol Buffer contracts over the Connect protocol (which also
// answers gRPC and gRPC-Web on the same routes), verifies the existing
// identity system's access tokens, and reads the existing database through a
// read-only connection that the production-protection guard has approved.
//
// It contains no schema migration code and never runs DDL.
package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/analytics"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/countryctx"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/dbguard"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/server"
)

const (
	maxDBConnections  = 8
	startupTimeout    = 10 * time.Second
	shutdownTimeout   = 15 * time.Second
	readHeaderTimeout = 5 * time.Second
	readTimeout       = 15 * time.Second
	writeTimeout      = 30 * time.Second
	idleTimeout       = 120 * time.Second
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	if err := run(logger); err != nil {
		logger.Error("gateway stopped", slog.String("error", err.Error()))
		os.Exit(1)
	}
}

func run(logger *slog.Logger) error {
	cfg, err := config.Load(os.Getenv)
	if err != nil {
		return err
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	pool, err := openDatabase(ctx, cfg, logger)
	if err != nil {
		return err
	}
	defer pool.Close()

	var summarizer schools.Summarizer
	if cfg.AnalyticsAddr != "" {
		client, dialErr := analytics.Dial(cfg.AnalyticsAddr)
		if dialErr != nil {
			return dialErr
		}
		defer func() { _ = client.Close() }()
		summarizer = client
	}

	// The School Loan Application Portal's delivery worker: it sends each
	// lender its referral notification from the outbox, with retries.
	var workers sync.WaitGroup
	startWorker := func(fn func()) {
		workers.Add(1)
		go func() {
			defer workers.Done()
			fn()
		}()
	}
	worker := loans.NewWorker(loans.NewStore(pool), loans.NewMailer(cfg.Loans), cfg.Loans.PublicBaseURL, logger, time.Now)
	startWorker(func() { worker.Run(ctx, server.LoansSchemaReady(pool)) })
	// School notifications and weekly repayment reminders. Without an SMS
	// provider they wait in the history marked as such; none is claimed sent.
	smsWorker := loans.NewSMSWorker(loans.NewStore(pool), loans.NewSMSProvider(cfg.Loans), loans.DeriveKeys(cfg.JWTSecret),
		cfg.Loans.PublicBaseURL, logger, time.Now).WithCooldown(cfg.Loans.ReminderCooldownDays)
	startWorker(func() { smsWorker.Run(ctx, server.LoansSchemaReady(pool)) })
	// Cluster Actions: reminders, overdue notices and policy escalation every
	// thirty minutes; notices relayed into Edify's notifications every minute.
	actions, noticeSender, clusterReady := server.ClusterActionFollowUp(cfg, pool, logger)
	if noticeSender == nil {
		logger.Warn("cluster actions: no EDIFY_INTERNAL_KEY or existing application; notices stay queued")
	}
	startWorker(func() { actions.RunFollowUp(ctx, noticeSender, 30*time.Minute, clusterReady, logger) })

	server := &http.Server{
		Addr:              cfg.HTTPAddr,
		Handler:           server.New(cfg, pool, summarizer, logger),
		ReadHeaderTimeout: readHeaderTimeout,
		ReadTimeout:       readTimeout,
		WriteTimeout:      writeTimeout,
		IdleTimeout:       idleTimeout,
		Protocols:         protocols(),
	}

	failed := make(chan error, 1)
	go func() {
		logger.Info("gateway listening",
			slog.String("addr", cfg.HTTPAddr),
			slog.String("environment", string(cfg.Env)),
			slog.String("release", cfg.Release),
		)
		if serveErr := server.ListenAndServe(); !errors.Is(serveErr, http.ErrServerClosed) {
			failed <- serveErr
		}
	}()

	select {
	case err := <-failed:
		stop()
		return fmt.Errorf("gateway: serving: %w", err)
	case <-ctx.Done():
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()
	if err := server.Shutdown(shutdownCtx); err != nil {
		return fmt.Errorf("gateway: shutting down: %w", err)
	}
	workersDone := make(chan struct{})
	go func() {
		workers.Wait()
		close(workersDone)
	}()
	select {
	case <-workersDone:
	case <-shutdownCtx.Done():
		logger.Warn("gateway: background workers did not exit before shutdown timeout")
	}
	return nil
}

func configuredMaxDBConns() int32 {
	raw := strings.TrimSpace(os.Getenv("EDIFY_DB_MAX_CONNS"))
	if raw == "" {
		return maxDBConnections
	}
	n, err := strconv.Atoi(raw)
	if err != nil || n < 2 {
		return maxDBConnections
	}
	if n > 64 {
		return 64
	}
	return int32(n)
}

// openDatabase is the only way the gateway obtains a connection pool, and it
// cannot return one that the production-protection guard has not approved.
func openDatabase(ctx context.Context, cfg config.Config, logger *slog.Logger) (*pgxpool.Pool, error) {
	policy := dbguard.PolicyFrom(cfg)
	target, err := dbguard.CheckDSN(policy, cfg.DatabaseURL)
	if err != nil {
		return nil, err
	}

	poolConfig, err := pgxpool.ParseConfig(cfg.DatabaseURL)
	if err != nil {
		return nil, errors.New("gateway: the database URL could not be parsed")
	}
	poolConfig.MaxConns = configuredMaxDBConns()
	// Every session starts read-only. The database role is the real limit
	// (deploy/db/roles.sql); this makes an accidental write fail even where
	// a developer connects with a broader local role.
	poolConfig.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	poolConfig.ConnConfig.RuntimeParams["application_name"] = "edify-gateway"
	// Each connection carries the country its request is made in, for the
	// guarded tables' row-level security (docs/migration/80, §23).
	countryctx.Configure(poolConfig)

	ctx, cancel := context.WithTimeout(ctx, startupTimeout)
	defer cancel()
	pool, err := pgxpool.NewWithConfig(ctx, poolConfig)
	if err != nil {
		return nil, fmt.Errorf("gateway: opening the database pool: %w", err)
	}
	identity, err := dbguard.VerifyIdentity(ctx, policy, pool)
	if err != nil {
		pool.Close()
		return nil, err
	}
	logger.Info("database approved by the production-protection guard",
		slog.Any("hosts", target.Hosts),
		slog.String("database", identity.Database),
		slog.String("role", identity.Role),
		slog.Bool("superuser", identity.Superuser),
		slog.Any("writable_protected_tables", identity.WritableTables),
	)
	return pool, nil
}

// protocols enables HTTP/1.1 and cleartext HTTP/2, so gRPC clients work
// behind a TLS-terminating load balancer. TLS itself is the platform's.
func protocols() *http.Protocols {
	enabled := new(http.Protocols)
	enabled.SetHTTP1(true)
	enabled.SetUnencryptedHTTP2(true)
	return enabled
}
