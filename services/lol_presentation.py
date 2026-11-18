"""Shared, bounded Discord presentation. Missing evidence is never replaced by a generic build."""

from __future__ import annotations

import discord

from services.lol_builds import (
    recommend,
    insufficient,
    available,
    patch_key,
    ROLE_NAMES,
)
from services.lol_analysis import analyze

CDN = "https://ddragon.leagueoflegends.com/cdn"
COLOR = 0x0AC8B9
MODES = {
    420: "Ranqueada Solo/Duo",
    440: "Ranqueada Flex",
    400: "Normal Draft",
    430: "Normal",
    450: "ARAM",
    490: "Partida rapida",
    1700: "Arena",
}


def text(value, limit=200):
    return discord.utils.escape_markdown(str(value)).replace("@", "＠")[:limit]


def champion(catalog, identifier):
    return catalog.get("champions", {}).get(
        str(identifier), {"name": f"Campeao {identifier}", "id": "", "tags": []}
    )


def champion_icon(catalog, identifier):
    c = champion(catalog, identifier)
    return (
        f"{CDN}/{catalog['version']}/img/champion/{c['id']}.png"
        if c.get("id") and catalog.get("version")
        else None
    )


def item_icon(catalog, item_id):
    return (
        f"{CDN}/{catalog['version']}/img/item/{item_id}.png"
        if catalog.get("version")
        else None
    )


def item_label(catalog, item_id):
    item = catalog.get("items", {}).get(str(item_id))
    if not item:
        return f"Item {item_id}"
    icon = item_icon(catalog, item_id)
    return f"[{text(item['name'], 80)}]({icon})" if icon else text(item["name"], 80)


def build_recommendation(
    catalog, selected, enemies, role=None, map_id=11, rows=None, queue_id=420, now=None
):
    return recommend(
        catalog, selected, enemies, rows or [], role, map_id, queue_id, now
    )


