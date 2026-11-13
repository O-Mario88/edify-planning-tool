package pagegate

import "errors"

// ErrForbidden is a page the reader's role may open but that has nothing for
// them, which the existing view refuses with 403 (HttpResponseForbidden) and
// the feed answers as a page "not available to you" (the Staff Activity Log
// for a role that reads nobody's log).
var ErrForbidden = errors.New("pagegate: the page refuses this reader")
