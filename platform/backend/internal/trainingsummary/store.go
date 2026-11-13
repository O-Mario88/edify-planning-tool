package trainingsummary

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// profile is a staff column: a StaffProfile and the user behind it.
type profile struct {
	id, userID, name, email string
	roles                   []string
	activeRole              string
}

// display is profile.user.name or profile.user.email.
func (p profile) display() string {
	if p.name != "" {
		return p.name
	}
	return p.email
}

func (p profile) holds(role string) bool { return p.activeRole == role || in(p.roles, role) }

// courseSQL is training_ceilings._course_expr for a row of table t with its
// catalogue item joined as ci.
func courseSQL(t string) string {
	return "COALESCE(" + t + ".training_course_id, CASE WHEN ci.is_training_course THEN " + t + ".catalogue_item_id ELSE NULL END)"
}

// projectCourses is project_training_mappings().values("catalogue_item_id").
const projectCourses = `SELECT m.catalogue_item_id FROM activity_project_mapping m
  JOIN activity_catalogue_item mi ON m.catalogue_item_id = mi.id
  JOIN project mp ON m.project_id = mp.id
  WHERE m.active AND mi.activity_type = $1 AND mp.deleted_at IS NULL AND mp.status = ANY($2)`

// trainingSQL is _training_q, _outside_projects_q and the year, release and
// course filters _school_training_rows and _group_rows share. $1–$2 are the
// project courses' parameters; $3 the year; $4–$7 the types and statuses.
const trainingSQL = `(a.activity_type = ANY($4) OR (a.activity_type = ANY($5) AND a.meeting_kind = $6))
  AND (a.project_id IS NULL OR a.project_id = '')
  AND a.deleted_at IS NULL AND a.fy = $3
  AND NOT (a.status = ANY($7))`

func notProjectSQL(course string) string {
	return "NOT (" + course + " IS NULL) AND NOT (" + course + " IN (" + projectCourses + "))"
}

func baseArgs(fy string) []any {
	return []any{rules.CatalogueTrainingType, rules.LiveProjectStatuses, fy,
		rules.TrainingTypes, rules.MeetingTypes, rules.MeetingKindTraining, rules.ReleasedStatuses}
}

// commitment is one (owner, course, school) a training row reads, with
// whether the Partner has dated it.
type commitment struct {
	owner, course, school string
	dated                 bool
}

func collect(ctx context.Context, q schooldirectory.Querier, sql string, args []any, withDated bool) ([]commitment, error) {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (commitment, error) {
		var c commitment
		var owner *string
		var dated int
		targets := []any{&owner, &c.course, &c.school}
		if withDated {
			targets = append(targets, &dated)
		}
		if err := row.Scan(targets...); err != nil {
			return c, err
		}
		if owner != nil {
			c.owner = *owner
		}
		c.dated = dated == 1
		return c, nil
	})
}

// groupRows is _group_rows: each school invited to, or recorded at, a group
// delivery, filed under who is responsible for it.
func groupRows(ctx context.Context, q schooldirectory.Querier, owners []string, fy string) ([]commitment, error) {
	course := courseSQL("a")
	sql := `SELECT DISTINCT a.responsible_staff_id, ` + course + `, att.school_id
FROM cluster_activity_attendance att
JOIN activity a ON att.activity_id = a.id
LEFT JOIN activity_catalogue_item ci ON a.catalogue_item_id = ci.id
JOIN school s ON att.school_id = s.id
WHERE ` + trainingSQL + ` AND (att.invited OR att.attended) AND a.cluster_id IS NOT NULL AND a.school_id IS NULL
  AND ` + notProjectSQL(course) + ` AND a.responsible_staff_id = ANY($8)`
	out, err := collect(ctx, q, sql, append(baseArgs(fy), owners), false)
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading group trainings: %w", err)
	}
	return out, nil
}

