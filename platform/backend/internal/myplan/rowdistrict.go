package myplan

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// District marks (apps.daily_visit_batches.district_marks): an activity on
// a shared costed day carries the day's mark, any other its own district's
// type for the person responsible.
const (
	primaryDay   = "primary"
	secondaryDay = "secondary"
	mixedDay     = "mixed"
)

// dayMark is pricing.day_district_mark.
func dayMark(types []string) string {
	hasPrimary, hasSecondary := false, false
	for _, t := range types {
		if t == "" {
			t = primaryDay
		}
		hasPrimary = hasPrimary || t == primaryDay
		hasSecondary = hasSecondary || t == secondaryDay
	}
	if hasSecondary {
		if hasPrimary {
			return mixedDay
		}
		return secondaryDay
	}
	return primaryDay
}

type traveller struct {
	found      bool // a profile or an account to resolve for
	profile    bool
	home       *string
	roles      []string
	activeRole *string
}

func isNoRows(err error) bool { return errors.Is(err, pgx.ErrNoRows) }

func casefold(s string) string { return strings.ToLower(pyStrip(s)) }

func isFieldRole(role string) bool {
	return in(rules.Rows.FieldRoles, role) || in(rules.Rows.FieldRoleAliases, casefold(role))
}

func (t traveller) field() bool {
	if len(t.roles) == 0 {
		return t.activeRole != nil && isFieldRole(*t.activeRole)
	}
	for _, r := range t.roles {
		if isFieldRole(r) {
			return true
		}
	}
	return false
}

type districtRow struct {
	id, name     string
	districtType *string
}

// districtMarks is district_marks.district_type_marks, read in the shape the
// existing code reads it.
type districtMarks struct {
	db         schooldirectory.Querier
	travellers map[string]traveller
	districts  map[string]districtRow
	types      map[[2]string]string
}

func (m *districtMarks) traveller(ctx context.Context, id string) (traveller, error) {
	if t, ok := m.travellers[id]; ok {
		return t, nil
	}
	var t traveller
	if id != "" {
		var hasUser bool
		err := m.db.QueryRow(ctx, `SELECT sp.primary_district_id, u.id IS NOT NULL, COALESCE(u.roles, '{}'), u.active_role
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.user_id = $1 OR sp.id = $1) ORDER BY sp.id ASC LIMIT 1`, id).
			Scan(&t.home, &hasUser, &t.roles, &t.activeRole)
		switch {
		case err == nil:
			t.profile, t.found = true, hasUser
		case isNoRows(err):
			err = m.db.QueryRow(ctx, `SELECT COALESCE(roles, '{}'), active_role FROM "user" WHERE id = $1`, id).Scan(&t.roles, &t.activeRole)
			if err == nil {
				t.found = true
			} else if !isNoRows(err) {
				return t, fmt.Errorf("myplan: traveller: %w", err)
			}
		default:
			return t, fmt.Errorf("myplan: traveller: %w", err)
		}
	}
	m.travellers[id] = t
	return t, nil
}

// typeFor is district_type_for_staff, else the primary day: ok is false
// for a district type the existing code has no label for (it fails there).
func (m *districtMarks) typeFor(ctx context.Context, person, districtID string) (string, error) {
	key := [2]string{person, districtID}
	if t, ok := m.types[key]; ok {
		return t, nil
	}
	d, ok := m.districts[districtID]
	t := ""
	if ok {
		who, err := m.traveller(ctx, person)
		if err != nil {
			return "", err
		}
		switch {
		case !who.found:
			t = str(d.districtType)
		case who.profile && who.field():
			if isSet(who.home) {
				t = secondaryDay
				if *who.home == d.id {
					t = primaryDay
				}
			} else {
				t = str(d.districtType)
			}
		default:
			t = secondaryDay
			for _, name := range rules.Rows.HQPrimaryDistricts {
				if casefold(d.name) == casefold(name) {
					t = primaryDay
				}
			}
		}
	}
	if t == "" {
		t = primaryDay
	}
	m.types[key] = t
	return t, nil
}

type markRow struct {
	id                     string
	staff, batch           *string
	day                    *time.Time
	school, cluster, event *string
}

func firstDistrict(ids ...*string) string {
	for _, id := range ids {
		if isSet(id) {
			return *id
		}
	}
	return ""
}

// DistrictTypeLabels is district_marks.district_type_labels: each
// activity's Primary, Secondary or Mixed District mark.
func DistrictTypeLabels(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]string, error) {
	return readDistrictTypes(ctx, db, ids)
}