def live_embeds(game, watched, context, catalog, test=False):
    prefix = "MODO TESTE • " if test else ""
    players = game.get("participants", [])
    tracked = {p["puuid"]: p["riot_id"] for p in watched}
    focus = next((p for p in players if p.get("puuid") in tracked), None)
    highlights = []
    for account in watched[:10]:
        p = next((p for p in players if p.get("puuid") == account["puuid"]), {})
        highlights.append(
            f"**{text(account['riot_id'], 60)}** · {text(champion(catalog, p.get('championId'))['name'], 30)}"
        )
    mode = MODES.get(
        game.get("gameQueueConfigId"), game.get("gameMode", "Fila indisponível")
    )
    start = game.get("gameStartTime", 0)
    elapsed = (
        f"Início <t:{int(start / 1000)}:R>"
        if start
        else f"Tempo aproximado: {int(game['gameLength']) // 60} min"
        if game.get("gameLength")
        else "Início indisponível"
    )
    e = discord.Embed(
        title=prefix + "LIVE MATCH",
        description="⭐ "
        + ("\n⭐ ".join(highlights))
        + "\n"
        + f"**{mode}** · {elapsed}\nDados **históricos**, não telemetria. WR ranqueado: acumulado da fila (League-V4). KDA recente: até 5 partidas anteriores (fila quando identificável). WR no campeão: amostra em até 20 jogos consultados, não total da temporada.",
        color=COLOR,
    )
    if focus and champion_icon(catalog, focus.get("championId")):
        e.set_thumbnail(url=champion_icon(catalog, focus["championId"]))
    for team, label in [(100, "🔵 Equipe azul"), (200, "🔴 Equipe vermelha")]:
        teammates = [p for p in players if p.get("teamId") == team]
        e.add_field(
            name=label,
            value=f"{len(teammates)} jogadores · Riot oficial · estatísticas históricas",
            inline=False,
        )
        for p in teammates[:8]:
            puuid = p.get("puuid")
            rid = p.get("riotId") or (
                f"{p['riotIdGameName']}#{p['riotIdTagline']}"
                if p.get("riotIdGameName") and p.get("riotIdTagline")
                else None
            )
            data = context.get(puuid, {}) if rid else {}
            name = text(rid, 45) if rid else "Identidade ocultada/indisponível"
            cname = text(champion(catalog, p.get("championId"))["name"], 30)
            field_name = f"{'⭐ ' if puuid in tracked else ''}{cname} · {name}"
            if not context and rid and puuid:
                e.add_field(
                    name=field_name,
                    value="⏳ Carregando estatísticas…",
                    inline=True,
                )
                continue
            history = data.get("recent")
            ranked = data.get("ranked_wr")
            rank_queue = data.get("rank_queue_name", "Solo/Duo")
            lines = [
                f"**Elo {text(rank_queue, 12)}:** {text(data.get('rank', 'indisponível'), 70)}"
            ]

            def percentage(stats):
                return f"{stats['win_rate']:.1f}".replace(".", ",") + "%"

            def score(stats):
                return (
                    f"{stats['wins']}V/{stats['losses']}D"
                    if "wins" in stats and "losses" in stats
                    else f"n={stats['count']}"
                )

            if isinstance(ranked, dict) and isinstance(
                ranked.get("win_rate"), (int, float)
            ):
                lines.append(
                    f"**WR {text(ranked['queue_name'], 12)}:** **{percentage(ranked)}** · {score(ranked)}"
                )
            elif isinstance(ranked, dict) and ranked.get("count") == 0:
                lines.append(
                    f"**WR {text(ranked['queue_name'], 12)}:** sem jogos registrados"
                )
            else:
                lines.append("**WR ranqueado:** indisponível")
            if history:
                if isinstance(history.get("kda"), (int, float)):
                    kda_n = history.get("kda_count", history["count"])
                    summary = f"**KDA recente:** {history['kda']:.2f} ({kda_n}j)"
                    if all(
                        isinstance(history.get(k), (int, float))
                        for k in ["kills", "deaths", "assists"]
                    ):
                        summary += f" · K/D/A médio {history['kills']:.1f}/{history['deaths']:.1f}/{history['assists']:.1f}"
                    lines.append(summary)
                else:
                    lines.append("**KDA recente:** indisponível")
                if history.get("start_at") and history.get("end_at"):
                    lines.append(
                        f"Período recente: <t:{int(history['start_at'] / 1000)}:d>–<t:{int(history['end_at'] / 1000)}:d>"
                    )
            else:
                lines.append("**KDA recente:** indisponível")
            selected_wr = data.get("champion_wr")
            window = data.get("history_window")
            if isinstance(selected_wr, dict) and isinstance(
                selected_wr.get("win_rate"), (int, float)
            ):
                lines.append(
                    f"**WR no campeão (n={selected_wr['count']}):** **{percentage(selected_wr)}** · {score(selected_wr)}"
                )
                lines.append(
                    f"{'Na mesma fila' if data.get('history_queue') is not None else 'Em filas não identificadas'}, entre {window} jogos consultados"
                    + (" · amostra pequena" if selected_wr["count"] < 5 else "")
                )
            elif window is not None:
                lines.append(
                    f"**WR no campeão:** sem jogos nos {window} consultados da fila"
                )
            else:
                lines.append("**WR no campeão:** indisponível")
            mastery = data.get("mastery")
            if isinstance(mastery, dict) and mastery.get("championLevel") is not None:
                points = (
                    f" · {mastery['championPoints']:,} pontos"
                    if isinstance(mastery.get("championPoints"), (int, float))
                    else ""
                )
                lines.append(f"**Maestria:** nível {mastery['championLevel']}{points}")
            else:
                lines.append("**Maestria:** indisponível")
            e.add_field(
                name=field_name,
                value="\n".join(lines),
                inline=True,
            )
    e.set_footer(
        text=prefix
        + "League-V4: WR da fila • Match-V5: WR no campeão e KDA recente • remakes excluídos"
    )
    return [e]


def demo_advice(catalog):
    # This miniature fixture is ONLY used by the explicitly labeled demo, never by production advice.
    import time

    candidates = [
        i
        for i in [6655, 2503, 4645, 3089, 3135, 3157]
        if available(i, catalog, 11, 103)
    ]
    if len(candidates) < 3:
        return insufficient(
            catalog, "Itens da demonstração não disponíveis neste catálogo."
        )
    boots = [i for i in [3020, 3158] if available(i, catalog, 11, 103)]
    starters = [i for i in [1056, 2003] if available(i, catalog, 11, 103)]
    rows = [
        {
            "match_id": f"DEMO_{i}",
            "participant_id": 1,
            "patch": patch_key(catalog.get("version")),
            "played_at": time.time() - i * 3600,
            "champion_id": 103,
            "role": "MIDDLE",
            "map_id": 11,
            "queue_id": 420,
            "win": i < 12,
            "items": candidates[:3]
            + boots[:1]
            + ([3157] if i % 2 == 0 and available(3157, catalog, 11, 103) else []),
            "enemies": [54, 86, 64, 16, 99],
            "purchases": {"core": candidates[:3], "starters": starters},
        }
        for i in range(20)
    ]
    advice = recommend(catalog, 103, [], rows, "MIDDLE")
    advice["source"] = "MODO TESTE — amostra fictícia"
    advice["source_url"] = None
    return advice


