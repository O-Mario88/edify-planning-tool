"""Reads the two planning drawers on a school's profile for the native app:
Schedule visit (``/planning/schedule-modal``) and Assign to Partner
(``/planning/assign-partner-modal``).

Their fields come and go with the drawer's own script: a Training list for an
In-school Training, the training followed up for a Follow Up, hidden values
the chosen training fills in, purposes greyed for a date's financial year. The
app runs the same rules (platform/mobile/src/ui/planning/planningLogic.ts).
This reads what those rules work from — the values the script starts with,
which Django writes into the form's ``x-data`` as JSON — and the parts the
drawer draws around them, from the drawer the web renders for the same person.
Nothing is computed here that the web does not show.
"""

from __future__ import annotations

import json
import re

from apps.mobile_feed import drawer_blocks
from apps.mobile_feed.page_blocks import Node, parse

#: A key of the script's object, at the start of a line or after { or ,.
SCRIPT_KEY = re.compile(r"(?:^|[{,\n])\s*(\w+)\s*:\s*")
#: A single-quoted script string, its escapes kept.
QUOTED = re.compile(r"'((?:[^'\\]|\\.)*)'")
REQUIRED_MARK = re.compile(r"\s*\*\s*$")
OPTIONAL_MARK = re.compile(r"\s*\(optional\)\s*$")

#: What each drawer's save may send besides its own hidden values: the
#: fields its form names, as the person (or the script) filled them.
SAVED_FIELDS = {
    "assign": (
        "partner_id",
        "purpose_of_visit",
        "catalogue_item_id",
        "activity_type",
        "focus_intervention",
        "source_activity_id",
    ),
    "schedule": (
        "purpose_of_visit",
        "catalogue_item_id",
        "activity_type",
        "recommendation_reason",
        "focus_intervention",
        "ssa_deviation_reason",
        "source_activity_id",
        "facilitating_partner_id",
        "scheduled_date",
        "expected_participants",
        "executor_type",
        "delivery_type",
        "activity_purpose_text",
        "visit_justification",
    ),
}


# ── The script's starting values ──────────────────────────────────────────
def script_values(source: str) -> dict:
    """The literal values of the script's object, by key: JSON lists and
    objects, true/false/null, numbers and quoted strings. Getters and
    functions are left out. A key met twice keeps its first (outermost)
    value."""
    decoder = json.JSONDecoder()
    values: dict = {}
    for match in SCRIPT_KEY.finditer(source):
        key, at = match.group(1), match.end()
        if key in values:
            continue
        if source.startswith("'", at):
            quoted = QUOTED.match(source, at)
            if quoted:
                values[key] = _unquote(quoted.group(1))
            continue
        if source[at : at + 1] in "[{-0123456789" or source.startswith(
            ("true", "false", "null"), at
        ):
            try:
                values[key] = decoder.raw_decode(source, at)[0]
            except ValueError:
                continue
    return values


def _unquote(inner: str) -> str:
    """A single-quoted script string's text. Django's ``escapejs`` writes
    quotes and line ends as \\uXXXX, which JSON reads the same way."""
    try:
        return json.loads('"' + inner.replace('"', '\\"').replace("\\'", "'") + '"')
    except ValueError:
        return inner


def _quoted_strings(expression: str) -> list[str]:
    return [_unquote(text) for text in QUOTED.findall(expression)]


# ── Finding the drawer's parts ────────────────────────────────────────────
def _by_id(form: Node, ident: str) -> Node | None:
    return form.find(lambda n: n.get("id") == ident)


def _with_attr(form: Node, name: str) -> Node | None:
    return form.find(lambda n: name in n.attrs)


def _shown_when(form: Node, expression: str) -> Node | None:
    return form.find(lambda n: n.get("x-show") == expression)


def _text(node: Node | None) -> str:
    return node.text() if node is not None else ""


def _own_text(node: Node | None) -> str:
    """The node's own words, its child elements left out."""
    if node is None:
        return ""
    return " ".join("".join(c for c in node.children if isinstance(c, str)).split())


