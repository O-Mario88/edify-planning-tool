package helpcenter

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// reader is one reading of a Knowledge Center page.
type reader struct {
	s    *Service
	ctx  context.Context
	p    auth.Principal
	role string
	path string
	args []any
}

func (r *reader) arg(v any) string {
	r.args = append(r.args, v)
	return "$" + strconv.Itoa(len(r.args))
}

// visible is services.visible_articles on article `a`: a readable state,
// and for a reader with a role, an article open to that role or to every
// role (no role access at all).
func (r *reader) visible() string {
	where := "a.state = ANY(" + r.arg(rules.ReadableStates) + ")"
	if r.role != "" {
		where += ` AND (EXISTS (SELECT 1 FROM help_center_helparticleroleaccess x WHERE x.article_id = a.id AND x.role = ` + r.arg(r.role) + `)
  OR NOT EXISTS (SELECT 1 FROM help_center_helparticleroleaccess x WHERE x.article_id = a.id))`
	}
	return where
}

// section is one part of an article's content.
type section struct {
	Heading string   `json:"heading"`
	Body    string   `json:"body"`
	Items   []string `json:"items"`
}

// article is a HelpArticle as the pages draw it.
type article struct {
	id, slug, title, summary, categorySlug, categoryName string
	searchDocument, reviewerName                         string
	minutes, version                                     int
	lastReviewed, reviewDue                              *time.Time
	reviewer                                             *string
	keywords                                             []string
	content                                              []section
}

const articleColumns = `a.id, a.slug, a.title, a.summary, c.slug, c.name, a.search_document, a.reviewer_name,
  a.estimated_reading_minutes, a.version, a.last_reviewed_at, a.review_due_at,
  (SELECT u.name FROM "user" u WHERE u.id = a.reviewer_id), a.keywords, a.content`

const articleFrom = ` FROM help_center_helparticle a JOIN help_center_helpcategory c ON c.id = a.category_id`

// byTitle is the order of a list of articles: by title, then, as the
// view's DISTINCT sorts what ties, by the article's own columns in turn.
const byTitle = "a.title, a.created_at, a.updated_at, a.id"

// articles reads the articles `where` selects, in `order`.
func (r *reader) articles(where, order string) ([]article, error) {
	rows, err := r.s.db.Query(r.ctx, `SELECT `+articleColumns+articleFrom+` WHERE `+where+` ORDER BY `+order, r.args...)
	if err != nil {
		return nil, fmt.Errorf("helpcenter: reading the articles: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (article, error) {
		var a article
		var keywords, content []byte
		if err := row.Scan(&a.id, &a.slug, &a.title, &a.summary, &a.categorySlug, &a.categoryName, &a.searchDocument,
			&a.reviewerName, &a.minutes, &a.version, &a.lastReviewed, &a.reviewDue, &a.reviewer, &keywords, &content); err != nil {
			return a, err
		}
		if err := json.Unmarshal(keywords, &a.keywords); err != nil {
			return a, fmt.Errorf("the keywords of %s: %w", a.slug, err)
		}
		if err := json.Unmarshal(content, &a.content); err != nil {
			return a, fmt.Errorf("the content of %s: %w", a.slug, err)
		}
		return a, nil
	})
	if err != nil {
		return nil, fmt.Errorf("helpcenter: reading the articles: %w", err)
	}
	return list, nil
}

// exists answers one EXISTS question.
func (r *reader) exists(query string, args ...any) (bool, error) {
	var yes bool
	if err := r.s.db.QueryRow(r.ctx, `SELECT EXISTS (`+query+`)`, args...).Scan(&yes); err != nil {
		return false, fmt.Errorf("helpcenter: %w", err)
	}
	return yes, nil
}

// installed is whether any article exists: without one the views install
// the canonical content first (ensure_canonical_content), a write.
func (r *reader) installed() (bool, error) {
	return r.exists(`SELECT 1 FROM help_center_helparticle`)
}

// category is a HelpCategory.
type category struct {
	slug, name, description string
	order                   int
}

// entry is one link of the contents.
type entry struct {
	title, url string
	active     bool
}

// group is one area of the contents (knowledge_tree).
type group struct {
	name, description, url, countLabel string
	entries                            []entry
	expanded                           bool
}

