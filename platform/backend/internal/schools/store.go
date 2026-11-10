package schools

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
)

// ErrNotFound is returned when no school of the portfolio matches.
var ErrNotFound = errors.New("schools: not found")

// School is one row of the existing `school` table with its geography names.
type School struct {
	ID                  string
	SchoolID            string
	Name                string
	SchoolType          string
	OperationalStatus   string
	ClusterStatus       string
	CurrentFYSSAStatus  string
	PlanningReadiness   string
	Region              string
	District            string
	SubCounty           string
	Parish              string
	ClusterID           string
	Enrollment          *int32
	SalesforceAccountID string
}

// PortfolioFact is the little of a school the analytics worker receives.
type PortfolioFact struct {
	SchoolType string
	Enrollment *int32
}

// Querier is the read access the store needs; *pgxpool.Pool satisfies it.
type Querier interface {
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// Store reads schools. It never writes.
type Store struct {
	db Querier
}

// NewStore returns a Store reading through db.
func NewStore(db Querier) *Store {
	return &Store{db: db}
}

// portfolioPredicate is the direct portfolio of staff profile $1: schools
// that are not soft-deleted, are operating (the existing
// `_operationally_active` rule), and are assigned to that profile.
const portfolioPredicate = `
  s.deleted_at IS NULL
  AND s.operational_status IN ('active', 'reopened')
  AND s.id IN (SELECT a.school_id FROM staff_school_assignment a WHERE a.staff_id = $1)`

const selectSchool = `
SELECT s.id,
       s.school_id,
       s.name,
       s.school_type,
       s.operational_status,
       s.cluster_status,
       s.current_fy_ssa_status,
       s.planning_readiness,
       COALESCE(r.name, ''),
       COALESCE(d.name, ''),
       COALESCE(sc.name, ''),
       COALESCE(p.name, ''),
       COALESCE(s.cluster_id, ''),
       s.enrollment,
       COALESCE(s.salesforce_account_id, '')
FROM school s
LEFT JOIN region r ON r.id = s.region_id
LEFT JOIN district d ON d.id = s.district_id
LEFT JOIN sub_county sc ON sc.id = s.sub_county_id
LEFT JOIN parish p ON p.id = s.parish_id
WHERE` + portfolioPredicate

const searchPredicate = `
  AND ($2 = '' OR s.name ILIKE $2 ESCAPE '\' OR s.school_id ILIKE $2 ESCAPE '\')`

// maxPortfolioFacts bounds the rows sent to the analytics worker.
const maxPortfolioFacts = 20000

// List returns one page of the portfolio and the size of the whole result.
func (s *Store) List(ctx context.Context, staffProfileID, search string, limit, offset int) ([]School, int64, error) {
	pattern := likePattern(search)

	var total int64
	countSQL := `SELECT count(*) FROM school s WHERE` + portfolioPredicate + searchPredicate
	if err := s.db.QueryRow(ctx, countSQL, staffProfileID, pattern).Scan(&total); err != nil {
		return nil, 0, fmt.Errorf("schools: counting the portfolio: %w", err)
	}

	listSQL := selectSchool + searchPredicate + `
ORDER BY s.name, s.id
LIMIT $3 OFFSET $4`
	rows, err := s.db.Query(ctx, listSQL, staffProfileID, pattern, limit, offset)
	if err != nil {
		return nil, 0, fmt.Errorf("schools: listing the portfolio: %w", err)
	}
	schools, err := pgx.CollectRows(rows, scanSchool)
	if err != nil {
		return nil, 0, fmt.Errorf("schools: reading the portfolio: %w", err)
	}
	return schools, total, nil
}

// Get returns one school of the portfolio by Edify School ID, else by record
// id: the same order the existing application resolves a reference in.
func (s *Store) Get(ctx context.Context, staffProfileID, ref string) (School, error) {
	for _, column := range []string{"s.school_id", "s.id"} {
		rows, err := s.db.Query(ctx, selectSchool+` AND `+column+` = $2`, staffProfileID, ref)
		if err != nil {
			return School{}, fmt.Errorf("schools: reading a school: %w", err)
		}
		school, err := pgx.CollectOneRow(rows, scanSchool)
		if errors.Is(err, pgx.ErrNoRows) {
			continue
		}
		if err != nil {
			return School{}, fmt.Errorf("schools: reading a school: %w", err)
		}
		return school, nil
	}
	return School{}, ErrNotFound
}

// Facts returns the type and enrolment of every school in the portfolio.
func (s *Store) Facts(ctx context.Context, staffProfileID string) ([]PortfolioFact, error) {
	factsSQL := `SELECT s.school_type, s.enrollment FROM school s WHERE` + portfolioPredicate + `
ORDER BY s.id
LIMIT $2`
	rows, err := s.db.Query(ctx, factsSQL, staffProfileID, maxPortfolioFacts)
	if err != nil {
		return nil, fmt.Errorf("schools: reading portfolio facts: %w", err)
	}
	facts, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (PortfolioFact, error) {
		var fact PortfolioFact
		return fact, row.Scan(&fact.SchoolType, &fact.Enrollment)
	})
	if err != nil {
		return nil, fmt.Errorf("schools: reading portfolio facts: %w", err)
	}
	return facts, nil
}

func scanSchool(row pgx.CollectableRow) (School, error) {
	var school School
	err := row.Scan(
		&school.ID,
		&school.SchoolID,
		&school.Name,
		&school.SchoolType,
		&school.OperationalStatus,
		&school.ClusterStatus,
		&school.CurrentFYSSAStatus,
		&school.PlanningReadiness,
		&school.Region,
		&school.District,
		&school.SubCounty,
		&school.Parish,
		&school.ClusterID,
		&school.Enrollment,
		&school.SalesforceAccountID,
	)
	return school, err
}

// likePattern turns free text into a contains-pattern with the LIKE
// wildcards escaped, so "50%" searches for the text and not for everything.
func likePattern(search string) string {
	search = strings.TrimSpace(search)
	if search == "" {
		return ""
	}
	escaped := strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`).Replace(search)
	return "%" + escaped + "%"
}
