"""Forms a page shows itself (Escalations' "Escalate to …"): read as the
drawer's form parts are (apps.mobile_feed.drawer_blocks) and saved through
the drawer save with the page's path and the form's key, posting the form's
own fields and hidden values to where the form posts.
"""

from __future__ import annotations

from apps.mobile_feed.page_blocks import Node

#: What a form item may be on a page; a drawer's tables and figures are not.
ITEM_KINDS = ("note", "heading", "text", "field")
#: Words a card may carry around its form (its title and line) and still be
#: read as the form: more than this and the card is a section holding a form.
INTRO_LIMIT = 400
HEADINGS = ("h1", "h2", "h3", "h4")


def is_post_form(node: Node) -> bool:
    from apps.mobile_feed import drawer_blocks

    return (
        node.tag == "form"
        and node.get("method").lower() == "post"
        and node.find(drawer_blocks._is_control) is not None
    )


def key(form: Node) -> str:
    """The form's name among the page's forms: the action it sends
    (``action=raise``), else its id, else where it posts."""
    action = form.find(
        lambda n: n.tag == "input"
        and n.get("type").lower() == "hidden"
        and n.get("name") == "action"
    )
    return (
        (action.get("value") if action is not None else "")
        or form.get("id")
        or form.get("action")
        or "form"
    )


def find(root: Node, wanted: str) -> Node | None:
    """The page's form named ``wanted``."""
    return root.find(lambda n: is_post_form(n) and key(n) == wanted)


def read(node: Node) -> dict | None:
    """``node`` as a page form: a POST form, or a card that holds one with
    only its title and line around it. None for anything else."""
    form, card = _form_of(node)
    if form is None:
        return None
    from apps.mobile_feed import drawer_blocks

    items = drawer_blocks._items(form, form, [])
    drawer_blocks._resolve(items, form)
    title = _outside(card, form, lambda n: n.tag in HEADINGS) if card else None
    line = (
        _outside(card, form, lambda n: n.tag == "p" and bool(n.text()))
        if card
        else None
    )
    submit = form.find(
        lambda n: n.tag == "button" and n.get("type").lower() in ("submit", "")
    )
    return {
        "title": title.text() if title is not None else "",
        "text": line.text() if line is not None else "",
        "items": [item for item in items if any(kind in item for kind in ITEM_KINDS)],
        "submitLabel": submit.text() if submit is not None else "Save",
        "key": key(form),
    }


def _form_of(node: Node) -> tuple[Node | None, Node | None]:
    if is_post_form(node):
        return node, None
    if not (node.has("edify-surface") or node.has("card")):
        return None, None
    forms = node.find_all(lambda n: n.tag == "form")
    if len(forms) != 1 or not is_post_form(forms[0]):
        return None, None
    form = forms[0]
    if _intro_size(node, form) > INTRO_LIMIT or node.find(
        lambda n: n.tag in ("table", "ul", "ol", "dl") and not _inside(n, form)
    ):
        return None, None
    return form, node


def _intro_size(card: Node, form: Node) -> int:
    """How many characters the card shows outside its form."""
    outside = card.text()
    return len(outside) - len(form.text())


def _outside(card: Node, form: Node, test) -> Node | None:
    return card.find(lambda n: test(n) and not _inside(n, form))


def _inside(node: Node, holder: Node) -> bool:
    while node is not None:
        if node is holder:
            return True
        node = node.parent
    return False
