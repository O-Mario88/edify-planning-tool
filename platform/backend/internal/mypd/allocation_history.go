package mypd

import (
	"cmp"
	"context"
	"fmt"
	"slices"
)

// HistoryYear is one financial year of the PD allocation history form, its
// money as the form prints it.
type HistoryYear struct {
	FY, Allocation, Committed, Accounted, Remaining string
}

type historyAllocation struct {
	annual   int64
	currency string
}

type historyRequest struct {
	fy, status           string
	requested, accounted int64
}

// AllocationHistory is StaffPDService.allocation_history for the signed-in
// person: every year they hold an allocation or a request, newest first.
// Nothing is written; a person without a staff profile has no history.
func AllocationHistory(ctx context.Context, db DB, userID string) ([]HistoryYear, error) {
	sp, ok, err := (&Service{db: db}).staffOf(ctx, userID)
	if err != nil || !ok {
		return nil, err
	}
	allocations, err := readHistoryAllocations(ctx, db, sp.id)
	if err != nil {
		return nil, err
	}
	requests, err := readHistoryRequests(ctx, db, sp.id)
	if err != nil {
		return nil, err
	}
	return historyYears(allocations, requests), nil
}

func readHistoryAllocations(ctx context.Context, db DB, staffID string) (map[string]historyAllocation, error) {
	rows, err := db.Query(ctx, `SELECT fy, annual_allocation, currency FROM pd_allocation WHERE staff_id = $1`, staffID)
	if err != nil {
		return nil, fmt.Errorf("mypd: reading the allocation history: %w", err)
	}
	defer rows.Close()
	out := map[string]historyAllocation{}
	for rows.Next() {
		var fy string
		var a historyAllocation
		if err := rows.Scan(&fy, &a.annual, &a.currency); err != nil {
			return nil, fmt.Errorf("mypd: reading an allocation: %w", err)
		}
		out[fy] = a
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("mypd: reading the allocation history: %w", err)
	}
	return out, nil
}

func readHistoryRequests(ctx context.Context, db DB, staffID string) ([]historyRequest, error) {
	rows, err := db.Query(ctx, `SELECT fy, status, requested_amount_cents, COALESCE(accounted_amount, 0)
		FROM pd_request WHERE staff_id = $1`, staffID)
	if err != nil {
		return nil, fmt.Errorf("mypd: reading the request history: %w", err)
	}
	defer rows.Close()
	var out []historyRequest
	for rows.Next() {
		var r historyRequest
		if err := rows.Scan(&r.fy, &r.status, &r.requested, &r.accounted); err != nil {
			return nil, fmt.Errorf("mypd: reading a request: %w", err)
		}
		out = append(out, r)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("mypd: reading the request history: %w", err)
	}
	return out, nil
}

// historyYears adds up each year: what is committed counts only in a committed
// status, what is accounted counts in any, and what remains never goes below
// zero. A year with requests and no allocation row reads as USD 0.
func historyYears(allocations map[string]historyAllocation, requests []historyRequest) []HistoryYear {
	type totals struct{ committed, accounted int64 }
	byYear := map[string]totals{}
	for fy := range allocations {
		byYear[fy] = totals{}
	}
	for _, r := range requests {
		t := byYear[r.fy]
		if in(rules.CommittedStatuses, r.status) {
			t.committed += r.requested
		}
		t.accounted += r.accounted
		byYear[r.fy] = t
	}
	years := make([]string, 0, len(byYear))
	for fy := range byYear {
		years = append(years, fy)
	}
	slices.SortFunc(years, func(a, b string) int { return cmp.Compare(b, a) })

	out := make([]HistoryYear, 0, len(years))
	for _, fy := range years {
		t := byYear[fy]
		currency := allocationCcy
		var annual int64
		if a, ok := allocations[fy]; ok {
			currency, annual = a.currency, a.annual
		}
		out = append(out, HistoryYear{
			FY:         fy,
			Allocation: money(currency, annual),
			Committed:  money(currency, t.committed),
			Accounted:  money(currency, t.accounted),
			Remaining:  money(currency, max(0, annual-t.committed-t.accounted)),
		})
	}
	return out
}