// inSchoolRows is _in_school_rows: in-school trainings staff deliver.
func inSchoolRows(ctx context.Context, q schooldirectory.Querier, owners []string, fy string) ([]commitment, error) {
	course := courseSQL("a")
	sql := `SELECT DISTINCT a.responsible_staff_id, ` + course + `, a.school_id
FROM activity a
LEFT JOIN activity_catalogue_item ci ON a.catalogue_item_id = ci.id
WHERE ` + trainingSQL + ` AND a.school_id IS NOT NULL
  AND ` + notProjectSQL(course) + ` AND NOT (a.delivery_type = $9) AND a.responsible_staff_id = ANY($8)`
	out, err := collect(ctx, q, sql, append(baseArgs(fy), owners, rules.PartnerDeliveryType), false)
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading in-school trainings: %w", err)
	}
	return out, nil
}

// partnerRows is _partner_rows: in-school trainings a Partner delivers that
// no open hand-over still carries, with whose they are and whether the
// Partner has dated them.
func partnerRows(ctx context.Context, q schooldirectory.Querier, owners []string, fy string) ([]commitment, error) {
	course := courseSQL("a")
	owner := `COALESCE(NULLIF(a.monitored_by_staff_id, ''), NULLIF(a.responsible_staff_id, ''), s.account_owner_id)`
	planned := `a.status = ANY($11) AND (a.planned_date IS NOT NULL OR a.scheduled_date IS NOT NULL)`
	dated := `CASE WHEN ((a.delivery_type = $9 AND ` + planned + ` AND (a.partner_date_set_by = $12 OR (a.partner_date_set_by = '' AND NOT (a.executor_type = $13))))
  OR (` + planned + ` AND a.executor_type = $13)) THEN 1 ELSE 0 END`
	sql := `SELECT DISTINCT ` + owner + `, ` + course + `, a.school_id, ` + dated + `
FROM activity a
JOIN school s ON a.school_id = s.id
LEFT JOIN activity_catalogue_item ci ON a.catalogue_item_id = ci.id
WHERE ` + trainingSQL + ` AND a.school_id IS NOT NULL
  AND ` + notProjectSQL(course) + ` AND a.delivery_type = $9
  AND NOT (a.id IN (SELECT h.source_activity_id FROM partner_assignment h WHERE h.status = ANY($10) AND h.source_activity_id IS NOT NULL))
  AND ` + owner + ` = ANY($8)`
	args := append(baseArgs(fy), owners, rules.PartnerDeliveryType, rules.UnscheduledHandoverStatuses,
		rules.PlannedStates, rules.DatedByPartner, rules.CertifiedPartnerAgency)
	out, err := collect(ctx, q, sql, args, true)
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading partner trainings: %w", err)
	}
	return out, nil
}

// handoversReadIn is handovers_read_in: a hand-over waiting for the
// Partner's date is read in the running year and a later one.
func handoversReadIn(fy string, now time.Time) bool {
	year, err := strconv.Atoi(fy)
	operational, err2 := strconv.Atoi(schooldirectory.OperationalFY(now))
	if err != nil || err2 != nil {
		return fy == schooldirectory.OperationalFY(now)
	}
	return year >= operational
}

// handoverRows is _handover_rows: schools handed to a Partner for a
// training, outside projects, still waiting for the Partner's date.
func handoverRows(ctx context.Context, q schooldirectory.Querier, owners []string, fy string, now time.Time) ([]commitment, error) {
	if !handoversReadIn(fy, now) {
		return nil, nil
	}
	course := courseSQL("pa")
	owner := `COALESCE(NULLIF(pa.monitoring_staff_id, ''), NULLIF(pa.assigning_staff_id, ''), s.account_owner_id)`
	sql := `SELECT DISTINCT ` + owner + `, ` + course + `, pa.school_id
FROM partner_assignment pa
JOIN school s ON pa.school_id = s.id
LEFT JOIN activity_catalogue_item ci ON pa.catalogue_item_id = ci.id
WHERE pa.status = ANY($3) AND pa.project_id IS NULL AND pa.school_id IS NOT NULL
  AND ` + notProjectSQL(course) + ` AND ` + owner + ` = ANY($4)`
	out, err := collect(ctx, q, sql, []any{rules.CatalogueTrainingType, rules.LiveProjectStatuses,
		rules.UnscheduledHandoverStatuses, owners}, false)
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading partner hand-overs: %w", err)
	}
	return out, nil
}

