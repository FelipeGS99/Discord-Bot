"""Shared presentation for Discord command replies and notices."""

from __future__ import annotations

from functools import partial
import re

import discord


COLORS = {
    "info": 0x2F80ED,
    "success": 0x27AE60,
    "warning": 0xF2C94C,
    "error": 0xEB5757,
}


def brand_embed(embed: discord.Embed, feature: str) -> discord.Embed:
    """Brand informational cards; event markers/provenance already in footers are preserved."""
    if not embed.footer.text:
        embed.set_footer(text=f"Tigrão • {feature}")
    return embed


def _pages(text: str, limit: int):
    while len(text) > limit:
        boundary = text.rfind("\n", 0, limit + 1)
        if boundary <= 0:
            boundary = text.rfind(" ", 0, limit + 1)
        if boundary <= 0:
            boundary = limit
        yield text[:boundary]
        text = text[boundary:].lstrip("\n ")
    if text:
        yield text


async def send_response(
    destination,
    description: str,
    *,
    feature: str,
    title: str | None = None,
    tone: str = "info",
    fields=(),
    **options,
):
    """Send readable cards, with a plain-text fallback when embeds are unavailable."""
    description = str(description).strip()
    heading = re.match(r"^\*\*([^*\n]+)\*\*\n", description)
    if heading:
        title = title or heading[1]
        description = description[heading.end() :].lstrip()
    title = title or {
        "warning": "Verifique as informações",
        "error": "Não foi possível concluir",
    }.get(tone, feature)
    options.setdefault("allowed_mentions", discord.AllowedMentions.none())

    channel = getattr(destination, "channel", destination)
    guild = getattr(destination, "guild", None)
    member = getattr(guild, "me", None)
    rich = True
    if member is not None and hasattr(channel, "permissions_for"):
        rich = (
            getattr(channel.permissions_for(member), "embed_links", True) is not False
        )

    # Long catalogs/help are paginated rather than silently truncated.
    if not rich:
        body = f"**{title}**\n\n{description}"
        for name, value in fields:
            body += f"\n\n**{name}**\n{value}"
        messages = []
        for page in _pages(body, 1900):
            messages.append(await destination.send(page, **options))
        return messages[-1] if messages else None

    embeds = []
    for page in _pages(description or "—", 3800):
        embed = brand_embed(
            discord.Embed(title=title[:256], description=page, color=COLORS[tone]),
            feature,
        )
        embeds.append(embed)
    for name, value in fields:
        for page in _pages(str(value) or "—", 1024):
            embed = embeds[-1]
            if (
                len(embed.fields) == 25
                or len(embed) + len(name[:256]) + len(page) > 5900
            ):
                embed = brand_embed(
                    discord.Embed(title=title[:256], color=COLORS[tone]), feature
                )
                embeds.append(embed)
            embed.add_field(name=name[:256], value=page, inline=False)
    messages = []
    for embed in embeds:
        messages.append(await destination.send(embed=embed, **options))
    return messages[-1]


def response_sender(feature: str):
    return partial(send_response, feature=feature)
