package myplan_test

import (
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trainingsummary"
)

func init() { myplan.SetGoldenSummary(trainingsummary.OwnSummary) }
