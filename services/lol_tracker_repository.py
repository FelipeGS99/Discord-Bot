"""Namespaced tracker tables in the bot's existing SQLite database."""

import json
import sqlite3
import time

from services.pro_live_service import LiveRepository


class LoLRepository(LiveRepository):
    def _connect(self):
        c = super()._connect()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS lol_build_samples(
              patch TEXT, champion_id INTEGER, role TEXT, map_id INTEGER, queue_id INTEGER,
              match_id TEXT, participant_id INTEGER, played_at REAL, payload TEXT NOT NULL,
              PRIMARY KEY(patch,match_id,participant_id));
            CREATE INDEX IF NOT EXISTS lol_build_lookup ON lol_build_samples(patch,champion_id,map_id,queue_id);
            CREATE TABLE IF NOT EXISTS lol_channel_config(
              guild_id INTEGER PRIMARY KEY, role_id INTEGER NOT NULL, category_id INTEGER);
            CREATE TABLE IF NOT EXISTS lol_player_channels(
              guild_id INTEGER, puuid TEXT, generation INTEGER NOT NULL,
              channel_id INTEGER, last_match TEXT, last_live REAL, delete_at REAL,
              closed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(guild_id,puuid));
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
            for puuid in puuids:
                c.execute(
                    "UPDATE lol_player_channels SET delete_at=COALESCE(delete_at,?) WHERE guild_id=? AND puuid=? AND closed=0",
                    (time.time() + 3600, guild_id, puuid),
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

    async def was_delivered(self, gid, mid, kind, subject):
        def work(c):
            row = c.execute(
                "SELECT message_id FROM lol_deliveries WHERE guild_id=? AND match_id=? AND kind=? AND subject=?",
                (gid, mid, kind, subject),
            ).fetchone()
            return row is not None and row[0] is not None

        return await self._run(work)

    async def configure_sessions(self, gid, role_id, category_id):
        await self._run(
            lambda c: c.execute(
                "INSERT OR REPLACE INTO lol_channel_config VALUES (?,?,?)",
                (gid, role_id, category_id),
            )
        )

    async def session_configs(self):
        def work(c):
            c.row_factory = sqlite3.Row
            return {
                r["guild_id"]: dict(r)
                for r in c.execute("SELECT * FROM lol_channel_config")
            }

        return await self._run(work)

    async def session(self, gid, puuid):
        def work(c):
            c.row_factory = sqlite3.Row
            row = c.execute(
                "SELECT * FROM lol_player_channels WHERE guild_id=? AND puuid=?",
                (gid, puuid),
            ).fetchone()
            return dict(row) if row else None

        return await self._run(work)

    async def sessions(self):
        def work(c):
            c.row_factory = sqlite3.Row
            return [
                dict(r)
                for r in c.execute("SELECT * FROM lol_player_channels WHERE closed=0")
            ]

        return await self._run(work)

    async def new_session(self, gid, puuid, mid, now):
        def work(c):
            c.execute(
                """INSERT INTO lol_player_channels VALUES (?,?,1,NULL,?,?,NULL,0)
              ON CONFLICT(guild_id,puuid) DO UPDATE SET generation=generation+1,
              channel_id=NULL,last_match=excluded.last_match,last_live=excluded.last_live,delete_at=NULL,closed=0""",
                (gid, puuid, mid, now),
            )

        await self._run(work)
        return await self.session(gid, puuid)

    async def session_update(self, gid, puuid, **values):
        if not values or not set(values) <= {
            "channel_id",
            "last_match",
            "last_live",
            "delete_at",
            "closed",
        }:
            raise ValueError("Campos de sessao invalidos.")
        fields = ",".join(f"{key}=?" for key in values)
        await self._run(
            lambda c: c.execute(
                f"UPDATE lol_player_channels SET {fields} WHERE guild_id=? AND puuid=?",
                (*values.values(), gid, puuid),
            )
        )

    async def store_build_samples(self, rows):
        def work(c):
            for row in rows:
                old = c.execute(
                    "SELECT payload FROM lol_build_samples WHERE patch=? AND match_id=? AND participant_id=?",
                    (row["patch"], row["match_id"], row["participant_id"]),
                ).fetchone()
                if old and "purchases" not in row:
                    previous = json.loads(old[0])
                    if "purchases" in previous:
                        row = {**row, "purchases": previous["purchases"]}
                c.execute(
                    "INSERT OR REPLACE INTO lol_build_samples VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        row["patch"],
                        row["champion_id"],
                        row["role"],
                        row["map_id"],
                        row["queue_id"],
                        row["match_id"],
                        row["participant_id"],
                        row["played_at"],
                        json.dumps(row),
                    ),
                )
            c.execute(
                "DELETE FROM lol_build_samples WHERE played_at<?",
                (time.time() - 30 * 86400,),
            )

        await self._run(work)

    async def build_samples(self, patch, champion_id, map_id, queue_id):
        return await self._run(
            lambda c: [
                json.loads(r[0])
                for r in c.execute(
                    "SELECT payload FROM lol_build_samples WHERE patch=? AND champion_id=? AND map_id=? AND queue_id=? ORDER BY played_at DESC LIMIT 3000",
                    (patch, champion_id, map_id, queue_id),
                )
            ]
        )
