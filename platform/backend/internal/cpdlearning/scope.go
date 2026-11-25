package cpdlearning

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrregister"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// errHandOn is a reader the page passes on to the existing system.
var errHandOn = errors.New("cpdlearning: hand the page on")

// scope is _scoped_staff_ids: every staff id (all), or the ones listed, and
// the country a Country Director is held to.
type scope struct {
	all    bool
	ids    []string
	locked string
}

// where is the scope as a condition on a staff id column, its argument
// appended to args.
func (s scope) where(col string, args []any) (string, []any) {
	if s.all {
		return "TRUE", args
	}
	args = append(args, s.ids)
	return fmt.Sprintf("%s = ANY($%d)", col, len(args)), args
}

func readScope(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) (scope, error) {
	switch p.ActiveRole {
	case "Admin":
		return scope{all: true}, nil
	case "HumanResources":
		where, args, everything, err := hrregister.PeopleReachProfiles(ctx, db, p, nil)
		if err != nil {
			return scope{}, fmt.Errorf("cpdlearning: reading the reader's reach: %w", err)
		}
		if everything {
			return scope{all: true}, nil
		}
		ids, err := strings1(ctx, db, `SELECT sp.id FROM staff_profile sp WHERE sp.deleted_at IS NULL AND `+where, args...)
		return scope{ids: ids}, err
	case "CountryDirector":
		var country *string
		err := db.QueryRow(ctx, `
SELECT country FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL ORDER BY id LIMIT 1`, p.UserID).Scan(&country)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return scope{}, fmt.Errorf("cpdlearning: reading the director's country: %w", err)
		}
		if country == nil || *country == "" {
			return scope{ids: []string{}}, nil
		}
		ids, err := strings1(ctx, db, `SELECT id FROM staff_profile WHERE deleted_at IS NULL AND country = $1`, *country)
		return scope{ids: ids, locked: *country}, err
	case "Program Lead":
		// The Lead's live supervisees (resolve_user_scope's supervised_staff_ids).
		sc, err := schooldirectory.ResolveScope(ctx, db, p, now)
		if err != nil {
			return scope{}, fmt.Errorf("cpdlearning: resolving the reader's scope: %w", err)
		}
		ids := sc.SupervisedStaffIDs
		if ids == nil {
			ids = []string{}
		}
		return scope{ids: ids}, nil
	case "RegionalVicePresident":
		sc, err := schooldirectory.ResolveScope(ctx, db, p, now)
		if err != nil {
			return scope{}, fmt.Errorf("cpdlearning: resolving the reader's scope: %w", err)
		}
		if sc.SummaryOnly && len(sc.RegionIDs) > 0 {
			return scope{}, errHandOn
		}
		return scope{all: true}, nil
	}
	return scope{ids: []string{}}, nil
}

func strings1(ctx context.Context, db schooldirectory.Querier, sql string, args ...any) ([]string, error) {
	rows, err := db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: reading the scope: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (string, error) {
		var v *string
		err := row.Scan(&v)
		if v == nil {
			return "", err
		}
		return strings.Clone(*v), err
	})
	if err != nil {
		return nil, fmt.Errorf("cpdlearning: reading the scope: %w", err)
	}
	return out, nil
}
