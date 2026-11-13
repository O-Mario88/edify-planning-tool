package hrregister

import (
	"context"
	"net/url"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ErrNotAvailable is a register refused to the reader's role, which the
// existing feed answers as a page that is not there.
var ErrNotAvailable = pagegate.ErrNotAvailable

// builders are the registers Go answers, by path.
var builders = map[string]func(context.Context, schooldirectory.Querier, reach, url.Values) (register, error){
	"/org-structure": orgStructure,
}

// Service builds the HR registers.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the service to the database it reads.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// Build answers path for p with the page's query. served is false for a
// path this package does not answer.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	build, ok := builders[path]
	if !ok {
		return nil, false, nil
	}
	role, ok := rules.Pages[path].Roles[p.ActiveRole]
	if !ok || !role.Page {
		return nil, true, ErrNotAvailable
	}
	r, err := peopleReach(ctx, s.db, p)
	if err != nil {
		return nil, true, err
	}
	reg, err := build(ctx, s.db, r, query)
	if err != nil {
		return nil, true, err
	}
	return render(reg, role, query), true, nil
}
