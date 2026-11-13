package trainingsummary

import (
	"context"
	"math"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// flagTones is SummaryRow.flag_tone.
var flagTones = map[string]string{"unset": "neutral", "above": "danger", "available": "warning", "reached": "success"}

// OwnSummary is training_ceilings.own_summary (My Plan's My Training
// Summary, myplan.Service.WithTrainingSummary) for the person with this
// staff profile (and user id, the other id their work is filed under):
// summary_for_staff over that one profile, in its order.
func OwnSummary(ctx context.Context, q schooldirectory.Querier, staffProfileID, userID, name, fy string, now time.Time) ([]myplan.TrainingSummaryRow, error) {
	if staffProfileID == "" {
		return nil, nil
	}
	rows, err := summaryForStaff(ctx, q, []profile{{id: staffProfileID, userID: userID, name: name}}, fy, now)
	if err != nil {
		return nil, err
	}
	out := make([]myplan.TrainingSummaryRow, 0, len(rows))
	for _, r := range rows {
		o := myplan.TrainingSummaryRow{
			StaffID: r.staffID, TrainingID: r.trainingID, TrainingName: r.trainingName, Ceiling: r.ceiling,
			InSchool: r.inSchool, Partner: r.partner, PartnerScheduled: r.partnerScheduled, Group: r.group,
			Total: r.total(), AwaitingPartner: r.awaitingPartner(), Excess: r.excess(), Balance: r.balance(),
			State: r.state(), Flag: r.flag(),
		}
		o.FlagTone = flagTones[o.State]
		if r.ceiling != nil {
			u := 0
			switch {
			case *r.ceiling == 0 && o.Total != 0:
				u = 100
			case *r.ceiling != 0:
				u = int(math.RoundToEven(float64(o.Total*100) / float64(*r.ceiling)))
			}
			o.Utilization = &u
		}
		out = append(out, o)
	}
	return out, nil
}
