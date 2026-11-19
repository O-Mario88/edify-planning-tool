package helpcenter

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/feeddom"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

var el = feeddom.El

// sp is the whitespace the templates leave between two elements; the feed
// reads an element's words joined, so it matters where they touch.
const sp = " "

// searchLimit is the search view's [:40]; listLimit the home's [:6].
const (
	searchLimit = 40
	listLimit   = 6
	// excerptLimit and excerptLead are services.excerpt's limit and the
	// characters it keeps before the match.
	excerptLimit = 180
	excerptLead  = 52
)

// toc is partials/help/toc.html.
func toc(groups []group) *feeddom.Node {
	nav := el("nav", "help-toc", sp, el("p", "help-toc__eyebrow", "Table of contents"), sp).Attr("aria-label", "Knowledge Center contents")
	for _, g := range groups {
		list := el("ul", "help-toc__list", sp).Attr("role", "list")
		for _, e := range g.entries {
			class := "help-toc__link"
			if e.active {
				class += " help-toc__link--active"
			}
			list.Add(el("li", "", sp, el("a", class, e.title).Attr("href", e.url), sp), sp)
		}
		details := el("details", "help-toc__group", sp,
			el("summary", "help-toc__summary", sp, el("span", "help-toc__category", g.name), sp,
				el("span", "help-toc__count", strconv.Itoa(len(g.entries)), el("span", "sr-only", " "+g.countLabel)), sp),
			sp, list, sp)
		if g.expanded {
			details.Attr("open", "")
		}
		nav.Add(details, sp)
	}
	return nav
}

// shell is layouts/help_center.html below its header: the contents rail
// and the page's own content, read as the feed reads the page.
func (r *reader) shell(title, activeSlug string, content ...any) (*screensv1.GetPageResponse, error) {
	groups, err := r.tree(activeSlug)
	if err != nil {
		return nil, err
	}
	return framed(title, groups, content), nil
}

// framed is the page around its contents and content.
func framed(title string, groups []group, content []any) *screensv1.GetPageResponse {
	body := el("div", "help-shell__body", sp, el("aside", "help-shell__rail", sp, toc(groups), sp), sp,
		el("div", "help-shell__main", append(append([]any{sp}, content...), sp)...), sp)
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{Eyebrow: "Documentation", Title: title},
		Blocks: feeddom.Walk(el("div", "", body), nil),
	}
}

func link(text, href string) *feeddom.Node { return el("a", "", text).Attr("href", href) }

// crumbs is a one-line breadcrumb: the Knowledge Center, then this page.
func crumbs(here string) *feeddom.Node {
	return el("nav", "text-sm mb-4", link("Knowledge Center", "/help"), el("span", "", " / ").Attr("aria-hidden", "true"), el("span", "", here)).
		Attr("aria-label", "Breadcrumb")
}

