"""Post-match analysis based on verified team totals and comparable historical samples."""

from __future__ import annotations

from statistics import mean

MIN_HISTORY = 3


def performance_rows(matches, puuid):
    rows = []
    seen = set()
    for m in matches:
        mid = m.get("metadata", {}).get("matchId")
        if mid and mid in seen:
            continue
        if mid:
            seen.add(mid)
        info = m.get("info", {})
        p = next(
            (p for p in info.get("participants", []) if p.get("puuid") == puuid), None
        )
        if (
            not p
            or p.get("gameEndedInEarlySurrender")
            or info.get("gameDuration", 0) < 300
        ):
            continue
        rows.append(
            {
                **{
                    k: p[k]
                    for k in [
                        "championId",
                        "teamPosition",
                        "kills",
                        "deaths",
                        "assists",
                        "totalMinionsKilled",
                        "neutralMinionsKilled",
                        "visionScore",
                        "totalDamageDealtToChampions",
                    ]
                    if k in p
                },
                "duration": info["gameDuration"],
                "queue_id": info.get("queueId"),
                "map_id": info.get("mapId"),
                "played_at": info.get("gameEndTimestamp") or info.get("gameCreation"),
            }
        )
    return rows


def metrics(p, duration):
    result = {}
    if duration <= 0:
        return result
    minutes = duration / 60
    if all(isinstance(p.get(k), (int, float)) for k in ["kills", "deaths", "assists"]):
        result["kda"] = (p["kills"] + p["assists"]) / max(1, p["deaths"])
    if all(
        isinstance(p.get(k), (int, float))
        for k in ["totalMinionsKilled", "neutralMinionsKilled"]
    ):
        result["cs"] = (p["totalMinionsKilled"] + p["neutralMinionsKilled"]) / minutes
    if isinstance(p.get("visionScore"), (int, float)):
        result["vision"] = p["visionScore"] / minutes
    if isinstance(p.get("totalDamageDealtToChampions"), (int, float)):
        result["damage"] = p["totalDamageDealtToChampions"] / minutes
    return result


def baseline_for(info, player, history):
    rows = [
        r
        for r in history
        if r.get("map_id") == info.get("mapId")
        and r.get("queue_id") == info.get("queueId")
        and r.get("duration", 0) >= 300
    ]
    champ = [r for r in rows if r.get("championId") == player.get("championId")]
    comparable = [
        r
        for r in champ
        if player.get("teamPosition")
        and r.get("teamPosition") == player["teamPosition"]
    ]
    if len(comparable) >= MIN_HISTORY:
        chosen, scope = comparable, "mesmo campeao e posicao"
    elif len(champ) >= MIN_HISTORY:
        chosen, scope = champ, "mesmo campeao; posicoes podem diferir"
    else:
        chosen, scope = rows, "mesma fila/mapa; campeoes e posicoes podem diferir"
    result = {
        "count": len(chosen),
        "scope": scope,
        "metrics": {},
        "enough": len(chosen) >= MIN_HISTORY,
    }
    for key in ["kda", "cs", "vision", "damage"]:
        values = [m[key] for r in chosen if key in (m := metrics(r, r["duration"]))]
        if len(values) >= MIN_HISTORY:
            result["metrics"][key] = mean(values)
    return result


def team_total(info, player, field):
    team = player.get("teamId")
    if team is None:
        return None
    if field == "kills":
        objective = next(
            (
                t.get("objectives", {}).get("champion", {}).get("kills")
                for t in info.get("teams", [])
                if t.get("teamId") == team
            ),
            None,
        )
        if isinstance(objective, (int, float)) and objective >= 0:
            return objective
    rows = [p for p in info.get("participants", []) if p.get("teamId") == team]
    if len(rows) != 5 or not all(isinstance(p.get(field), (int, float)) for p in rows):
        return None
    return sum(p[field] for p in rows)