// readerCountry is training_ceilings.country_of: the reader's profile's
// country, else the platform's.
func readerCountry(ctx context.Context, q schooldirectory.Querier, userID string) (string, error) {
	var country *string
	err := q.QueryRow(ctx, `SELECT country FROM staff_profile WHERE user_id = $1`, userID).Scan(&country)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("trainingsummary: reading the country: %w", err)
	}
	if country != nil && strings.TrimSpace(*country) != "" {
		return strings.TrimSpace(*country), nil
	}
	return rules.DefaultCountry, nil
}

// isSuperuser reads the flag is_country_reader also accepts.
func isSuperuser(ctx context.Context, q schooldirectory.Querier, userID string) (bool, error) {
	var yes bool
	err := q.QueryRow(ctx, `SELECT is_superuser FROM "user" WHERE id = $1`, userID).Scan(&yes)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return false, fmt.Errorf("trainingsummary: reading the account: %w", err)
	}
	return yes, nil
}

// countryIdentities is _country_identities: every id a plan may name its
// owner by, for the country's staff.
func countryIdentities(ctx context.Context, q schooldirectory.Querier, country string) ([]string, error) {
	rows, err := q.Query(ctx, `SELECT id, user_id FROM staff_profile WHERE deleted_at IS NULL AND (country = $1 OR country = '')`, country)
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading the country's staff: %w", err)
	}
	pairs, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) ([2]*string, error) {
		var p [2]*string
		return p, row.Scan(&p[0], &p[1])
	})
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading the country's staff: %w", err)
	}
	out := []string{}
	for _, p := range pairs {
		for _, id := range p {
			if id != nil && *id != "" && !in(out, *id) {
				out = append(out, *id)
			}
		}
	}
	return out, nil
}

const profileColumns = `sp.id, sp.user_id, COALESCE(u.name, ''), COALESCE(u.email, ''), COALESCE(u.roles, '{}'), COALESCE(u.active_role, '')`

func profiles(ctx context.Context, q schooldirectory.Querier, sql string, args ...any) ([]profile, error) {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (profile, error) {
		var p profile
		return p, row.Scan(&p.id, &p.userID, &p.name, &p.email, &p.roles, &p.activeRole)
	})
}

func holdsSQL(role string) string {
	return `(u.active_role = ` + role + ` OR u.roles @> (ARRAY[` + role + `])::varchar(64)[])`
}

// countryOfficers is training_summary.country_officers, before its sort:
// the country's live CCEOs and Programme Leads.
func countryOfficers(ctx context.Context, q schooldirectory.Querier, country string) ([]profile, error) {
	out, err := profiles(ctx, q, `SELECT `+profileColumns+` FROM staff_profile sp JOIN "user" u ON sp.user_id = u.id
WHERE sp.deleted_at IS NULL AND (`+holdsSQL("$1")+` OR `+holdsSQL("$2")+`)
  AND u.deleted_at IS NULL AND u.is_active AND (sp.country = $3 OR sp.country = '')`,
		rules.CCEORole, rules.ProgramLeadRole, country)
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading the country's officers: %w", err)
	}
	return out, nil
}

// leadLink is one officer's Programme Lead (training_summary._leads_of).
type leadLink struct{ officer, lead, name string }

func leadLinks(ctx context.Context, q schooldirectory.Querier, officers []string) ([]leadLink, error) {
	rows, err := q.Query(ctx, `SELECT a.supervisee_id, a.supervisor_id, u.name FROM staff_supervisor_assignment a
JOIN staff_profile sp ON a.supervisor_id = sp.id JOIN "user" u ON sp.user_id = u.id
WHERE `+holdsSQL("$1")+` AND a.supervisee_id = ANY($2) AND sp.deleted_at IS NULL`, rules.ProgramLeadRole, officers)
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading the Programme Leads: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (leadLink, error) {
		var l leadLink
		var name *string
		err := row.Scan(&l.officer, &l.lead, &name)
		if name != nil {
			l.name = *name
		}
		return l, err
	})
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading the Programme Leads: %w", err)
	}
	return out, nil
}

// ownProfile is training_ceilings._profile(staff_profile_id).
func ownProfile(ctx context.Context, q schooldirectory.Querier, id string) (*profile, error) {
	if id == "" {
		return nil, nil
	}
	found, err := profiles(ctx, q, `SELECT `+profileColumns+` FROM staff_profile sp JOIN "user" u ON sp.user_id = u.id
WHERE (sp.id = $1 OR sp.user_id = $1) AND sp.deleted_at IS NULL ORDER BY sp.id LIMIT 1`, id)
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading the reader's profile: %w", err)
	}
	if len(found) == 0 {
		return nil, nil
	}
	return &found[0], nil
}