// home is help_center.views.home under pages/help/index.html.
func (r *reader) home() (*screensv1.GetPageResponse, bool, error) {
	if ok, err := r.installed(); err != nil || !ok {
		return nil, false, err
	}
	due, err := r.exists(`SELECT 1 FROM help_center_helparticle WHERE state = $1 AND review_due_at < $2`, rules.Published, r.s.now())
	if err != nil || due {
		return nil, false, err // mark_review_due_articles would mark them
	}
	if mapped, err := r.exists(`SELECT 1 FROM help_center_helparticleroutecontext`); err != nil || !mapped {
		return nil, false, err // sync_route_contexts would map the routes
	}
	r.args = nil
	guides, err := r.articles(r.visible()+" AND a.slug = "+r.arg(rules.Roles[r.role].Guide), "a.title LIMIT 1")
	if err != nil {
		return nil, false, err
	}
	r.args = nil
	workflows, err := r.articles(r.visible()+" AND a.workflow > ''", byTitle+" LIMIT "+strconv.Itoa(listLimit))
	if err != nil {
		return nil, false, err
	}
	r.args = nil
	problems, err := r.articles(r.visible()+" AND a.feature = 'troubleshooting'", byTitle+" LIMIT "+strconv.Itoa(listLimit))
	if err != nil {
		return nil, false, err
	}
	staff := false
	if err := r.s.db.QueryRow(r.ctx, `SELECT COALESCE((SELECT is_staff FROM "user" WHERE id = $1), false)`, r.p.UserID).Scan(&staff); err != nil {
		return nil, false, fmt.Errorf("helpcenter: reading the reader: %w", err)
	}
	groups, err := r.tree("")
	if err != nil {
		return nil, false, err
	}
	content := []any{
		el("div", "help-article__prose", sp, el("p", "", "This is the authoritative manual for the Edify Planning & Monitoring "+
			"platform. Use the contents on the left to browse by area, or start with your own role guide below. Everything here is "+
			"filtered to what your active role may do — opening an article never grants a permission."), sp), sp,
	}
	if len(guides) > 0 {
		g := guides[0]
		content = append(content, el("section", "mt-6 rounded-surface border p-4 edify-border", sp, el("p", "", "Start here"), sp,
			el("h2", "", sp, link(g.title, "/help/articles/"+g.slug), sp), sp, el("p", "", g.summary), sp), sp)
	}
	areas := el("ul", "mt-4 grid", sp).Attr("role", "list")
	for _, g := range groups {
		card := el("a", "block rounded-surface border p-4 edify-border", sp,
			el("div", "flex", sp, el("h3", "", g.name), sp, el("span", "help-toc__count", strconv.Itoa(len(g.entries)), el("span", "sr-only", " articles")), sp), sp).
			Attr("href", g.url)
		if g.description != "" {
			card.Add(el("p", "", g.description), sp)
		}
		areas.Add(el("li", "", sp, card, sp), sp)
	}
	content = append(content, el("section", "mt-7", sp, el("h2", "", "Documentation areas"), sp,
		el("p", "", "Every area you are authorised to read, with the number of guides in each."), sp, areas, sp), sp)
	if len(workflows) > 0 {
		content = append(content, el("section", "mt-7", sp, el("h2", "", "End-to-end workflows"), sp,
			el("p", "", "How work travels from one role to the next, and what Edify does automatically at each handoff."), sp,
			links(workflows), sp), sp)
	}
	if len(problems) > 0 {
		content = append(content, el("section", "mt-7", sp, el("h2", "", "Common problems"), sp, links(problems), sp,
			link("All troubleshooting guides", "/help/troubleshooting"), sp), sp)
	}
	if staff || r.role == "Admin" {
		content = append(content, el("section", "mt-7", sp, el("a", "btn h-8", "Download the manual").Attr("href", "/help/export/complete"), sp).
			Attr("aria-label", "Reference"))
	}
	return framed("Help & Knowledge Center", groups, content), true, nil
}

// links is a list of articles, each a link to it.
func links(list []article) *feeddom.Node {
	ul := el("ul", "mt-3 grid", sp).Attr("role", "list")
	for _, a := range list {
		ul.Add(el("li", "", link(a.title, "/help/articles/"+a.slug)), sp)
	}
	return ul
}

// article is help_center.views.article under pages/help/article.html: 404
// for no such article, 403 for one the role may not read.
func (r *reader) article(slug string) (*screensv1.GetPageResponse, bool, error) {
	if ok, err := r.installed(); err != nil || !ok {
		return nil, false, err
	}
	r.args = nil
	found, err := r.articles("a.slug = "+r.arg(slug), "a.title LIMIT 1")
	if err != nil {
		return nil, false, err
	}
	if len(found) == 0 {
		return nil, true, pagegate.ErrNotAvailable
	}
	r.args = nil
	readable, err := r.exists(`SELECT 1`+articleFrom+` WHERE `+r.visible()+` AND a.slug = `+r.arg(slug), r.args...)
	if err != nil {
		return nil, false, err
	}
	if !readable {
		return nil, true, pagegate.ErrForbidden
	}
	a := found[0]
	extra, err := r.articleParts(a.id)
	if err != nil {
		return nil, false, err
	}
	resp, err := r.shell(a.title, a.slug, crumbsTo(a), sp, articleNode(a, extra, r.path), sp)
	if err != nil {
		return nil, false, err
	}
	return resp, true, nil
}

