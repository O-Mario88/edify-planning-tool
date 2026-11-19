package schoolevidence

import (
	"context"
	"fmt"
	"math"
	"net/url"
	"sort"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iapages"
)

// record is one discipleship record as the page reads it.
type record struct {
	id, schoolID, school, fy                        string
	observed                                        time.Time
	devotions, groups, inGroups, enrolled, staffPct *int
	lead, bible                                     *bool
	recordedBy, status, reason, country             string
	recorder                                        *string
}

// num is _num of a whole number: nothing for none, else the number and its
// suffix.
func num(n *int, suffix string) string {
	if n == nil {
		return ""
	}
	return strconv.Itoa(*n) + suffix
}

func yesNo(b *bool) string {
	switch {
	case b == nil:
		return ""
	case *b:
		return "Yes"
	}
	return "No"
}

const discipleshipColumns = `d.id, d.school_id, s.name, d.fy, d.observed_on, d.devotions_per_week, d.discipleship_groups_active,
  d.learners_in_groups, d.learners_enrolled, d.staff_in_devotions_pct, d.spiritual_lead_in_post, d.bible_lessons_timetabled,
  d.recorded_by_user_id, d.verification_status, COALESCE(d.return_reason, ''), COALESCE(d.country, ''),
  (SELECT u.name FROM "user" u WHERE u.id = d.recorded_by_user_id AND u.deleted_at IS NULL)`

func scanRecords(rows pgx.Rows) ([]record, error) {
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (record, error) {
		var x record
		err := row.Scan(&x.id, &x.schoolID, &x.school, &x.fy, &x.observed, &x.devotions, &x.groups, &x.inGroups, &x.enrolled,
			&x.staffPct, &x.lead, &x.bible, &x.recordedBy, &x.status, &x.reason, &x.country, &x.recorder)
		return x, err
	})
}

// discipleshipTab is _discipleship_tab: each school's latest confirmed
// record of the year beside its latest of the year before, then the
// register of records.
func (s *Service) discipleshipTab(ctx context.Context, r *reader, query url.Values) (tabContent, error) {
	c := tabContent{recordLabel: "Record discipleship practice", record: discipleship,
		description: "Observable discipleship practice beside the SSA's self-scored Christ-like Behaviour and Word of God domains, " +
			"and the Most Significant Change stories Impact Assessment approved for each school this year."}
	summary, err := s.discipleshipSummary(ctx, r, query)
	if err != nil {
		return tabContent{}, err
	}
	register, err := s.discipleshipRegister(ctx, r, query)
	if err != nil {
		return tabContent{}, err
	}
	c.tables = append(summary, register...)
	return c, nil
}

func (s *Service) discipleshipRegister(ctx context.Context, r *reader, query url.Values) ([]*screensv1.PageBlock, error) {
	args := append([]any{}, r.args...)
	arg := func(v any) string {
		args = append(args, v)
		return "$" + strconv.Itoa(len(args))
	}
	where := "d.deleted_at IS NULL AND " + r.schools + " AND d.fy = " + arg(r.fy)
	if r.status != "" {
		where += " AND d.verification_status = " + arg(r.status)
	}
	from := ` FROM impact_discipleship_record d JOIN school s ON s.id = d.school_id WHERE ` + where
	var total int
	if err := s.db.QueryRow(ctx, `SELECT count(*)`+from, args...).Scan(&total); err != nil {
		return nil, fmt.Errorf("schoolevidence: counting the discipleship records: %w", err)
	}
	number, pages := closedschools.PageOf(query.Get("register_page"), total, pageSize)
	limit, offset := arg(pageSize), arg((number-1)*pageSize)
	rows, err := s.db.Query(ctx, `SELECT `+discipleshipColumns+from+`
ORDER BY d.observed_on DESC, d.created_at DESC LIMIT `+limit+` OFFSET `+offset, args...)
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the discipleship records: %w", err)
	}
	records, err := scanRecords(rows)
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the discipleship records: %w", err)
	}
	cells := [][]*screensv1.PageCell{}
	for _, x := range records {
		inGroups := num(x.inGroups, "")
		if x.inGroups != nil && x.enrolled != nil && *x.enrolled != 0 {
			inGroups = strconv.Itoa(*x.inGroups) + " of " + strconv.Itoa(*x.enrolled)
		}
		v := verdict{recordedBy: x.recordedBy, status: x.status, reason: x.reason, country: x.country, recorder: x.recorder}
		tail, err := v.cells(ctx, r, discipleship, x.id)
		if err != nil {
			return nil, err
		}
		cells = append(cells, append([]*screensv1.PageCell{
			cell(x.school, ""), cell(x.observed.Format("2 Jan 2006"), ""), cell(num(x.devotions, ""), ""), cell(num(x.groups, ""), ""),
			cell(inGroups, ""), cell(yesNo(x.lead), ""),
		}, tail...))
	}
	return table("Discipleship records", []string{"School", "Observed", "Devotions a week", "Active groups", "Learners in groups",
		"Spiritual lead", "Recorded by", "Status"}, cells, len(cells) > 0, total, number, pages, "register_page",
		"No discipleship records", "Record what a visit observed: devotions, groups, a spiritual lead.", query), nil
}

