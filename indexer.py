"""
indexer.py — Crawls Discord library and saves chunks to SQLite.
No embedding API. No ChromaDB. Just text + metadata saved locally.

Can be used two ways:
  1. Imported by bot.py — run_indexer(bot) / run_indexer_new(bot) are called
     with the bot's already-logged-in discord.Client, triggered by /reindex
     and /reindex-new slash commands.
  2. Run standalone — `python indexer.py` logs into Discord itself, runs a
     full reindex, then exits. Used by start.py on first deploy when
     library.db doesn't exist yet.
"""

import asyncio
import discord

from database import init_db, clear_db, save_chunks, save_chunks_append, get_indexed_thread_ids, delete_thread_chunks
from search   import build_index, invalidate_index
from config   import (
    GUILD_ID, CHUNK_SIZE, CHUNK_OVERLAP,
    LIBRARY_CATEGORY_IDS, SKIP_CHANNEL_IDS,
)


# ── Chunking ───────────────────────────────────────────────────────────────────

def chunk_text(text: str) -> list[str]:
    if len(text) <= CHUNK_SIZE:
        return [text.strip()]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return [c for c in chunks if c]


# ── Discord helpers ────────────────────────────────────────────────────────────

async def get_all_threads(channel: discord.TextChannel) -> list[discord.Thread]:
    threads = list(channel.threads)
    try:
        async for t in channel.archived_threads(limit=None):
            threads.append(t)
    except discord.Forbidden:
        print(f"    [!] No permission to read archived threads in #{channel.name}")
    except Exception as e:
        print(f"    [!] Archived threads error in #{channel.name}: {e}")
    return threads

#---scrape_thread----------------------------------------------------------------------------------
async def scrape_thread(thread: discord.Thread, guild_id: int) -> dict | None:
    messages = []
    embed_count = 0
    try:
        async for msg in thread.history(limit=None, oldest_first=True):
            parts = []

            if msg.content and not msg.author.bot:
                parts.append(msg.content.strip())

            for embed in msg.embeds:
                embed_count += 1
                if embed.title:
                    parts.append(embed.title.strip())
                if embed.description:
                    parts.append(embed.description.strip())
                for field in embed.fields:
                    if field.name:
                        parts.append(field.name.strip())
                    if field.value:
                        parts.append(field.value.strip())

            if parts:
                messages.append("\n".join(parts))

        await asyncio.sleep(0.3)
    except discord.Forbidden:
        print(f"    [!] No permission to read: {thread.name}")
        return None
    except Exception as e:
        print(f"    [!] Error reading '{thread.name}': {e}")
        return None

    if not messages:
        return None

    print(f'    [Thread] "{thread.name}" → {len(messages)} messages, {embed_count} embeds')
    return {
        "text":        "\n\n".join(messages),
        "thread_name": thread.name,
        "thread_url":  f"https://discord.com/channels/{guild_id}/{thread.id}",
    }
# ── Main indexer ───────────────────────────────────────────────────────────────

async def run_indexer(bot: discord.Client) -> tuple[int, int]:
    """
    Crawl the library and rebuild the SQLite + BM25 index from scratch.
    Returns (total_threads, total_chunks).
    """
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        raise RuntimeError(f"Guild {GUILD_ID} not found. Is the bot in the server?")

    if not LIBRARY_CATEGORY_IDS:
        print("[Indexer] ⚠️  LIBRARY_CATEGORY_IDS is empty in config.py")
        return 0, 0

    # Prepare DB and clear stale data
    await asyncio.to_thread(init_db)
    await asyncio.to_thread(clear_db)
    await asyncio.to_thread(invalidate_index)   # clear BM25 cache

    target_categories = [c for c in guild.categories if c.id in LIBRARY_CATEGORY_IDS]

    # Warn about IDs not found
    found = {c.id for c in target_categories}
    for cid in LIBRARY_CATEGORY_IDS:
        if cid not in found:
            print(f"[Indexer] ⚠️  Category ID {cid} not found in server.")

    all_chunks:    list[dict] = []
    total_threads: int        = 0

    for category in target_categories:
        print(f"\n[Category] {category.name}")

        for channel in category.channels:
            # Handle both regular TextChannels (with threads) and
            # ForumChannels (where every post is a thread).
            # VoiceChannels, StageChannels etc. are skipped.
            if not isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
                continue
            if channel.id in SKIP_CHANNEL_IDS:
                continue

            perms = channel.permissions_for(guild.me)
            if not (perms.read_messages and perms.read_message_history):
                print(f"  [Skip] #{channel.name} — no read permission")
                continue

            print(f"  [Channel] #{channel.name}")
            threads = await get_all_threads(channel)

            if not threads:
                print("    (no threads)")
                continue

            for thread in threads:
                data = await scrape_thread(thread, GUILD_ID)
                if not data:
                    continue

                chunks = chunk_text(data["text"])
                print(f'    [Thread] "{data["thread_name"]}" → {len(chunks)} chunk(s)')

                for i, chunk in enumerate(chunks):
                    all_chunks.append({
                        "id":          f"{thread.id}_{i}",
                        "text":        chunk,
                        "thread_name": data["thread_name"],
                        "thread_url":  data["thread_url"],
                        "category":    category.name,
                        "channel":     channel.name,
                    })

                total_threads += 1

    # Save everything to SQLite in one shot
    await asyncio.to_thread(save_chunks, all_chunks)
    total_chunks = len(all_chunks)

    # Rebuild BM25 index from the freshly saved data
    await asyncio.to_thread(build_index)

    print(f"\n[Indexer] ✅ Done — {total_threads} threads → {total_chunks} chunks.")
    return total_threads, total_chunks


