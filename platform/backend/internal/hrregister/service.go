package hrregister

import (
	"context"
	"net/url"
	"time"

	_ "time/tzdata" // the server's day is Nairobi's wherever the gateway runs

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// ErrNotAvailable is a register refused to the reader's role, which the
// existing feed answers as a page that is not there.
var ErrNotAvailable = pagegate.ErrNotAvailable

// input is what a register is built from.
type input struct {
	db    schooldirectory.Querier
	reach reach
	query url.Values
	// search is the register's search, stripped.
	search string
	// today is date.today(): the server's day, Nairobi's.
	today time.Time
	// now is the moment of the request (get_operational_fy reads it in UTC).
	now time.Time
}

// builders are the registers Go answers, by path.
var builders = map[string]func(context.Context, input) (register, error){
	"/org-structure":       orgStructure,
	"/recognition":         recognition,
	"/health-safety":       healthSafety,
	"/onboarding":          onboarding,
	"/offboarding":         offboarding,
	"/candidate-pipeline":  candidatePipeline,
	"/compliance-register": complianceRegister,
	"/hr-audit-log":        hrAuditLog,
	"/workforce-planning":  workforcePlanning,
	"/policies":            policies,
}

// zone is settings.TIME_ZONE, the zone the server's day is read in.
var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		panic("hrregister: " + err.Error())
	}
	return z
}()

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
	now := s.now().In(zone)
	in := input{db: s.db, reach: r, query: query, search: closedschools.StripSpace(query.Get("q")),
		today: time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC), now: now}
	reg, err := build(ctx, in)
	if err != nil {
		return nil, true, err
	}
	return render(reg, role, query), true, nil
}
