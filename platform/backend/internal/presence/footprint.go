package presence

import (
	"slices"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/staffactivity"
)

// Request is the request of the existing application's that a Go answer
// stands for, as SlidingSessionMiddleware would have seen it.
type Request struct {
	// Method and Path are the request's own ("POST", "/today/snooze"). For
	// the app's requests the path is the feed's (/api/mobile/v1/…), which
	// names no page.
	Method, Path string
	// HTMX and CurrentURL are the htmx headers (HX-Request, HX-Current-URL):
	// an htmx request's page is the document the person is on.
	HTMX       bool
	CurrentURL string
	// LoginID is the sign-in the session names (LOGIN_EVENT_SESSION_KEY);
	// empty when there is none.
	LoginID string
	// Bearer is a request signed by an access token rather than a session
	// (the app's, through the gateway): it has no session to slide and its
	// person is an AuthPrincipal, which carries no beat to credit.
	Bearer bool
	// Background is a request nobody made (the page keeping up, a tab
	// nobody has touched, a redraw the gateway asks for).
	Background bool
}

// Touches is whether the middleware touches presence for the request:
// never in the background; always for a write. A read is touched by the
// session's once-a-minute slide or, over htmx, every few seconds; a bearer
// request has no session, so its reads never are. Go answers no read of a
// session's (the web pages it answers are the feed's, signed by a bearer),
// so a session read is not stamped here.
func Touches(r Request) bool {
	if r.Background {
		return false
	}
	return !isRead(r.Method)
}

func isRead(method string) bool {
	if method == "" {
		method = "GET"
	}
	return slices.Contains(rules.ReadMethods, method)
}

// Untracked is presence.is_untracked_path: not a page a person works on.
func Untracked(path string) bool {
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

// Footprint is presence.request_footprint: the page and the action, or
// false when the request is not a person working on a page.
func Footprint(r Request) (page, action string, ok bool) {
	path := r.Path
	if path == "" {
		path = "/"
	}
	if Untracked(path) {
		return "", "", false
	}
	page = path
	if r.HTMX && r.CurrentURL != "" {
		page = staffactivity.PagePath(r.CurrentURL)
	}
	method := r.Method
	if method == "" {
		method = "GET"
	}
	if !isRead(method) || r.HTMX {
		action = method + " " + path
	}
	return cut(page, rules.Lengths.Page), cut(action, rules.Lengths.Action), true
}

// Describe is presence_labels.describe: the part of the platform a beat was
// on and what the person was doing there.
func Describe(path, action string) (section, workingOn string) {
	return staffactivity.SectionFor(path), activityFor(path, action)
}

// activityFor is presence_labels.activity_for: the verb of the last action
// on the page, or a reading of the page itself.
func activityFor(path, action string) string {
	if action != "" {
		actionPath := action
		if i := strings.Index(action, " "); i >= 0 {
			actionPath = action[i+1:]
		}
		if lowered := strings.ToLower(staffactivity.PagePath(actionPath)); lowered != "" {
			for _, p := range actions {
				if p.re.MatchString(lowered) {
					return p.label
				}
			}
		}
	}
	section := staffactivity.SectionFor(path)
	var segments []string
	for _, seg := range strings.Split(staffactivity.PagePath(path), "/") {
		if seg != "" {
			segments = append(segments, seg)
		}
	}
	if len(segments) > 1 {
		for _, seg := range segments[1:] {
			if idSegment.MatchString(seg) {
				return "Viewing a " + strings.ToLower(singular(section)) + " record"
			}
		}
		tail := strings.NewReplacer("-", " ", "_", " ").Replace(segments[len(segments)-1])
		return "Viewing " + section + " · " + tail
	}
	return "Viewing " + section
}

// singular is presence_labels._singular.
func singular(section string) string {
	if strings.HasSuffix(section, "ies") {
		return strings.TrimSuffix(section, "ies") + "y"
	}
	if strings.HasSuffix(section, "s") && !strings.HasSuffix(section, "ss") {
		return strings.TrimSuffix(section, "s")
	}
	return section
}

// cut is a Python slice to n characters.
func cut(s string, n int) string {
	if r := []rune(s); len(r) > n {
		return string(r[:n])
	}
	return s
}