// parts is what an article page shows beside the article itself.
type parts struct {
	roles   []string
	related []article
	tour    *walkthrough
}

type walkthrough struct {
	title string
	steps []string
}

// articleParts reads the article's role accesses (in the table's order,
// as role_accesses.all() does), its related articles by title and its first
// walkthrough.
func (r *reader) articleParts(id string) (parts, error) {
	var out parts
	rows, err := r.s.db.Query(r.ctx, `SELECT role FROM help_center_helparticleroleaccess WHERE article_id = $1`, id)
	if err != nil {
		return out, fmt.Errorf("helpcenter: reading who an article applies to: %w", err)
	}
	if out.roles, err = pgx.CollectRows(rows, pgx.RowTo[string]); err != nil {
		return out, fmt.Errorf("helpcenter: reading who an article applies to: %w", err)
	}
	r.args = []any{id}
	if out.related, err = r.articles(`a.id IN (SELECT to_helparticle_id FROM help_center_helparticle_related_articles WHERE from_helparticle_id = $1)`, byTitle); err != nil {
		return out, err
	}
	var title string
	var steps []byte
	err = r.s.db.QueryRow(r.ctx, `SELECT title, steps FROM help_center_helpwalkthrough WHERE article_id = $1 ORDER BY id LIMIT 1`, id).Scan(&title, &steps)
	switch {
	case err == pgx.ErrNoRows:
	case err != nil:
		return out, fmt.Errorf("helpcenter: reading an article's walkthrough: %w", err)
	default:
		w := &walkthrough{title: title}
		if err := json.Unmarshal(steps, &w.steps); err != nil {
			return out, fmt.Errorf("helpcenter: reading an article's walkthrough: %w", err)
		}
		out.tour = w
	}
	return out, nil
}

func crumbsTo(a article) *feeddom.Node {
	return el("nav", "text-[13px] mb-4", sp, link("Knowledge Center", "/help"), sp, el("span", "", " / ").Attr("aria-hidden", "true"), sp,
		link(a.categoryName, "/help/categories/"+a.categorySlug), sp, el("span", "", " / ").Attr("aria-hidden", "true"), sp,
		el("span", "", a.title), sp).Attr("aria-label", "Breadcrumb")
}

