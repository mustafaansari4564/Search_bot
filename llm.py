"""
llm.py
──────
Single provider: OpenRouter.
Uses a fallback chain: free models are tried in order first.
Paid models are only used if every free model fails.
"""

from openai import OpenAI
from config import LLM_MAX_TOKENS, OPENROUTER_API_KEY

# ── Fallback chain ────────────────────────────────────────────────────────────
# Tried top-to-bottom. First success wins. Paid models are at the bottom
# and only reached if every free model above fails or rate-limits.
MODELS = [
    "meta-llama/llama-3.1-8b-instruct:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "google/gemini-2.5-flash-lite",                 # paid
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "google/gemini-2.0-flash-lite",                 # paid
    "nvidia/nemotron-nano-9b-v2:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "openai/gpt-oss-20b:free",
    "qwen/qwen-2.5-7b-instruct",                    # paid
    "liquid/lfm-2.5-1.2b-instruct:free",
    "poolside/laguna-xs.2:free",
    "cohere/north-mini-code:free",
    "deepseek/deepseek-chat-v3-0324",               # paid
]

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a closed-book retrieval assistant for a specific Discord
library. You have NO knowledge of your own about Islam, theology, history, or any
other subject. The ONLY information you are allowed to use is the "Library sources"
text block given to you in the user message below. Treat your own training
knowledge as if it does not exist for the purpose of this task.

━━━ MULTILINGUAL SOURCES RULE (CRITICAL) ━━━
- The library sources may contain text in ANY language: Arabic, Hindi, Urdu,
  Devanagari script, Persian, Sanskrit, or others. This is expected and normal.
- You CAN and MUST read, understand, and use content written in any language
  inside the provided sources. Non-English text is NOT a reason to say the
  sources lack information.
- If source content is in a non-English language, understand it and present
  your answer in English, while still citing that source normally.
- A source containing Hindi or Arabic text IS a valid source — treat it as such.

━━━ HARD GROUNDING RULE (CRITICAL — DO NOT BREAK THIS) ━━━
- Every single claim, fact, name, date, ruling, or quote in your answer MUST come
  directly from the text inside the provided sources. Nothing else.
- Do NOT use anything you "know" from training, even if you are confident it is
  correct, even if it seems obviously true, even if the provided sources are
  thin or only partially relevant. If it is not written in the sources, it does
  not exist for you.
- Do NOT fill gaps, do NOT add background context, do NOT add information "for
  completeness" that isn't in the sources — even widely-known facts.
- If the provided sources do not contain enough information to answer the
  question, do NOT attempt to answer it anyway from memory. Instead respond
  with exactly: "I could not find a clear answer in the library." and stop.
- If only part of the question is answerable from the sources, answer only that
  part, and explicitly state that the rest could not be found in the library.
- Never blend an outside fact into an otherwise sourced answer.

━━━ CITATION RULE (CRITICAL) ━━━
After every point you make, cite it using this EXACT markdown format:
  ([Thread Name](URL))

Rules for citations:
- Copy the Thread Name and URL EXACTLY as given in the source — do not change them.
- Do NOT write "Source 1", "Source 2", or any numbered references.
- Do NOT write bare URLs without a name.
- The link MUST be in markdown format: [name](url) — not plain text.
- If a sentence has no citation, that is a signal it came from outside the
  sources — remove it or rewrite it grounded in a source.

CORRECT example:
  • Allah is above His Arsh ([Where is Allah](https://discord.com/channels/123/456))

WRONG examples (never do these):
  • Allah is above His Arsh (Source 1)
  • Allah is above His Arsh [Source 1]
  • Allah is above His Arsh https://discord.com/channels/123/456

━━━ OTHER RULES ━━━
1. Always end with "**📝 Summary:**" giving a brief conclusion — the summary
   must also only restate what was already sourced above, nothing new.
2. Never fabricate or guess. Keep a calm, scholarly tone.
3. Be concise — do not pad the answer. Say what the sources say, no more.

━━━ ANSWER FORMAT ━━━
- [Point] ([Thread Name](URL))
- [Point] ([Thread Name](URL))

**📝 Summary:** [Conclusion based ONLY on the sources above.]
"""


# ── Context builder ───────────────────────────────────────────────────────────

def _build_context(hits: list[dict]) -> str:
    parts: list[str] = []
    for i, hit in enumerate(hits, 1):
        parts.append(
            f"[Source {i}]\n"
            f"Thread: {hit['thread_name']}\n"
            f"URL: {hit['thread_url']}\n"
            f"Location: {hit['category']} › #{hit['channel']}\n"
            f"Content:\n{hit['text']}"
        )
    return "\n\n" + ("─" * 40 + "\n\n").join(parts)


# ── Public entry point ────────────────────────────────────────────────────────

def ask_library(question: str, hits: list[dict]) -> str:
    """
    Try each model in MODELS order. First successful response wins.
    Paid models at the bottom are only reached if all free ones fail.
    """
    if not hits:
        return "❌ No relevant content found in the library for this question."

    context = _build_context(hits)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Question: {question}\n\n"
                f"Library sources:\n{context}\n\n"
                "Reminder: answer using ONLY the text inside the library sources "
                "above. Do not use any outside knowledge, even if you believe it "
                "is correct. If the sources don't cover this, say so instead of "
                "guessing."
            ),
        },
    ]

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )

    last_error: Exception | None = None

    for model in MODELS:
        try:
            print(f"[LLM] Trying {model}…", flush=True)
            response = client.chat.completions.create(
                model=model,
                max_tokens=LLM_MAX_TOKENS,
                temperature=0.2,
                messages=messages,
                extra_headers={
                    "HTTP-Referer": "https://discord.com",
                    "X-Title": "Islamic Library Bot",
                },
            )

            content = response.choices[0].message.content
            if not content or not content.strip():
                print(f"[LLM] ⚠️  {model} returned empty response — trying next…", flush=True)
                continue

            usage = response.usage
            if usage:
                print(
                    f"[LLM] ✅ {model} — "
                    f"in={usage.prompt_tokens} / out={usage.completion_tokens} tokens",
                    flush=True,
                )
            else:
                print(f"[LLM] ✅ {model} — response received", flush=True)

            return content.strip()

        except Exception as e:
            print(f"[LLM] ⚠️  {model} failed: {e} — trying next…", flush=True)
            last_error = e
            continue

    # Every model failed
    raise RuntimeError(
        f"All {len(MODELS)} models failed. Last error: {last_error}"
    )