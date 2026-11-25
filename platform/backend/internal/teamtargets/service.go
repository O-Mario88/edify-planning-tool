package teamtargets

import (
	"context"
	"errors"
	"net/url"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is team_targets_view's address (with or without its slash).
const Path = "/team-targets"

// Service answers /team-targets.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService wires the page.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// Build is team_targets_view for p: the page, or served=false where the
// existing application keeps it (ErrHandOn).
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path && path != Path+"/" {
		return nil, false, nil
	}
	page, err := Page(ctx, s.db, p, Query(query), s.now())
	if errors.Is(err, ErrHandOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	page.WebPath = Path
	return page, true, nil
}

// Query is a request's query as the page reads it: each key's last value.
func Query(query url.Values) map[string]string {
	out := map[string]string{}
	for k, v := range query {
		if len(v) > 0 {
			out[k] = v[len(v)-1]
		}
	}
	return out
}
