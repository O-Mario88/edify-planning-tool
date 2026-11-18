package schoolprofile

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The Participation tab's activity list (apps.activities.profile_activities
// for a school, drawn by partials/components/profile_activities.html and
// profile_activity_table.html): the school's planned and completed work in
// two tables, each row with the menu the reader may use.

// listedActivity is one activity as the list reads it.
type listedActivity struct {
	id, status, kind, name                    string
	planned, actual, end                      *time.Time
	scheduled                                 *time.Time
	schoolID, clusterID                       string
	delivery, partnerID, staffID, monitorID   string
	intervention, purposeText, venue          string
	salesforceID                              string
	reschedules                               int
	schoolName, schoolCode, schoolOwner       string
	hasSchool, hasSchoolCode                  bool
	clusterName, clusterDistrict, clusterLead string
	hasCluster, clusterLive                   bool
	inCountry                                 bool
}

// activityRow is ProfileActivityRow: what one table row shows.
type activityRow struct {
	a                                    listedActivity
	title, subject, subjectURL, executor string
	purpose, statusLabel, statusTone     string
	day, endDay                          *time.Time
	actions                              []*screensv1.PageAction
	canPick                              bool
}

type activityList struct {
	planned, completed []activityRow
	overdue            int
}

// activityList reads the school's work (profile_activities.for_school): at
// the school, or a cluster session it was invited to or attended.
func (s *Service) activityList(ctx context.Context, p auth.Principal, scope schooldirectory.Scope, d doors, sc school, today time.Time) (activityList, error) {
	var out activityList
	pr := rules.Participation
	planned, err := s.listed(ctx, scope, sc, pr.OpenStatuses,
		"a.planned_date ASC NULLS LAST, a.created_at, a.id")
	if err != nil {
		return out, err
	}
	completed, err := s.listed(ctx, scope, sc, pr.DeliveredStatuses,
		"COALESCE(a.actual_delivery_date, a.planned_date) DESC NULLS LAST, a.created_at DESC, a.id")
	if err != nil {
		return out, err
	}
	// A table longer than its page is paged on the web.
	if len(planned) > pr.PageSize || len(completed) > pr.PageSize {
		return out, errTooLong
	}
	for _, a := range planned {
		if a.planned != nil && a.planned.Before(today) && slices.Contains(pr.PlannedStatuses, a.status) {
			out.overdue++
		}
	}
	all := append(append([]listedActivity{}, planned...), completed...)
	names, err := s.executors(ctx, all)
	if err != nil {
		return out, err
	}
	r := reader{p: p, scope: scope, s: s}
	for i, a := range all {
		row, err := r.decorate(ctx, d, a, names, today)
		if err != nil {
			return out, err
		}
		if i < len(planned) {
			out.planned = append(out.planned, row)
		} else {
			out.completed = append(out.completed, row)
		}
	}
	return out, nil
}

func (s *Service) listed(ctx context.Context, scope schooldirectory.Scope, sc school, statuses []string, order string) ([]listedActivity, error) {
	return s.listedWhere(ctx, scope, statuses, order, func(args *[]any) string {
		*args = append(*args, sc.ID)
		n := len(*args)
		return fmt.Sprintf(`(a.school_id = $%[1]d OR a.id IN (
    SELECT c.activity_id FROM cluster_activity_attendance c WHERE c.school_id = $%[1]d AND (c.invited OR c.attended)))`, n)
	})
}

