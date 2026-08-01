"""Versioned, application-rendered documents used by the first-login gate.

The database version records the immutable version number and checksum while
the readable content lives in this module and its source-derived safeguarding
template. Changing wording requires a new version and checksum.
"""

from __future__ import annotations

SAFEGUARDING_SLUG = "edify-safeguarding-policy"
CREED_SLUG = "edify-apostles-creed"

CANONICAL_SLUGS = frozenset({SAFEGUARDING_SLUG, CREED_SLUG})


APOSTLES_CREED = {
    "eyebrow": "We Believe",
    "scripture": [
        {
            "text": "“The time has come,” Jesus said. “The kingdom of God is near. Repent and believe the good news.”",
            "reference": "Mark 1:15",
        },
        {
            "text": "“All Scripture is God-breathed and is useful for teaching, rebuking, correcting and training in righteousness, so that the servants of God may be thoroughly equipped for every good work.”",
            "reference": "2 Timothy 3:16–17",
        },
    ],
    "creed": (
        "I believe in God, the Father Almighty, creator of heaven and earth. "
        "I believe in Jesus Christ, his only Son, our Lord, who was conceived "
        "by the Holy Spirit, born of the Virgin Mary, suffered under Pontius "
        "Pilate, was crucified, died, and was buried; he descended to the dead. "
        "On the third day he rose again; he ascended into heaven, is seated at "
        "the right hand of the Father, and will come again to judge the living "
        "and the dead. I believe in the Holy Spirit, the holy catholic church, "
        "the communion of saints, the forgiveness of sins, the resurrection "
        "of the body, and the life everlasting. Amen."
    ),
}


def context_for(slug: str) -> dict | None:
    if slug == SAFEGUARDING_SLUG:
        return {
            "kind": "safeguarding",
            "eyebrow": "Required safeguarding commitment",
        }
    if slug == CREED_SLUG:
        return {
            "kind": "creed",
            **APOSTLES_CREED,
        }
    return None