def _options(select: Node | None) -> list[dict]:
    if select is None:
        return []
    return [
        {
            "value": option.get("value"),
            "label": option.text(),
            "group": "",
            "disabled": "disabled" in option.attrs,
        }
        for option in select.find_all(lambda n: n.tag == "option")
        if option.get("value")
    ]


def _placeholder_choice(select: Node | None) -> str:
    """The select's empty first line ("Select a purpose…")."""
    if select is None:
        return ""
    first = select.find(lambda n: n.tag == "option" and not n.get("value"))
    return _text(first)


def _labels(form: Node) -> dict[str, str]:
    """Every label's words by the id it names, its * and (optional) marks
    left off; and the spans that label a read-only box, by their own id."""
    labels = {}
    for label in form.find_all(lambda n: n.tag == "label" and n.get("for")):
        words = OPTIONAL_MARK.sub("", REQUIRED_MARK.sub("", _own_text(label)))
        labels[label.get("for")] = words or _text(label)
    for span in form.find_all(lambda n: n.tag == "span" and n.get("id")):
        labels[span.get("id")] = _text(span)
    return labels


def _note(node: Node, tone: str = "") -> dict:
    """A note with its title apart from its body, as the web draws it."""
    title = node.find(lambda n: n.has("edify-note__title"))
    bodies = node.find_all(lambda n: n.has("edify-note__body"))
    if title is None and not bodies:
        paragraphs = [c for c in node.children if isinstance(c, Node) and c.tag == "p"]
        if len(paragraphs) > 1:
            title, bodies = paragraphs[0], paragraphs[1:]
    return {
        "title": _text(title),
        "text": " ".join(_text(body) for body in bodies)
        if bodies or title
        else node.text(),
        "tone": tone or node.get("data-tone") or "info",
    }


def _hidden_values(form: Node) -> dict[str, str]:
    """The hidden inputs the web renders with a value; the ones the script
    fills (``:value``) are the app's to send."""
    return {
        node.get("name"): node.get("value")
        for node in form.find_all(
            lambda n: n.tag == "input"
            and n.get("type").lower() == "hidden"
            and ":value" not in n.attrs
        )
        if node.get("name") and node.get("name") != "csrfmiddlewaretoken"
    }


def _follow_up_captions(form: Node) -> dict[str, str]:
    return {
        "followUpDone": _text(_shown_when(form, "followUpActivities.length > 0")),
        "followUpNoneRequired": _text(
            _shown_when(
                form, "followUpActivities.length === 0 && followUpRequiresTraining"
            )
        ),
        "followUpNoneOptional": _text(_with_attr(form, "data-no-prior-training")),
    }


def _drawer_frame(root: Node) -> dict:
    """Title and footer buttons, read as every drawer's are."""
    title = root.find(lambda n: n.get("id") == "drawer-title")
    submit = root.find(
        lambda n: n.tag == "button" and n.get("type").lower() == "submit"
    )
    cancel = root.find(
        lambda n: n.tag == "button"
        and n.get("type").lower() != "submit"
        and "requestClose" in n.get("@click")
        and n.parent is not None
        and n.parent.has("drawer-footer")
    )
    return {
        "title": _text(title),
        "submitLabel": _text(submit),
        "cancelLabel": _text(cancel) or "Cancel",
    }


def _script(form: Node) -> dict:
    values = script_values(form.get("x-data"))
    return {
        "trainings": [
            _training(item) for item in values.get("trainingActivities") or []
        ],
        "followUps": [
            {
                "id": item.get("id", ""),
                "label": item.get("label", ""),
                "interventionLabel": item.get("interventionLabel", ""),
            }
            for item in values.get("followUpActivities") or []
        ],
        "followUpRequiresTraining": bool(values.get("followUpRequiresTraining")),
        "values": values,
    }


