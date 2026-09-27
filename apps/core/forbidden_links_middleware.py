"""Links a role cannot follow are not drawn (owner, 2026-09-27).

"Hide all feature that a role is blocked from accessing ... Forbidden pages
should not be shown completely. only the right roles should see." Most
templates gate their links with `|can_open`, but not all of them: a partner's
school names, a country director's links into Impact Assessment's queues and
HR's shortcuts to Planning each led to a page that answered with a redirect
to the dashboard.

After rendering, every in-app link and every `hx-get` button in an HTML
response is checked against the page gate of the view it resolves to — the
rule `|can_open` and the views themselves apply
(apps.core.permissions.can_open_url):

- a link drawn as a control (a button, tab, navigation or menu item) and a
  button whose request the role may not make are removed;
- a link inside content (a school name, a staff name, a figure) keeps its
  words and loses its link.

Unknown and ungated routes count as openable, exactly as for `|can_open`, so
this never hides a link it cannot judge. Anonymous requests, streams, errors
and non-HTML responses pass through untouched, and nothing inside a <script>
is read.
"""

from __future__ import annotations

import re

# End tags end at the first ">", whatever sits before it ("</script foo>" is
# still the end of the script), as an HTML parser reads them.
_SCRIPT = re.compile(r"(<script\b.*?</script\b[^>]*>)", re.S | re.I)
_ANCHOR = re.compile(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a\b[^>]*>", re.S | re.I)
_HX_BUTTON = re.compile(
    r"<button\b(?P<attrs>[^>]*\bhx-get\s*=\s*\"(?P<url>/[^\"]*)\"[^>]*)>.*?</button\b[^>]*>",
    re.S | re.I,
)
_HREF = re.compile(r"\bhref\s*=\s*\"(?P<url>/[^\"]*)\"", re.I)
_CLASS = re.compile(r"\bclass\s*=\s*\"(?P<value>[^\"]*)\"", re.I)
_TITLE = re.compile(r"\btitle\s*=\s*\"(?P<value>[^\"]*)\"", re.I)
_ARROW = re.compile(r"(?:→|&rarr;|&#8594;|›|&rsaquo;)\s*(?:</span>\s*)?$", re.S)
_CONTROL_ROLE = re.compile(
    r"\brole\s*=\s*\"(?:button|tab|menuitem)\"|\bdata-edify-tab\b", re.I
)
# A class naming a control: one of its hyphen/underscore-separated words is
# one of these ("edify-tab", "row-menu__item", "btn-primary", "app-sidebar__nav")
# — whole words, so "edify-table-link" is not a tab.
_CONTROL_WORDS = frozenset(
    {"btn", "button", "tab", "tabs", "nav", "item", "action", "actions", "menuitem"}
)


def _is_control(attrs: str, class_value: str) -> bool:
    if _CONTROL_ROLE.search(attrs):
        return True
    for token in class_value.split():
        if token == "edify-primary-solid" or token.startswith("row-menu"):
            return True
        if _CONTROL_WORDS.intersection(re.split(r"[-_]+", token.lower())):
            return True
    return False


class ForbiddenLinksMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if (
            user is None
            or not user.is_authenticated
            or response.streaming
            or response.status_code != 200
            or "text/html" not in response.get("Content-Type", "")
        ):
            return response

        from apps.core.permissions import can_open_url

        verdicts: dict[str, bool] = {}

        def allowed(url: str) -> bool:
            url = url.replace("&amp;", "&")
            if url not in verdicts:
                try:
                    verdicts[url] = can_open_url(user, url)
                except Exception:  # an unjudgeable link stays, as for |can_open
                    verdicts[url] = True
            return verdicts[url]

        def link(match: re.Match) -> str:
            attrs = match["attrs"]
            href = _HREF.search(attrs)
            if not href or allowed(href["url"]):
                return match[0]
            classes = _CLASS.search(attrs)
            class_value = classes["value"] if classes else ""
            # A call to action ("Location data quality →") is a control too.
            if _is_control(attrs, class_value) or _ARROW.search(match["body"]):
                return ""
            title = _TITLE.search(attrs)
            kept = f' class="{class_value}"' if class_value else ""
            if title:
                kept += f' title="{title["value"]}"'
            return f"<span{kept} data-edify-link-off>{match['body']}</span>"

        def button(match: re.Match) -> str:
            return match[0] if allowed(match["url"]) else ""

        html = response.content.decode(response.charset)
        parts = _SCRIPT.split(html)
        for index in range(0, len(parts), 2):  # odd entries are <script> blocks
            if 'href="/' not in parts[index] and 'hx-get="/' not in parts[index]:
                continue
            parts[index] = _HX_BUTTON.sub(button, _ANCHOR.sub(link, parts[index]))
        changed = "".join(parts)
        if changed != html:
            response.content = changed.encode(response.charset)
            if response.has_header("Content-Length"):
                response["Content-Length"] = str(len(response.content))
        return response
