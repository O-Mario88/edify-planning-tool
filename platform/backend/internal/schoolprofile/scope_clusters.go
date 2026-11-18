package schoolprofile

import (
	"context"
	"strconv"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/tablepager"
)

// The Clusters tab of a profile of many schools: the scope's clusters with
// what Cluster Management knows of each (profile_intelligence.
// cluster_management), and their rankings.

// ClusterCard is what Cluster Management knows of one cluster
// (clusteroversight.Cards, which cannot be imported here: it reads cluster
// pages that read this package).
type ClusterCard struct {
	Sessions                                             int
	Rate                                                 *int
	Invited, Attended                                    int
	Teachers, Leaders, Absent                            int
	Health, Impact                                       *int
	HealthBand, ImpactBand                               string
	Maturity                                             int
	MaturityLabel                                        string
	EnrolmentCompared, EnrolmentBefore, EnrolmentAfter   int
	LearningCompared, LearningImproved, LearningDeclined int
	StoriesApproved                                      int
}

// ClusterCards reads the clusters' cards for a year on a day
// ("2026-11-18"), and the sessions in a row that count a school absent.
type ClusterCards interface {
	Cards(ctx context.Context, clusterIDs []string, fy, today string) (map[string]ClusterCard, error)
	AlertAfter() int
}

// WithClusterCards gives the profiles their Clusters tab.
func (sp *ScopePages) WithClusterCards(c ClusterCards) *ScopePages {
	sp.s.clusterCards = c
	return sp
}

// clusterLine is one cluster's row: its schools here and their figures,
// then the whole cluster's card.
type clusterLine struct {
	ranked
	schools, assessed, meetings, meetingsDone, teachers, leaders, enrolment int
	card                                                                    ClusterCard
}

func (s *Service) clusterLines(ctx context.Context, pr *scopeProfile, fy, today string) ([]clusterLine, error) {
	rows := pr.clusterRows(pr.book)
	ids := make([]string, len(rows))
	for i, r := range rows {
		ids[i] = r.id
	}
	cards, err := s.clusterCards.Cards(ctx, ids, fy, today)
	if err != nil {
		return nil, err
	}
	out := make([]clusterLine, len(rows))
	for i, r := range rows {
		line := clusterLine{ranked: r, card: cards[r.id]}
		for _, x := range pr.schools {
			if x.cluster != r.id {
				continue
			}
			line.schools++
			if pr.scores[x.id].current != nil {
				line.assessed++
			}
			line.enrolment += x.enrolment
			if w := pr.schoolWork[x.id]; w != nil {
				line.teachers += w.teachers
				line.leaders += w.leaders
			}
		}
		if w := pr.clusterWork[r.id]; w != nil {
			line.meetings, line.meetingsDone = w.meetings, w.meetingsDone
		}
		out[i] = line
	}
	return out, nil
}