def _training(item: dict) -> dict:
    return {
        "id": item.get("id", ""),
        "label": item.get("label", ""),
        "stableCode": item.get("stableCode", ""),
        "category": item.get("category", ""),
        "ssaIndicator": item.get("ssaIndicator", ""),
        "ssaIntervention": item.get("ssaIntervention", ""),
        "ssaInterventionLabel": item.get("ssaInterventionLabel", ""),
        "plannerChooses": bool(item.get("plannerChooses")),
        "universal": bool(item.get("universal")),
        "staffDeliveryAllowed": bool(item.get("staffDeliveryAllowed")),
        "certifiedAgencyDeliveryAllowed": bool(
            item.get("certifiedAgencyDeliveryAllowed")
        ),
        "priorityTitles": list(item.get("priorityTitles") or []),
    }


def _form_of(html: str) -> tuple[Node, Node] | None:
    root = drawer_blocks._drawer(parse(html))
    form = root.find(lambda n: n.tag == "form")
    return (root, form) if form is not None else None


# ── Assign to Partner ─────────────────────────────────────────────────────
def read_assign(html: str) -> dict | None:
    found = _form_of(html)
    if found is None:
        return None
    root, form = found
    script = _script(form)
    values = script.pop("values")
    handover = _with_attr(form, "data-project-handover")
    withdrawal = next(
        (
            note
            for note in form.find_all(lambda n: n.has("edify-note"))
            if note.get("data-tone") == "warning"
        ),
        None,
    )
    assigned = _with_attr(form, "data-assigned-date")
    monitored = next(
        (
            p
            for p in form.find_all(lambda n: n.tag == "p")
            if _text(p).startswith("Monitored by")
        ),
        None,
    )
    planner_select = _by_id(form, "partner_training_focus_intervention")
    return {
        "kind": "assign",
        **_drawer_frame(root),
        **script,
        "partners": _options(_by_id(form, "partner_id")),
        "purposes": _options(_by_id(form, "purpose_of_visit")),
        "initialPurpose": values.get("purposeOfVisit", ""),
        "purposeNotes": [
            _text(p)
            for p in form.find_all(
                lambda n: "data-visit-locked-reason" in n.attrs
                or "data-on-top-training" in n.attrs
            )
        ],
        "partnerCourses": {
            partner: {"codes": list(codes)}
            for partner, codes in (values.get("partnerCourses") or {}).items()
        },
        "interventions": _options(planner_select),
        "projectHandovers": [
            {"label": _text(button), "path": button.get("hx-get")}
            for button in (
                handover.find_all(lambda n: n.tag == "button") if handover else []
            )
        ],
        "captions": {
            **_follow_up_captions(form),
            "partnerCourses": _text(_with_attr(form, "data-partner-courses")),
            "trainingHelp": _text(_by_id(form, "partner-training-help")),
            "linkedIntervention": _text(
                (
                    _with_attr(form, "data-training-ssa-intervention")
                    or Node("p", {}, None)
                ).find(lambda n: n.tag == "p")
            ),
            "plannerChooses": _text(
                planner_select.parent.find(lambda n: n.tag == "p")
                if planner_select is not None and planner_select.parent is not None
                else None
            ),
            "handoverTitle": _text(handover.find(lambda n: n.tag == "p"))
            if handover
            else "",
            "handover": _text(handover.find_all(lambda n: n.tag == "p")[-1])
            if handover
            else "",
            "assignedDateLabel": _text(assigned.find(lambda n: n.tag == "span"))
            if assigned
            else "",
            "assignedDate": _text(assigned.find(lambda n: n.tag == "div"))
            if assigned
            else "",
            "assignedDateHelp": _text(assigned.find(lambda n: n.tag == "p"))
            if assigned
            else "",
            "monitoredBy": _text(monitored),
        },
        "placeholders": _placeholders(form),
        "labels": _labels(form),
        "notes": [_note(withdrawal)] if withdrawal is not None else [],
        "hidden": _hidden_values(form),
    }


def _placeholders(form: Node) -> dict[str, str]:
    """Each select's empty first line, by the select's id."""
    return {
        select.get("id"): _placeholder_choice(select)
        for select in form.find_all(lambda n: n.tag == "select" and n.get("id"))
    }