// readDistrictTypes answers {activity id: label} (district_type_labels).
func readDistrictTypes(ctx context.Context, db schooldirectory.Querier, ids []string) (map[string]string, error) {
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT a.id, a.responsible_staff_id, a.planned_date, a.daily_visit_batch_id, s.district_id, c.district_id, a.event_district_id
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE a.deleted_at IS NULL AND a.id = ANY($1)`, ids)
	if err != nil {
		return nil, fmt.Errorf("myplan: district marks: %w", err)
	}
	var marks []markRow
	for rows.Next() {
		var r markRow
		if err := rows.Scan(&r.id, &r.staff, &r.day, &r.batch, &r.school, &r.cluster, &r.event); err != nil {
			rows.Close()
			return nil, err
		}
		marks = append(marks, r)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	var staff []string
	for _, r := range marks {
		if isSet(r.staff) && !in(staff, *r.staff) {
			staff = append(staff, *r.staff)
		}
	}
	userOf := map[string]string{}
	if len(staff) > 0 {
		rows, err := db.Query(ctx, `SELECT id, user_id FROM staff_profile WHERE deleted_at IS NULL AND id = ANY($1)`, staff)
		if err != nil {
			return nil, fmt.Errorf("myplan: staff accounts: %w", err)
		}
		for rows.Next() {
			var id string
			var user *string
			if err := rows.Scan(&id, &user); err != nil {
				rows.Close()
				return nil, err
			}
			userOf[id] = "None"
			if user != nil {
				userOf[id] = *user
			}
		}
		rows.Close()
	}
	person := func(staff string) string {
		if u, ok := userOf[staff]; ok {
			return u
		}
		return staff
	}
	type loose struct{ user, day string }
	batches := map[string]bool{}
	looseDays := map[loose]bool{}
	var users, days []string
	for _, r := range marks {
		if isSet(r.batch) {
			batches[*r.batch] = true
		} else if isSet(r.staff) && r.day != nil {
			k := loose{person(*r.staff), r.day.Format(time.DateOnly)}
			looseDays[k] = true
			users, days = append(users, k.user), append(days, k.day)
		}
	}
	dayOf := map[loose]string{}
	if len(looseDays) > 0 {
		rows, err := db.Query(ctx, `SELECT id, responsible_user, visit_date FROM daily_visit_batch
WHERE responsible_user = ANY($1) AND visit_date = ANY($2::date[])`, users, days)
		if err != nil {
			return nil, fmt.Errorf("myplan: visit days: %w", err)
		}
		for rows.Next() {
			var id string
			var user *string
			var d time.Time
			if err := rows.Scan(&id, &user, &d); err != nil {
				rows.Close()
				return nil, err
			}
			if k := (loose{str(user), d.Format(time.DateOnly)}); user != nil && looseDays[k] {
				dayOf[k] = id
				batches[id] = true
			}
		}
		rows.Close()
	}
	var batchIDs []string
	for id := range batches {
		batchIDs = append(batchIDs, id)
	}
	ownerOf, members := map[string]string{}, map[string][]string{}
	if len(batchIDs) > 0 {
		rows, err := db.Query(ctx, `SELECT id, responsible_user FROM daily_visit_batch WHERE id = ANY($1)`, batchIDs)
		if err != nil {
			return nil, fmt.Errorf("myplan: visit days: %w", err)
		}
		for rows.Next() {
			var id string
			var user *string
			if err := rows.Scan(&id, &user); err != nil {
				rows.Close()
				return nil, err
			}
			ownerOf[id] = str(user)
		}
		rows.Close()
		rows, err = db.Query(ctx, `SELECT a.daily_visit_batch_id, s.district_id, c.district_id, a.event_district_id
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE a.deleted_at IS NULL AND a.daily_visit_batch_id = ANY($1) AND NOT COALESCE(a.status = ANY($2), false)`,
			batchIDs, rules.Rows.NonFundableStatuses)
		if err != nil {
			return nil, fmt.Errorf("myplan: day members: %w", err)
		}
		for rows.Next() {
			var batch string
			var school, cluster, event *string
			if err := rows.Scan(&batch, &school, &cluster, &event); err != nil {
				rows.Close()
				return nil, err
			}
			members[batch] = append(members[batch], firstDistrict(school, cluster, event))
		}
		rows.Close()
	}
	var districtIDs []string
	for _, r := range marks {
		if d := firstDistrict(r.school, r.cluster, r.event); d != "" && !in(districtIDs, d) {
			districtIDs = append(districtIDs, d)
		}
	}
	for _, ds := range members {
		for _, d := range ds {
			if d != "" && !in(districtIDs, d) {
				districtIDs = append(districtIDs, d)
			}
		}
	}
	m := &districtMarks{db: db, travellers: map[string]traveller{}, districts: map[string]districtRow{}, types: map[[2]string]string{}}
	if len(districtIDs) > 0 {
		rows, err := db.Query(ctx, `SELECT id, name, district_type FROM district WHERE id = ANY($1)`, districtIDs)
		if err != nil {
			return nil, fmt.Errorf("myplan: districts: %w", err)
		}
		for rows.Next() {
			var d districtRow
			if err := rows.Scan(&d.id, &d.name, &d.districtType); err != nil {
				rows.Close()
				return nil, err
			}
			m.districts[d.id] = d
		}
		rows.Close()
	}
	dayMarks := map[string]string{}
	for _, r := range marks {
		own, err := m.typeFor(ctx, str(r.staff), firstDistrict(r.school, r.cluster, r.event))
		if err != nil {
			return nil, err
		}
		batch := str(r.batch)
		if batch == "" && isSet(r.staff) && r.day != nil {
			batch = dayOf[loose{person(*r.staff), r.day.Format(time.DateOnly)}]
		}
		mark := own
		if batch != "" && len(members[batch]) > 0 {
			of, seen := dayMarks[batch]
			if !seen {
				var types []string
				for _, d := range members[batch] {
					t, err := m.typeFor(ctx, ownerOf[batch], d)
					if err != nil {
						return nil, err
					}
					types = append(types, t)
				}
				of = dayMark(types)
				dayMarks[batch] = of
			}
			mark = of
			if of != mixedDay {
				mark = dayMark([]string{of, own})
			}
		}
		label, ok := rules.Rows.DayMarkLabels[mark]
		if !ok {
			return nil, fmt.Errorf("%w: a district type with no label", ErrUnported)
		}
		out[r.id] = label
	}
	return out, nil
}
