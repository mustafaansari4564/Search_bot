"""
bot.py — Discord library search bot.

Access rules:
  COD_ID role          → can use /ask anywhere in the server
  LIBRARY_PASS_ID role → can use /ask only in LIBRARY_CHANNEL_ID
  ADMIN_ROLE_ID role   → can use /reindex and /reindex-new

Model cost note:
  This bot calls ask_library() in llm.py. To switch away from Perplexity,
  set MODEL in llm.py to a cheaper OpenRouter model, e.g.:
    "deepseek/deepseek-chat-v3-0324"      (~$0.07 / 1M tokens)
    "google/gemini-flash-1.5"             (~$0.075 / 1M tokens)
    "mistralai/mistral-small-3.1-24b-instruct"

Embed reading note:
  To index translated/embedded cards, update extract_message_text() in
  indexer.py to also iterate message.embeds and pull title, description,
  and field values. See README or the provided snippet.
"""

import asyncio
import atexit
import contextlib
import fcntl
import os
import signal
import sys

import discord
from discord import app_commands

from config  import (
    ADMIN_ROLE_ID, COD_ID, DISCORD_TOKEN,
    GUILD_ID, LIBRARY_CHANNEL_ID, LIBRARY_PASS_ID,
)
from indexer import run_indexer, run_indexer_new, run_indexer_thread
from llm     import ask_library
from search  import build_index, is_index_empty, search_prioritized

# ── Bot setup ─────────────────────────────────────────────────────────────────

intents                 = discord.Intents.default()
intents.guilds          = True
intents.message_content = True   # required to read forum post content

bot       = discord.Client(intents=intents)
tree      = app_commands.CommandTree(bot)
GUILD_OBJ = discord.Object(id=GUILD_ID)

FOOTER_TEXT = "Powered by 𝐓𝐡𝐞𝐨𝐥𝐨𝐠𝐢𝐜𝐚𝐥 𝐃𝐢𝐬𝐜𝐨𝐮𝐫𝐬𝐞🎙"
DESC_LIMIT  = 4096   # Discord embed description max
FIELD_LIMIT = 1024   # Discord embed field value max


# ── Helpers ───────────────────────────────────────────────────────────────────

def _truncate(text: str, limit: int) -> str:
    """
    Trim *text* to *limit* characters, cutting at the last paragraph or
    sentence boundary so the answer doesn't end mid-word.
    """
    if len(text) <= limit:
        return text
    cut = text[:limit - 30]
    for sep in ("\n\n", "\n", ". ", " "):
        pos = cut.rfind(sep)
        if pos > limit // 2:
            cut = cut[:pos]
            break
    return cut + "\n\n*…(answer truncated)*"


def _role_ids(member: discord.Member) -> set[int]:
    return {r.id for r in member.roles}


def _check_ask_access(interaction: discord.Interaction) -> tuple[bool, str]:
    """
    Returns (allowed, error_message).

    COD_ID          → allowed in any channel
    LIBRARY_PASS_ID → allowed only in LIBRARY_CHANNEL_ID
    Neither         → denied
    """
    roles = _role_ids(interaction.user)

    if COD_ID in roles:
        return True, ""

    if LIBRARY_PASS_ID in roles:
        if interaction.channel_id == LIBRARY_CHANNEL_ID:
            return True, ""
        return False, f"❌ You can only use `/ask` in <#{LIBRARY_CHANNEL_ID}>."

    return False, "❌ You don't have permission to use this command."


def _is_admin(member: discord.Member) -> bool:
    return ADMIN_ROLE_ID in _role_ids(member)


# ── /ask ─────────────────────────────────────────────────────────────────────

#--temporary--------------------------------------------