# ── Schedule visit ────────────────────────────────────────────────────────
def _lead(form: Node, purpose_holder: Node | None) -> tuple[list[dict], dict | None]:
    """The notes and the SSA evidence drawn above Purpose of visit, in order,
    and the "already has plans" warning with its plans."""
    items: list[dict] = []
    existing = None
    for child in form.children:
        if not isinstance(child, Node):
            continue
        if purpose_holder is not None and (
            child is purpose_holder or purpose_holder in child.nodes()
        ):
            break
        if (
            child.tag in ("input", "template", "script")
            or child.get("id") == "form-errors"
        ):
            continue
        if "data-existing-plan-warning" in child.attrs:
            existing = {
                "note": _note(child),
                "plans": [
                    {
                        "label": _text(row.find(lambda n: n.tag == "span")),
                        "status": _text(
                            row.find(lambda n: n.has("school-planning-badge"))
                        ),
                        "tone": (
                            row.find(lambda n: n.has("school-planning-badge"))
                            or Node("span", {}, None)
                        ).get("data-planning-tone"),
                    }
                    for row in child.find_all(lambda n: n.tag == "li")
                ],
                "buttons": {
                    button.get("data-existing-plan-action"): _text(button)
                    for button in child.find_all(lambda n: n.tag == "button")
                },
            }
            existing["note"]["text"] = _text(
                child.find(lambda n: n.has("edify-note__body"))
            )
            continue
        if child.tag == "section":
            heading = child.find(lambda n: n.tag in ("h2", "h3", "h4"))
            items.append({"heading": _text(heading)})
            for row in child.find_all(lambda n: n.tag == "li"):
                score = next(
                    (
                        s
                        for s in row.find_all(lambda n: n.tag == "span")
                        if s.has("edify-text-caption")
                    ),
                    None,
                )
                label = _own_text(row) or _text(row)
                items.append(
                    {"line": {"label": label, "value": _text(score), "tone": "danger"}}
                )
            for p in child.find_all(lambda n: n.tag == "p"):
                items.append({"text": _text(p)})
            continue
        if child.has("edify-note") or child.get("role") == "status":
            tone = child.get("data-tone") or (
                "warning" if "data-partner-support-notice" in child.attrs else "info"
            )
            items.append({"note": _note(child, tone)})
    return items, existing


