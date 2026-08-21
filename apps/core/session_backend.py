"""Database-backed sessions that remain usable during a cache outage.

Django's cached-db backend already tolerates a failed cache *read*, but its
read-through write and deletion paths can still raise. Authentication must use
the authoritative database copy when Redis is unavailable; cache population is
an optimization, never a sign-in dependency.
"""

from __future__ import annotations

import logging

from django.contrib.sessions.backends.cached_db import SessionStore as CachedDBStore
from django.contrib.sessions.backends.db import SessionStore as DatabaseStore

logger = logging.getLogger("edify.sessions")


class SessionStore(CachedDBStore):
    def load(self):
        try:
            return super().load()
        except Exception:  # noqa: BLE001 - cache providers raise backend-specific errors
            logger.warning(
                "Session cache unavailable; reading from database", exc_info=True
            )
            return DatabaseStore.load(self)

    async def aload(self):
        try:
            return await super().aload()
        except Exception:  # noqa: BLE001 - see synchronous path
            logger.warning(
                "Session cache unavailable; reading from database", exc_info=True
            )
            return await DatabaseStore.aload(self)

    def exists(self, session_key):
        try:
            return super().exists(session_key)
        except Exception:  # noqa: BLE001 - cache membership can raise
            logger.warning(
                "Session cache unavailable; checking database", exc_info=True
            )
            return DatabaseStore.exists(self, session_key)

    async def aexists(self, session_key):
        try:
            return await super().aexists(session_key)
        except Exception:  # noqa: BLE001 - see synchronous path
            logger.warning(
                "Session cache unavailable; checking database", exc_info=True
            )
            return await DatabaseStore.aexists(self, session_key)

    def delete(self, session_key=None):
        DatabaseStore.delete(self, session_key)
        key = session_key or self.session_key
        if not key:
            return
        try:
            self._cache.delete(self.cache_key_prefix + key)
        except Exception:  # noqa: BLE001 - the database deletion already succeeded
            logger.warning("Session cache unavailable during deletion", exc_info=True)

    async def adelete(self, session_key=None):
        await DatabaseStore.adelete(self, session_key)
        key = session_key or self.session_key
        if not key:
            return
        try:
            await self._cache.adelete(self.cache_key_prefix + key)
        except Exception:  # noqa: BLE001 - the database deletion already succeeded
            logger.warning("Session cache unavailable during deletion", exc_info=True)
