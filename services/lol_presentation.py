"""Shared real/demo rendering; all recommendations are explicitly heuristic."""

from __future__ import annotations

import discord

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
HEALERS = {
    "Aatrox",
    "Soraka",
    "Vladimir",
    "DrMundo",
    "Warwick",
    "Swain",
    "Sylas",
    "Yuumi",
    "Briar",
    "Fiora",
    "Illaoi",
    "Zac",
    "Nami",
}
MAGIC = {
    "Ahri",
    "Akali",
    "Anivia",
    "Annie",
    "AurelionSol",
    "Azir",
    "Brand",
    "Cassiopeia",
    "Diana",
    "Evelynn",
    "Fiddlesticks",
    "Fizz",
    "Karthus",
    "Kassadin",
    "Katarina",
    "Kennen",
    "LeBlanc",
    "Lillia",
    "Lux",
    "Malzahar",
    "Morgana",
    "Orianna",
    "Rumble",
    "Ryze",
    "Swain",
    "Syndra",
    "Teemo",
    "Veigar",
    "Velkoz",
    "Vex",
    "Viktor",
    "Vladimir",
    "Xerath",
    "Ziggs",
    "Zoe",
    "Zyra",
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


def build_recommendation(catalog, selected, enemies, role=None, map_id=11):
    champ = champion(catalog, selected)
    tags = champ.get("tags", [])
    foes = [champion(catalog, e.get("championId")) for e in enemies]
    magic = sum("Mage" in c.get("tags", []) or c.get("id") in MAGIC for c in foes)
    physical = sum(
        c.get("id") not in MAGIC
        and any(t in c.get("tags", []) for t in ["Marksman", "Fighter", "Assassin"])
        for c in foes
    )
    tanks = sum("Tank" in c.get("tags", []) for c in foes)
    healing = sum(c.get("id") in HEALERS for c in foes)
    cc = sum("Tank" in c.get("tags", []) or "Mage" in c.get("tags", []) for c in foes)
    primary = tags[0] if tags else None
    profile = {
        "Mage": "mage",
        "Marksman": "marksman",
        "Tank": "tank",
        "Support": "support",
        "Fighter": "fighter",
        "Assassin": "assassin",
    }.get(primary, "unknown")
    if champ.get("id") in MAGIC:
        profile = "mage"
    if champ.get("id") in {
        "Soraka",
        "Nami",
        "Lulu",
        "Janna",
        "Yuumi",
        "Milio",
        "Sona",
        "Renata",
        "Ivern",
        "Bard",
    }:
        profile = "support"
    if role in ["UTILITY", "SUPPORT"] and "Support" in tags:
        profile = "support"
    pools = {
        "mage": ([1056, 1054], [6655, 2503, 4645, 3089, 3135, 3157]),
        "marksman": ([1055], [6672, 3094, 3031, 3508, 3085, 3036]),
        "tank": ([1054], [3068, 6664, 6665, 3083, 3075, 3065]),
        "support": ([3865], [4005, 3504, 3107, 3190, 6617]),
        "fighter": ([1055, 1054], [3071, 3074, 3161, 3053, 6333, 3153]),
        "assassin": ([1036, 1055], [3142, 6692, 6694, 6697, 3814]),
    }
    items = catalog.get("items", {})

    def available(i):
        d = items.get(str(i), {})
        return bool(
            d
            and d.get("gold", {}).get("purchasable", False)
            and d.get("maps", {}).get(str(map_id), False)
            and not d.get("requiredChampion")
            and not d.get("inStore") is False
        )

    def pick(ids, n):
        return [i for i in ids if available(i)][:n]

    starter, core = pools.get(profile, ([], []))
    boots = (
        [3111, 3047]
        if magic > physical or cc >= 3
        else [3047, 3111]
        if physical >= 3
        else [3006, 3158]
        if profile == "marksman"
        else [3020, 3158]
        if profile == "mage"
        else [3158, 3111, 3047]
    )
    situational = []
    options = [
        (
            "Contra tanques",
            [3135] if profile == "mage" else [3036, 3153, 3071],
            "Penetracao ou dano contra alvos resistentes; presenca estimada pelas classes dos inimigos.",
        ),
        (
            "Contra cura",
            [3165]
            if profile == "mage"
            else [3075]
            if profile == "tank"
            else [3033, 6609],
            "Feridas Dolorosas quando a cura inimiga estiver decidindo as lutas.",
        ),
        (
            "Contra dano magico",
            [3102, 3157] if profile == "mage" else [3156, 3065],
            "Protecao contra ameacas magicas; ajuste ao adversario que esta forte.",
        ),
        (
            "Contra dano fisico",
            [3157] if profile == "mage" else [3143, 3110, 6333],
            "Armadura ou mitigacao contra as ameacas fisicas.",
        ),
        (
            "Sobrevivencia",
            [3157, 3102] if profile == "mage" else [3026, 3053, 3814],
            "Alternativa defensiva para evitar mortes antes de contribuir.",
        ),
    ]
    if tanks >= 2:
        replacement = pick(options[0][1], 1)
        if replacement:
            core = [
                *core[:1],
                *replacement,
                *[i for i in core[1:] if i not in replacement],
            ]
    for title, ids, why in options:
        found = pick(ids, 1)
        if found:
            situational.append((title, found[0], why))
    return {
        "profile": profile,
        "role": role or "nao identificada",
        "starters": pick(starter, 1) + pick([2003], 1),
        "boots": pick(boots, 1),
        "core": pick(list(dict.fromkeys(core)), 3),
        "situational": situational,
        "threats": {
            "physical": physical,
            "magic": magic,
            "tanks": tanks,
            "healing": healing,
            "cc": cc,
        },
        "available": bool(
            catalog.get("version") and profile != "unknown" and map_id in (11, 12)
        ),
    }


def live_embeds(game, watched, context, catalog, test=False):
    prefix = "MODO TESTE • " if test else ""
    players = game.get("participants", [])
    tracked = {p["puuid"]: p["riot_id"] for p in watched}
    names = ", ".join(text(p["riot_id"], 70) for p in watched)
    mode = MODES.get(
        game.get("gameQueueConfigId"), game.get("gameMode", "Modo indisponivel")
    )
    start = game.get("gameStartTime", 0)
    duration = (
        f"Inicio: <t:{int(start / 1000)}:R>"
        if start
        else f"Duracao aproximada: {int(game['gameLength']) // 60} min"
        if game.get("gameLength")
        else "Horario de inicio indisponivel"
    )
    embed = discord.Embed(
        title=prefix + "LIVE MATCH",
        description=f"**Em acompanhamento: {names}**\n{mode} · {duration}\nEstatisticas abaixo sao historicas, nao dados ao vivo de kills/ouro.",
        color=COLOR,
    )
    focus = next((p for p in players if p.get("puuid") in tracked), None)
    if focus and champion_icon(catalog, focus.get("championId")):
        embed.set_thumbnail(url=champion_icon(catalog, focus["championId"]))
    for team, label in [(100, "🔵 Equipe azul"), (200, "🔴 Equipe vermelha")]:
        lines = []
        for p in [p for p in players if p.get("teamId") == team]:
            puuid = p.get("puuid")
            # Never resolve identities omitted by Spectator: no cross-lookup of hidden participants.
            rid = p.get("riotId") or (
                f"{p['riotIdGameName']}#{p['riotIdTagline']}"
                if p.get("riotIdGameName") and p.get("riotIdTagline")
                else None
            )
            visible = bool(rid)
            identity = text(rid, 45) if visible else "Identidade ocultada/indisponivel"
            stats = context.get(puuid, {}) if visible else {}
            champ = text(champion(catalog, p.get("championId"))["name"], 25)
            history = stats.get("recent")
            recent = (
                f"WR {history['win_rate']}% · KDA {history['kda']:.2f} · n={history['count']}"
                if history
                else "Historico indisponivel"
            )
            mastery = stats.get("mastery")
            mastery_label = (
                f" · M{mastery['championLevel']}"
                if isinstance(mastery, dict)
                and mastery.get("championLevel") is not None
                else ""
            )
            lines.append(
                f"{'⭐ ' if puuid in tracked else ''}**{champ}** — {identity}\n↳ {text(stats.get('rank', 'Elo indisponivel'), 45)} · {recent}{mastery_label}"
            )
        embed.add_field(
            name=label,
            value="\n".join(lines)[:1024] or "Participantes indisponiveis",
            inline=False,
        )
    for p in watched[:10]:
        participant = next(
            (row for row in players if row.get("puuid") == p["puuid"]), {}
        )
        data = context.get(p["puuid"], {})
        history = data.get("recent")
        summary = (
            f"WR {history['win_rate']}% · KDA medio {history['kda']:.2f} em {history['count']} partidas anteriores"
            if history
            else "WR/KDA historicos indisponiveis"
        )
        mastery = data.get("mastery")
        summary += (
            f"\nMaestria: nivel {mastery.get('championLevel')} · {mastery.get('championPoints', 0):,} pontos"
            if isinstance(mastery, dict) and mastery.get("championLevel") is not None
            else "\nMaestria indisponivel"
        )
        embed.add_field(
            name=text(p["riot_id"], 80)
            + " · "
            + text(champion(catalog, participant.get("championId"))["name"], 40),
            value=summary,
            inline=False,
        )
    embed.set_footer(
        text=prefix
        + "Riot Spectator-V5 • imagens Data Dragon • sem telemetria durante a partida"
    )
    return [embed]


def build_embeds(game, player, catalog, test=False):
    prefix = "MODO TESTE • " if test else ""
    participant = next(
        (p for p in game.get("participants", []) if p.get("puuid") == player["puuid"]),
        None,
    )
    if not participant:
        return [
            discord.Embed(
                title=prefix + "Build indisponivel",
                description="Jogador nao identificavel na resposta oficial. Nenhuma identidade foi inferida.",
                color=COLOR,
            )
        ]
    enemies = [
        p
        for p in game.get("participants", [])
        if p.get("teamId") != participant.get("teamId")
    ]
    advice = build_recommendation(
        catalog,
        participant.get("championId"),
        enemies,
        participant.get("teamPosition"),
        game.get("mapId"),
    )
    c = champion(catalog, participant.get("championId"))
    e = discord.Embed(
        title=prefix + "BUILD • " + text(c["name"], 60),
        description=f"**{text(player['riot_id'])}**\n**Recomendacao heuristica — sem estatisticas de win rate.**\nPatch {catalog.get('version') or 'indisponivel'} · Rota: {advice['role']}\nPerfil estimado: {advice['profile']}. Ajuste aos adversarios e ao estado real do jogo.",
        color=0xE5B65A,
    )
    icon = champion_icon(catalog, participant.get("championId"))
    if icon:
        e.set_thumbnail(url=icon)
    if not advice["available"]:
        e.add_field(
            name="Dados insuficientes",
            value="Catalogo atual indisponivel ou modo sem guia suportado. Nenhuma ordem de itens e apresentada como validada.",
            inline=False,
        )
        return [e]
    for label, ids in [
        ("Itens iniciais", advice["starters"]),
        ("Botas", advice["boots"]),
        ("Ordem principal", advice["core"]),
    ]:
        e.add_field(
            name=label,
            value=" → ".join(item_label(catalog, i) for i in ids)
            or "Sem item elegivel neste patch/mapa",
            inline=False,
        )
    threat = advice["threats"]
    e.add_field(
        name="Leitura heuristica da composicao",
        value=f"Tendencias por classe: fisico {threat['physical']}, magico {threat['magic']}, tanques {threat['tanks']}, cura elevada {threat['healing']}. Classes nao medem dano real nem garantem controle de grupo. Botas defensivas priorizadas contra dano/controle estimados.",
        inline=False,
    )
    for label, i, why in advice["situational"]:
        e.add_field(name=label, value=f"{item_label(catalog, i)} — {why}", inline=False)
    e.set_footer(
        text=prefix
        + "Heuristica do Tigrao • Data Dragon valida nomes/itens/imagens, nao desempenho de builds"
    )
    cards = [e]
    for i in (advice["starters"][:1] + advice["boots"] + advice["core"])[:5]:
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
            ("VITORIA" if p["win"] else "DERROTA")
            if isinstance(p.get("win"), bool)
            else "RESULTADO INDISPONIVEL"
        )
        e = discord.Embed(
            title=f"{prefix}{result} • {text(account['riot_id'], 80)}",
            description=f"{text(p.get('championName', 'Campeao indisponivel'))} · Duracao: {int(duration) // 60}:{int(duration) % 60:02d}",
            color=0x37B878 if p.get("win") else 0xDB5964,
        )
        icon = champion_icon(catalog, p.get("championId"))
        if icon:
            e.set_thumbnail(url=icon)
        e.add_field(
            name="K / D / A",
            value=f"{k} / {d} / {a} · KDA {kda:.2f}" if complete else "indisponivel",
        )
        e.add_field(
            name="Farm",
            value=f"{cs} CS · {cs / minutes:.1f} CS/min"
            if cs is not None and duration
            else "indisponivel",
        )
        e.add_field(
            name="Dano a campeoes",
            value=f"{p['totalDamageDealtToChampions']:,}"
            if "totalDamageDealtToChampions" in p
            else "indisponivel",
        )
        e.add_field(
            name="Dano recebido",
            value=f"{p['totalDamageTaken']:,}"
            if "totalDamageTaken" in p
            else "indisponivel",
        )
        e.add_field(
            name="Ouro obtido",
            value=f"{p['goldEarned']:,}" if "goldEarned" in p else "indisponivel",
        )
        e.add_field(
            name="Visao",
            value=str(p["visionScore"])
            if "visionScore" in p
            else "indisponivel neste modo",
        )
        items = [p.get("item" + str(i), 0) for i in range(7)]
        e.add_field(
            name="Itens finais",
            value=" · ".join(item_label(catalog, i) for i in items if i)[:1024]
            or "Nenhum item registrado",
            inline=False,
        )
        baseline = context.get(account["puuid"], {}).get("recent")
        summary = (
            f"Participou de {k + a} abates e sofreu {d} mortes."
            if complete
            else "Dados de desempenho incompletos na resposta oficial."
        )
        if cs is not None and duration:
            summary += f" Farm medio de {cs / minutes:.1f} CS/min."
        if baseline and kda is not None:
            summary += f"\nKDA {kda - baseline['kda']:+.2f} em relacao a media das {baseline['count']} partidas anteriores. Comparacao historica, modos/rotas podem diferir."
        e.add_field(name="Resumo baseado nos dados", value=summary, inline=False)
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
            "recent": {
                "count": 5,
                "win_rate": 60,
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
    b = build_recommendation(catalog, int(ids[0]), game["participants"][5:])
    for index, i in enumerate((b["starters"][:1] + b["boots"] + b["core"])[:6]):
        p["item" + str(index)] = i
    result = {
        "metadata": {"matchId": "BR1_DEMO"},
        "info": {"gameDuration": 1860, "participants": [p]},
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
