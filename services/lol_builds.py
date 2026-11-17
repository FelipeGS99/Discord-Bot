"""Empirical build suggestions from current-patch Riot observations, never class-wide item pools."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import html
import re
import time

from services.riot_service import RiotError

MIN_SAMPLE = 20
MIN_SEQUENCE = 5
MIN_ALTERNATIVE = 5
MAX_AGE = 14 * 86400
ROLES = {"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"}
ROLE_NAMES = {
    "TOP": "Topo",
    "JUNGLE": "Selva",
    "MIDDLE": "Meio",
    "BOTTOM": "Atirador",
    "UTILITY": "Suporte",
}
# Reviewed kit traits, not inferred from a champion's class or claimed to measure actual damage.
TRAITS = {
    "Malphite": {"tank", "armor", "magic", "cc"},
    "Rammus": {"tank", "armor", "cc"},
    "Ornn": {"tank", "armor", "cc"},
    "Sion": {"tank", "cc"},
    "Shen": {"tank", "cc"},
    "Sejuani": {"tank", "magic", "cc"},
    "Zac": {"tank", "magic", "healing", "cc"},
    "DrMundo": {"tank", "healing"},
    "Leona": {"tank", "cc"},
    "Nautilus": {"tank", "cc"},
    "Alistar": {"tank", "healing", "cc"},
    "Braum": {"tank", "cc"},
    "Rell": {"tank", "cc"},
    "Soraka": {"magic", "healing"},
    "Yuumi": {"magic", "healing"},
    "Nami": {"magic", "healing", "cc"},
    "Vladimir": {"magic", "healing"},
    "Swain": {"magic", "healing", "cc"},
    "Sylas": {"magic", "healing", "cc"},
    "Aatrox": {"physical", "healing", "cc"},
    "Warwick": {"mixed", "healing", "cc"},
    "Briar": {"physical", "healing"},
    "Fiora": {"physical", "healing"},
    "Ahri": {"magic", "cc"},
    "Lux": {"magic", "cc"},
    "Morgana": {"magic", "cc"},
    "Syndra": {"magic", "cc"},
    "Veigar": {"magic", "cc"},
    "Orianna": {"magic", "cc"},
    "Jinx": {"physical"},
    "Ashe": {"physical", "cc"},
    "Caitlyn": {"physical"},
    "Aphelios": {"physical"},
    "Yunara": {"mixed"},
    "KogMaw": {"mixed"},
    "Garen": {"physical"},
    "Darius": {"physical", "cc"},
    "LeeSin": {"physical", "cc"},
    "Zed": {"physical"},
    "Talon": {"physical"},
    "Akali": {"magic"},
    "Katarina": {"mixed"},
}


def patch_key(version):
    parts = str(version or "").split(".")
    return (
        ".".join(parts[:2])
        if len(parts) >= 2 and all(p.isdigit() for p in parts[:2])
        else None
    )


def role_key(role):
    return {
        "MID": "MIDDLE",
        "BOT": "BOTTOM",
        "ADC": "BOTTOM",
        "SUPPORT": "UTILITY",
    }.get(str(role).upper(), str(role).upper())


def combat_profile(champion_ids, catalog):
    result = {
        k: 0
        for k in [
            "short_range",
            "tank",
            "armor",
            "physical",
            "magic",
            "mixed",
            "healing",
            "cc",
        ]
    }
    result["known_kits"] = 0
    result["known_ranges"] = 0
    result["total"] = len(champion_ids)
    for cid in champion_ids:
        c = catalog.get("champions", {}).get(str(cid), {})
        traits = TRAITS.get(c.get("id"))
        if traits is not None:
            result["known_kits"] += 1
            for key in traits:
                result[key] += 1
        reach = c.get("stats", {}).get("attackrange")
        if isinstance(reach, (int, float)):
            result["known_ranges"] += 1
            result["short_range"] += int(reach <= 350)
    return result


def available(item_id, catalog, map_id, champion_id=None):
    item = catalog.get("items", {}).get(str(item_id), {})
    required = item.get("requiredChampion")
    current = catalog.get("champions", {}).get(str(champion_id), {}).get("id")
    return bool(
        item
        and item.get("gold", {}).get("purchasable")
        and item.get("maps", {}).get(str(map_id))
        and item.get("inStore", True)
        and (not required or required == current)
    )


def is_core(item_id, catalog, map_id, champion_id=None):
    item = catalog.get("items", {}).get(str(item_id), {})
    return (
        available(item_id, catalog, map_id, champion_id)
        and item.get("gold", {}).get("total", 0) >= 2000
        and not set(item.get("tags", [])) & {"Boots", "Consumable", "Trinket"}
    )


def observations(matches):
    """Compact verified facts. No account names or PUUIDs are stored in the statistics table."""
    output = []
    for match in matches:
        info = match.get("info", {})
        mid = match.get("metadata", {}).get("matchId")
        patch = patch_key(info.get("gameVersion"))
        played = info.get("gameEndTimestamp") or info.get("gameCreation")
        if (
            not mid
            or not patch
            or not isinstance(played, (int, float))
            or info.get("gameDuration", 0) < 600
        ):
            continue
        for p in info.get("participants", []):
            role = role_key(p.get("teamPosition"))
            if (
                role not in ROLES
                or not isinstance(p.get("win"), bool)
                or not isinstance(p.get("participantId"), int)
            ):
                continue
            items = [
                p[f"item{i}"]
                for i in range(7)
                if isinstance(p.get(f"item{i}"), int) and p[f"item{i}"] > 0
            ]
            output.append(
                {
                    "match_id": mid,
                    "participant_id": p["participantId"],
                    "patch": patch,
                    "played_at": played / 1000,
                    "champion_id": p.get("championId"),
                    "role": role,
                    "map_id": info.get("mapId"),
                    "queue_id": info.get("queueId"),
                    "win": p["win"],
                    "items": list(dict.fromkeys(items)),
                    "enemies": [
                        e["championId"]
                        for e in info.get("participants", [])
                        if e.get("teamId") != p.get("teamId")
                        and isinstance(e.get("championId"), int)
                    ],
                }
            )
    return output


def purchase_facts(timeline, catalog, map_id, champion_id, participant_id, final_items):
    """First completed purchases, excluding undone actions; later sales cannot rewrite early build order."""
    events = []
    for frame in timeline.get("info", {}).get("frames", []):
        for event in frame.get("events", []):
            if event.get("participantId") == participant_id:
                events.append(event)
    owned = []
    starters = []
    completed = []
    for e in sorted(events, key=lambda e: e.get("timestamp", 0)):
        kind = e.get("type")
        iid = e.get("itemId")
        if kind == "ITEM_PURCHASED" and isinstance(iid, int):
            owned.append(iid)
            if is_core(iid, catalog, map_id, champion_id):
                completed.append(iid)
            if e.get("timestamp", 0) <= 90000 and available(
                iid, catalog, map_id, champion_id
            ):
                item = catalog["items"][str(iid)]
                if item.get("gold", {}).get("total", 0) < 1500 and not set(
                    item.get("tags", [])
                ) & {"Trinket", "Boots"}:
                    starters.append(iid)
        elif kind in {"ITEM_SOLD", "ITEM_DESTROYED"} and iid in owned:
            owned.remove(iid)
        elif kind == "ITEM_UNDO":
            before, after = e.get("beforeId"), e.get("afterId")
            if before in owned:
                owned.remove(before)
            if after and after not in owned:
                owned.append(after)
            if before in starters:
                starters.remove(before)
            if before in completed:
                last = len(completed) - 1 - completed[::-1].index(before)
                completed.pop(last)
    core = list(dict.fromkeys(completed))
    return {"core": core[:3], "starters": list(dict.fromkeys(starters))[:3]}


def insufficient(catalog, reason, sample=0, role=None):
    return {
        "available": False,
        "reason": reason,
        "sample": sample,
        "role": role,
        "patch": patch_key(catalog.get("version")),
        "source": "Riot Match-V5 · amostra local",
        "source_url": "https://developer.riotgames.com/apis#match-v5",
        "core": [],
        "boots": [],
        "starters": [],
        "alternatives": [],
        "adaptations": [],
    }


def item_answers(item_id, trait, catalog):
    item = catalog.get("items", {}).get(str(item_id), {})
    tags = set(item.get("tags", []))
    description = html.unescape(
        re.sub("<[^>]+>", " ", item.get("description", ""))
    ).casefold()
    if trait == "healing":
        return "feridas dolorosas" in description or "grievous wounds" in description
    if trait == "armor":
        return bool(tags & {"ArmorPenetration", "MagicPenetration"})
    if trait == "tank":
        return bool(tags & {"ArmorPenetration", "MagicPenetration", "OnHit"})
    if trait == "magic":
        return "SpellBlock" in tags
    if trait == "physical":
        return "Armor" in tags
    if trait == "short_range":
        return item_id == 3085 and (
            "adicionais" in description or "additional" in description
        )
    return False


def recommend(
    catalog, champion_id, enemies, rows, role=None, map_id=11, queue_id=420, now=None
):
    now = time.time() if now is None else now
    patch = patch_key(catalog.get("version"))
    if not patch:
        return insufficient(catalog, "Catalogo do patch atual indisponivel.")
    pool = {}
    for row in rows:
        if (
            row.get("patch") == patch
            and row.get("champion_id") == champion_id
            and row.get("map_id") == map_id
            and row.get("queue_id") == queue_id
            and 0 <= now - row.get("played_at", 0) <= MAX_AGE
            and role_key(row.get("role")) in ROLES
        ):
            pool[(row.get("match_id"), row.get("participant_id"))] = row
    pool = list(pool.values())
    selected = role_key(role)
    reference = selected not in ROLES
    if reference and pool:
        selected = Counter(r["role"] for r in pool).most_common(1)[0][0]
    pool = [r for r in pool if r["role"] == selected]
    if len(pool) < MIN_SAMPLE:
        return insufficient(
            catalog,
            f"Amostra insuficiente: {len(pool)}/{MIN_SAMPLE} partidas do campeao, posicao, fila e patch.",
            len(pool),
            selected if selected in ROLES else None,
        )
    sequences = Counter()
    wins = Counter()
    item_counts = Counter()
    item_wins = Counter()
    boot_counts = Counter()
    starter_counts = Counter()
    for r in pool:
        facts = r.get("purchases", {})
        seq = tuple(facts.get("core", [])[:3])
        if (
            len(seq) == 3
            and len(set(seq)) == 3
            and all(is_core(i, catalog, map_id, champion_id) for i in seq)
        ):
            sequences[seq] += 1
            wins[seq] += int(r["win"])
        for i in set(r["items"]):
            if not available(i, catalog, map_id, champion_id):
                continue
            item_counts[i] += 1
            item_wins[i] += int(r["win"])
            if "Boots" in catalog["items"][str(i)].get("tags", []):
                boot_counts[i] += 1
        for i in set(facts.get("starters", [])):
            if available(i, catalog, map_id, champion_id):
                starter_counts[i] += 1
    if not sequences or sequences.most_common(1)[0][1] < MIN_SEQUENCE:
        return insufficient(
            catalog,
            f"Ordem de compra sem evidencia suficiente: minimo de {MIN_SEQUENCE} ocorrencias confirmadas por timeline.",
            len(pool),
            selected,
        )
    core, n = sequences.most_common(1)[0]
    sample = len(pool)

    def item_stats(i):
        return {
            "item_id": i,
            "games": item_counts[i],
            "pick_rate": item_counts[i] * 100 / sample,
            "win_rate": item_wins[i] * 100 / item_counts[i],
        }

    alternatives = [
        item_stats(i)
        for i, count in item_counts.most_common()
        if count >= MIN_ALTERNATIVE
        and i not in core
        and is_core(i, catalog, map_id, champion_id)
    ]
    profile = combat_profile([e.get("championId") for e in enemies], catalog)
    conditions = [
        ("short_range", 3, "Multiplos adversarios de curto alcance"),
        ("tank", 2, "Dois ou mais tanques de kit conhecido"),
        ("armor", 1, "Possivel acumulador de armadura"),
        ("healing", 1, "Cura elevada em kits conhecidos"),
        ("magic", 3, "Tres ameacas magicas conhecidas"),
        ("physical", 3, "Tres ameacas fisicas conhecidas"),
    ]
    adaptations = []
    for trait, threshold, label in conditions:
        if profile[trait] < threshold:
            continue
        subset = [
            r for r in pool if combat_profile(r["enemies"], catalog)[trait] >= threshold
        ]
        if len(subset) < MIN_SAMPLE:
            adaptations.append(
                {
                    "label": label,
                    "sample": len(subset),
                    "note": "Sem amostra condicional suficiente; nao troca automaticamente o nucleo.",
                }
            )
            continue
        candidates = []
        for alt in alternatives:
            matches = [r for r in subset if alt["item_id"] in r["items"]]
            if len(matches) >= MIN_ALTERNATIVE and item_answers(
                alt["item_id"], trait, catalog
            ):
                candidates.append(
                    {
                        **alt,
                        "games": len(matches),
                        "pick_rate": len(matches) * 100 / len(subset),
                        "win_rate": sum(r["win"] for r in matches) * 100 / len(matches),
                    }
                )
        adaptations.append(
            {
                "label": label,
                "sample": len(subset),
                "items": sorted(candidates, key=lambda x: x["games"], reverse=True)[:2],
                "note": "Associacao observada, nao evidencia causal de superioridade.",
            }
        )
    return {
        "available": True,
        "patch": patch,
        "sample": sample,
        "ordered_sample": sum(sequences.values()),
        "sequence_games": n,
        "sequence_pick_rate": n * 100 / sum(sequences.values()),
        "sequence_win_rate": wins[core] * 100 / n,
        "role": selected,
        "role_reference": reference,
        "core": list(core),
        "boots": [i for i, c in boot_counts.most_common(1) if c >= MIN_ALTERNATIVE],
        "starters": [
            i for i, c in starter_counts.most_common(2) if c >= MIN_ALTERNATIVE
        ],
        "alternatives": alternatives[:5],
        "adaptations": adaptations,
        "profile": profile,
        "source": "Riot Match-V5 + timelines · amostra local",
        "source_url": "https://developer.riotgames.com/apis#match-v5",
        "period_start": min(r["played_at"] for r in pool),
        "period_end": max(r["played_at"] for r in pool),
        "limitations": "Amostra local exploratoria; nao representa o meta global. Frequencias e vitorias sao observacionais, com incerteza elevada em grupos pequenos.",
        "audit_items": [
            item_stats(i)
            if item_counts[i]
            else {"item_id": i, "games": 0, "pick_rate": 0, "win_rate": None}
            for i in [6672, 3085, 3031, 2512, 3094]
            if available(i, catalog, map_id, champion_id)
        ]
        if champion_id == 804
        else [],
    }


class BuildService:
    def __init__(self, riot, repository, clock=time.time):
        self.riot, self.repository, self.clock = riot, repository, clock
        self.cache = {}

    async def ingest(self, matches):
        rows = observations(matches)
        if rows:
            await self.repository.store_build_samples(rows)
            self.cache.clear()

    async def advise(self, game, player, catalog):
        p = next(
            (
                p
                for p in game.get("participants", [])
                if p.get("puuid") == player["puuid"]
            ),
            None,
        )
        if not p:
            return insufficient(
                catalog, "Jogador nao identificavel na resposta oficial."
            )
        champion_id = p.get("championId")
        role = p.get("teamPosition")
        map_id = game.get("mapId")
        queue_id = game.get("gameQueueConfigId")
        key = (patch_key(catalog.get("version")), champion_id, role, map_id, queue_id)
        cached = self.cache.get(key)
        if cached and cached[0] > self.clock():
            rows = cached[1]
        else:
            rows = await self.repository.build_samples(
                key[0], champion_id, map_id, queue_id
            )
            # Fetch a bounded number of official timelines; no additional account crawling.
            selected = role_key(role)
            if selected not in ROLES and rows:
                selected = Counter(r["role"] for r in rows).most_common(1)[0][0]
            relevant = [
                r
                for r in rows
                if r["role"] == selected
                and 0 <= self.clock() - r["played_at"] <= MAX_AGE
            ]
            if len(relevant) >= MIN_SAMPLE:
                missing = list(
                    dict.fromkeys(
                        r["match_id"] for r in relevant if "purchases" not in r
                    )
                )[:8]
                for mid in missing:
                    try:
                        timeline = await self.riot.timeline(mid, player["platform"])
                    except RiotError:
                        break
                    if timeline is None:
                        continue
                    for row in rows:
                        if row["match_id"] == mid:
                            row["purchases"] = purchase_facts(
                                timeline,
                                catalog,
                                map_id,
                                champion_id,
                                row["participant_id"],
                                row["items"],
                            )
                            await self.repository.store_build_samples([row])
            self.cache[key] = (self.clock() + 300, rows)
            if len(self.cache) > 200:
                self.cache = {
                    k: v for k, v in self.cache.items() if v[0] > self.clock()
                }
        enemies = [
            e for e in game["participants"] if e.get("teamId") != p.get("teamId")
        ]
        return recommend(
            catalog, champion_id, enemies, rows, role, map_id, queue_id, self.clock()
        )


def fingerprint(advice):
    return hashlib.sha256(
        json.dumps(advice, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
