package schoolprofile

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// notSpecified is what the Details tab writes for an empty field.
const notSpecified = "Not specified"

// details is partials/schools/_details.html for a school without Business
// Transformation records, read as the page blocks read it: the record's
// panel, Business Transformation, the data quality card, and an Admin's
// Danger Zone.
func (s *Service) details(ctx context.Context, p auth.Principal, scope schooldirectory.Scope, sc school, now time.Time) ([]*screensv1.PageBlock, error) {
	record, err := s.recordPanel(ctx, p, sc, now)
	if err != nil {
		return nil, err
	}
	bt, err := s.businessTransformation(ctx, btReader{p: p, scope: scope, doors: rules.Doors[p.ActiveRole]}, sc)
	if err != nil {
		return nil, err
	}
	blocks := []*screensv1.PageBlock{panelBlock(record), panelBlock(bt), panelBlock(quality(sc))}
	if rules.Doors[p.ActiveRole].DeleteSchool {
		blocks = append(blocks, panelBlock(&screensv1.PagePanel{
			Title:  "Danger Zone",
			Badges: []*screensv1.PageBadge{},
			Items: []*screensv1.PagePanelItem{text("Deleting this school removes it from every directory, dashboard, and analysis. " +
				"SSA history and audit logs are retained. Deletion is blocked while activities are in flight or disbursed funds are unaccounted.")},
		}))
	}
	return blocks, nil
}

func panelBlock(panel *screensv1.PagePanel) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: panel}}
}

func text(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
}

func heading(t string) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Heading{Heading: t}}
}

func fields(facts ...*screensv1.PageFact) *screensv1.PagePanelItem {
	return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Fields{Fields: &screensv1.PageFacts{Facts: facts}}}
}

func fact(label, value, href string) *screensv1.PageFact {
	return &screensv1.PageFact{Label: label, Value: value, Href: href}
}

// orNot is |default:"Not specified".
func orNot(value string) string {
	if value == "" {
		return notSpecified
	}
	return value
}