// articleNode is the <article> of pages/help/article.html.
func articleNode(a article, x parts, path string) *feeddom.Node {
	reviewed := day(a.lastReviewed)
	if reviewed == "" {
		reviewed = "Pending first review"
	}
	meta := el("div", "help-article__meta mt-2", sp, el("span", "", "Version "+strconv.Itoa(a.version)), sp,
		el("span", "", "Last reviewed "+reviewed), sp, el("span", "", strconv.Itoa(a.minutes)+" min read"), sp)
	if a.reviewDue != nil {
		meta.Add(el("span", "", "Next review "+day(a.reviewDue)))
	}
	reviewer := "Edify documentation review"
	switch {
	case a.reviewerName != "":
		reviewer = a.reviewerName
	case a.reviewer != nil:
		reviewer = *a.reviewer
	}
	meta.Add(sp, el("span", "", "Reviewed by "+reviewer), sp)
	lead := el("div", "min-w-0", sp, el("h2", "", a.title), sp, meta, sp)
	if len(x.roles) > 0 {
		lead.Add(el("p", "mt-2", sp, el("span", "font-bold", "Applies to:"), sp, strings.Join(x.roles, ", "), sp), sp)
	}
	node := el("article", "", sp, el("div", "flex", sp, lead, sp,
		el("a", "shrink-0", "Print view").Attr("href", "/help/articles/"+a.slug+"/print"), sp), sp)
	if len(a.content) > 3 {
		ol := el("ol", "mt-2 grid", sp)
		for i, s := range a.content {
			ol.Add(el("li", "", link(s.Heading, "#section-"+strconv.Itoa(i+1))), sp)
		}
		node.Add(el("nav", "mt-5", sp, el("p", "", "On this page"), sp, ol, sp).Attr("aria-label", "On this page"), sp)
	}
	prose := el("div", "help-article__prose mt-6", sp)
	for i, s := range a.content {
		part := el("section", "", sp, el("h3", "", s.Heading), sp).Attr("id", "section-"+strconv.Itoa(i+1))
		if s.Body != "" {
			part.Add(el("p", "", s.Body))
		}
		part.Add(sp)
		if len(s.Items) > 0 {
			ul := el("ul", "mt-3", sp)
			for _, item := range s.Items {
				ul.Add(el("li", "", item))
			}
			part.Add(ul, sp)
		}
		prose.Add(part, sp)
	}
	node.Add(prose, sp, sp)
	if x.tour != nil {
		ol := el("ol", "mt-2", sp)
		for _, step := range x.tour.steps {
			ol.Add(el("li", "", step))
		}
		node.Add(el("section", "mt-7 rounded-surface border p-4", sp, el("h3", "", "Guided walkthrough · "+x.tour.title), sp, ol, sp), sp)
	}
	node.Add(sp)
	if len(x.related) > 0 {
		ul := el("ul", "mt-2 grid", sp).Attr("role", "list")
		for _, rel := range x.related {
			ul.Add(el("li", "", link(rel.title, "/help/articles/"+rel.slug)), sp)
		}
		node.Add(el("section", "mt-7", sp, el("h3", "", "Related documentation"), sp, ul, sp), sp)
	}
	form := el("form", "flex", sp,
		el("input", "").Attr("type", "hidden", "name", "csrfmiddlewaretoken"), sp,
		el("input", "").Attr("type", "hidden", "name", "page_context", "value", path), sp,
		el("span", "", "Was this helpful?"), sp,
		el("button", "", "Yes").Attr("type", "submit", "name", "feedback_type", "value", "helpful"), sp,
		el("button", "", "Report outdated").Attr("type", "submit", "name", "feedback_type", "value", "outdated"), sp,
		el("button", "", "Report missing step").Attr("type", "submit", "name", "feedback_type", "value", "missing"), sp).
		Attr("action", "/help/articles/"+a.slug+"/feedback", "method", "post")
	node.Add(sp, el("footer", "mt-8", sp, el("p", "", "Opening an article never grants a permission — guidance is filtered to your active role."), sp, form, sp), sp)
	return node
}

// listing is pages/help/category.html: the area's articles as cards.
func (r *reader) listing(c category, list []article) (*screensv1.GetPageResponse, error) {
	ul := el("ul", "mt-5 grid").Attr("role", "list")
	for _, a := range list {
		ul.Add(el("li", "", el("a", "block edify-surface rounded-surface border p-5", el("p", "", strconv.Itoa(a.minutes)+" min read"),
			el("h3", "", a.title), el("p", "", a.summary)).Attr("href", "/help/articles/"+a.slug)))
	}
	if len(list) == 0 {
		ul.Add(el("li", "text-sm", "No articles are authorised for your active role in this section."))
	}
	return r.shell(c.name, "", el("section", "", crumbs(c.name), el("h2", "", c.name), el("p", "", c.description), ul))
}

// category is help_center.views.category: 404 for no such area.
func (r *reader) category(slug string) (*screensv1.GetPageResponse, bool, error) {
	c, found, err := r.categoryBySlug(slug)
	if err != nil {
		return nil, false, err
	}
	if !found {
		return nil, true, pagegate.ErrNotAvailable
	}
	r.args = nil
	list, err := r.articles(r.visible()+" AND c.slug = "+r.arg(slug), byTitle)
	if err != nil {
		return nil, false, err
	}
	resp, err := r.listing(c, list)
	return resp, err == nil, err
}

// troubleshooting is help_center.views.troubleshooting: the troubleshooting
// area with every troubleshooting article (handed on without the area,
// which the view cannot open).
func (r *reader) troubleshooting() (*screensv1.GetPageResponse, bool, error) {
	c, found, err := r.categoryBySlug("troubleshooting")
	if err != nil || !found {
		return nil, false, err
	}
	r.args = nil
	list, err := r.articles(r.visible()+" AND a.feature = 'troubleshooting'", byTitle)
	if err != nil {
		return nil, false, err
	}
	resp, err := r.listing(c, list)
	return resp, err == nil, err
}

