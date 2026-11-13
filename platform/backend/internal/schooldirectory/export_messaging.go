package schooldirectory

import (
	"context"
	"errors"
	"fmt"

	"github.com/jackc/pgx/v5"
)

// UnheldInCountry is data_gaps.unheld(country).filter(id=schoolID).exists():
// an operating school nobody holds, in the country when one is named, for the
// Messages inbox's record gate (internal/messaging).
func UnheldInCountry(ctx context.Context, q Querier, country, schoolID string) (bool, error) {
	b := unheldBase(country)
	b.and("s.id = " + b.arg(schoolID))
	var found bool
	if err := q.QueryRow(ctx, "SELECT EXISTS (SELECT 1 FROM school s WHERE "+b.where()+")", b.args...).Scan(&found); err != nil {
		return false, fmt.Errorf("schooldirectory: reading whether the school is held: %w", err)
	}
	return found, nil
}

// OfficerCountry is data_gaps.country_of: the country on the person's live
// staff profile (the first by id), or "".
func OfficerCountry(ctx context.Context, q Querier, userID string) (string, error) {
	var country *string
	err := q.QueryRow(ctx, `SELECT country FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL ORDER BY id ASC LIMIT 1`, userID).Scan(&country)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("schooldirectory: reading the officer's country: %w", err)
	}
	if country == nil {
		return "", nil
	}
	return *country, nil
}
