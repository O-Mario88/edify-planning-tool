package hrforms

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrregister"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/realtime"
)

// PulsePath is the register the survey's save returns to.
const PulsePath = "/pulse-surveys"

// PulseQuestions are PULSE_QUESTIONS' statements, in order.
var PulseQuestions = []string{
	"I understand how my work serves Edify's mission.",
	"I get the support I need from my supervisor.",
	"My workload is manageable.",
	"My contribution is recognised.",
	"I have opportunities to learn and grow.",
}

// PulseCountries is the countries the drawer offers to survey
// (_country_options).
func (f Forms) PulseCountries(ctx context.Context, p auth.Principal) ([]string, error) {
	names, _, err := hrregister.PeopleReachCountryOptions(ctx, f.DB, p)
	return names, err
}

// PulseCountryField is the tick box a country is surveyed by. The existing
// form names it country_<Name>, which the gateway refuses (a field name is
// lower case), so Go names it in lower case, anything else an underscore.
func PulseCountryField(country string) string {
	b := strings.Builder{}
	for _, r := range strings.ToLower(country) {
		if (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9') {
			b.WriteRune(r)
		} else {
			b.WriteRune('_')
		}
	}
	return "country_" + b.String()
}

func anyList(xs []string) []any {
	out := make([]any, 0, len(xs))
	for _, x := range xs {
		out = append(out, x)
	}
	return out
}

// OpenPulse is pulse_open with open_pulse_survey: the countries ticked among
// those offered (every one when none is), HR only, titled, each country one
// the reader oversees, a closing day not before today; then the survey, a
// notice to every active staff account in its countries (partners' logins
// apart) and its audit row, in one transaction. It says the survey's title.
func (f Forms) OpenPulse(ctx context.Context, p auth.Principal, values map[string]string, o activities.Origin) (string, error) {
	offered, err := f.PulseCountries(ctx, p)
	if err != nil {
		return "", err
	}
	countries := []string{}
	for _, c := range offered {
		if checked(values[PulseCountryField(c)]) {
			countries = append(countries, c)
		}
	}
	closes, err := day(values["closes_on"])
	if err != nil {
		return "", err
	}
	if err := assertHR(p); err != nil {
		return "", err
	}
	title := strings.TrimSpace(values["title"])
	if title == "" {
		return "", refuse("Give the survey a title.")
	}
	if len(countries) == 0 {
		countries = offered
	}
	for _, c := range countries {
		ok, err := hrregister.PeopleReachAllowsCountry(ctx, f.DB, p, c)
		if err != nil {
			return "", err
		}
		if !ok {
			return "", refuse("You may only survey the countries you oversee.")
		}
	}
	if len(countries) == 0 {
		return "", refuse("Choose at least one country.")
	}
	opens := f.today()
	if closes == nil {
		return "", refuse("Choose when the survey closes.")
	}
	if closes.Before(opens) {
		return "", refuse("A survey cannot close before it opens.")
	}
	listed, err := json.Marshal(countries)
	if err != nil {
		return "", err
	}
	var told []string
	now, id := f.now(), cuid.New()
	err = f.write(ctx, func(tx pgx.Tx) error {
		if _, err := tx.Exec(ctx, `INSERT INTO hr_pulse_survey (id, created_at, updated_at, title, countries, opens_on, closes_on, status, created_by_id)
VALUES ($1, $2, $2, $3, $4::jsonb, $5, $6, 'open', $7)`, id, now, title, string(listed), opens, *closes, nullable(p.UserID)); err != nil {
			return fmt.Errorf("hrforms: opening the survey: %w", err)
		}
		rows, err := tx.Query(ctx, `
SELECT u.id FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id
WHERE u.deleted_at IS NULL AND u.is_active AND sp.country = ANY($1)
  AND NOT (COALESCE(u.roles::text[], '{}') && ARRAY['PartnerAdmin', 'PartnerFieldOfficer']::text[])`, countries)
		if err != nil {
			return fmt.Errorf("hrforms: reading the staff to tell: %w", err)
		}
		people, err := pgx.CollectRows(rows, pgx.RowTo[string])
		if err != nil {
			return fmt.Errorf("hrforms: reading the staff to tell: %w", err)
		}
		to := make([]activities.NoticeTo, 0, len(people))
		for _, u := range people {
			to = append(to, activities.NoticeTo{UserID: u, Route: "/pulse/" + id, Label: "Answer the survey"})
		}
		if len(to) > 0 {
			if told, err = activities.NotifyInTxFrom(ctx, tx, f.Push, f.Logger, now, id, o, activities.Notice{
				Title: "Staff pulse: " + title, Event: "hr.pulse_survey.opened", Category: "hr", ContextType: "pulse_survey",
				Priority: "normal",
				Body: "Five quick statements about your work at Edify. Your answers are anonymous. Open until " +
					closes.Format("02 Jan 2006") + ".",
			}, to); err != nil {
				return err
			}
		}
		return auditRow(ctx, tx, "hr.pulse_survey_opened", "pulse_survey", id, p,
			map[string]any{"countries": anyList(countries), "closesOn": closes.Format("2006-01-02")}, o, now)
	})
	if err == nil && f.Live != nil {
		// The trigger's word to each one's open pages, once it commits.
		for _, u := range told {
			f.Live.Publish(realtime.Event{Type: "notification.hr.pulse_survey.opened", EntityType: "pulse_survey", EntityID: id,
				TargetUserID: u, ActorUserID: p.UserID})
		}
	}
	return title, err
}