// recordPanel is "School Demographics & Assignment": where the school is,
// who holds it, its year's visit and training, its cluster and every
// membership before it, and its contacts.
func (s *Service) recordPanel(ctx context.Context, p auth.Principal, sc school, now time.Time) (*screensv1.PagePanel, error) {
	d := rules.Doors[p.ActiveRole]
	fy := schooldirectory.OperationalFY(now)
	facts := []*screensv1.PageFact{fact("Region", orNot(sc.RegionName), "")}
	if sc.HasDistrict {
		facts = append(facts, fact("District", sc.DistrictName, "/districts/"+sc.DistrictID))
	} else {
		facts = append(facts, fact("District", notSpecified, ""))
	}
	if sc.HasSubCounty {
		facts = append(facts, fact("Sub-county", sc.SubCountyName, "/schools?sub_county="+sc.SubCountyID))
	} else {
		facts = append(facts, fact("Sub-county", notSpecified, ""))
	}
	facts = append(facts, fact("Parish", orNot(sc.ParishName), ""))
	enrolment := notSpecified
	if sc.Enrollment != nil && *sc.Enrollment != 0 {
		enrolment = strconv.Itoa(*sc.Enrollment)
	}
	facts = append(facts, fact("Pupil Enrolment", enrolment, ""))
	coordinates := notSpecified
	if sc.Latitude != nil && sc.Longitude != nil {
		coordinates = floatformat(*sc.Latitude, 6) + ", " + floatformat(*sc.Longitude, 6)
	}
	facts = append(facts, fact("Coordinates", coordinates, ""), fact("Current Partner Type", label(rules.SchoolTypes, sc.Type), ""))
	if (sc.CohortYear != nil && *sc.CohortYear != 0) || sc.core() {
		cohort := "Not set yet. Add it in Edit school."
		if sc.CohortYear != nil && *sc.CohortYear != 0 {
			cohort = "Cohort " + intText(sc.CohortNumber) + " · " + strconv.Itoa(*sc.CohortYear)
		}
		facts = append(facts, fact("Core Cohort", cohort, ""))
	}
	assigned := sc.OwnerNameRaw
	if assigned == "" {
		assigned = sc.OwnerID
	}
	if assigned == "" {
		assigned = "Unassigned"
	}
	ownerHref := ""
	if sc.OwnerID != "" {
		ownerHref = "/staff/" + sc.OwnerID
	}
	facts = append(facts, fact("Assigned Staff", assigned, ownerHref))

	visit, err := schooldirectory.VisitStatusOf(ctx, s.db, sc.ID, fy)
	if err != nil {
		return nil, err
	}
	visitText := visit.Label
	if visit.Next != nil {
		visitText += " " + jMY(*visit.Next)
	}
	facts = append(facts, fact("Visit status (FY"+fy+")", visitText, ""))
	if sc.Type == "core" {
		marks, err := s.corePackageFacts(ctx, sc, fy)
		if err != nil {
			return nil, err
		}
		facts = append(facts, marks...)
	}

	coverage, err := schooldirectory.CoverageOf(ctx, s.db, sc.ID, sc.Type, sc.ClusterID, fy)
	if err != nil {
		return nil, err
	}
	trainingText, trainingHref := coverage.Label, ""
	switch {
	case coverage.Planned && coverage.ClusterName != "":
		trainingText += " · " + coverage.ClusterName
		if d.OpenCluster && coverage.ClusterID != "" {
			trainingHref = "/clusters/" + coverage.ClusterID
		}
		if coverage.Day != nil {
			trainingText += " · " + jMY(*coverage.Day)
		}
	case coverage.Reason != "":
		trainingText += " " + coverage.Reason
	}
	facts = append(facts, fact("Cluster training (FY"+fy+")", trainingText, trainingHref))

	cluster, err := s.currentCluster(ctx, sc)
	if err != nil {
		return nil, err
	}
	facts = append(facts, cluster)

	items := []*screensv1.PagePanelItem{fields(facts...)}
	history, err := s.clusterHistory(ctx, sc.ID)
	if err != nil {
		return nil, err
	}
	if len(history) > 0 {
		items = append(items,
			heading(fmt.Sprintf("Cluster history (%d)", len(history))),
			&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: history}}})
	}
	lastEnrolment := notSpecified
	if sc.LastEnrollment != nil {
		lastEnrolment = dMY(*sc.LastEnrollment)
	}
	items = append(items,
		heading("Contact & operational details"),
		text("Optional fields can be completed through Edit Details."),
		fields(
			fact("School Phone", orNot(sc.Phone), ""),
			fact("Primary Contact", orNot(sc.ContactName), ""),
			fact("Director", orNot(sc.Director), ""),
			fact("Headteacher", orNot(sc.Headteacher), ""),
			fact("Last Enrolment Date", lastEnrolment, ""),
			fact("Physical Address", orNot(sc.Address), ""),
		))
	return &screensv1.PagePanel{Title: "School Demographics & Assignment", Badges: []*screensv1.PageBadge{}, Items: items}, nil
}

func intText(n *int) string {
	if n == nil {
		return "None"
	}
	return strconv.Itoa(*n)
}

// currentCluster is the Cluster field: the school's live cluster, with its
// district where that is not the school's, or "Not in a cluster".
func (s *Service) currentCluster(ctx context.Context, sc school) (*screensv1.PageFact, error) {
	if sc.ClusterID == "" {
		return fact("Cluster", "Not in a cluster", ""), nil
	}
	var name, districtID, districtName string
	err := s.db.QueryRow(ctx, `
SELECT COALESCE(c.name, ''), COALESCE(c.district_id, ''), COALESCE(d.name, '')
FROM cluster c LEFT JOIN district d ON d.id = c.district_id
WHERE c.id = $1 AND c.deleted_at IS NULL`, sc.ClusterID).Scan(&name, &districtID, &districtName)
	if err == pgx.ErrNoRows {
		return fact("Cluster", "Not in a cluster", ""), nil
	}
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the cluster: %w", err)
	}
	// The page writes " · " and the district's link; with no district name
	// the link is empty and the dot stays.
	value := name
	if districtID != sc.DistrictID {
		value += " ·"
		if districtName != "" {
			value += " " + districtName
		}
	}
	return fact("Cluster", value, "/clusters/"+sc.ClusterID), nil
}