func (r *reader) categories() ([]category, error) {
	rows, err := r.s.db.Query(r.ctx, `SELECT slug, name, description, sort_order FROM help_center_helpcategory ORDER BY sort_order, name`)
	if err != nil {
		return nil, fmt.Errorf("helpcenter: reading the categories: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (category, error) {
		var c category
		err := row.Scan(&c.slug, &c.name, &c.description, &c.order)
		return c, err
	})
	if err != nil {
		return nil, fmt.Errorf("helpcenter: reading the categories: %w", err)
	}
	return list, nil
}

// tree is services.knowledge_tree: every area the role may read, with the
// articles it may open, then the release notes.
func (r *reader) tree(activeSlug string) ([]group, error) {
	r.args = nil
	rows, err := r.s.db.Query(r.ctx, `SELECT a.slug, a.title, c.slug`+articleFrom+` WHERE `+r.visible()+` ORDER BY c.sort_order, a.title, a.slug`, r.args...)
	if err != nil {
		return nil, fmt.Errorf("helpcenter: reading the contents: %w", err)
	}
	grouped := map[string][]entry{}
	for rows.Next() {
		var slug, title, cat string
		if err := rows.Scan(&slug, &title, &cat); err != nil {
			rows.Close()
			return nil, fmt.Errorf("helpcenter: reading the contents: %w", err)
		}
		grouped[cat] = append(grouped[cat], entry{title: title, url: "/help/articles/" + slug, active: slug == activeSlug})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("helpcenter: reading the contents: %w", err)
	}
	cats, err := r.categories()
	if err != nil {
		return nil, err
	}
	sortKey := func(c category) (int, int) {
		first, second := c.order, 1
		if c.slug == "glossary" || c.slug == "troubleshooting" {
			first = 12
		}
		if c.slug == "glossary" {
			second = 0
		}
		return first, second
	}
	sort.SliceStable(cats, func(i, j int) bool {
		a1, a2 := sortKey(cats[i])
		b1, b2 := sortKey(cats[j])
		return a1 < b1 || (a1 == b1 && a2 < b2)
	})
	here := trimSlash(r.path)
	out := []group{}
	for _, c := range cats {
		entries := grouped[c.slug]
		if len(entries) == 0 {
			continue
		}
		if c.slug == "glossary" {
			entries = append([]entry{{title: "Browse all glossary terms", url: "/help/glossary", active: here == "/help/glossary"}}, entries...)
		}
		g := group{name: c.name, description: c.description, url: "/help/categories/" + c.slug, countLabel: "items", entries: entries}
		switch c.slug {
		case "glossary":
			g.url = "/help/glossary"
		case "troubleshooting":
			g.url = "/help/troubleshooting"
		}
		for _, e := range entries {
			g.expanded = g.expanded || e.active
		}
		g.expanded = g.expanded || here == g.url
		out = append(out, g)
	}
	notes, err := r.s.db.Query(r.ctx, `SELECT id, title, version_label FROM help_center_helpreleasenote ORDER BY published_at DESC`)
	if err != nil {
		return nil, fmt.Errorf("helpcenter: reading the release notes: %w", err)
	}
	releases := []entry{}
	for notes.Next() {
		var id, title, version string
		if err := notes.Scan(&id, &title, &version); err != nil {
			notes.Close()
			return nil, fmt.Errorf("helpcenter: reading the release notes: %w", err)
		}
		releases = append(releases, entry{title: version + " — " + title, url: "/help/release-notes#release-note-" + id})
	}
	notes.Close()
	if err := notes.Err(); err != nil {
		return nil, fmt.Errorf("helpcenter: reading the release notes: %w", err)
	}
	if len(releases) > 0 {
		out = append(out, group{name: "Release notes", description: "What changed in Edify, newest first.", url: "/help/release-notes",
			countLabel: "release notes", entries: releases, expanded: here == "/help/release-notes"})
	}
	return out, nil
}

// trimSlash is str.rstrip("/").
func trimSlash(s string) string {
	for len(s) > 0 && s[len(s)-1] == '/' {
		s = s[:len(s)-1]
	}
	return s
}