// clustersBlocks is the Clusters tab.
func (pr *scopeProfile) clustersBlocks(l lens, lines []clusterLine, d doors, alert int) []*screensv1.PageBlock {
	records := l.records()
	yearLabel, previousLabel := fyLabel(l.fy), fyLabel(previousFY(l.fy))
	var sessions, invited, attended, teachers, leaders, absent int
	var enrolmentCompared, enrolmentBefore, enrolmentAfter, learningCompared, learningImproved, learningDeclined, stories int
	for _, c := range lines {
		k := c.card
		sessions, invited, attended, teachers, leaders, absent =
			sessions+k.Sessions, invited+k.Invited, attended+k.Attended, teachers+k.Teachers, leaders+k.Leaders, absent+k.Absent
		enrolmentCompared, enrolmentBefore, enrolmentAfter = enrolmentCompared+k.EnrolmentCompared, enrolmentBefore+k.EnrolmentBefore, enrolmentAfter+k.EnrolmentAfter
		learningCompared, learningImproved, learningDeclined = learningCompared+k.LearningCompared, learningImproved+k.LearningImproved, learningDeclined+k.LearningDeclined
		stories += k.StoriesApproved
	}
	rate := 0
	if invited > 0 {
		rate = pyRoundHalfEven(float64(100*attended) / float64(invited))
	}
	coverage := 0
	if len(pr.schools) > 0 {
		coverage = pyRoundHalfEven(float64(pr.clustered) * 100 / float64(len(pr.schools)))
	}
	blocks := []*screensv1.PageBlock{strip("Cluster Sessions",
		kpi{label: "Clusters", value: intcomma(len(pr.clusters)), link: "#profile-clusters-table",
			helper: intcomma(pr.clustered) + " of " + intcomma(len(pr.schools)) + " schools · " + intcomma(coverage) + "%"},
		kpi{label: "Sessions Held", value: intcomma(sessions), link: records + "cluster_sessions", helper: "cluster meetings and trainings, " + yearLabel},
		kpi{label: "Attendance", value: strconv.Itoa(rate) + "%", link: records + "cluster_attendance",
			helper: intcomma(attended) + " of " + intcomma(invited) + " invitations attended"},
		kpi{label: "Absent " + strconv.Itoa(alert) + "+ Sessions", value: intcomma(absent), link: records + "cluster_absent", helper: "schools missing sessions in a row"},
		kpi{label: "Teachers Reached", value: intcomma(teachers), link: records + "cluster_attendance", helper: "recorded at cluster sessions"},
		kpi{label: "School Leaders Reached", value: intcomma(leaders), link: records + "cluster_attendance", helper: "recorded at cluster sessions"},
	)}
	if len(lines) > 0 {
		growth := "0%"
		if enrolmentBefore != 0 {
			g := pyRound(float64(enrolmentAfter-enrolmentBefore)*100/float64(enrolmentBefore), 1)
			growth = pyFloat(g) + "%"
			if g > 0 {
				growth = "+" + growth
			}
		}
		blocks = append(blocks, strip("Cluster Impact",
			kpi{label: "Enrolment Growth", value: growth, link: records + "enrolment_growth",
				helper: intcomma(enrolmentCompared) + " cluster schools with a figure in both years"},
			kpi{label: "Learning Results Improved", value: intcomma(learningImproved), link: records + "learning",
				helper: "of " + intcomma(learningCompared) + " schools compared · " + intcomma(learningDeclined) + " declined"},
			kpi{label: "Change Stories", value: intcomma(stories), link: records + "stories_approved", helper: "approved stories from cluster schools"},
		))
	}
	subtitle := intcomma(len(pr.clusters)) + " cluster" + plural(len(pr.clusters)) + " · " + yearLabel
	if d.ClusterOversight {
		subtitle += " · Cluster Oversight"
	}
	t := &screensv1.PageTable{Title: "Clusters", Subtitle: subtitle}
	if len(lines) == 0 {
		t.EmptyMessage = "No school of this portfolio is in a cluster."
		return append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	}
	for _, label := range []string{"Cluster", "Schools", "Assessed", previousLabel, yearLabel, "Change", "Status", "Visits", "Meetings",
		"Group Trainings", "Teachers Trained", "Leaders Trained", "Enrolment", "Sessions Held", "Attendance",
		"Absent " + strconv.Itoa(alert) + "+", "Health", "Impact", "Maturity"} {
		t.Columns = append(t.Columns, &screensv1.PageColumn{Label: label, Numeric: label != "Cluster" && label != "Status" && label != "Maturity"})
	}
	page := tablepager.Paginate(len(lines), tablePageSize, l.query, "clusters_page")
	for _, c := range lines[page.Start:page.End] {
		k := c.card
		profile := "/clusters/" + c.id + "/profile?tab="
		attendance := &screensv1.PageCell{Text: "—"}
		if k.Rate != nil {
			attendance = &screensv1.PageCell{Text: strconv.Itoa(*k.Rate) + "%", Href: profile + "attendance&fy=" + l.fy}
		}
		absentCell := &screensv1.PageCell{Text: "0"}
		if k.Absent > 0 {
			absentCell = &screensv1.PageCell{Text: intcomma(k.Absent), Href: profile + "attendance&fy=" + l.fy + "&show=missing", Tone: "danger"}
		}
		scored := func(v *int) *screensv1.PageCell {
			if v == nil {
				return &screensv1.PageCell{Text: "—"}
			}
			return &screensv1.PageCell{Text: strconv.Itoa(*v), Href: profile + "scores&fy=" + l.fy}
		}
		maturity := "—"
		if k.Maturity != 0 {
			maturity = strconv.Itoa(k.Maturity) + " · " + k.MaturityLabel
		}
		changeCell := &screensv1.PageCell{Text: "—"}
		if c.verdict.delta != nil {
			changeCell = &screensv1.PageCell{Text: signedTwoPlaces(*c.verdict.delta), Tone: c.verdict.tone()}
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: c.name, Href: "/clusters/" + c.id}, {Text: intcomma(c.schools)}, {Text: intcomma(c.assessed)},
			{Text: score(c.previous)}, {Text: score(c.current), Strong: true}, changeCell, {Text: c.verdict.label()},
			{Text: intcomma(c.visitsDone) + " / " + intcomma(c.visits)}, {Text: intcomma(c.meetingsDone) + " / " + intcomma(c.meetings)},
			{Text: intcomma(c.trainingsDone) + " / " + intcomma(c.trainings)}, {Text: intcomma(c.teachers)}, {Text: intcomma(c.leaders)},
			{Text: intcomma(c.enrolment)}, {Text: intcomma(k.Sessions), Href: profile + "attendance&fy=" + l.fy}, attendance, absentCell,
			scored(k.Health), scored(k.Impact), {Text: maturity},
		}})
	}
	t.Footnote = "Schools, Assessed and the SSA columns count the cluster's schools in this portfolio. Attendance, Absent, " +
		"Health, Impact and Maturity are the whole cluster's, as on its own profile. A score is left blank when too few of its parts can be measured."
	if page.Pager != nil {
		t.Pager, t.Footnote = page.Pager, page.Pager.Summary
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if len(lines) <= 1 {
		return blocks
	}
	plain := make([]ranked, len(lines))
	for i, c := range lines {
		plain[i] = c.ranked
	}
	best, worst := rank(plain)
	improving, declining := movers(plain)
	clusterRanking := func(list []ranked, title, empty string) *screensv1.PageBlock {
		rt := &screensv1.PageTable{Title: title, Subtitle: yearLabel}
		if len(list) == 0 {
			rt.EmptyMessage = empty
			return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: rt}}
		}
		rt.Columns = []*screensv1.PageColumn{{Label: "#", Numeric: true}, {Label: "Cluster"},
			{Label: previousLabel, Numeric: true}, {Label: yearLabel, Numeric: true}, {Label: "Change", Numeric: true}}
		for _, r := range list {
			changeCell := &screensv1.PageCell{Text: "—"}
			if r.verdict.delta != nil {
				changeCell = &screensv1.PageCell{Text: signedTwoPlaces(*r.verdict.delta), Tone: r.verdict.tone()}
			}
			rt.Rows = append(rt.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
				{Text: strconv.Itoa(r.rank)}, {Text: r.name, Href: "/clusters/" + r.id},
				{Text: score(r.previous)}, {Text: score(r.current), Strong: true}, changeCell,
			}})
		}
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: rt}}
	}
	return append(blocks,
		clusterRanking(best, "Best Performing Clusters", "No cluster has a confirmed SSA in this year."),
		clusterRanking(worst, "Clusters Needing The Most Support", "No further cluster has a confirmed SSA in this year."),
		clusterRanking(improving, "Improving Clusters", "No cluster's SSA improved since the previous year."),
		clusterRanking(declining, "Declining Clusters", "No cluster's SSA declined since the previous year."),
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Badges: []*screensv1.PageBadge{},
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Text{Text: rules.Engine.Scope.RankingMethod + " " + rules.Engine.Scope.MoversMethod}}}}}},
	)
}
