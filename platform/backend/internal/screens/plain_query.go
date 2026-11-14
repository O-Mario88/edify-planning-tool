package screens

import "net/url"

// PlainQuery is a page query as the gateway's pages see it: every key with a
// value, a blank value (q=) dropped. The gateway reads every page query
// through it (pageQuery), and the parity tool asks the existing application
// through it, so both sides are asked the same question.
func PlainQuery(given map[string]string) url.Values {
	query := url.Values{}
	for key, value := range given {
		if value != "" {
			query.Set(key, value)
		}
	}
	return query
}