def build_embeds(game, player, catalog, test=False, advice=None):
    prefix = "MODO TESTE • " if test else ""
    p = next(
        (p for p in game.get("participants", []) if p.get("puuid") == player["puuid"]),
        None,
    )
    if not p:
        return [
            discord.Embed(
                title=prefix + "BUILD INDISPONÍVEL",
                description="Jogador não identificável na resposta oficial.",
                color=0xE5B65A,
            )
        ]
    if advice is None:
        advice = (
            demo_advice(catalog)
            if test
            else insufficient(
                catalog,
                "Sem amostra empírica validada para este campeão, posição e patch.",
            )
        )
    c = champion(catalog, p.get("championId"))
    e = discord.Embed(
        title=prefix + "BUILD • " + text(c["name"], 60),
        description=f"**{text(player['riot_id'])}**\nItens ordenados por compras observadas, sem lista genérica por classe.",
        color=0xE5B65A,
    )
    icon = champion_icon(catalog, p.get("championId"))
    if icon:
        e.set_thumbnail(url=icon)
    e.add_field(name="Patch", value=advice.get("patch") or "indisponível", inline=True)
    e.add_field(
        name="Posição da amostra",
        value=ROLE_NAMES.get(advice.get("role"), "não identificada")
        + (" · sua rota não confirmada" if advice.get("role_reference") else ""),
        inline=True,
    )
    e.add_field(
        name="Amostra", value=f"**{advice.get('sample', 0)} partidas**", inline=True
    )
    source = text(advice.get("source", "indisponível"), 180)
    if advice.get("source_url"):
        source = f"[{source}]({advice['source_url']})"
    e.add_field(
        name="Fonte e validade",
        value=source + "\nDados separados por campeão, posição, fila, mapa e patch.",
        inline=False,
    )
    if not advice.get("available"):
        e.add_field(
            name="Dados insuficientes",
            value=advice.get("reason", "Fonte indisponível.")
            + "\nNenhum núcleo genérico é apresentado como build atualizada.",
            inline=False,
        )
        e.set_footer(
            text=prefix
            + "Sem evidência suficiente • nenhuma taxa ou ordem foi inventada"
        )
        return [e]
    sequence = "\n".join(
        f"**{index}.** {item_label(catalog, i)}"
        for index, i in enumerate(advice["core"], 1)
    )
    e.add_field(name="Build principal · ordem confirmada", value=sequence, inline=False)
    e.add_field(
        name="Botas",
        value=" · ".join(item_label(catalog, i) for i in advice["boots"])
        or "Sem frequência mínima na amostra",
        inline=True,
    )
    e.add_field(
        name="Itens iniciais",
        value=" · ".join(item_label(catalog, i) for i in advice["starters"])
        or "Sem frequência mínima na amostra",
        inline=True,
    )
    e.add_field(
        name="Evidência do núcleo",
        value=f"**{advice['sequence_games']} ocorrências** · {advice['sequence_pick_rate']:.1f}% das **{advice['ordered_sample']} timelines elegíveis**\nVitórias observadas: **{advice['sequence_win_rate']:.1f}%**. Associação, não garantia de eficiência.",
        inline=False,
    )
    alternatives = advice.get("alternatives", [])
    e.add_field(
        name="Alternativas observadas",
        value="\n".join(
            f"{item_label(catalog, a['item_id'])} · {a['games']} jogos · presença {a['pick_rate']:.1f}% · vitórias {a['win_rate']:.1f}%"
            for a in alternatives
        )[:1024]
        or "Nenhuma alternativa com amostra mínima; não improvisar substituições.",
        inline=False,
    )
    for a in advice.get("adaptations", [])[:4]:
        lines = [f"**Amostra condicional: {a['sample']} jogos.**", a["note"]]
        lines.extend(
            f"{item_label(catalog, i['item_id'])}: {i['games']} jogos · presença {i['pick_rate']:.1f}% · vitórias {i['win_rate']:.1f}%"
            for i in a.get("items", [])
        )
        e.add_field(name=a["label"], value="\n".join(lines)[:1024], inline=False)
    if advice.get("audit_items"):
        e.add_field(
            name="Yunara · frequência dos itens investigados",
            value="\n".join(
                f"{item_label(catalog, a['item_id'])} · {a['games']} jogos · presença {a['pick_rate']:.1f}% · "
                + (
                    f"vitórias {a['win_rate']:.1f}%"
                    if a["games"] >= 5
                    else "vitórias: amostra insuficiente"
                )
                for a in advice["audit_items"]
            )[:1024],
            inline=False,
        )
        e.add_field(
            name="Sinergias: hipóteses, não prioridades fixas",
            value="Runaan atinge inimigos próximos adicionais; Dardos fortalece ataques após a ultimate (efeitos do catálogo atual). O kit e a composição podem favorecer esses efeitos, mas a substituição exige amostra. Canhão não entra por ser um item genérico de atirador.",
            inline=False,
        )
    profile = advice.get("profile", {})
    if profile:
        e.add_field(
            name="Leitura dos adversários",
            value=f"Curto alcance: {profile['short_range']}/{profile['known_ranges']} com alcance conhecido. Kits revisados: {profile['known_kits']}/{profile['total']}.\nTanques {profile['tank']} · armadura {profile['armor']} · cura {profile['healing']} · dano físico {profile['physical']} / mágico {profile['magic']} / misto {profile['mixed']}. Dados parciais não medem o dano real.",
            inline=False,
        )
    e.add_field(
        name="Período e limites",
        value=f"<t:{int(advice['period_start'])}:d> a <t:{int(advice['period_end'])}:d>\n{advice['limitations']}",
        inline=False,
    )
    e.set_footer(
        text=prefix
        + "Riot Match-V5 / timelines • Data Dragon apenas valida nomes, itens e imagens"
    )
    cards = [e]
    for i in (advice["starters"][:1] + advice["boots"][:1] + advice["core"])[:5]:
        card = discord.Embed(
            title=prefix + text(catalog["items"][str(i)]["name"], 70),
            url=item_icon(catalog, i),
            color=0xE5B65A,
        )
        card.set_thumbnail(url=item_icon(catalog, i))
        cards.append(card)
    return cards


