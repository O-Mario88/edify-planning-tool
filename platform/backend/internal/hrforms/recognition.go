package hrforms

import (
	"context"
	"slices"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrregister"
)

// RecognitionCategories are RecognitionCategory's choices, in order.
var RecognitionCategories = []Choice{
	{"values", "Living Edify's values"},
	{"excellence", "Excellence in delivery"},
	{"teamwork", "Teamwork"},
	{"innovation", "Innovation"},
	{"above_and_beyond", "Above and beyond"},
	{"service_milestone", "Service milestone"},
}

// RecognitionPath is the register the save returns to.
const RecognitionPath = "/recognition"

// Recognise is recognition_award with rewards_wellbeing_service.recognise:
// the employee in the reader's reach, HR only, in a country the reader
// oversees, never oneself, a known category and a citation; then the
// recognition and its hr.staff_recognised row. It says the employee's name.
func (f Forms) Recognise(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error) {
	var name string
	err := f.write(ctx, func(tx pgx.Tx) error {
		s, err := f.staffInReach(ctx, tx, p, values["staff_id"])
		if err != nil {
			return err
		}
		if s == nil {
			return refuse("Choose an employee you oversee.")
		}
		awarded, err := day(values["awarded_on"])
		if err != nil {
			return err
		}
		if err := assertHR(p); err != nil {
			return err
		}
		ok, err := hrregister.PeopleReachAllowsCountry(ctx, tx, p, s.country)
		if err != nil {
			return err
		}
		if !ok {
			return refuse("You may only record recognitions in the countries you oversee.")
		}
		if s.userID != "" && s.userID == p.UserID {
			return refuse("You cannot recognise yourself.")
		}
		category := values["category"]
		if !slices.ContainsFunc(RecognitionCategories, func(c Choice) bool { return c.Value == category }) {
			return refuse("Choose what the recognition is for.")
		}
		citation := strings.TrimSpace(values["citation"])
		if citation == "" {
			return refuse("Write the citation: what they did and why it mattered.")
		}
		on := f.today()
		if awarded != nil {
			on = *awarded
		}
		now := f.now()
		id := cuid.New()
		var by any
		if p.UserID != "" {
			by = p.UserID
		}
		if _, err := tx.Exec(ctx, `
INSERT INTO hr_staff_recognition (id, created_at, updated_at, staff_id, country, category, citation, awarded_by_id, awarded_on)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8)`, id, now, s.id, s.country, category, citation, by, on); err != nil {
			return err
		}
		name = s.name
		return auditRow(ctx, tx, "hr.staff_recognised", "staff_recognition", id, p,
			map[string]any{"staffId": s.id, "category": category}, o, now)
	})
	return name, err
}