def analyze(info, player, context):
    current = metrics(player, info.get("gameDuration", 0))
    kills = team_total(info, player, "kills")
    participation = (
        player.get("kills", 0) + player.get("assists", 0)
        if all(isinstance(player.get(k), (int, float)) for k in ["kills", "assists"])
        else None
    )
    kp = (
        participation / kills * 100
        if participation is not None and kills and 0 <= participation <= kills
        else None
    )
    damage_total = team_total(info, player, "totalDamageDealtToChampions")
    share = (
        player.get("totalDamageDealtToChampions", 0) / damage_total * 100
        if damage_total
        and isinstance(player.get("totalDamageDealtToChampions"), (int, float))
        else None
    )
    history = context.get("performances", [])
    base = baseline_for(info, player, history)
    if not history and context.get("recent"):
        old = context["recent"]
        base = {
            "count": old.get("count", 0),
            "scope": "historico geral anterior; fila/posicao nao verificadas",
            "metrics": {},
            "enough": old.get("count", 0) >= MIN_HISTORY,
        }
        if base["enough"] and isinstance(old.get("kda"), (int, float)):
            base["metrics"]["kda"] = old["kda"]
    comparisons = []
    readings = []
    labels = {"kda": "KDA", "cs": "CS/min", "vision": "Visao/min", "damage": "Dano/min"}
    for key in [
        "kda",
        "cs",
        "vision" if player.get("teamPosition") == "UTILITY" else "damage",
    ]:
        if key not in current or key not in base["metrics"]:
            continue
        value, average = current[key], base["metrics"][key]
        tolerance = max(
            {"kda": 0.2, "cs": 0.5, "vision": 0.1, "damage": 50}[key],
            abs(average) * 0.1,
        )
        delta = value - average
        label, icon = (
            ("acima", "↑")
            if delta > tolerance
            else ("abaixo", "↓")
            if delta < -tolerance
            else ("proximo", "≈")
        )
        comparisons.append(
            f"{icon} **{labels[key]} {label} da media** · {value:.2f} vs {average:.2f}"
        )
        readings.append(
            f"{labels[key]} {'acima do seu padrao recente' if label == 'acima' else 'abaixo do seu padrao recente' if label == 'abaixo' else 'alinhado ao seu padrao recente'}"
        )
    indicators = [
        f"**Participacao em abates:** {kp:.1f}% ({participation:g}/{kills:g})"
        if kp is not None
        else "**Participacao em abates:** indisponivel (total da equipe ausente, zero ou inconsistente)"
    ]
    if "cs" in current:
        indicators.append(f"**Farm/min:** {current['cs']:.1f}")
    if share is not None:
        indicators.append(f"**Parcela do dano da equipe:** {share:.1f}%")
    if player.get("teamPosition") == "UTILITY" and "vision" in current:
        indicators.append(f"**Visao/min:** {current['vision']:.2f}")
    if readings:
        conclusion = (
            "; ".join(readings[:2])
            + ". Comparacao descritiva, sem isolar duracao, adversarios ou estado do jogo."
        )
    elif kp is not None:
        conclusion = "A participacao nos abates foi calculada com o total real da equipe. Sem historico comparavel suficiente para classificar o desempenho."
    else:
        conclusion = "Os dados atuais nao permitem avaliar o desempenho em relacao ao seu padrao. Nao ha evidencia suficiente para uma conclusao categorica."
    comparison = (
        "\n".join(comparisons)
        if comparisons
        else f"Amostra insuficiente para classificar acima/abaixo: {base['count']}/{MIN_HISTORY} partidas comparaveis."
    )
    comparison += f"\nBase: **{base['count']} jogos** · {base['scope']}. Margens descritivas; nao sao significancia estatistica."
    return {
        "kp": kp,
        "damage_share": share,
        "indicators": "\n".join(indicators),
        "comparison": comparison,
        "reading": conclusion,
        "baseline": base,
    }
