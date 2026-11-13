package staffactivity

import (
	"regexp"
	"strings"
)

// pagePath is presence_labels.page_path: the path part of a URL or path,
// with no query string.
func pagePath(value string) string {
	if value == "" {
		return ""
	}
	path := value
	if m := scheme.FindStringIndex(path); m != nil {
		path = path[m[1]:]
	}
	if strings.HasPrefix(path, "//") {
		rest := path[2:]
		cut := strings.IndexAny(rest, "/?#")
		if cut < 0 {
			return "/"
		}
		path = rest[cut:]
	}
	if i := strings.IndexAny(path, "?#"); i >= 0 {
		path = path[:i]
	}
	if path == "" {
		return "/"
	}
	return path
}

// scheme is urlsplit's: a letter, then letters, digits, "+", "-" or ".",
// then ":".
var scheme = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9+.-]*:`)

// untracked is presence.is_untracked_path: not a page a person works on.
func untracked(path string) bool {
	for _, prefix := range rules.UntrackedPrefixes {
		if strings.HasPrefix(path, prefix) {
			return true
		}
	}
	last := path
	if i := strings.LastIndex(path, "/"); i >= 0 {
		last = path[i+1:]
	}
	return strings.Contains(last, ".")
}

// sectionFor is presence_labels.section_for: the sidebar's label for the
// path first (longest url first), then the prefix table, then the path's
// first segment in words.
func sectionFor(raw string) string {
	path := strings.TrimRight(pagePath(raw), "/")
	if path == "" {
		path = "/"
	}
	for _, pair := range rules.SectionRegistry {
		if path == pair[0] || strings.HasPrefix(path, pair[0]+"/") {
			return pair[1]
		}
	}
	for _, pair := range rules.SectionPrefixes {
		if pair[0] == "/" {
			continue
		}
		if path == pair[0] || strings.HasPrefix(path, pair[0]+"/") {
			return pair[1]
		}
	}
	if path == "/" {
		return "Dashboard"
	}
	head := strings.Split(path, "/")[1]
	head = pyTitle(strings.ReplaceAll(strings.ReplaceAll(head, "-", " "), "_", " "))
	if head == "" {
		return "Dashboard"
	}
	return head
}
