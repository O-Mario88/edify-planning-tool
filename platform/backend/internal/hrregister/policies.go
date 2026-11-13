package hrregister

import (
	"context"
	"fmt"
	"math"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
)

// reviewSoonDays is how far ahead "Policy reviews due" looks.
const reviewSoonDays = 60

// policies is policies_view: the policies and manuals that are not archived,
// of every country and (for a reach short of the organisation) of the
// reach's countries, whose title, category or country holds the search, by
// title; each with its current version, review day, the acknowledgements of
// that version by the people in reach (everyone's for the organisation), its
// status and a link to manage it.
func policies(ctx context.Context, in input) (register, error) {
	args := []any{}
	scope := "TRUE"
	if in.reach.kind != reachAll {
		args = append(args, in.reach.countries)
		scope = fmt.Sprintf("(d.country = '' OR d.country = ANY($%d))", len(args))
	}
	searchSQL, args := contains(in.search, args, "d.title", "d.category", "d.country")
	people := "TRUE"
	if in.reach.kind != reachAll {
		reachSQL, more := in.reach.profiles(args)
		args = more
		people = fmt.Sprintf(`a.user_id IN (SELECT sp.user_id FROM staff_profile sp WHERE sp.deleted_at IS NULL AND sp.user_id IS NOT NULL AND %s)`, reachSQL)
	}
	rows, err := in.db.Query(ctx, fmt.Sprintf(`
SELECT d.slug, d.title, d.document_type, d.country, d.status, d.acknowledgement_required, v.version_number, v.review_date,
       count(a.id) FILTER (WHERE a.state = 'agreed'), count(a.id) FILTER (WHERE a.state = 'pending'),
       count(a.id) FILTER (WHERE a.state = 'disagreed')
FROM document_asset d LEFT JOIN document_version v ON v.id = d.current_version_id
LEFT JOIN document_acknowledgement a ON a.document_id = d.id AND a.version_id = d.current_version_id AND %s
WHERE d.document_type IN ('policy', 'manual') AND NOT (d.status = 'archived') AND %s AND %s
GROUP BY d.id, v.id ORDER BY d.title`, people, scope, searchSQL), args...)
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the policies: %w", err)
	}
	type document struct {
		slug, title, kind, country, status string
		required                           bool
		version                            *int
		review                             *time.Time
		agreed, pending, disagreed         int
	}
	docs, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (document, error) {
		var d document
		err := row.Scan(&d.slug, &d.title, &d.kind, &d.country, &d.status, &d.required, &d.version, &d.review,
			&d.agreed, &d.pending, &d.disagreed)
		return d, err
	})
	if err != nil {
		return register{}, fmt.Errorf("hrregister: reading the policies: %w", err)
	}
	reg := register{
		path: "/policies", title: "Policies & Documents", eyebrow: "Policy and compliance",
		description: "The policies and manuals that apply to the countries you oversee: their current version, when each is due " +
			"for review, and who has acknowledged it.",
		columns:    []string{"Document", "Type", "Country", "Version", "Review by", "Acknowledged", "Status"},
		actions:    []action{{label: "Publish a policy", href: "/uploads/new"}},
		emptyTitle: "No policies yet",
		emptyBody:  "Publish a policy or manual to track its review and acknowledgement here.",
	}
	soon := in.today.AddDate(0, 0, reviewSoonDays)
	agreedTotal, askedTotal, disagreedTotal, reviewsDue, published, inReview := 0, 0, 0, 0, 0, 0
	for _, d := range docs {
		asked := d.agreed + d.pending + d.disagreed
		agreedTotal += d.agreed
		askedTotal += asked
		disagreedTotal += d.disagreed
		review := ""
		if d.review != nil {
			review = d.review.Format(time.DateOnly)
			if !d.review.After(soon) {
				reviewsDue++
			}
		}
		switch d.status {
		case "published", "effective":
			published++
		case "draft", "under_review", "returned":
			inReview++
		}
		country := d.country
		if country == "" {
			country = "All countries"
		}
		version := "No version yet"
		if d.version != nil {
			version = "v" + strconv.Itoa(*d.version)
		}
		acknowledged := "Not required"
		if d.required {
			acknowledged = fmt.Sprintf("%d of %d", d.agreed, asked)
		}
		reg.rows = append(reg.rows, []string{dash(d.title), dash(labelOf(rules.DocumentTypes, d.kind)), country, version, dash(review),
			acknowledged, dash(labelOf(rules.DocumentStatuses, d.status))})
		reg.rowActions = append(reg.rowActions, []action{{label: "Manage", href: "/documents/" + d.slug + "/manage"}})
	}
	rate := "—"
	if askedTotal > 0 {
		rate = strconv.Itoa(int(math.RoundToEven(float64(agreedTotal)*100/float64(askedTotal)))) + "%"
	}
	disagreeTone := "success"
	if disagreedTotal > 0 {
		disagreeTone = "danger"
	}
	reg.metrics = []metric{
		{"Published policies", count(published), "in force", "success"},
		{"Policies in review", count(inReview), "draft, in review or returned", "warning"},
		{"Acknowledgement rate", rate, "of required acknowledgements agreed", "info"},
		{"Policy reviews due", count(reviewsDue), "review date within 60 days", "warning"},
		{"Disagreements", count(disagreedTotal), "staff who did not agree", disagreeTone},
	}
	return reg, nil
}
