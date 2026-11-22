// Command scheduler is the standalone Go background-job runner replacing
// Django's runscheduler.py. It opens its database through dbguard, enforces
// single-executor execution via PostgreSQL advisory locks, and shuts down
// cleanly on SIGINT/SIGTERM.
package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/config"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/countryctx"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/dbguard"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/scheduler"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/server"
)

const (
	lockClusterFollowUp = 400101
	lockHealthHeartbeat = 400102
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	if err := run(logger); err != nil {
		logger.Error("scheduler stopped", slog.String("error", err.Error()))
		os.Exit(1)
	}
}

func run(logger *slog.Logger) error {
	cfg, err := config.Load(os.Getenv)
	if err != nil {
		return err
	}
	if _, err := time.LoadLocation("Africa/Kampala"); err != nil {
		return fmt.Errorf("scheduler: loading Africa/Kampala timezone: %w", err)
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	policy := dbguard.PolicyFrom(cfg)
	if _, err := dbguard.CheckDSN(policy, cfg.DatabaseURL); err != nil {
		return err
	}
	poolCfg, err := pgxpool.ParseConfig(cfg.DatabaseURL)
	if err != nil {
		return fmt.Errorf("scheduler: parsing database URL")
	}
	poolCfg.MaxConns = 4
	poolCfg.ConnConfig.RuntimeParams["default_transaction_read_only"] = "on"
	poolCfg.ConnConfig.RuntimeParams["application_name"] = "edify-scheduler"
	countryctx.Configure(poolCfg)

	startupCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	pool, err := pgxpool.NewWithConfig(startupCtx, poolCfg)
	if err != nil {
		return fmt.Errorf("scheduler: opening database pool: %w", err)
	}
	defer pool.Close()
	if _, err := dbguard.VerifyIdentity(startupCtx, policy, pool); err != nil {
		return err
	}

	actions, noticeSender, clusterReady := server.ClusterActionFollowUp(cfg, pool, logger)
	jobs := append([]scheduler.Job{
		{
			Name:     "cluster_action_followup",
			LockKey:  lockClusterFollowUp,
			Interval: 30 * time.Minute,
			Run: func(jctx context.Context) error {
				if err := clusterReady(jctx); err != nil {
					return err
				}
				if _, err := actions.FollowUp(jctx); err != nil {
					return err
				}
				if noticeSender != nil {
					_, err := actions.RelayNotices(jctx, noticeSender)
					return err
				}
				return nil
			},
		},
		{
			Name:     "scheduler_heartbeat",
			LockKey:  lockHealthHeartbeat,
			Interval: 5 * time.Minute,
			Run: func(jctx context.Context) error {
				return pool.Ping(jctx)
			},
		},
	}, scheduler.BuildUgandaJobs(pool)...)
	runner := scheduler.NewRunner(
		scheduler.NewPGLocker(pool),
		logger,
		time.Now,
		jobs...,
	)

	logger.Info("go scheduler started",
		slog.String("environment", string(cfg.Env)),
		slog.String("release", cfg.Release),
		slog.Bool("django_absent", cfg.ExistingAppURL == ""),
	)
	runner.Start(ctx)
	logger.Info("go scheduler exited cleanly")
	return nil
}