// listedWhere reads the activities of one status group that source picks
// (a profile's own question: profile_activities.for_school, for_district…),
// in order.
func (s *Service) listedWhere(ctx context.Context, scope schooldirectory.Scope, statuses []string, order string, source func(args *[]any) string) ([]listedActivity, error) {
	args := []any{statuses}
	picked := source(&args)
	inCountry := "false"
	if scope.CountryScope && scope.Country != "" {
		args = append(args, scope.CountryIDs())
		inCountry = activityInCountry(len(args))
	}
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.status, ''), COALESCE(a.activity_type, ''), COALESCE(a.activity_name_snapshot, ''),
  a.planned_date, a.actual_delivery_date, a.end_date, a.scheduled_date,
  COALESCE(a.school_id, ''), COALESCE(a.cluster_id, ''), COALESCE(a.delivery_type, ''),
  COALESCE(a.assigned_partner_id, ''), COALESCE(a.responsible_staff_id, ''), COALESCE(a.monitored_by_staff_id, ''),
  COALESCE(a.purpose_intervention, ''), COALESCE(a.activity_purpose_text, ''), COALESCE(a.venue, ''),
  COALESCE(a.reschedule_count, 0), COALESCE(a.salesforce_activity_id, ''),
  COALESCE(s.name, ''), COALESCE(s.school_id, ''), COALESCE(s.account_owner_id, ''), s.id IS NOT NULL, s.school_id IS NOT NULL,
  COALESCE(cl.name, ''), COALESCE(cl.district_id, ''), COALESCE(cl.responsible_staff_id, ''),
  cl.id IS NOT NULL, cl.id IS NOT NULL AND cl.deleted_at IS NULL, `+inCountry+`
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN cluster cl ON cl.id = a.cluster_id
WHERE a.deleted_at IS NULL AND a.status = ANY($1) AND `+picked+`
ORDER BY `+order, args...)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the profile's activities: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (listedActivity, error) {
		var a listedActivity
		var reschedules int32
		err := row.Scan(&a.id, &a.status, &a.kind, &a.name, &a.planned, &a.actual, &a.end, &a.scheduled,
			&a.schoolID, &a.clusterID, &a.delivery, &a.partnerID, &a.staffID, &a.monitorID,
			&a.intervention, &a.purposeText, &a.venue, &reschedules, &a.salesforceID,
			&a.schoolName, &a.schoolCode, &a.schoolOwner, &a.hasSchool, &a.hasSchoolCode,
			&a.clusterName, &a.clusterDistrict, &a.clusterLead, &a.hasCluster, &a.clusterLive, &a.inCountry)
		a.reschedules = int(reschedules)
		return a, err
	})
}

// activityInCountry is scoping.activity_country_q over an activity a with
// its school s and cluster cl, the country being argument n: through its
// school (a placed school's region, or an unplaced school's owner), its
// cluster (its region, or its district's), or, with neither, the person
// responsible for it.
func activityInCountry(n int) string {
	return registry.ActivityIn("a", "s", "cl", fmt.Sprintf("$%d", n))
}

// executorNames are _staff_names and _partner_names for the listed work.
type executorNames struct{ staff, partners map[string]string }

func (s *Service) executors(ctx context.Context, all []listedActivity) (executorNames, error) {
	names := executorNames{staff: map[string]string{}, partners: map[string]string{}}
	staffIDs, partnerIDs := []string{}, []string{}
	for _, a := range all {
		if a.staffID != "" {
			staffIDs = append(staffIDs, a.staffID)
		}
		if a.partnerID != "" {
			partnerIDs = append(partnerIDs, a.partnerID)
		}
	}
	if len(staffIDs) > 0 {
		rows, err := s.db.Query(ctx, `
