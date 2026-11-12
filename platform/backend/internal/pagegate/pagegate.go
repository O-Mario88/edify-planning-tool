// Package pagegate holds what every page Go builds (internal/clusterpage and
// the ones beside it) shares with the gateway's page service.
package pagegate

import "errors"

// ErrNotAvailable is a page refused to the reader, which the existing feed
// answers as a page that is not there.
var ErrNotAvailable = errors.New("pagegate: the page is not available to this reader")