@tree.command(name="debug-db", description="Debug DB and index state", guild=GUILD_OBJ)
async def debug_db_command(interaction: discord.Interaction, query: str):
    if not _is_admin(interaction.user):
        await interaction.response.send_message("❌ No permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)

    import sqlite3
    from config import DB_PATH

    with sqlite3.connect(DB_PATH) as conn:
        # Total chunks in DB
        total = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

        # Sample chunks matching the query word
        rows = conn.execute(
            "SELECT id, thread_name, text FROM chunks WHERE text LIKE ? OR thread_name LIKE ? LIMIT 5",
            (f"%{query}%", f"%{query}%")
        ).fetchall()

    result = f"**Total chunks in DB:** {total}\n\n"
    result += f"**DB rows matching '{query}':** {len(rows)}\n"
    for r in rows:
        result += f"\n`{r[0]}` | {r[1]}\n> {r[2][:100]}…\n"

    await interaction.followup.send(result[:1900], ephemeral=True)

#--temporaryend-----------------------------------------

@tree.command(
    name        = "ask",
    description = "Search the THxD library for an answer",
    guild       = GUILD_OBJ,
)
@app_commands.describe(question="Your question")
async def ask_command(interaction: discord.Interaction, question: str):
    # DEBUG: if this line never appears for a COD member in a "broken" channel,
    # Discord is blocking the interaction before it reaches this handler
    # (check Server Settings → Integrations → per-command channel restrictions).
    # If it appears but nothing follows, the bug is in search/llm, not here.
    print(
        f"[DEBUG] /ask by {interaction.user} "
        f"(roles={[r.id for r in interaction.user.roles]}) "
        f"in channel {interaction.channel_id}",
        flush=True,
    )

    allowed, reason = _check_ask_access(interaction)
    if not allowed:
        await interaction.response.send_message(reason, ephemeral=True)
        return

    await interaction.response.defer(thinking=True)

    if await asyncio.to_thread(is_index_empty):
        await interaction.followup.send(
            "⚠️ Library index is empty. An admin needs to run `/reindex` first.",
            ephemeral=True,
        )
        return

    try:
        hits, _name_match = await asyncio.to_thread(search_prioritized, question)
        print(f"[DEBUG] search hits for '{question}': {len(hits)} — {[h['thread_name'] for h in hits[:3]]}", flush=True)

        # ── No results ────────────────────────────────────────────────────────
        if not hits:
            embed = discord.Embed(
                description="There is no information about this in the library.",
                color=0x808080,
            )
            embed.set_footer(text=FOOTER_TEXT)
            await interaction.followup.send(embed=embed)
            return

        # ── Generate cited answer ─────────────────────────────────────────────
        answer = await asyncio.to_thread(ask_library, question, hits)

        embed = discord.Embed(
            title       = f"📖  {question[:200]}",
            description = _truncate(answer, DESC_LIMIT),
            color       = 0x1B6B45,
        )

        # Deduplicate sources by URL
        seen_urls:      set[str]   = set()
        unique_sources: list[dict] = []
        for h in hits:
            if h["thread_url"] not in seen_urls:
                seen_urls.add(h["thread_url"])
                unique_sources.append(h)

        if unique_sources:
            sources_text = "\n".join(
                f"[{h['thread_name']}]({h['thread_url']})"
                for h in unique_sources
            )
            embed.add_field(
                name   = "📚 Sources",
                value  = _truncate(sources_text, FIELD_LIMIT),
                inline = False,
            )

        embed.set_footer(text=FOOTER_TEXT)
        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"❌ Error: `{e}`", ephemeral=True)
        raise


# ── /reindex ──────────────────────────────────────────────────────────────────

@tree.command(
    name        = "reindex",
    description = "Wipe and rebuild the entire library index (admin only)",
    guild       = GUILD_OBJ,
)
async def reindex_command(interaction: discord.Interaction):
    if not _is_admin(interaction.user):
        await interaction.response.send_message(
            "❌ You don't have permission to run this command.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        "⏳ Full re-index started… Progress is in the server console.\n"
        "For large libraries this takes over 15 min — check the console for completion.",
        ephemeral=True,
    )

    try:
        threads, chunks = await run_indexer(bot)
        msg = f"✅ Full reindex done — **{threads}** threads → **{chunks}** chunks."
        print(f"[Reindex] {msg}")
        try:
            await interaction.followup.send(msg, ephemeral=True)
        except discord.HTTPException:
            print("[Reindex] Token expired — result logged to console.")
    except Exception as e:
        print(f"[Reindex] ❌ Failed: {e}")
        try:
            await interaction.followup.send(f"❌ Failed: `{e}`", ephemeral=True)
        except discord.HTTPException:
            pass
        raise


# ── /reindex-new ──────────────────────────────────────────────────────────────

@tree.command(
    name        = "reindex-new",
    description = "Index only new threads added since last reindex (admin only)",
    guild       = GUILD_OBJ,
)
async def reindex_new_command(interaction: discord.Interaction):
    if not _is_admin(interaction.user):
        await interaction.response.send_message(
            "❌ You don't have permission to run this command.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        "⏳ Scanning for new threads… Check the console for progress.",
        ephemeral=True,
    )

    try:
        threads, chunks = await run_indexer_new(bot)
        msg = (
            f"✅ New-thread index done — **{threads}** new threads → **{chunks}** new chunks."
            if threads > 0
            else "✅ No new threads found — library is already up to date."
        )
        print(f"[Reindex-New] {msg}")
        try:
            await interaction.followup.send(msg, ephemeral=True)
        except discord.HTTPException:
            print("[Reindex-New] Token expired — result logged to console.")
    except Exception as e:
        print(f"[Reindex-New] ❌ Failed: {e}")
        try:
            await interaction.followup.send(f"❌ Failed: `{e}`", ephemeral=True)
        except discord.HTTPException:
            pass
        raise

