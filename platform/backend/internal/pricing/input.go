package pricing

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing"
)

// Input is what the single cost writer prices a stored activity with:
// _costing_input(activity, {}) before the costing profile is applied.
type Input struct {
	costing.Activity
	CatalogueItemID string
	Profile         string
	PlannedDate     *time.Time
}

type stored struct {
	activityType, delivery, responsible, profile, itemID string
	teachers, leaders, others, expected                  *int
	printing, photocopyPages, photocopyCopies            *int
	plannedDate, endDate                                 *time.Time
	facilitator                                          *string
	schoolDistrict, clusterDistrict, eventDistrict       *string
}

// StoredInput reads the activity and builds its input.
func StoredInput(ctx context.Context, db Querier, activityID string) (Input, error) {
	var s stored
	err := db.QueryRow(ctx, `
		SELECT COALESCE(a.activity_type, ''), COALESCE(a.delivery_type, ''), COALESCE(a.responsible_staff_id, ''),
		       COALESCE(a.costing_profile_snapshot, ''), COALESCE(a.catalogue_item_id, ''),
		       a.teachers_attended, a.leaders_attended, a.other_participants, a.expected_participants,
		       a.printing_pages, a.photocopy_pages, a.photocopy_copies, a.planned_date, a.end_date,
		       a.facilitating_partner_id, sc.district_id, cl.district_id, a.event_district_id
		FROM activity a
		LEFT JOIN school sc ON sc.id = a.school_id
		LEFT JOIN cluster cl ON cl.id = a.cluster_id
		WHERE a.id = $1`, activityID,
	).Scan(&s.activityType, &s.delivery, &s.responsible, &s.profile, &s.itemID,
		&s.teachers, &s.leaders, &s.others, &s.expected, &s.printing, &s.photocopyPages, &s.photocopyCopies,
		&s.plannedDate, &s.endDate, &s.facilitator, &s.schoolDistrict, &s.clusterDistrict, &s.eventDistrict)
	if err != nil {
		return Input{}, fmt.Errorf("pricing: reading activity %s: %w", activityID, err)
	}
	traveller, err := readTraveller(ctx, db, s.responsible)
	if err != nil {
		return Input{}, err
	}
	district := ""
	switch {
	case s.schoolDistrict != nil:
		if district, err = traveller.districtType(ctx, db, *s.schoolDistrict); err != nil {
			return Input{}, err
		}
	case s.clusterDistrict != nil:
		if district, err = traveller.districtType(ctx, db, *s.clusterDistrict); err != nil {
			return Input{}, err
		}
	}
	if district == "" && (s.activityType == "field_event" || s.eventDistrict != nil) {
		// _field_event_district_type: the destination as the day reads it, an
		// unknown or unclassified destination primary.
		district = "primary"
		if s.eventDistrict != nil {
			found, err := traveller.districtType(ctx, db, *s.eventDistrict)
			if err != nil {
				return Input{}, err
			}
			if found != "" {
				district = found
			}
		}
	}
	days := 1
	if s.endDate != nil && s.plannedDate != nil {
		days = int(s.endDate.Sub(*s.plannedDate).Hours()/24) + 1
	}
	in := Input{
		Activity: costing.Activity{
			ActivityType: s.activityType, DeliveryType: s.delivery, DistrictType: district,
			AccommodationKey:     traveller.accommodationKey(),
			Facilitated:          s.facilitator != nil && *s.facilitator != "",
			ExpectedParticipants: s.expected,
			TeachersAttended:     deref(s.teachers), LeadersAttended: deref(s.leaders), OtherParticipants: deref(s.others),
			Days:          days,
			PrintingPages: deref(s.printing), PhotocopyPages: deref(s.photocopyPages), PhotocopyCopies: deref(s.photocopyCopies),
		},
		CatalogueItemID: s.itemID,
		Profile:         s.profile,
		PlannedDate:     s.plannedDate,
	}
	return in, nil
}

func deref(n *int) int {
	if n == nil {
		return 0
	}
	return *n
}

// traveller is the person whose day it is (districts._staff_profile and
// _account): their profile (by account or profile id), the account behind
// it, its roles and its primary district.
type traveller struct {
	hasProfile, known bool
	roles             []string
	active            string
	primaryDistrict   *string
	// The night rate's account (accommodation_key_for_staff): the profile's,
	// else the account the id itself names, which differs from the district's
	// rule only for a profile with no account.
	nightKnown  bool
	nightRoles  []string
	nightActive string
}

func readTraveller(ctx context.Context, db Querier, responsible string) (traveller, error) {
	var t traveller
	if responsible == "" {
		return t, nil
	}
	var userID *string
	err := db.QueryRow(ctx, `
		SELECT sp.user_id, sp.primary_district_id FROM staff_profile sp
		WHERE (sp.user_id = $1 OR sp.id = $1) AND sp.deleted_at IS NULL
		ORDER BY sp.id LIMIT 1`, responsible).Scan(&userID, &t.primaryDistrict)
	switch {
	case errors.Is(err, pgx.ErrNoRows):
		userID = &responsible
	case err != nil:
		return t, fmt.Errorf("pricing: reading the traveller: %w", err)
	default:
		t.hasProfile = true
	}
	account := func(id string) (bool, []string, string, error) {
		var roles []string
		var active string
		err := db.QueryRow(ctx, `SELECT COALESCE(roles, '{}'), COALESCE(active_role, '') FROM "user" WHERE id = $1`, id).
			Scan(&roles, &active)
		switch {
		case errors.Is(err, pgx.ErrNoRows):
			return false, nil, "", nil
		case err != nil:
			return false, nil, "", fmt.Errorf("pricing: reading the traveller's account: %w", err)
		}
		return true, roles, active, nil
	}
	if userID != nil {
		if t.known, t.roles, t.active, err = account(*userID); err != nil {
			return t, err
		}
		t.nightKnown, t.nightRoles, t.nightActive = t.known, t.roles, t.active
		return t, nil
	}
	// A profile with no account: the night rate reads the account the id
	// names; the district rule stops at the district's own classification.
	t.nightKnown, t.nightRoles, t.nightActive, err = account(responsible)
	return t, err
}

// districtType is district_type_for_staff for the traveller and the
// district (by id): "" when the district is not on file.
func (t traveller) districtType(ctx context.Context, db Querier, districtID string) (string, error) {
	var name, legacy *string
	err := db.QueryRow(ctx, `SELECT name, district_type FROM district WHERE id = $1`, districtID).Scan(&name, &legacy)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("pricing: reading district %s: %w", districtID, err)
	}
	str := func(p *string) string {
		if p == nil {
			return ""
		}
		return *p
	}
	return t.decide(districtID, str(name), str(legacy)), nil
}

// decide is district_type_for_staff's rule for a district on file: field
// staff against their primary district (the district's own classification
// until they have one), head office against the Kampala, Wakiso and Mukono
// zone, nobody known the district's own classification.
func (t traveller) decide(districtID, name, legacy string) string {
	if !t.known {
		return legacy
	}
	if t.hasProfile && holdsFieldRole(t.roles, t.active) {
		if t.primaryDistrict != nil && *t.primaryDistrict != "" {
			if *t.primaryDistrict == districtID {
				return "primary"
			}
			return "secondary"
		}
		return legacy
	}
	return hqDistrictType(name)
}

func (t traveller) accommodationKey() string {
	return accommodationKeyFor(t.nightRoles, t.nightActive, t.nightKnown)
}