def read_schedule(html: str) -> dict | None:
    found = _form_of(html)
    if found is None:
        return None
    root, form = found
    script = _script(form)
    values = script.pop("values")
    purpose = _by_id(form, "purpose_of_visit")
    purpose_holder = purpose.parent if purpose is not None else None
    lead, existing = _lead(form, purpose_holder)
    lock_note = _with_attr(form, "data-visit-locked-reason")
    deviation = _with_attr(form, "data-ssa-deviation")
    deviation_text = (
        deviation.find(lambda n: n.tag == "p" and n.get("x-text"))
        if deviation
        else None
    )
    facilitated = _with_attr(form, "data-facilitated-by")
    responsible = next(
        (
            span.parent
            for span in form.find_all(lambda n: n.tag == "span")
            if _text(span) == "Responsible person" and span.parent is not None
        ),
        None,
    )
    justification = _by_id(form, "visit_justification")
    goal = _by_id(form, "activity_purpose_text")
    monitored = next(
        (
            p
            for p in form.find_all(lambda n: n.tag == "p")
            if _text(p).startswith("Monitored by")
        ),
        None,
    )
    profiles = values.get("profiles") or {}
    return {
        "kind": "schedule",
        **_drawer_frame(root),
        **script,
        "lead": lead,
        "existingPlans": existing,
        "purposes": _options(purpose),
        "initialPurpose": values.get("purposeOfVisit", ""),
        "purposeNotes": [
            _text(p)
            for p in form.find_all(
                lambda n: "data-outreach-only" in n.attrs
                or "data-purpose-locked-reason" in n.attrs
            )
        ],
        "visitLocks": {
            purpose_value: {"byYear": dict(years)}
            for purpose_value, years in (values.get("visitLocks") or {}).items()
        },
        "purposesLockedEveryYear": list(values.get("purposesLockedEveryYear") or []),
        "trainingLocks": dict(values.get("trainingLocks") or {}),
        "trainingLockedEveryYear": bool(values.get("trainingLockedEveryYear")),
        "profiles": {
            key: {
                "requiresParticipants": profile.get("requiresParticipants") is True,
                "schedulable": profile.get("schedulable") is not False,
                "unavailableReason": profile.get("unavailableReason", ""),
            }
            for key, profile in profiles.items()
        },
        "initialTraining": values.get("trainingActivityId", ""),
        "defaultCatalogueItem": values.get("defaultCatalogueItemId", ""),
        "interventions": _options(_by_id(form, "focus_intervention")),
        "initialIntervention": values.get("focusIntervention", ""),
        "ssaPriorities": list(values.get("ssaPriorities") or []),
        "activityType": values.get("activityType", ""),
        "recommendationReason": values.get("recommendationReason", ""),
        "facilitators": [
            {**option, "label": option["label"]}
            for option in (
                [
                    {
                        "value": "",
                        "label": _placeholder_choice(
                            facilitated.find(lambda n: n.tag == "select")
                        ),
                        "group": "",
                        "disabled": False,
                    }
                ]
                + _options(facilitated.find(lambda n: n.tag == "select"))
                if facilitated
                else []
            )
        ],
        "captions": {
            **_follow_up_captions(form),
            "lockTail": _own_text(lock_note),
            "lockStatic": _text(lock_note.find(lambda n: n.tag == "span"))
            if lock_note
            else "",
            "trainingHelp": _text(_by_id(form, "training-catalogue-help")),
            "linkedIntervention": _text(
                (
                    _with_attr(form, "data-training-ssa-intervention")
                    or Node("p", {}, None)
                ).find(lambda n: n.tag == "p")
            ),
            "deviationNamed": (
                _quoted_strings(deviation_text.get("x-text")) + ["", ""]
            )[0]
            if deviation_text
            else "",
            "deviationUnnamed": (
                _quoted_strings(deviation_text.get("x-text")) + ["", ""]
            )[1]
            if deviation_text
            else "",
            "ssaStale": _text(_with_attr(form, "data-ssa-stale")),
            "facilitated": _text(facilitated.find(lambda n: n.tag == "p"))
            if facilitated
            else "",
            "dateYearUsed": _text(_with_attr(form, "data-visit-year-used")),
            "responsible": _text(responsible.find(lambda n: n.tag == "div"))
            if responsible
            else "",
            "responsibleHelp": _text(responsible.find(lambda n: n.tag == "p"))
            if responsible
            else "",
            "goalPlaceholder": goal.get("placeholder") if goal else "",
            "justificationPlaceholder": justification.get("placeholder")
            if justification
            else "",
            "justificationHelp": _text(
                justification.parent.find(lambda n: n.tag == "p")
            )
            if justification is not None and justification.parent is not None
            else "",
            "monitoredBy": _text(monitored),
        },
        "hasJustification": justification is not None,
        "placeholders": _placeholders(form),
        "labels": _labels(form),
        "notes": [],
        "hidden": _hidden_values(form),
    }


def toast_message(html: str) -> str:
    """A planning save's confirmation: the toast card's sentence and the
    warning under it, without its link, Undo and dismiss buttons."""
    card = parse(html).find(lambda n: "data-planning-saved-toast" in n.attrs)
    if card is None:
        return ""
    sentence = card.find(lambda n: n.tag == "span")
    notice = card.find(lambda n: "data-ceiling-notice" in n.attrs)
    return " ".join(filter(None, (_own_text(sentence), _text(notice))))


def form_data(kind: str, html: str, values: dict) -> dict[str, str]:
    """What a save posts: the drawer's hidden values as the web rendered
    them, and the person's values for the fields this drawer sends only."""
    found = _form_of(html)
    hidden = _hidden_values(found[1]) if found else {}
    allowed = set(SAVED_FIELDS.get(kind, ())) - set(hidden)
    return {
        **{name: str(value) for name, value in values.items() if name in allowed},
        **hidden,
    }