def report_embeds(match, watched, context, catalog, test=False):
    prefix = "MODO TESTE • " if test else ""
    info = match.get("info", {})
    duration = info.get("gameDuration", 0)
    embeds = []
    for account in watched:
        p = next(
            (
                p
                for p in info.get("participants", [])
                if p.get("puuid") == account["puuid"]
            ),
            None,
        )
        if not p:
            continue
        k, d, a = p.get("kills"), p.get("deaths"), p.get("assists")
        complete = all(isinstance(v, (int, float)) for v in (k, d, a))
        kda = (k + a) / max(1, d) if complete else None
        cs = (
            (p["totalMinionsKilled"] + p["neutralMinionsKilled"])
            if all(
                isinstance(p.get(f), (int, float))
                for f in ["totalMinionsKilled", "neutralMinionsKilled"]
            )
            else None
        )
        minutes = max(duration / 60, 1 / 60)
        result = (
            ("VITÓRIA" if p["win"] else "DERROTA")
            if isinstance(p.get("win"), bool)
            else "RESULTADO INDISPONÍVEL"
        )
        e = discord.Embed(
            title=f"{prefix}{result} • {text(account['riot_id'], 80)}",
            description=f"{text(p.get('championName', 'Campeão indisponível'))} · Duração: {int(duration) // 60}:{int(duration) % 60:02d}",
            color=0x37B878 if p.get("win") else 0xDB5964,
        )
        icon = champion_icon(catalog, p.get("championId"))
        if icon:
            e.set_thumbnail(url=icon)
        e.add_field(
            name="K / D / A",
            value=f"{k} / {d} / {a} · KDA {kda:.2f}" if complete else "indisponível",
        )
        e.add_field(
            name="Farm",
            value=f"{cs} CS · {cs / minutes:.1f} CS/min"
            if cs is not None and duration
            else "indisponível",
        )
        e.add_field(
            name="Dano a campeões",
            value=f"{p['totalDamageDealtToChampions']:,}"
            if "totalDamageDealtToChampions" in p
            else "indisponível",
        )
        e.add_field(
            name="Dano recebido",
            value=f"{p['totalDamageTaken']:,}"
            if "totalDamageTaken" in p
            else "indisponível",
        )
        e.add_field(
            name="Ouro obtido",
            value=f"{p['goldEarned']:,}" if "goldEarned" in p else "indisponível",
        )
        e.add_field(
            name="Visão",
            value=str(p["visionScore"])
            if "visionScore" in p
            else "indisponível neste modo",
        )
        items = [p.get("item" + str(i), 0) for i in range(7)]
        e.add_field(
            name="Itens finais",
            value=" · ".join(item_label(catalog, i) for i in items if i)[:1024]
            or "Nenhum item registrado",
            inline=False,
        )
        analysis = analyze(info, p, context.get(account["puuid"], {}))
        e.add_field(
            name="ANÁLISE DE DESEMPENHO",
            value="Leitura contextual dos dados coletados, separada dos números da partida.",
            inline=False,
        )
        e.add_field(
            name="Indicadores principais", value=analysis["indicators"], inline=False
        )
        e.add_field(
            name="Comparação histórica", value=analysis["comparison"], inline=False
        )
        e.add_field(name="Leitura da partida", value=analysis["reading"], inline=False)
        e.set_footer(
            text=prefix
            + "Riot Match-V5 • "
            + str(match.get("metadata", {}).get("matchId", ""))
        )
        embeds.append(e)
    return embeds