# ── /reindex-thread ───────────────────────────────────────────────────────────

@tree.command(
    name        = "reindex-thread",
    description = "Index (or re-index) a single thread by its ID (admin only)",
    guild       = GUILD_OBJ,
)
@app_commands.describe(thread_id="The Discord thread ID to index")
async def reindex_thread_command(interaction: discord.Interaction, thread_id: str):
    if not _is_admin(interaction.user):
        await interaction.response.send_message(
            "❌ You don't have permission to run this command.", ephemeral=True
        )
        return

    # Validate that the input is actually a numeric snowflake
    try:
        tid = int(thread_id)
    except ValueError:
        await interaction.response.send_message(
            "❌ Invalid thread ID — must be a numeric Discord snowflake.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"⏳ Fetching thread `{tid}`…", ephemeral=True
    )

    # Resolve the channel object
    try:
        channel = await bot.fetch_channel(tid)
    except discord.NotFound:
        await interaction.followup.send(
            f"❌ No channel/thread found with ID `{tid}`.", ephemeral=True
        )
        return
    except discord.Forbidden:
        await interaction.followup.send(
            f"❌ Bot lacks permission to access thread `{tid}`.", ephemeral=True
        )
        return

    if not isinstance(channel, discord.Thread):
        await interaction.followup.send(
            f"❌ `{tid}` is a channel, not a thread.", ephemeral=True
        )
        return

    try:
        chunks = await run_indexer_thread(bot, channel)
        msg = (
            f"✅ Thread **{channel.name}** indexed — **{chunks}** chunk(s) stored."
            if chunks > 0
            else f"✅ Thread **{channel.name}** processed — no indexable content found."
        )
        print(f"[Reindex-Thread] {msg}")
        try:
            await interaction.followup.send(msg, ephemeral=True)
        except discord.HTTPException:
            print("[Reindex-Thread] Token expired — result logged to console.")
    except Exception as e:
        print(f"[Reindex-Thread] ❌ Failed: {e}")
        try:
            await interaction.followup.send(f"❌ Failed: `{e}`", ephemeral=True)
        except discord.HTTPException:
            pass
        raise


# ── Single-instance lock ──────────────────────────────────────────────────────
# Uses kernel-level flock() so the lock is tied to the open file descriptor,
# not a PID we store ourselves. If the process dies in any way — crash, OOM,
# forced redeploy — the kernel releases the lock automatically. This avoids
# the PID-file trap where PID 1 is always "alive" inside a container and a
# stale lock file permanently bricks every future restart.

_LOCK_FILE = "/tmp/library_bot.lock"
_lock_fd   = None   # kept open for the process lifetime — closing releases the lock


def _acquire_lock() -> None:
    """Exit immediately if another instance currently holds the lock."""
    global _lock_fd
    _lock_fd = open(_LOCK_FILE, "w")
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(
            "[Bot] ❌ Another instance is already running (lock held).\n"
            "[Bot]    Exiting to prevent double replies.",
            flush=True,
        )
        sys.exit(1)

    _lock_fd.write(str(os.getpid()))
    _lock_fd.flush()
    print(f"[Bot] 🔒 Lock acquired (PID {os.getpid()})", flush=True)


def _release_lock() -> None:
    global _lock_fd
    if _lock_fd is not None:
        with contextlib.suppress(Exception):
            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            _lock_fd.close()
        _lock_fd = None
    with contextlib.suppress(FileNotFoundError):
        os.remove(_LOCK_FILE)


atexit.register(_release_lock)   # clean exit; kernel handles unclean exits


# ── Startup ───────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    # Graceful SIGTERM / SIGINT so the bot disconnects before releasing the
    # lock and allowing the new container instance to start.
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):   # not supported on Windows
            loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.close()))

    # Ensure no stale global commands fire alongside guild commands
    # (would cause every interaction to fire twice).
    tree.clear_commands(guild=None)
    await tree.sync(guild=None)       # push empty set → removes all global cmds
    await tree.sync(guild=GUILD_OBJ)  # register commands for this guild only

    await asyncio.to_thread(build_index)

    print(f"[Bot] ✅ Logged in as {bot.user}")
    print(f"[Bot] Slash commands synced to guild {GUILD_ID}")
    print(f"[Bot] Ready.")


if __name__ == "__main__":
    _acquire_lock()
    try:
        bot.run(DISCORD_TOKEN)
    finally:
        _release_lock()