// clusterHistory is clusters.membership_history: every membership, newest
// first, each opening its cluster.
func (s *Service) clusterHistory(ctx context.Context, schoolID string) ([]*screensv1.PageLink, error) {
	rows, err := s.db.Query(ctx, `
SELECT m.cluster_id, COALESCE(c.name, ''), m.started_at, m.ended_at, COALESCE(m.start_reason, ''), COALESCE(m.end_reason, '')
FROM school_cluster_membership m LEFT JOIN cluster c ON c.id = m.cluster_id
WHERE m.school_id = $1 ORDER BY m.started_at DESC`, schoolID)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading cluster history: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (*screensv1.PageLink, error) {
		var clusterID, name, start, end string
		var started time.Time
		var ended *time.Time
		if err := row.Scan(&clusterID, &name, &started, &ended, &start, &end); err != nil {
			return nil, err
		}
		caption := localJMY(started) + " – "
		if ended != nil {
			caption += localJMY(*ended)
		} else {
			caption += "present"
		}
		if start != "" {
			caption += " · " + start
		}
		if end != "" {
			caption += " · Ended: " + end
		}
		return &screensv1.PageLink{Text: name, Href: "/clusters/" + clusterID, Caption: caption}, nil
	})
}

// quality is the Data Quality Score card. Its "Required Cleanups" list
// never shows on the existing page (the template asks the school for
// data_quality_issues; the relation is quality_issues), so it is not shown
// here either.
func quality(sc school) *screensv1.PagePanel {
	status := "None"
	if sc.QualityStatus != nil {
		status = *sc.QualityStatus
	}
	tone := "alert"
	switch status {
	case "Clean":
		tone = "good"
	case "Needs Review":
		tone = "plain"
	case "Needs Cleanup":
		tone = "caution"
	}
	value, fraction := "None%", 0.0
	if sc.QualityScore != nil {
		value = strconv.Itoa(*sc.QualityScore) + "%"
		fraction = float64(*sc.QualityScore) / 100
	}
	return &screensv1.PagePanel{
		Title:  "Data Quality Score",
		Badges: []*screensv1.PageBadge{{Text: status, Tone: tone}},
		Items: []*screensv1.PagePanelItem{
			{Kind: &screensv1.PagePanelItem_Meter{Meter: &screensv1.PageMeter{
				Label: "of the school's fields complete and verified", Value: value, Fraction: fraction,
			}}},
			text("Score is updated automatically. Keep fields complete and verified to improve it."),
		},
	}
}

// corePackageFacts are a Core school's package on its Details
// (_core_package_marks): the visits and trainings taken of the targets, and
// V1..V4 / T1..T4. The school's live package for the year, else its newest
// (get_live_core_plan); none where it has no package.
func (s *Service) corePackageFacts(ctx context.Context, sc school, fy string) ([]*screensv1.PageFact, error) {
	core := rules.Gate.Core
	var planID, planFY string
	var visitsTarget, trainingsTarget *int32
	err := s.db.QueryRow(ctx, `
SELECT id, fy, visits_target, trainings_target FROM core_plan
WHERE school_id = $1 AND NOT (status = ANY($2))
ORDER BY (fy = $3) DESC, fy DESC LIMIT 1`, sc.SchoolID, core.PlanClosedStatuses, fy).Scan(&planID, &planFY, &visitsTarget, &trainingsTarget)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the Core plan: %w", err)
	}
	rows, err := s.db.Query(ctx, `
SELECT activity_type, COALESCE(sequence_number, 0), COALESCE(status, '') FROM core_activity_slot
WHERE core_plan_id = $1 ORDER BY COALESCE(sequence_number, 0), id`, planID)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the Core slots: %w", err)
	}
	defer rows.Close()
	marks := map[string]string{}
	taken := map[string]int{}
	for rows.Next() {
		var kind, status string
		var sequence int32
		if err := rows.Scan(&kind, &sequence, &status); err != nil {
			return nil, err
		}
		if core.SlotTaken(status) {
			taken[kind]++
		}
		letter := map[string]string{"visit": "V", "training": "T"}[kind]
		marks[kind] += letter + strconv.Itoa(int(sequence))
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	target := func(t *int32) int {
		if t == nil || *t == 0 {
			return 4
		}
		return int(*t)
	}
	value := func(kind string, t *int32) string {
		return strings.TrimSpace(strconv.Itoa(taken[kind]) + "/" + strconv.Itoa(target(t)) + " " + marks[kind])
	}
	return []*screensv1.PageFact{
		fact("Core visits (FY"+planFY+")", value("visit", visitsTarget), ""),
		fact("Core trainings (FY"+planFY+")", value("training", trainingsTarget), ""),
	}, nil
}
