package costsettings

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pricing"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Service builds the two doors.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// The query the page reads: the year and each table's page.
const (
	ratesPageParam    = "cost_items_page"
	coveragePageParam = "activity_coverage_page"
)

var ownQuery = []string{"fy", ratesPageParam, coveragePageParam}

type catalogue struct {
	id, kind, country, fy string
	version               int
	provisional           bool
}

type rate struct {
	key, label, unit string
	unitCost         int64
	minimum          *int64
	version          int
	itemID, itemName *string
}

type item struct {
	id, name, workflowKind, profile, activityType, delivery string
	primaryIntervention                                     *string
	hasPrimary                                              bool
}

type review struct {
	activity, reason, status string
	current                  int64
	proposed                 *int64
}

// Build answers the two doors; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != SettingsPath && path != IntelligencePath {
		return nil, false, nil
	}
	if !mayOpen(p.ActiveRole, path) {
		return nil, true, pagegate.ErrNotAvailable
	}
	for key := range query {
		if !slices.Contains(ownQuery, key) {
			return nil, false, nil
		}
	}
	now := s.now()
	fy := strings.TrimSpace(query.Get("fy"))
	if fy == "" {
		fy = schooldirectory.OperationalFY(now)
	}
	if !slices.Contains(schooldirectory.FYOptions(now), fy) {
		return nil, false, nil
	}
	card, err := s.catalogue(ctx)
	if err != nil {
		return nil, true, err
	}
	if card == nil || card.provisional {
		return nil, false, nil
	}
	shown, priced, err := s.rates(ctx, card.id)
	if err != nil {
		return nil, true, err
	}
	local := now.In(zone)
	items, err := s.items(ctx, time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC))
	if err != nil {
		return nil, true, err
	}
	if len(shown) == 0 || len(items) == 0 {
		return nil, false, nil
	}
	coverage, ok := coverageOf(items, priced)
	if !ok {
		return nil, false, nil
	}
	var reviews []review
	if rules.Roles[p.ActiveRole].Reference {
		if reviews, err = s.reviews(ctx); err != nil {
			return nil, true, err
		}
	}
	v := view{
		path: path, fy: fy, years: schooldirectory.FYOptions(now), role: rules.Roles[p.ActiveRole],
		card: *card, rates: shown, coverage: coverage, reviews: reviews, query: query,
	}
	blocks, ok := v.blocks()
	if !ok {
		return nil, false, nil
	}
	return &screensv1.GetPageResponse{Header: v.header(), Blocks: blocks, WebPath: path}, true, nil
}

// catalogue is active_catalogue(): the newest published, active country
// operational card.
func (s *Service) catalogue(ctx context.Context) (*catalogue, error) {
	var c catalogue
	err := s.db.QueryRow(ctx, `
		SELECT id, kind, country, fy, version, is_provisional
		FROM cost_catalogue
		WHERE country = $1 AND kind = $2 AND status = $3 AND is_active
		ORDER BY fy DESC, version DESC
		LIMIT 1`, auth.SettingsName(ctx, rules.Country), rules.OperationalKind, rules.PublishedStatus,
	).Scan(&c.id, &c.kind, &c.country, &c.fy, &c.version, &c.provisional)
	if err == pgx.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("costsettings: reading the published card: %w", err)
	}
	return &c, nil
}

