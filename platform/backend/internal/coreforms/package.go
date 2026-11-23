// Package coreforms reads what the Core Schools scheduling and assignment
// forms offer (apps/frontend/views/core_schools_views.py). Opening a form
// writes nothing: where Django would make the year's package on open, the
// package is worked out in memory.
package coreforms

import (
	"context"
	"errors"
	"fmt"
	"strconv"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

const (
	kindVisit      = "visit"
	kindTraining   = "training"
	packageTarget  = 4
	schoolTypeCore = "core"
)

// slotOrdinals is CORE_SLOT_ORDINALS.
var slotOrdinals = map[int]string{1: "First", 2: "Second", 3: "Third", 4: "Fourth"}

// Slot is one open place in a package.
type Slot struct {
	Sequence int
	Label    string
}

// Package is what a school's package for the year offers. Available is false
// for a school with none and no earlier one to make it from.
type Package struct {
	Available, Complete bool
	Visits, Trainings   []Slot
}

type slotRow struct {
	kind, status string
	sequence     int
}

// slotOf is available_options' label.
func slotOf(sequence int, kind string) Slot {
	ordinal, ok := slotOrdinals[sequence]
	if !ok {
		ordinal = strconv.Itoa(sequence)
	}
	name := "Training"
	if kind == kindVisit {
		name = "Visit"
	}
	return Slot{Sequence: sequence, Label: ordinal + " " + name}
}

// unmadePackage is what ensure_plan would make: four open visits and four
// open trainings.
func unmadePackage() Package {
	pack := Package{Available: true}
	for sequence := 1; sequence <= packageTarget; sequence++ {
		pack.Visits = append(pack.Visits, slotOf(sequence, kindVisit))
		pack.Trainings = append(pack.Trainings, slotOf(sequence, kindTraining))
	}
	return pack
}

// packageFrom is available_options and summary for a package's slots, read
// in sequence order. A blank target is the package's four.
func packageFrom(rules visitgate.CoreRules, visitsTarget, trainingsTarget int, slots []slotRow) Package {
	if visitsTarget == 0 {
		visitsTarget = packageTarget
	}
	if trainingsTarget == 0 {
		trainingsTarget = packageTarget
	}
	pack := Package{Available: true}
	visits, trainings := 0, 0
	for _, slot := range slots {
		taken := rules.SlotTaken(slot.status)
		switch slot.kind {
		case kindVisit:
			if taken {
				visits++
			} else {
				pack.Visits = append(pack.Visits, slotOf(slot.sequence, kindVisit))
			}
		case kindTraining:
			if taken {
				trainings++
			} else {
				pack.Trainings = append(pack.Trainings, slotOf(slot.sequence, kindTraining))
			}
		}
	}
	pack.Complete = visits >= visitsTarget && trainings >= trainingsTarget
	return pack
}

// packageFor is ensure_core_plan followed by the slots, without the write.
func (s *Service) packageFor(ctx context.Context, school School, fy string) (Package, error) {
	if school.Type != schoolTypeCore {
		return Package{}, nil
	}
	rules := s.gates.Core
	var planID, status string
	var visitsTarget, trainingsTarget *int
	err := s.db.QueryRow(ctx, `SELECT id, COALESCE(status, ''), visits_target, trainings_target
FROM core_plan WHERE school_id = $1 AND fy = $2 ORDER BY id LIMIT 1`, school.Code, fy).Scan(&planID, &status, &visitsTarget, &trainingsTarget)
	if errors.Is(err, pgx.ErrNoRows) {
		var earlier bool
		if err := s.db.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM core_plan
WHERE school_id = $1 AND NOT COALESCE(status, '') = ANY($2))`, school.Code, rules.PlanClosedStatuses).Scan(&earlier); err != nil {
			return Package{}, fmt.Errorf("coreforms: reading the school's earlier packages: %w", err)
		}
		if !earlier {
			return Package{}, nil
		}
		return unmadePackage(), nil
	}
	if err != nil {
		return Package{}, fmt.Errorf("coreforms: reading the year's package: %w", err)
	}
	for _, closed := range rules.PlanClosedStatuses {
		if status == closed {
			return Package{}, nil
		}
	}
	rows, err := s.db.Query(ctx, `SELECT COALESCE(activity_type, ''), sequence_number, COALESCE(status, '')
FROM core_activity_slot WHERE core_plan_id = $1 ORDER BY sequence_number`, planID)
	if err != nil {
		return Package{}, fmt.Errorf("coreforms: reading the package's slots: %w", err)
	}
	slots, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (slotRow, error) {
		var slot slotRow
		err := row.Scan(&slot.kind, &slot.sequence, &slot.status)
		return slot, err
	})
	if err != nil {
		return Package{}, fmt.Errorf("coreforms: reading a slot: %w", err)
	}
	return packageFrom(rules, intOr(visitsTarget), intOr(trainingsTarget), slots), nil
}

func intOr(value *int) int {
	if value == nil {
		return 0
	}
	return *value
}