def demo_data(catalog):
    ids = (
        [
            k
            for k in ["103", "222", "266", "16", "54", "22", "99", "86", "64", "25"]
            if k in catalog.get("champions", {})
        ]
        + [
            k
            for k in catalog.get("champions", {})
            if k not in ["103", "222", "266", "16", "54", "22", "99", "86", "64", "25"]
        ]
    )[:10]
    ids = (
        ["103", "222", "266", "16", "54", "22", "99", "86", "64", "25"]
        if len(ids) < 10
        else ids
    )
    game = {
        "gameId": 123456789,
        "gameMode": "CLASSIC",
        "gameQueueConfigId": 420,
        "mapId": 11,
        "gameStartTime": 0,
        "participants": [],
    }
    for i, cid in enumerate(ids):
        game["participants"].append(
            {
                "puuid": f"DEMO-{i}",
                "riotId": "Mochila#bunny" if i == 0 else f"Exemplo {i}#TESTE",
                "championId": int(cid),
                "teamId": 100 if i < 5 else 200,
            }
        )
    watched = [{"puuid": "DEMO-0", "riot_id": "Mochila#bunny", "platform": "BR1"}]
    context = {
        "DEMO-0": {
            "rank": "GOLD II · 42 LP (ficticio)",
            "rank_queue_name": "Solo/Duo",
            "ranked_wr": {
                "queue_name": "Solo/Duo",
                "wins": 10,
                "losses": 10,
                "count": 20,
                "win_rate": 50.0,
            },
            "champion_wr": {"wins": 2, "losses": 1, "count": 3, "win_rate": 200 / 3},
            "history_window": 20,
            "history_queue": 420,
            "recent": {
                "count": 5,
                "win_rate": 60.0,
                "wins": 3,
                "losses": 2,
                "kills": 6.2,
                "deaths": 4,
                "assists": 8,
                "kda": 3.55,
                "damage": 20000,
            },
            "mastery": {"championLevel": 12, "championPoints": 120000},
        }
    }
    p = {
        **game["participants"][0],
        "championName": champion(catalog, ids[0])["name"],
        "win": True,
        "kills": 8,
        "deaths": 3,
        "assists": 11,
        "totalMinionsKilled": 205,
        "neutralMinionsKilled": 12,
        "totalDamageDealtToChampions": 28430,
        "totalDamageTaken": 17200,
        "goldEarned": 14500,
        "visionScore": 24,
    }
    b = demo_advice(catalog)
    for index, i in enumerate((b["starters"][:1] + b["boots"] + b["core"])[:6]):
        p["item" + str(index)] = i
    result = {
        "metadata": {"matchId": "BR1_DEMO"},
        "info": {
            "gameDuration": 1860,
            "participants": [p],
            "teams": [{"teamId": 100, "objectives": {"champion": {"kills": 32}}}],
        },
    }
    return game, watched, context, result


def fallback_catalog():
    """Explicit demo-only metadata, never used as current patch data for real advice."""
    names = [
        ("103", "Ahri", "Ahri", ["Mage"]),
        ("222", "Jinx", "Jinx", ["Marksman"]),
        ("266", "Aatrox", "Aatrox", ["Fighter"]),
        ("16", "Soraka", "Soraka", ["Support"]),
        ("54", "Malphite", "Malphite", ["Tank"]),
        ("22", "Ashe", "Ashe", ["Marksman"]),
        ("99", "Lux", "Lux", ["Mage"]),
        ("86", "Garen", "Garen", ["Fighter"]),
        ("64", "LeeSin", "Lee Sin", ["Fighter"]),
        ("25", "Morgana", "Morgana", ["Mage"]),
    ]
    return {
        "version": None,
        "champions": {
            key: {"key": key, "id": cid, "name": name, "tags": tags}
            for key, cid, name, tags in names
        },
        "items": {},
    }
