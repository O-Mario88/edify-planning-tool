// Package schoolcode is what the web writes for a {% school_code %} tag once
// a page has rendered (apps/core/school_identity_middleware.py): the tag
// leaves a placeholder naming a school by its record id or its School ID,
// and the middleware fills in the School ID of the live school it names, or
// "ID unavailable". The feed now runs that middleware too (2026-11-20), so
// a Go page writes the same words where it used to read the placeholder as
// nothing, and the apps' School ID columns stop reading empty.
package schoolcode

import (
	"context"
	"fmt"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Unavailable is what the middleware writes for a school it cannot name.
const Unavailable = "ID unavailable"

// Codes are the School IDs of the live schools some references name, keyed
// by record id and by School ID, as the middleware reads them.
type Codes map[string]string

// Lookup reads the School IDs of the live schools (School.objects: not
// deleted) that refs name, by record id or by School ID, in one query.
func Lookup(ctx context.Context, db schooldirectory.Querier, refs []string) (Codes, error) {
	out := Codes{}
	wanted := []string{}
	for _, r := range refs {
		if r != "" {
			wanted = append(wanted, r)
		}
	}
	if len(wanted) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `
SELECT id, COALESCE(school_id, '') FROM school
WHERE deleted_at IS NULL AND (id = ANY($1) OR school_id = ANY($1))`, wanted)
	if err != nil {
		return nil, fmt.Errorf("schoolcode: reading the School IDs: %w", err)
	}
	defer rows.Close()
	byCode := Codes{}
	for rows.Next() {
		var id, code string
		if err := rows.Scan(&id, &code); err != nil {
			return nil, err
		}
		out[id] = code
		if code != "" {
			byCode[code] = code
		}
	}
	for code := range byCode {
		if _, isID := out[code]; !isID {
			out[code] = code
		}
	}
	return out, rows.Err()
}

// Of is the words the web writes for a school_code tag naming ref: its
// School ID, or "ID unavailable" for a school not found or without one.
func (c Codes) Of(ref string) string {
	if code := c[ref]; code != "" {
		return code
	}
	return Unavailable
}