SELECT sp.id, COALESCE(sp.user_id, ''), CASE WHEN sp.user_id IS NULL OR sp.user_id = '' THEN '' ELSE COALESCE(NULLIF(u.name, ''), u.email, '') END
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1))`, staffIDs)
		if err != nil {
			return names, fmt.Errorf("schoolprofile: reading staff names: %w", err)
		}
		for rows.Next() {
			var id, userID, name string
			if err := rows.Scan(&id, &userID, &name); err != nil {
				rows.Close()
				return names, err
			}
			names.staff[id] = name
			if userID != "" {
				names.staff[userID] = name
			}
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return names, err
		}
		missing := []string{}
		for _, id := range staffIDs {
			if _, ok := names.staff[id]; !ok {
				missing = append(missing, id)
			}
		}
		if len(missing) > 0 {
			rows, err := s.db.Query(ctx, `SELECT id, COALESCE(NULLIF(name, ''), email, '') FROM "user" WHERE id = ANY($1)`, missing)
			if err != nil {
				return names, fmt.Errorf("schoolprofile: reading user names: %w", err)
			}
			for rows.Next() {
				var id, name string
				if err := rows.Scan(&id, &name); err != nil {
					rows.Close()
					return names, err
				}
				names.staff[id] = name
			}
			rows.Close()
			if err := rows.Err(); err != nil {
				return names, err
			}
		}
	}
	if len(partnerIDs) > 0 {
		rows, err := s.db.Query(ctx, `SELECT id, COALESCE(name, '') FROM partner WHERE id = ANY($1) AND deleted_at IS NULL`, partnerIDs)
		if err != nil {
			return names, fmt.Errorf("schoolprofile: reading partner names: %w", err)
		}
		defer rows.Close()
		for rows.Next() {
			var id, name string
			if err := rows.Scan(&id, &name); err != nil {
				return names, err
			}
			names.partners[id] = name
		}
		return names, rows.Err()
	}
	return names, nil
}

// reader is the person the list is drawn for, and what deciding whether
// they may run a piece of work reads.
type reader struct {
	p     auth.Principal
	scope schooldirectory.Scope
	s     *Service
	// clusterOwners is cluster_owner_ids(scope, direct_only=True), read once.
	clusterOwners []string
	ownersRead    bool
}

// ownerIDs is scoping.owner_ids: both ids the reader's work is filed under.
func (r *reader) ownerIDs() []string {
	ids := []string{}
	for _, id := range []string{r.p.UserID, r.p.StaffProfileID} {
		if id != "" {
			ids = append(ids, id)
		}
	}
	return ids
}

func (r *reader) owns(id string) bool { return id != "" && slices.Contains(r.ownerIDs(), id) }

// decorate is profile_activities._decorate for one activity.
func (r *reader) decorate(ctx context.Context, d doors, a listedActivity, names executorNames, today time.Time) (activityRow, error) {
	pr := rules.Participation
	isPartner := a.delivery == "partner" || a.status == "assigned_to_partner" || a.status == "partner_scheduled"
	kindLabel, ok := pr.ActivityTypes[a.kind]
	if !ok {
		kindLabel = pyTitle(strings.ReplaceAll(a.kind, "_", " "))
	}
	row := activityRow{a: a, title: a.name}
	if row.title == "" {
		row.title = kindLabel
	}
	row.statusLabel, row.statusTone = activityStatus(a, today)
	row.subject, row.subjectURL = activitySubject(a)
	if isPartner && a.partnerID != "" {
		row.executor = "Partner"
		if name, ok := names.partners[a.partnerID]; ok {
			row.executor = name
		}
	} else {
		row.executor = names.staff[a.staffID]
	}
	if row.executor == "" {
		row.executor = "—"
	}
	row.purpose = rules.SSAInterventions[a.intervention]
	if row.purpose == "" {
		row.purpose = a.purposeText
	}
	switch {
	case slices.Contains(pr.DeliveredStatuses, a.status) && a.actual != nil:
		row.day = a.actual
	case a.planned != nil:
		row.day = a.planned
	case a.scheduled != nil:
		local := kampalaDay(*a.scheduled)
		row.day = &local
	}
	if a.end != nil && (a.planned == nil || !a.end.Equal(*a.planned)) {
		row.endDay = a.end
	}

	row.actions = []*screensv1.PageAction{menuItem("View activity", "/my-plan/"+a.id, "menu")}
	if !d.MyPlan || isPartner {
		return row, nil
	}
	may, err := r.mayRun(ctx, a)
	if err != nil || !may {
		return row, err
	}
	editable := (slices.Contains(pr.EditableStatuses, a.status) || slices.Contains(pr.BegunStatuses, a.status)) && a.delivery != "partner"
	locked := slices.Contains(pr.ExecutedStatuses, a.status)
	var mayComplete, mayReschedule, mayCancel bool
	completeLabel := "Complete"
	switch {
	case slices.Contains(pr.OpenStatuses, a.status):
		awaiting := a.status == "awaiting_owner_approval"
		mayComplete = !awaiting && !slices.Contains(pr.NeedsReplanningStatuses, a.status)
		mayReschedule = !awaiting && !locked
		mayCancel = true
	case slices.Contains(pr.StillCompletingStatuses, a.status):
		mayComplete = true
		completeLabel = "Finish completion"
	}
	// A locked Edit has no address, so the menu the app reads leaves it out.
	if editable {
		row.actions = append(row.actions, menuItem("Edit", "/my-plan/"+a.id+"/edit-drawer", "menu"))
	}
	if mayComplete {
		row.actions = append(row.actions, menuItem(completeLabel, "/my-plan/"+a.id+"/complete-drawer", "menu"))
	}
	if mayReschedule {
		row.actions = append(row.actions, menuItem("Reschedule", "/my-plan/"+a.id+"/reschedule-drawer", "menu"))
	}
	if mayCancel {
		row.actions = append(row.actions, menuItem("Cancel activity", "/my-plan/"+a.id+"/cancel-drawer", "danger"))
	}
	row.canPick = mayReschedule || mayCancel
	return row, nil
}

func menuItem(label, href, key string) *screensv1.PageAction {
	return &screensv1.PageAction{Key: key, Label: label, Enabled: true, Href: href, Drawer: true}
}

// mayRun is profile_activities._may_run: the scope, scheduling and
// execution checks the complete, reschedule and cancel services run.
func (r *reader) mayRun(ctx context.Context, a listedActivity) (bool, error) {
	if !r.inScope(a) || !r.maySchedule(a) {
		return false, nil
	}
	return r.mayExecute(ctx, a)
}

// inScope is services._assert_in_scope.
func (r *reader) inScope(a listedActivity) bool {
	sc := r.scope
	if sc.CountryScope {
		return sc.Country == "" || a.inCountry
	}
	switch {
	case r.p.StaffProfileID != "" && a.staffID == r.p.StaffProfileID:
	case r.owns(a.monitorID):
	case a.schoolID != "" && slices.Contains(sc.SchoolIDs, a.schoolID):
	case a.schoolID != "" && a.hasSchool && r.owns(a.schoolOwner):
	default:
		return false
	}
	return true
}

// maySchedule is services._assert_may_schedule.
func (r *reader) maySchedule(a listedActivity) bool {
	if slices.Contains(rules.Participation.CountrySchedulingRoles, r.scope.Role) || r.owns(a.staffID) {
		return true
	}
	return !r.scope.CountryScope
}

// mayExecute is services._assert_may_execute: supervision is not holding.
func (r *reader) mayExecute(ctx context.Context, a listedActivity) (bool, error) {
	sc := r.scope
	if sc.Role == rules.Participation.CountryDirector {
		return r.owns(a.staffID) || r.owns(a.monitorID), nil
	}
	if slices.Contains(rules.Participation.CountrySchedulingRoles, sc.Role) || sc.CountryScope {
		return true, nil
	}
	if len(sc.SupervisedStaffIDs) == 0 {
		return true, nil
	}
	if r.owns(a.staffID) || r.owns(a.monitorID) {
		return true, nil
	}
	if a.schoolID != "" && slices.Contains(sc.OwnSchoolIDs, a.schoolID) {
		return true, nil
	}
	if a.clusterID == "" || !a.clusterLive {
		return false, nil
	}
	// cluster_in_scope(direct_only=True).
	if slices.Contains(sc.OwnClusterIDs, a.clusterID) {
		return true, nil
	}
	if lead := strings.TrimSpace(a.clusterLead); lead != "" {
		owners, err := r.directClusterOwners(ctx)
		return slices.Contains(owners, lead), err
	}
	return a.clusterDistrict != "" && slices.Contains(sc.OwnDistrictIDs, a.clusterDistrict), nil
}

// directClusterOwners is cluster_owner_ids(direct_only=True): the reader's
// ids, each with its twin in the other id space.
func (r *reader) directClusterOwners(ctx context.Context) ([]string, error) {
	if r.ownersRead {
		return r.clusterOwners, nil
	}
	ids := []string{}
	for _, id := range []string{r.scope.UserID, r.p.StaffProfileID} {
		if id != "" {
			ids = append(ids, id)
		}
	}
	r.clusterOwners, r.ownersRead = ids, true
	if len(ids) == 0 {
		return ids, nil
	}
	rows, err := r.s.db.Query(ctx, `