func (r *reader) categoryBySlug(slug string) (category, bool, error) {
	var c category
	err := r.s.db.QueryRow(r.ctx, `SELECT slug, name, description, sort_order FROM help_center_helpcategory WHERE slug = $1`, slug).
		Scan(&c.slug, &c.name, &c.description, &c.order)
	switch {
	case err == pgx.ErrNoRows:
		return c, false, nil
	case err != nil:
		return c, false, fmt.Errorf("helpcenter: reading a category: %w", err)
	}
	return c, true, nil
}

// contains is Django's icontains on a column: UPPER(col) LIKE UPPER('%v%'),
// with the pattern's own wildcards escaped.
func (r *reader) contains(column, value string) string {
	escaped := strings.NewReplacer(`\`, `\\`, `%`, `\%`, `_`, `\_`).Replace(value)
	return "UPPER(" + column + "::text) LIKE UPPER(" + r.arg("%"+escaped+"%") + ")"
}

// glossary is help_center.views.glossary under pages/help/glossary.html:
// every term, or those whose term or definition holds the search.
func (r *reader) glossary(q string) (*screensv1.GetPageResponse, bool, error) {
	r.args = nil
	where := "true"
	if q != "" {
		where = "(" + r.contains("g.term", q) + " OR " + r.contains("g.definition", q) + ")"
	}
	rows, err := r.s.db.Query(r.ctx, `SELECT g.slug, g.term, g.definition, g.used_in, a.slug FROM help_center_helpglossaryterm g
LEFT JOIN help_center_helparticle a ON a.id = g.article_id WHERE `+where+` ORDER BY g.term`, r.args...)
	if err != nil {
		return nil, false, fmt.Errorf("helpcenter: reading the glossary: %w", err)
	}
	dl := el("dl", "mt-5 grid")
	n := 0
	for rows.Next() {
		var slug, term, definition, usedIn string
		var guide *string
		if err := rows.Scan(&slug, &term, &definition, &usedIn, &guide); err != nil {
			rows.Close()
			return nil, false, fmt.Errorf("helpcenter: reading the glossary: %w", err)
		}
		card := el("div", "edify-surface rounded-surface border p-4", el("dt", "", term), el("dd", "", definition)).Attr("id", slug)
		if usedIn != "" {
			card.Add(el("dd", "", "Used in: "+usedIn))
		}
		if guide != nil {
			card.Add(el("dd", "", link("Open related guide →", "/help/articles/"+*guide)))
		}
		dl.Add(card)
		n++
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, false, fmt.Errorf("helpcenter: reading the glossary: %w", err)
	}
	if n == 0 {
		dl.Add(el("p", "", "No glossary entries match your search."))
	}
	section := el("section", "", crumbs("Glossary")).Attr("aria-label", "Edify glossary")
	if q != "" {
		section.Add(el("p", "", "Showing terms matching ", el("span", "", q)))
	}
	section.Add(dl)
	resp, err := r.shell("Edify glossary", "", section)
	return resp, err == nil, err
}

// releaseNotes is help_center.views.release_notes, newest first.
func (r *reader) releaseNotes() (*screensv1.GetPageResponse, bool, error) {
	rows, err := r.s.db.Query(r.ctx, `SELECT id, title, version_label, summary, published_at FROM help_center_helpreleasenote ORDER BY published_at DESC`)
	if err != nil {
		return nil, false, fmt.Errorf("helpcenter: reading the release notes: %w", err)
	}
	list := el("div", "mt-5 space-y-3")
	n := 0
	for rows.Next() {
		var id, title, version, summary string
		var published time.Time
		if err := rows.Scan(&id, &title, &version, &summary, &published); err != nil {
			rows.Close()
			return nil, false, fmt.Errorf("helpcenter: reading the release notes: %w", err)
		}
		list.Add(el("article", "edify-surface rounded-surface border p-5", el("p", "", version+" · "+day(&published)),
			el("h3", "", title), el("p", "", summary)).Attr("id", "release-note-"+id))
		n++
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, false, fmt.Errorf("helpcenter: reading the release notes: %w", err)
	}
	if n == 0 {
		list.Add(el("p", "", "No release notes have been published."))
	}
	resp, err := r.shell("Release notes", "", el("section", "", crumbs("Release Notes"), list).Attr("aria-label", "Release notes"))
	return resp, err == nil, err
}

// terms is services.expand_query: the search in lower case with its words
// single-spaced, and its synonym when it has one.
func terms(q string) []string {
	clean := strings.Join(strings.Fields(strings.ToLower(q)), " ")
	out := []string{clean}
	if syn, ok := rules.Synonyms[clean]; ok && syn != clean {
		out = append(out, syn)
	}
	return out
}

// search is help_center.views.search under pages/help/search.html: the
// readable articles whose title, summary, instructions or a keyword hold
// the search or its synonym, by title, at most forty.
func (r *reader) search(q string) (*screensv1.GetPageResponse, bool, error) {
	if ok, err := r.installed(); err != nil || !ok {
		return nil, false, err
	}
	var results []article
	if q != "" {
		r.args = nil
		where := r.visible() + " AND ("
		for i, t := range terms(q) {
			if i > 0 {
				where += " OR "
			}
			where += r.contains("a.title", t) + " OR " + r.contains("a.summary", t) + " OR " + r.contains("a.search_document", t) +
				" OR EXISTS (SELECT 1 FROM help_center_helpsearchkeyword k WHERE k.article_id = a.id AND " + r.contains("k.term", t) + ")"
		}
		var err error
		if results, err = r.articles(where+")", byTitle+" LIMIT "+strconv.Itoa(searchLimit)); err != nil {
			return nil, false, err
		}
	}
	section := el("section", "", sp, crumbs("Search"), sp).Attr("aria-label", "Search the Knowledge Center")
	if q != "" {
		plural := "s"
		if len(results) == 1 {
			plural = ""
		}
		section.Add(el("p", "mt-5", strconv.Itoa(len(results))+" authorised result"+plural+" for “"+q+"”."))
	}
	ol := el("ol", "mt-3").Attr("role", "list")
	for _, a := range results {
		if a.searchDocument == "" {
			return nil, false, nil // excerpt would rebuild the document from its content
		}
		ol.Add(el("li", "edify-surface rounded-surface border p-5", el("p", "", a.categoryName+" · "+reason(a, q)),
			el("h3", "", link(a.title, "/help/articles/"+a.slug)), el("p", "", excerpt(a.searchDocument, q)),
			el("p", "", "Reviewed "+day(a.lastReviewed)+" · "+strconv.Itoa(a.minutes)+" min read")))
	}
	if len(results) == 0 && q != "" {
		ol.Add(el("li", "rounded-surface border p-6", el("h3", "", "No authorised results"),
			el("p", "", "Try a status, button label, identifier or feature name. Restricted operational guidance is not shown outside its authorised roles.")))
	}
	section.Add(sp, ol, sp)
	resp, err := r.shell("Search the Knowledge Center", "", section)
	return resp, err == nil, err
}

// reason is services.result_match_reason.
func reason(a article, q string) string {
	all := terms(q)
	t := strings.ToLower(all[len(all)-1])
	switch {
	case strings.Contains(strings.ToLower(a.title), t):
		return "Matched article title"
	case strings.Contains(strings.ToLower(strings.Join(a.keywords, " ")), t):
		return "Matched keyword or synonym"
	case strings.Contains(strings.ToLower(a.summary), t):
		return "Matched article summary"
	}
	return "Matched verified instructions"
}

// excerpt is services.excerpt: up to 180 characters of the instructions
// from 52 before the first match, ellipses where it was cut.
func excerpt(text, q string) string {
	lower := strings.ToLower(text)
	start := -1
	for _, t := range terms(q) {
		if i := strings.Index(lower, t); i >= 0 {
			if at := utf8.RuneCountInString(lower[:i]); start < 0 || at < start {
				start = at
			}
		}
	}
	if start < 0 {
		start = 0
	}
	runes := []rune(text)
	begin := max(0, start-excerptLead)
	end := min(len(runes), begin+excerptLimit)
	out := strings.TrimSpace(strings.ReplaceAll(string(runes[begin:end]), "\n", " "))
	if begin > 0 {
		out = "…" + out
	}
	if end < len(runes) {
		out += "…"
	}
	return out
}