// teamMembers is hr.team_roster._read_team_members for a lead working in
// their own role: the live CCEOs they and any Programme Lead they cover
// supervise, by name.
func teamMembers(ctx context.Context, q schooldirectory.Querier, profileID string, now time.Time) ([]profile, error) {
	if profileID == "" {
		return nil, nil
	}
	out, err := profiles(ctx, q, `SELECT `+profileColumns+` FROM staff_profile sp JOIN "user" u ON sp.user_id = u.id
WHERE `+holdsSQL("$1")+` AND sp.id IN (
    SELECT a.supervisee_id FROM staff_supervisor_assignment a WHERE a.supervisor_id = $3 OR a.supervisor_id IN (
      SELECT c.id FROM staff_profile c JOIN "user" cu ON c.user_id = cu.id
      WHERE c.deleted_at IS NULL AND (cu.active_role = $2 OR cu.roles @> (ARRAY[$2])::varchar(64)[]) AND c.id IN (
        SELECT t.original_staff_id FROM temporary_coverage_assignment t
        WHERE t.covering_staff_id = $3 AND t.start_datetime <= $4 AND t.end_datetime >= $4 AND t.status = 'active')))
  AND sp.deleted_at IS NULL AND u.deleted_at IS NULL AND u.is_active AND NOT (sp.id = $3)
ORDER BY u.name ASC`, rules.CCEORole, rules.ProgramLeadRole, profileID, now)
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading the team: %w", err)
	}
	return out, nil
}

// ceiling is a TrainingCeiling or TrainingCountryCeiling row.
type ceiling struct {
	id    string
	value int
}

// staffCeilings is the TrainingCeiling rows of these staff in the year.
func staffCeilings(ctx context.Context, q schooldirectory.Querier, staff []string, fy string) (map[[2]string]ceiling, error) {
	rows, err := q.Query(ctx, `SELECT id, staff_id, training_id, ceiling FROM training_ceiling WHERE fy = $1 AND staff_id = ANY($2)`, fy, staff)
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading ceilings: %w", err)
	}
	defer rows.Close()
	out := map[[2]string]ceiling{}
	for rows.Next() {
		var c ceiling
		var staffID, training string
		if err := rows.Scan(&c.id, &staffID, &training, &c.value); err != nil {
			return nil, fmt.Errorf("trainingsummary: reading ceilings: %w", err)
		}
		out[[2]string{staffID, training}] = c
	}
	return out, rows.Err()
}

// countryCeilings is training_ceilings.country_ceilings.
func countryCeilings(ctx context.Context, q schooldirectory.Querier, fy, country string) (map[string]ceiling, error) {
	rows, err := q.Query(ctx, `SELECT id, training_id, ceiling FROM training_country_ceiling WHERE country = $1 AND fy = $2`, country, fy)
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading Country Ceilings: %w", err)
	}
	defer rows.Close()
	out := map[string]ceiling{}
	for rows.Next() {
		var c ceiling
		var training string
		if err := rows.Scan(&c.id, &training, &c.value); err != nil {
			return nil, fmt.Errorf("trainingsummary: reading Country Ceilings: %w", err)
		}
		out[training] = c
	}
	return out, rows.Err()
}

// item is a Training Catalogue entry.
type item struct{ id, name, method string }

// catalogueItems is the entries with these ids, by display name and code.
func catalogueItems(ctx context.Context, q schooldirectory.Querier, ids []string) ([]item, error) {
	rows, err := q.Query(ctx, `SELECT id, display_name, delivery_method FROM activity_catalogue_item WHERE id = ANY($1) ORDER BY display_name ASC, stable_code ASC`, ids)
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading the catalogue: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (item, error) {
		var i item
		return i, row.Scan(&i.id, &i.name, &i.method)
	})
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading the catalogue: %w", err)
	}
	return out, nil
}

// mapping is an active link between a live project and a training.
type mapping struct {
	projectID, projectName string
	training               item
}

