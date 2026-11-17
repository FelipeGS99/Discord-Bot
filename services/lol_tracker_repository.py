"""Namespaced tracker tables in the bot's existing SQLite database."""

import json
import sqlite3
import time

from services.pro_live_service import LiveRepository


class LoLRepository(LiveRepository):
    def _connect(self):
        c = super()._connect()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS lol_guilds(guild_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS lol_players(
              guild_id INTEGER, puuid TEXT, riot_id TEXT NOT NULL, platform TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1, current_match TEXT, last_notified TEXT,
              status TEXT NOT NULL DEFAULT 'aguardando', checked REAL,
              PRIMARY KEY(guild_id,puuid));
            CREATE TABLE IF NOT EXISTS lol_matches(
              guild_id INTEGER, match_id TEXT, platform TEXT NOT NULL, channel_id INTEGER NOT NULL,
              phase TEXT NOT NULL, payload TEXT NOT NULL, watched TEXT NOT NULL,
              context TEXT NOT NULL DEFAULT '{}', result TEXT, updated REAL NOT NULL,
              PRIMARY KEY(guild_id,match_id));
            CREATE TABLE IF NOT EXISTS lol_deliveries(
              guild_id INTEGER, match_id TEXT, kind TEXT, subject TEXT,
              channel_id INTEGER NOT NULL, message_id INTEGER,
              PRIMARY KEY(guild_id,match_id,kind,subject));
        """)
        return c

    async def configure(self, guild_id, channel_id):
        def work(c):
            c.execute(
                "INSERT OR REPLACE INTO lol_guilds VALUES (?,?)", (guild_id, channel_id)
            )
            c.execute(
                "UPDATE lol_matches SET channel_id=? WHERE guild_id=? AND phase!='complete'",
                (channel_id, guild_id),
            )
            c.execute(
                "UPDATE lol_deliveries SET channel_id=? WHERE guild_id=? AND message_id IS NULL",
                (channel_id, guild_id),
            )

        await self._run(work)

    async def channels(self):
        return await self._run(
            lambda c: dict(c.execute("SELECT guild_id,channel_id FROM lol_guilds"))
        )

    async def follow(self, guild_id, puuid, riot_id, platform="BR1"):
        def work(c):
            old = c.execute(
                "SELECT active FROM lol_players WHERE guild_id=? AND puuid=?",
                (guild_id, puuid),
            ).fetchone()
            c.execute(
                """INSERT INTO lol_players(guild_id,puuid,riot_id,platform) VALUES (?,?,?,?)
                ON CONFLICT(guild_id,puuid) DO UPDATE SET riot_id=excluded.riot_id,platform=excluded.platform,active=1""",
                (guild_id, puuid, riot_id, platform),
            )
            return not old or not old[0]

        return await self._run(work)

    async def unfollow(self, guild_id, riot_id):
        def work(c):
            rows = c.execute(
                "SELECT puuid,riot_id FROM lol_players WHERE guild_id=? AND active=1",
                (guild_id,),
            ).fetchall()
            puuids = [p for p, r in rows if r.casefold() == riot_id.casefold()]
            for p in puuids:
                c.execute(
                    "UPDATE lol_players SET active=0,current_match=NULL,status=? WHERE guild_id=? AND puuid=?",
                    ("inativo", guild_id, p),
                )
            # Removing a player cancels that player's pending notifications as well.
            # Reactivating later must not resurrect an old unfinished report.
            for mid, encoded in c.execute(
                "SELECT match_id,watched FROM lol_matches WHERE guild_id=? AND phase!='complete'",
                (guild_id,),
            ).fetchall():
                remaining = [p for p in json.loads(encoded) if p["puuid"] not in puuids]
                c.execute(
                    "UPDATE lol_matches SET watched=?,phase=CASE WHEN ?=0 THEN 'complete' ELSE phase END WHERE guild_id=? AND match_id=?",
                    (json.dumps(remaining), len(remaining), guild_id, mid),
                )
            return bool(puuids)

        return await self._run(work)

    async def players(self, guild_id=None, active=True):
        def work(c):
            c.row_factory = sqlite3.Row
            sql = "SELECT * FROM lol_players WHERE 1=1"
            args = []
            if active:
                sql += " AND active=1"
            if guild_id is not None:
                sql += " AND guild_id=?"
                args.append(guild_id)
            return [dict(r) for r in c.execute(sql, args)]

        return await self._run(work)

    async def player_state(self, gid, puuid, status, current=None, notified=None):
        await self._run(
            lambda c: c.execute(
                """UPDATE lol_players SET status=?,current_match=?,checked=?,
            last_notified=COALESCE(?,last_notified) WHERE guild_id=? AND puuid=?""",
                (status, current, time.time(), notified, gid, puuid),
            )
        )

    async def mark_notified(self, gid, puuid, mid):
        await self._run(
            lambda c: c.execute(
                "UPDATE lol_players SET last_notified=? WHERE guild_id=? AND puuid=?",
                (mid, gid, puuid),
            )
        )

    async def save_match(self, gid, mid, platform, channel, payload, watched):
        def work(c):
            c.execute(
                """INSERT INTO lol_matches(guild_id,match_id,platform,channel_id,phase,payload,watched,updated)
              VALUES (?,?,?,?,'live',?,?,?) ON CONFLICT(guild_id,match_id) DO UPDATE SET
              watched=excluded.watched,payload=excluded.payload,updated=excluded.updated
              WHERE lol_matches.phase!='complete' """,
                (
                    gid,
                    mid,
                    platform,
                    channel,
                    json.dumps(payload),
                    json.dumps(watched),
                    time.time(),
                ),
            )

        await self._run(work)

    async def matches(self):
        def work(c):
            c.row_factory = sqlite3.Row
            rows = [
                dict(r)
                for r in c.execute("SELECT * FROM lol_matches WHERE phase!='complete'")
            ]
            for row in rows:
                for k in ["payload", "watched", "context", "result"]:
                    row[k] = json.loads(row[k]) if row[k] else None
            return rows

        return await self._run(work)

    async def context(self, gid, mid, data):
        await self._run(
            lambda c: c.execute(
                "UPDATE lol_matches SET context=? WHERE guild_id=? AND match_id=?",
                (json.dumps(data), gid, mid),
            )
        )

    async def phase(self, gid, mid, phase, result=None):
        await self._run(
            lambda c: c.execute(
                "UPDATE lol_matches SET phase=?,result=COALESCE(?,result),updated=? WHERE guild_id=? AND match_id=?",
                (phase, json.dumps(result) if result else None, time.time(), gid, mid),
            )
        )

    async def delivery(self, gid, mid, kind, subject, channel):
        def work(c):
            c.execute(
                "INSERT OR IGNORE INTO lol_deliveries VALUES (?,?,?,?,?,NULL)",
                (gid, mid, kind, subject, channel),
            )
            return c.execute(
                "SELECT message_id FROM lol_deliveries WHERE guild_id=? AND match_id=? AND kind=? AND subject=?",
                (gid, mid, kind, subject),
            ).fetchone()[0]

        return await self._run(work)

    async def acknowledge(self, gid, mid, kind, subject, message):
        await self._run(
            lambda c: c.execute(
                "UPDATE lol_deliveries SET message_id=? WHERE guild_id=? AND match_id=? AND kind=? AND subject=?",
                (message, gid, mid, kind, subject),
            )
        )
