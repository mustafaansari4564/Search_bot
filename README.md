# 🤖 Search Bot

A Discord bot that **indexes your server threads and answers questions about it** using AI, backed by a fast BM25 + SQLite search engine.

---

## ✨ Features

- 🔍 **Full-Text Search** — BM25-style indexed search across forum threads
- 🌐 **Multilingual** — Supports multiple scripts, including Devanagari
- 🧵 **Thread + Title Indexing** — Indexes both thread bodies and thread names/titles
- 🃏 **Embed-Aware** — Extracts and indexes fields from translation-bot embed cards, so translated content is searchable too
- 🤖 **AI-Powered Answers** — Answers questions using an LLM grounded on your indexed content, with a model fallback chain (free models tried first)

---

## 🚀 Commands

| Command | Description |
|---|---|
| `/ask <question>` | Ask a question, answered using indexed content + AI |
| `/reindex` | Full reindex of the library |
| `/reindex-new` | Index only new content since the last run |
| `/reindex-thread <thread>` | Reindex a single specific thread |

---

## 🛠️ Tech Stack

| Service | Purpose |
|---|---|
| [discord.py](https://discordpy.readthedocs.io/) | Discord bot framework |
| SQLite + BM25 | Search indexing and scoring |
| [OpenRouter](https://openrouter.ai/) | AI-powered answers (16-model fallback chain) |
| [python-dotenv](https://pypi.org/project/python-dotenv/) | Environment variable management |
---

## 📋 Prerequisites

- Python 3.11+
- Discord Bot Token
- OpenRouter API Key (free at [openrouter.ai](https://openrouter.ai))

---

## ⚙️ Installation & Setup

### 1. Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
cd YOUR_REPO_NAME
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Create `.env` file
```env
DISCORD_TOKEN=Your discord token
GUILD_ID=your guild id here
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your openrouter API key

COD_ID=That id which can access the bot throughout the server
LIBRARY_PASS_ID=those members id who can acess this bot in a specific channel
LIBRARY_CHANNEL_ID=Specific channel id
ADMIN_ROLE_ID=That id which can run command reindex, reindex-new
```

### 4. Run the bot
```bash
python start.py
```

---

## 📁 Project Structure

```
library-search-bot/
├── README.md          # Project documentation
├── start.py           # Entry point for running the bot
├── bot.py             # Discord bot events and command handling
├── config.py          # Environment variables and configuration
├── database.py        # Database connection and helper functions
├── indexer.py         # Builds and updates the document index
├── llm.py             # LLM/OpenRouter interaction layer
├── search.py          # Search and retrieval logic
└── requirements.txt   # Python dependencies
```

---

## 🔑 Getting API Keys

### Discord Bot Token
1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Create new application → Bot → Reset Token
3. Enable **Message Content Intent**

### OpenRouter API Key (Free)
1. Go to [openrouter.ai](https://openrouter.ai)
2. Sign up → Keys → Create Key
- The bot tries free models first, falling back through a chain of 16 models

---

## 🤝 Invite Bot to Your Server

Generate an invite link:
1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. OAuth2 → URL Generator
3. Select `bot` and `applications.commands` scopes
4. Select permissions: `Read Messages`, `Send Messages`, `Read Message History`, `Use Slash Commands`
5. Copy and share the generated URL

---

## 📝 Example Usage

```
User: /ask what does the library say about X?
Bot: 📚 Based on indexed threads: [AI-generated answer grounded in your forum content]
```

## ⚠️ Important Notes

- Run `/reindex` after adding new forum channels for the first time


---

## Contributing

Contributions, feature requests, and bug reports are welcome.

Feel free to fork the repository and submit a pull request.

---

⭐ If this project helped you, consider giving it a star on GitHub!