// rates reads the card's rows once, in the model's order (label): the rows
// the register SHOWS (visible_rates), and the card it PRICES with
// (pricing_rates, with every renamed key answered by its canonical one).
func (s *Service) rates(ctx context.Context, catalogueID string) ([]rate, *pricing.Card, error) {
	renamed := []string{}
	for _, a := range costing.Aliases() {
		renamed = append(renamed, a.Old...)
	}
	rows, err := s.db.Query(ctx, `
		SELECT cs.key, cs.label, cs.unit, cs.unit_cost, cs.approved_minimum, cs.version,
		       cs.catalogue_item_id, i.display_name
		FROM cost_setting cs
		LEFT JOIN activity_catalogue_item i ON i.id = cs.catalogue_item_id
		WHERE cs.catalogue_id = $1
		  AND (cs.key = ANY($2) OR cs.key = ANY($3) OR cs.catalogue_item_id IS NOT NULL)
		ORDER BY cs.label, cs.id`, catalogueID, costing.CanonicalRateKeys(), renamed)
	if err != nil {
		return nil, nil, fmt.Errorf("costsettings: reading the card's rates: %w", err)
	}
	all, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (rate, error) {
		var r rate
		err := row.Scan(&r.key, &r.label, &r.unit, &r.unitCost, &r.minimum, &r.version, &r.itemID, &r.itemName)
		return r, err
	})
	if err != nil {
		return nil, nil, fmt.Errorf("costsettings: reading the card's rates: %w", err)
	}
	shown := []rate{}
	for _, r := range all {
		if costing.IsCanonical(r.key) || r.itemID != nil {
			shown = append(shown, r)
		}
	}
	return shown, priceCard(all), nil
}

// priceCard is the card the register prices with (pricing.Resolve over the
// rows in the card's order).
func priceCard(rows []rate) *pricing.Card {
	settings := make([]pricing.Setting, len(rows))
	for i, r := range rows {
		settings[i] = pricing.Setting{Key: r.key, Label: r.label, UnitCost: r.unitCost, ApprovedMinimum: r.minimum, ItemID: r.itemID}
	}
	return pricing.Resolve(settings)
}

// items is effective_items() ordered by name, each with its first active
// primary intervention mapping (in the mappings' own order).
func (s *Service) items(ctx context.Context, today time.Time) ([]item, error) {
	rows, err := s.db.Query(ctx, `
		SELECT i.id, i.display_name, i.workflow_kind, i.costing_profile, i.activity_type, i.delivery_method,
		       m.intervention, m.id IS NOT NULL
		FROM activity_catalogue_item i
		LEFT JOIN LATERAL (
			SELECT id, intervention FROM activity_intervention_mapping
			WHERE catalogue_item_id = i.id AND active AND is_primary
			ORDER BY priority, id
			LIMIT 1
		) m ON true
		WHERE i.status = $1
		  AND (i.effective_from IS NULL OR i.effective_from <= $2)
		  AND (i.effective_to IS NULL OR i.effective_to >= $2)
		ORDER BY i.display_name, i.stable_code`, rules.ActiveItemStatus, today)
	if err != nil {
		return nil, fmt.Errorf("costsettings: reading the governed activities: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (item, error) {
		var it item
		err := row.Scan(&it.id, &it.name, &it.workflowKind, &it.profile, &it.activityType, &it.delivery,
			&it.primaryIntervention, &it.hasPrimary)
		return it, err
	})
	if err != nil {
		return nil, fmt.Errorf("costsettings: reading the governed activities: %w", err)
	}
	return out, nil
}

// reviews is the cost review queue: the newest submitted reviews.
func (s *Service) reviews(ctx context.Context) ([]review, error) {
	rows, err := s.db.Query(ctx, `
		SELECT COALESCE(NULLIF(a.activity_name_snapshot, ''), a.activity_type, ''), r.reason_code, r.status,
		       r.current_operational_cost, r.proposed_operational_cost
		FROM activity_cost_review r
		JOIN activity a ON a.id = r.activity_id
		WHERE r.status = $1
		ORDER BY r.created_at DESC, r.id
		LIMIT $2`, rules.ReviewQueueStatus, rules.ReviewQueueLimit)
	if err != nil {
		return nil, fmt.Errorf("costsettings: reading the cost review queue: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (review, error) {
		var r review
		err := row.Scan(&r.activity, &r.reason, &r.status, &r.current, &r.proposed)
		return r, err
	})
	if err != nil {
		return nil, fmt.Errorf("costsettings: reading the cost review queue: %w", err)
	}
	return out, nil
}
