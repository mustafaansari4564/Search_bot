import os
from dotenv import load_dotenv
load_dotenv()

# ── Discord ────────────────────────────────────────────────────────────────────
DISCORD_TOKEN      = os.getenv("DISCORD_TOKEN")
GUILD_ID           = int(os.getenv("GUILD_ID", "0"))
ADMIN_ROLE_ID      = int(os.getenv("ADMIN_ROLE_ID", "0"))   # can run /reindex
COD_ID             = int(os.getenv("COD_ID", "0"))           # can /ask anywhere
LIBRARY_PASS_ID    = int(os.getenv("LIBRARY_PASS_ID", "0")) # can /ask in specific channel only
LIBRARY_CHANNEL_ID = int(os.getenv("LIBRARY_CHANNEL_ID", "0")) # channel for LIBRARY_PASS_ID

# ── LLM — OpenRouter only ──────────────────────────────────────────────────────
LLM_MAX_TOKENS = 1500

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# "openrouter/auto" is OpenRouter's built-in router — it automatically picks
# a currently-live model for you, so no manual fallback list is needed.
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/auto")

# ── Storage ────────────────────────────────────────────────────────────────────
DB_PATH = "./library.db"     # SQLite — persists between restarts

# ── Search ─────────────────────────────────────────────────────────────────────
TOP_K         = 5    # chunks returned per query
CHUNK_SIZE    = 800  # max chars per chunk
CHUNK_OVERLAP = 100  # overlap between chunks of the same thread

# ── Library category IDs ───────────────────────────────────────────────────────
LIBRARY_CATEGORY_IDS: list[int] = [
    1406552157003583509,   # general_library
    1497873349416849459,   # philosophy
    1497870596439281725,   # historical_library
    1479351372309594203,   # hinduism_library
    1498634482771820545,   # judeo-christ
    1479349422503755906,   # islamic_lib
]

# ── Optional: skip specific channels inside those categories ───────────────────
SKIP_CHANNEL_IDS: list[int] = [
    1456869427093049467,
    1456893368746381466,
]