SELECT id, COALESCE(user_id, '') FROM staff_profile WHERE deleted_at IS NULL AND (id = ANY($1) OR user_id = ANY($1))`, ids)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading cluster owners: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, userID string
		if err := rows.Scan(&id, &userID); err != nil {
			return nil, err
		}
		for _, v := range []string{id, userID} {
			if v != "" && !slices.Contains(r.clusterOwners, v) {
				r.clusterOwners = append(r.clusterOwners, v)
			}
		}
	}
	return r.clusterOwners, rows.Err()
}

// activityStatus is profile_activities._status.
func activityStatus(a listedActivity, today time.Time) (string, string) {
	pr := rules.Participation
	st := a.status
	switch {
	case slices.Contains(pr.VerifiedStatuses, st):
		return "Complete", "success"
	case st == "submitted_to_pl":
		return "PL Pending", "info"
	case st == "awaiting_ia_verification":
		if a.delivery == "partner" {
			return "IA Pending", "info"
		}
		return "PL Pending", "info"
	case st == "completed":
		return "Awaiting Verification", "info"
	case slices.Contains(pr.StillCompletingStatuses, st):
		if st == "salesforce_id_required" || a.salesforceID == "" {
			return "Activity ID Missing", "warning"
		}
		return "Evidence Uploaded", "warning"
	case slices.Contains(pr.NeedsReplanningStatuses, st):
		return "Returned for Correction", "danger"
	case st == "awaiting_owner_approval":
		return "Awaiting Owner Approval", "warning"
	case st == "assigned_to_partner":
		return "Partner to Schedule", "info"
	case st == "in_progress" || st == "completion_started":
		return "In Progress", "info"
	}
	label := "Scheduled"
	if st == "partner_scheduled" {
		label = "Partner Scheduled"
	} else if a.reschedules != 0 {
		label = "Rescheduled"
	}
	if a.planned != nil {
		if a.planned.Before(today) {
			return "Overdue", "danger"
		}
		if a.planned.Equal(today) {
			return "Due Today", "warning"
		}
	}
	return label, "info"
}

// activitySubject is profile_activities._subject with subject "auto".
func activitySubject(a listedActivity) (string, string) {
	if a.schoolID != "" && a.hasSchool {
		code := a.schoolCode
		if !a.hasSchoolCode {
			code = "None"
		}
		return a.schoolName, "/schools/" + code
	}
	if a.clusterID != "" && a.hasCluster {
		return a.clusterName, "/clusters/" + a.clusterID
	}
	if a.venue != "" {
		return a.venue, ""
	}
	return "Programme work", ""
}

// pyTitle is Python's str.title(): each run of letters starts upper case.
func pyTitle(s string) string {
	var b strings.Builder
	after := false
	for _, c := range s {
		letter := strings.ToUpper(string(c)) != strings.ToLower(string(c))
		if letter && !after {
			b.WriteString(strings.ToUpper(string(c)))
		} else if letter {
			b.WriteString(strings.ToLower(string(c)))
		} else {
			b.WriteRune(c)
		}
		after = letter
	}
	return b.String()
}

// truncateChars is Django's |truncatechars: n characters at most, the last
// an ellipsis.
func truncateChars(s string, n int) string {
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	return string([]rune(s)[:n-1]) + "…"
}

// collapse is how the page reader reads text: whitespace runs as one space.
func collapse(s string) string { return strings.Join(strings.Fields(s), " ") }

// ── Drawing the list ────────────────────────────────────────────────────────

func (l activityList) block() *screensv1.PageBlock {
	subtitle := fmt.Sprintf("%d planned · %d completed", len(l.planned), len(l.completed))
	if l.overdue != 0 {
		subtitle += fmt.Sprintf(" · %d overdue", l.overdue)
	}
	active := "planned"
	if len(l.planned) == 0 && len(l.completed) > 0 {
		active = "completed"
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Segments{Segments: &screensv1.PageSegments{
		Title:    "Planned & Completed Activities",
		Subtitle: subtitle,
		Caption:  "Visits and trainings at this school, and the cluster sessions it is invited to.",
		Segments: []*screensv1.PageSegment{
			{Label: "Planned", Count: fmt.Sprint(len(l.planned)), Active: active == "planned",
				Blocks: []*screensv1.PageBlock{activityTable(l.planned, false)}},
			{Label: "Completed", Count: fmt.Sprint(len(l.completed)), Active: active == "completed",
				Blocks: []*screensv1.PageBlock{activityTable(l.completed, true)}},
		},
	}}}
}

// selection is the bar for ticked activities, drawn where a planned row
// can be ticked.
func (l activityList) selection() *screensv1.PageSelection {
	for _, row := range l.planned {
		if row.canPick {
			return &screensv1.PageSelection{Noun: "activities selected", Actions: []*screensv1.PageSelectionAction{
				{Label: "Reschedule", Href: "/activity-selection/reschedule", Param: "ids", Joined: true},
				{Label: "Cancel", Href: "/activity-selection/cancel", Param: "ids", Joined: true},
			}}
		}
	}
	return nil
}

func activityTable(rows []activityRow, done bool) *screensv1.PageBlock {
	first, empty := "Planned Date", "No planned activities."
	if done {
		first, empty = "Delivered", "No completed activities yet."
	}
	table := &screensv1.PageTable{
		Columns: columns([][2]string{{first, ""}, {"Activity", ""}, {"Where", ""}, {"Executor", ""}, {"Status", ""},
			{"Purpose", ""}, {"Actions", "num"}}),
		Rows: []*screensv1.PageRow{},
	}
	for _, row := range rows {
		date := "Not dated"
		if row.day != nil {
			date = jMY(*row.day)
			if row.endDay != nil {
				date += " – " + jM(*row.endDay)
			}
		}
		purpose := row.purpose
		if purpose == "" {
			purpose = "—"
		}
		r := &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: date},
			{Text: collapse(row.title)},
			{Text: collapse(row.subject), Href: row.subjectURL},
			{Text: collapse(row.executor)},
			{Text: row.statusLabel, Tone: row.statusTone},
			{Text: collapse(truncateChars(purpose, 60))},
			{Actions: row.actions},
		}}
		if row.canPick {
			r.PickId, r.PickLabel = row.a.id, pickLabel(row)
		}
		table.Rows = append(table.Rows, r)
	}
	if len(rows) == 0 {
		table.Rows = append(table.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{{Text: empty}}})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}}
}

// pickLabel is partials/activities/pick_cell.html's aria-label.
func pickLabel(row activityRow) string {
	kind := row.title
	if kind == "" {
		kind = "activity"
	}
	label := "Select " + kind
	if row.subject != "" {
		label += " at " + row.subject
	}
	if row.day != nil {
		label += " on " + jMY(*row.day)
	}
	return label
}
