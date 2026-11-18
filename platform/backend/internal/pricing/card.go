package pricing

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing"
)

// Querier is the database the package reads.
type Querier interface {
	Query(ctx context.Context, sql string, args ...any) (pgx.Rows, error)
	QueryRow(ctx context.Context, sql string, args ...any) pgx.Row
}

// Setting is one rate card row as the recipe reads it.
type Setting struct {
	Key, Label      string
	UnitCost        int64
	ApprovedMinimum *int64
	ItemID          *string
}

// Card is one published rate card and what it prices with
// (costing_service._read_rate_card): one setting a key, each renamed key
// answered by its canonical one, only the canonical and the linked kept, in
// the card's order (the rows by label).
type Card struct {
	ID           string
	Version      int
	ThresholdBps *int
	Rates        map[string]int64
	Settings     map[string]Setting
	Order        []Setting
}

// ReadCard is active_catalogue(kind, on_date) and its rate card: the newest
// published, active card of the country of that kind (in force on the day,
// when there is one), or nil.
func ReadCard(ctx context.Context, db Querier, kind string, onDate *time.Time) (*Card, error) {
	c := &Card{}
	q := `
		SELECT id, version, material_difference_threshold_bps FROM cost_catalogue
		WHERE country = $1 AND kind = $2 AND status = $3 AND is_active`
	// The request's country's card (docs/migration/80, §18): Uganda's
	// wherever the caller works there or there is no caller.
	args := []any{auth.SettingsName(ctx, rules.Country), kind, rules.PublishedStatus}
	if onDate != nil {
		q += ` AND (effective_from IS NULL OR effective_from <= $4) AND (effective_to IS NULL OR effective_to >= $4)`
		args = append(args, *onDate)
	}
	q += ` ORDER BY fy DESC, version DESC LIMIT 1`
	err := db.QueryRow(ctx, q, args...).Scan(&c.ID, &c.Version, &c.ThresholdBps)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("pricing: reading the %s card: %w", kind, err)
	}
	renamed := []string{}
	for _, a := range costing.Aliases() {
		renamed = append(renamed, a.Old...)
	}
	rows, err := db.Query(ctx, `
		SELECT key, label, unit_cost, approved_minimum, catalogue_item_id FROM cost_setting
		WHERE catalogue_id = $1 AND (key = ANY($2) OR key = ANY($3) OR catalogue_item_id IS NOT NULL)
		ORDER BY label, id`, c.ID, costing.CanonicalRateKeys(), renamed)
	if err != nil {
		return nil, fmt.Errorf("pricing: reading the %s card's rates: %w", kind, err)
	}
	all, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (Setting, error) {
		var s Setting
		err := row.Scan(&s.Key, &s.Label, &s.UnitCost, &s.ApprovedMinimum, &s.ItemID)
		return s, err
	})
	if err != nil {
		return nil, fmt.Errorf("pricing: reading the %s card's rates: %w", kind, err)
	}
	c.resolve(all)
	return c, nil
}

// Resolve is the card's pricing over its rows in the card's order (for a
// caller that read them itself).
func Resolve(rows []Setting) *Card {
	c := &Card{}
	c.resolve(rows)
	return c
}

func (c *Card) resolve(rows []Setting) {
	keys := []string{}
	byKey := map[string]Setting{}
	for _, r := range rows {
		if _, seen := byKey[r.Key]; !seen {
			keys = append(keys, r.Key)
		}
		byKey[r.Key] = r
	}
	for _, a := range costing.Aliases() {
		if _, ok := byKey[a.Key]; ok {
			continue
		}
		for _, old := range a.Old {
			if r, ok := byKey[old]; ok {
				keys = append(keys, a.Key)
				byKey[a.Key] = r
				break
			}
		}
	}
	c.Rates, c.Settings, c.Order = map[string]int64{}, map[string]Setting{}, nil
	for _, key := range keys {
		r := byKey[key]
		if !costing.IsCanonical(key) && r.ItemID == nil {
			continue
		}
		c.Rates[key] = r.UnitCost
		c.Settings[key] = r
		c.Order = append(c.Order, r)
	}
}

// LinkedRates is _with_linked_rates: the costs the card links to the
// catalogue item, in the card's order, as (key, label).
func (c *Card) LinkedRates(itemID string) [][2]string {
	if c == nil || itemID == "" {
		return nil
	}
	var out [][2]string
	for _, s := range c.Order {
		if s.ItemID != nil && *s.ItemID == itemID {
			out = append(out, [2]string{s.Key, s.Label})
		}
	}
	return out
}