// share is the learners in groups as a whole percentage of those enrolled
// (Python's round, ties to even), or nil.
func share(x *record) *int {
	if x == nil || x.inGroups == nil || x.enrolled == nil || *x.enrolled == 0 {
		return nil
	}
	v := int(math.RoundToEven(100 * float64(*x.inGroups) / float64(*x.enrolled)))
	return &v
}

// discipleshipSummary is discipleship_summary: each school's latest
// confirmed record this year beside its latest the year before, its share
// of learners in groups and the change, and the spiritual change stories
// approved for it this year, by school name.
func (s *Service) discipleshipSummary(ctx context.Context, r *reader, query url.Values) ([]*screensv1.PageBlock, error) {
	n, _ := strconv.Atoi(r.fy)
	prev := strconv.Itoa(n - 1)
	args := append([]any{}, r.args...)
	args = append(args, r.fy, prev)
	rows, err := s.db.Query(ctx, `SELECT `+discipleshipColumns+`
FROM impact_discipleship_record d JOIN school s ON s.id = d.school_id
WHERE d.deleted_at IS NULL AND `+r.schools+` AND d.verification_status = 'confirmed' AND d.fy IN ($`+strconv.Itoa(len(args)-1)+`, $`+strconv.Itoa(len(args))+`)
ORDER BY d.school_id, d.observed_on DESC, d.created_at DESC`, args...)
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the latest discipleship records: %w", err)
	}
	records, err := scanRecords(rows)
	if err != nil {
		return nil, fmt.Errorf("schoolevidence: reading the latest discipleship records: %w", err)
	}
	type key struct{ school, fy string }
	latest := map[key]*record{}
	order := []key{}
	for i := range records {
		k := key{records[i].schoolID, records[i].fy}
		if _, ok := latest[k]; !ok {
			latest[k] = &records[i]
			order = append(order, k)
		}
	}
	stories, err := iapages.SpiritualStoriesBySchool(ctx, s.db, r.scope, r.fy)
	if err != nil {
		return nil, err
	}
	type entry struct {
		x       *record
		now     *int
		change  *int
		stories int
	}
	entries := []entry{}
	for _, k := range order {
		if k.fy != r.fy {
			continue
		}
		x := latest[k]
		now, before := share(x), share(latest[key{k.school, prev}])
		e := entry{x: x, now: now, stories: stories[k.school]}
		if now != nil && before != nil {
			d := *now - *before
			e.change = &d
		}
		entries = append(entries, e)
	}
	sort.SliceStable(entries, func(i, j int) bool { return entries[i].x.school < entries[j].x.school })
	number, pages := closedschools.PageOf(query.Get("summary_page"), len(entries), pageSize)
	cells := [][]*screensv1.PageCell{}
	for _, e := range entries[(number-1)*pageSize : min(number*pageSize, len(entries))] {
		change := "No comparable record last year"
		if e.change != nil {
			sign := ""
			if *e.change >= 0 {
				sign = "+"
			}
			change = sign + strconv.Itoa(*e.change) + " pts on FY" + prev
		}
		inGroups := "Not measured"
		if e.now != nil {
			inGroups = strconv.Itoa(*e.now) + "%"
		}
		cells = append(cells, []*screensv1.PageCell{
			cell(e.x.school, ""), cell(e.x.observed.Format("2 Jan 2006"), ""), cell(num(e.x.devotions, ""), ""),
			cell(num(e.x.groups, ""), ""), cell(inGroups, ""), cell(change, ""), cell(num(e.x.staffPct, "%"), ""),
			cell(yesNo(e.x.bible), ""), cell(strconv.Itoa(e.stories), ""),
		})
	}
	return table("Each school's latest confirmed record, FY"+r.fy, []string{"School", "Latest observed", "Devotions a week",
		"Active groups", "Learners in groups", "Change", "Staff in devotions", "Bible lessons timetabled", "Approved change stories"},
		cells, false, len(entries), number, pages, "summary_page", "No confirmed discipleship record this year",
		"Records count here once a second verifier confirms them.", query), nil
}
