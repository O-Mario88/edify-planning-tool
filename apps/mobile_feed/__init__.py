"""Screen feeds for the native app (migration branch only).

Each endpoint returns, as JSON, the same view-model the matching web page is
rendered from, built by the same service, behind the same permission check.
The shape is the Protocol Buffer JSON form of the messages in
platform/proto/edify/screens/v1. The Go gateway is the only caller.

No rule lives here: when a page's rules are ported to Go, its feed is deleted.
"""
