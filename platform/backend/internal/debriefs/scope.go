package debriefs

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/hrregister"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myteam"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// errHandOn is a page Go hands on to the existing application.
var errHandOn = errors.New("debriefs: handed on")

// scope is scoped_queryset's read scope as a condition on daily_debrief `d`
// and its arguments.
type scope struct {
	where string
	args  []any
	// team is team_member_ids for a Programme Lead (the review queue's
	// officers).
	team []string
}

func (s *scope) arg(v any) string {
	s.args = append(s.args, v)
	return fmt.Sprintf("$%d", len(s.args))
}

// recipient is "or the debrief was routed to the reader".
func (s *scope) recipient(user string) string {
	return "EXISTS (SELECT 1 FROM daily_debrief_recipient r WHERE r.debrief_id = d.id AND r.recipient_user_id = " +
		s.arg(user) + ")"
}

// readScope is FieldDebriefService.scoped_queryset's role scope.
func readScope(ctx context.Context, db schooldirectory.Querier, p auth.Principal, now time.Time) (*scope, error) {
	if p.InActingAppointment {
		return nil, errHandOn
	}
	if slices.Contains(rules.PartnerRoles, p.ActiveRole) {
		if !pagegate.DjangoAbsent(ctx) {
			return nil, errHandOn
		}
		s := &scope{}
		s.where = "(d.submitted_by_user_id = " + s.arg(p.UserID) + " OR " + s.recipient(p.UserID) + ")"
		return s, nil
	}
	s := &scope{}
	var profile, country *string
	err := db.QueryRow(ctx, `SELECT id, country FROM staff_profile WHERE user_id = $1 AND deleted_at IS NULL ORDER BY id LIMIT 1`,
		p.UserID).Scan(&profile, &country)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return nil, fmt.Errorf("debriefs: reading the reader's profile: %w", err)
	}
	switch {
	case p.ActiveRole == "Admin":
		s.where = "TRUE"
	case p.ActiveRole == "HumanResources":
		clause, args, all, err := hrregister.PeopleReachProfiles(ctx, db, p, nil)
		if err != nil {
			return nil, err
		}
		visible := "NOT d.is_restricted_incident"
		if !all {
			s.args = args
			visible += " AND d.staff_id IN (SELECT sp.id FROM staff_profile sp WHERE sp.deleted_at IS NULL AND " + clause + ")"
		}
		s.where = "((" + visible + ") OR " + s.recipient(p.UserID) + ")"
	case p.ActiveRole == "ImpactAssessment":
		s.where = "(NOT d.is_restricted_incident OR " + s.recipient(p.UserID) + ")"
	case p.ActiveRole == "CountryDirector":
		staff := "FALSE"
		if profile != nil && country != nil && *country != "" {
			staff = "d.staff_id IN (SELECT id FROM staff_profile WHERE deleted_at IS NULL AND country = " + s.arg(*country) + ")"
		}
		s.where = "(" + staff + " OR " + s.recipient(p.UserID) + ")"
	case p.ActiveRole == "RegionalVicePresident":
		s.where = "(d.risk_level = 'critical' OR " + s.recipient(p.UserID) + ")"
	case p.ActiveRole == "Program Lead" && profile != nil:
		team, err := myteam.TeamMemberIDs(ctx, db, *profile, now)
		if err != nil {
			return nil, err
		}
		s.team = team
		own := s.arg(*profile)
		s.where = "(d.staff_id = " + own + " OR d.staff_id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = " +
			own + ") OR d.staff_id = ANY(" + s.arg(team) + "))"
	case p.ActiveRole == "CCEO" && profile != nil:
		var lead *string
		err := db.QueryRow(ctx, `SELECT supervisor_id FROM staff_supervisor_assignment WHERE supervisee_id = $1 ORDER BY id LIMIT 1`,
			*profile).Scan(&lead)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return nil, fmt.Errorf("debriefs: reading the officer's lead: %w", err)
		}
		peers := "FALSE"
		if lead != nil {
			peers = "(d.staff_id IN (SELECT supervisee_id FROM staff_supervisor_assignment WHERE supervisor_id = " + s.arg(*lead) +
				") AND NOT d.is_restricted_incident)"
		}
		s.where = "(d.staff_id = " + s.arg(*profile) + " OR " + peers + ")"
	case p.ActiveRole == "ProjectCoordinator" && profile != nil:
		s.where = "d.staff_id = " + s.arg(*profile)
	default:
		s.where = "FALSE"
	}
	return s, nil
}

// filters is scoped_queryset's narrowing by the asked fy, district, risk
// and search, appended to the scope.
func (s *scope) filters(a ask) {
	if a.fyAsked {
		s.where += " AND d.fy = " + s.arg(a.fy)
	}
	if a.district != "" {
		s.where += " AND d.linked_school_ids && ARRAY(SELECT id FROM school WHERE deleted_at IS NULL AND district_id = " +
			s.arg(a.district) + ")::varchar[]"
	}
	if a.risk != "" {
		s.where += " AND d.risk_level = " + s.arg(a.risk)
	}
	if a.search != "" {
		like := s.arg("%" + likeEscape(a.search) + "%")
		s.where += " AND (UPPER(d.title::text) LIKE UPPER(" + like + ") OR UPPER(d.summary::text) LIKE UPPER(" + like + "))"
	}
}

// likeEscape escapes a search for LIKE as Django's icontains does.
func likeEscape(s string) string {
	out := []rune{}
	for _, r := range s {
		if r == '\\' || r == '%' || r == '_' {
			out = append(out, '\\')
		}
		out = append(out, r)
	}
	return string(out)
}
