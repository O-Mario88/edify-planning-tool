package ccelead

import (
	"context"
	"net/url"
	"time"

	_ "time/tzdata" // the reader's day is Nairobi's wherever the gateway runs

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("ccelead: " + err.Error())
	}
	return z
}()

// Service builds the CCE leadership registers.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// Build answers path for p. served is false for a path this package does not
// answer.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != ReportsPath && path != FeedbackPath && path != EngagementsPath && path != MyCoachingPath && path != TeamCoachingPath {
		return nil, false, nil
	}
	// An acting lead leads the appointing Lead's officers from that Lead's
	// seat, which Team Coaching has not taken over: the existing page answers.
	if path == TeamCoachingPath && p.InActingAppointment {
		return nil, false, nil
	}
	role, ok := rules.Pages[path].Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, pagegate.ErrNotAvailable
	}
	build := reports
	if path == FeedbackPath {
		build = feedback
	}
	if path == MyCoachingPath {
		build = func(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) (register, error) {
			return myCoaching(ctx, db, p, now, query)
		}
	}
	if path == TeamCoachingPath {
		build = func(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) (register, error) {
			return teamCoaching(ctx, db, p, now, query)
		}
	}
	if path == EngagementsPath {
		build = func(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) (register, error) {
			return engagements(ctx, db, p, now, query)
		}
	}
	reg, err := build(ctx, s.db, p, s.now())
	if err != nil {
		return nil, true, err
	}
	return render(reg, role, query), true, nil
}
