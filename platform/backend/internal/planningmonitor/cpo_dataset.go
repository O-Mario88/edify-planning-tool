package planningmonitor

import (
	"context"
	"fmt"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// cpoDataset is service.Dataset: every eligible school's facts, figures and
// allocation, and the owners holding them.
type cpoDataset struct {
	window      cpoWindow
	asOf        time.Time
	schools     []*cpoSchool
	byID        map[string]*cpoSchool
	owners      map[string]*cpoOwner // canonical owner key → owner
	allocations map[string]cpoAllocation
	vectors     map[string][]int
	claims      map[string]cpoClaims
}

// historicalAdjustments is requirements.historical_adjustments: for a past
// reporting date, the owner and type each school had then, from the first
// transfer or type change after it.
func historicalAdjustments(ctx context.Context, db schooldirectory.Querier, ids []string, asOf time.Time) (map[string]string, map[string]string, error) {
	owners, types := map[string]string{}, map[string]string{}
	rows, err := db.Query(ctx, `SELECT school_id, COALESCE(from_staff_id, '') FROM school_ownership_transfer
WHERE school_id = ANY($1) AND effective_date > $2::date ORDER BY school_id, effective_date, created_at`, ids, asOf)
	if err != nil {
		return nil, nil, fmt.Errorf("planningmonitor: the ownership history: %w", err)
	}
	for rows.Next() {
		var school, from string
		if err := rows.Scan(&school, &from); err != nil {
			rows.Close()
			return nil, nil, err
		}
		if _, ok := owners[school]; !ok {
			owners[school] = from
		}
	}
	rows.Close()
	rows, err = db.Query(ctx, `SELECT school_id, COALESCE(old_value, '') FROM school_change_log
WHERE school_id = ANY($1) AND field_name = 'school_type' AND (changed_at AT TIME ZONE '`+cpoZone+`')::date > $2::date
ORDER BY school_id, changed_at`, ids, asOf)
	if err != nil {
		return nil, nil, fmt.Errorf("planningmonitor: the type history: %w", err)
	}
	for rows.Next() {
		var school, old string
		if err := rows.Scan(&school, &old); err != nil {
			rows.Close()
			return nil, nil, err
		}
		if _, ok := types[school]; !ok {
			types[school] = old
		}
	}
	rows.Close()
	// Core onboarding after the date names the type before it; best-effort,
	// as the existing read is.
	rows, err = db.Query(ctx, `SELECT s.id, COALESCE(o.previous_school_type, '') FROM core_school_onboarding o
JOIN school s ON s.school_id = o.school_id WHERE s.id = ANY($1) AND (o.onboarded_at AT TIME ZONE '`+cpoZone+`')::date > $2::date`, ids, asOf)
	if err == nil {
		for rows.Next() {
			var school, previous string
			if rows.Scan(&school, &previous) == nil {
				if _, ok := types[school]; !ok {
					types[school] = previous
				}
			}
		}
		rows.Close()
	}
	return owners, types, nil
}

// buildCPODataset is service.build_dataset for a reader's scope and window.
func buildCPODataset(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope, w cpoWindow, today time.Time) (*cpoDataset, error) {
	c := rules.CountryOversight
	asOf := cpoReportingDate(w.fy, today)
	schools, err := eligibleSchools(ctx, db, scope, asOf)
	if err != nil {
		return nil, err
	}
	d := &cpoDataset{window: w, asOf: asOf, schools: schools, byID: map[string]*cpoSchool{}, owners: map[string]*cpoOwner{},
		allocations: map[string]cpoAllocation{}, vectors: map[string][]int{}, claims: map[string]cpoClaims{}}
	ids := make([]string, 0, len(schools))
	for _, s := range schools {
		d.byID[s.id] = s
		ids = append(ids, s.id)
	}
	if len(schools) > 0 && asOf.Before(today) {
		owners, types, err := historicalAdjustments(ctx, db, ids, asOf)
		if err != nil {
			return nil, err
		}
		for _, s := range schools {
			if t := types[s.id]; t != "" {
				s.schoolType, s.family = t, c.family(t)
			}
			if o, ok := owners[s.id]; ok {
				s.rawOwner = o
			}
		}
	}
	outside, err := visitgate.ProjectsOutsideSSA(ctx, db, schoolprofile.GateRules())
	if err != nil {
		return nil, err
	}
	if err := loadFacts(ctx, db, schools, w, outside); err != nil {
		return nil, err
	}
	raw := []string{}
	for _, s := range schools {
		if s.rawOwner != "" {
			raw = append(raw, s.rawOwner)
		}
	}
	directory, err := cpoOwnerDirectory(ctx, db, raw)
	if err != nil {
		return nil, err
	}
	noOwner := false
	for _, s := range schools {
		if o, ok := directory[s.rawOwner]; ok && s.rawOwner != "" {
			s.ownerKey = o.key
			if _, seen := d.owners[o.key]; !seen {
				d.owners[o.key] = o
			}
		} else {
			s.ownerKey, noOwner = c.NoOwner[0], true
		}
	}
	if noOwner {
		d.owners[c.NoOwner[0]] = &cpoOwner{key: c.NoOwner[0], name: c.NoOwner[1], leadKey: c.NoLead[0], leadName: c.NoLead[1]}
	}
	byOwner := map[string][]*cpoSchool{}
	order := []string{}
	for _, s := range schools {
		annualPosition(s)
		if _, ok := byOwner[s.ownerKey]; !ok {
			order = append(order, s.ownerKey)
		}
		byOwner[s.ownerKey] = append(byOwner[s.ownerKey], s)
	}
	for _, key := range order {
		owner := d.owners[key]
		if key == c.NoOwner[0] {
			owner = nil
		}
		allocate(owner, byOwner[key], d.allocations)
	}
	for _, s := range schools {
		if s.governed() {
			cl := claimsFor(s, d.allocations[s.id], w, "", nil)
			d.claims[s.id] = cl
			d.vectors[s.id] = schoolValues(s, cl)
		} else {
			d.vectors[s.id] = nil
		}
	}
	return d, nil
}