# ── Incremental indexer (new threads only) ────────────────────────────────────

async def run_indexer_new(bot: discord.Client) -> tuple[int, int]:
    """
    Only indexes threads that are NOT already in the database.
    Existing threads are untouched — much faster than a full reindex.
    Returns (new_threads_indexed, new_chunks_added).
    """
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        raise RuntimeError(f"Guild {GUILD_ID} not found.")

    if not LIBRARY_CATEGORY_IDS:
        print("[Indexer-New] ⚠️  LIBRARY_CATEGORY_IDS is empty in config.py")
        return 0, 0

    await asyncio.to_thread(init_db)

    # Load IDs of threads already in the DB so we can skip them
    existing_ids = await asyncio.to_thread(get_indexed_thread_ids)
    print(f"[Indexer-New] {len(existing_ids)} threads already indexed — scanning for new ones…")

    target_categories = [c for c in guild.categories if c.id in LIBRARY_CATEGORY_IDS]

    new_chunks:    list[dict] = []
    total_threads: int        = 0

    for category in target_categories:
        print(f"\n[Category] {category.name}")

        for channel in category.channels:
            if not isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
                continue
            if channel.id in SKIP_CHANNEL_IDS:
                continue

            perms = channel.permissions_for(guild.me)
            if not (perms.read_messages and perms.read_message_history):
                continue

            threads = await get_all_threads(channel)

            for thread in threads:
                # Skip threads already indexed
                if str(thread.id) in existing_ids:
                    continue

                data = await scrape_thread(thread, GUILD_ID)
                if not data:
                    continue

                chunks = chunk_text(data["text"])
                print(f'  [New] #{channel.name} → "{data["thread_name"]}" → {len(chunks)} chunk(s)')

                for i, chunk in enumerate(chunks):
                    new_chunks.append({
                        "id":          f"{thread.id}_{i}",
                        "text":        chunk,
                        "thread_name": data["thread_name"],
                        "thread_url":  data["thread_url"],
                        "category":    category.name,
                        "channel":     channel.name,
                    })

                total_threads += 1

    if new_chunks:
        # Append without touching existing chunks
        await asyncio.to_thread(save_chunks_append, new_chunks)
        # Rebuild index to include the new chunks
        await asyncio.to_thread(build_index)
        print(f"\n[Indexer-New] ✅ Added {total_threads} new threads → {len(new_chunks)} new chunks.")
    else:
        print("\n[Indexer-New] ✅ No new threads found.")

    return total_threads, len(new_chunks)

#--reindex specific thread---------------------------------------------------

async def run_indexer_thread(bot: discord.Client, thread: discord.Thread) -> int:
    await asyncio.to_thread(init_db)

    data = await scrape_thread(thread, thread.guild.id)
    if not data:
        return 0

    chunks = chunk_text(data["text"])
    if not chunks:
        return 0

    parent        = thread.parent
    channel_name  = parent.name if parent else "unknown"
    category_name = parent.category.name if (parent and parent.category) else "unknown"

    chunk_dicts = [
        {
            "id":          f"{thread.id}_{i}",
            "text":        chunk,
            "thread_name": data["thread_name"],
            "thread_url":  data["thread_url"],
            "category":    category_name,
            "channel":     channel_name,
        }
        for i, chunk in enumerate(chunks)
    ]

    await asyncio.to_thread(delete_thread_chunks, str(thread.id))
    await asyncio.to_thread(save_chunks_append, chunk_dicts)

    # Must invalidate first — build_index skips rebuilding if index is already loaded
    await asyncio.to_thread(invalidate_index)
    await asyncio.to_thread(build_index)

    print(f'[Reindex-Thread] "{data["thread_name"]}" → {len(chunk_dicts)} chunk(s) stored.')
    return len(chunk_dicts)



# ── Standalone CLI runner ───────────────────────────────────────────────────────
# Lets `python indexer.py` log into Discord on its own, run a full reindex,
# print the result, and exit cleanly with a real exit code.
# This is what start.py invokes via subprocess on first deploy.

if __name__ == "__main__":
    import os as _os
    import sys

    # Force unbuffered output so logs show up immediately in KeritCloud,
    # even if this file is ever run directly without the -u flag.
    _os.environ.setdefault("PYTHONUNBUFFERED", "1")
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    from config import DISCORD_TOKEN

    if not DISCORD_TOKEN:
        print("[Indexer-CLI] ❌ DISCORD_TOKEN not set in environment.", flush=True)
        sys.exit(1)

    if not GUILD_ID:
        print("[Indexer-CLI] ❌ GUILD_ID not set in environment.", flush=True)
        sys.exit(1)

    _cli_intents = discord.Intents.default()
    _cli_intents.guilds = True
    _cli_intents.message_content = True   # needed to read thread message content

    _cli_client = discord.Client(intents=_cli_intents)
    _result = {"code": 1}   # mutable holder so on_ready can set the exit code

    @_cli_client.event
    async def on_ready():
        print(f"[Indexer-CLI] ✅ Logged in as {_cli_client.user}", flush=True)
        try:
            threads, chunks = await run_indexer(_cli_client)
            print(f"[Indexer-CLI] ✅ Done — {threads} threads → {chunks} chunks.", flush=True)
            _result["code"] = 0
        except Exception as e:
            print(f"[Indexer-CLI] ❌ Indexing failed: {e}", flush=True)
            _result["code"] = 1
        finally:
            # Close the client so client.run() returns control to us
            await _cli_client.close()

    print("[Indexer-CLI] Connecting to Discord…", flush=True)
    _cli_client.run(DISCORD_TOKEN, log_handler=None)

    # client.run() blocks until close() above is called, then returns here
    sys.exit(_result["code"])