// projectMappings is project_training_mappings(), by project and training
// name.
func projectMappings(ctx context.Context, q schooldirectory.Querier) ([]mapping, error) {
	rows, err := q.Query(ctx, `SELECT p.id, p.name, ci.id, ci.display_name, ci.delivery_method
FROM activity_project_mapping m
JOIN activity_catalogue_item ci ON m.catalogue_item_id = ci.id
JOIN project p ON m.project_id = p.id
WHERE m.active AND ci.activity_type = $1 AND p.deleted_at IS NULL AND p.status = ANY($2)
ORDER BY p.name ASC, ci.display_name ASC`, rules.CatalogueTrainingType, rules.LiveProjectStatuses)
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading project trainings: %w", err)
	}
	out, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (mapping, error) {
		var m mapping
		return m, row.Scan(&m.projectID, &m.projectName, &m.training.id, &m.training.name, &m.training.method)
	})
	if err != nil {
		return nil, fmt.Errorf("trainingsummary: reading project trainings: %w", err)
	}
	return out, nil
}

// projectFigures are _project_rows' counts: the schools each staff member
// added to each project, the capacity set for them, and every school on
// each project.
type projectFigures struct {
	added, capacity map[[2]string]int
	hasCapacity     map[[2]string]bool
	onProject       map[string]int
}

func readProjectFigures(ctx context.Context, q schooldirectory.Querier, projects []string, staff []profile) (projectFigures, error) {
	f := projectFigures{added: map[[2]string]int{}, capacity: map[[2]string]int{}, hasCapacity: map[[2]string]bool{}, onProject: map[string]int{}}
	staffIDs, userIDs := []string{}, []string{}
	byUser := map[string]string{}
	for _, p := range staff {
		staffIDs = append(staffIDs, p.id)
		userIDs = append(userIDs, p.userID)
		byUser[p.userID] = p.id
	}
	rows, err := q.Query(ctx, `SELECT project_id, assigned_staff_id, assigned_by, COUNT(id) FROM project_school_assignment
WHERE project_id = ANY($1) AND (assigned_staff_id = ANY($2) OR (assigned_by = ANY($3) AND assigned_staff_id IS NULL)) GROUP BY 1, 2, 3`,
		projects, staffIDs, userIDs)
	if err != nil {
		return f, fmt.Errorf("trainingsummary: reading project schools: %w", err)
	}
	for rows.Next() {
		var project string
		var staffID, by *string
		var n int
		if err := rows.Scan(&project, &staffID, &by, &n); err != nil {
			rows.Close()
			return f, fmt.Errorf("trainingsummary: reading project schools: %w", err)
		}
		who := ""
		if staffID != nil && *staffID != "" {
			who = *staffID
		} else if by != nil {
			who = byUser[*by]
		}
		if who != "" {
			f.added[[2]string{project, who}] += n
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return f, fmt.Errorf("trainingsummary: reading project schools: %w", err)
	}
	rows, err = q.Query(ctx, `SELECT project_id, staff_id, max_schools FROM project_staff_capacity WHERE project_id = ANY($1) AND staff_id = ANY($2)`, projects, staffIDs)
	if err != nil {
		return f, fmt.Errorf("trainingsummary: reading project capacity: %w", err)
	}
	for rows.Next() {
		var project, staffID string
		var maximum int
		if err := rows.Scan(&project, &staffID, &maximum); err != nil {
			rows.Close()
			return f, fmt.Errorf("trainingsummary: reading project capacity: %w", err)
		}
		f.capacity[[2]string{project, staffID}] = maximum
		f.hasCapacity[[2]string{project, staffID}] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return f, fmt.Errorf("trainingsummary: reading project capacity: %w", err)
	}
	rows, err = q.Query(ctx, `SELECT project_id, COUNT(id) FROM project_school_assignment WHERE project_id = ANY($1) GROUP BY 1`, projects)
	if err != nil {
		return f, fmt.Errorf("trainingsummary: reading project totals: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var project string
		var n int
		if err := rows.Scan(&project, &n); err != nil {
			return f, fmt.Errorf("trainingsummary: reading project totals: %w", err)
		}
		f.onProject[project] = n
	}
	return f, rows.Err()
}
