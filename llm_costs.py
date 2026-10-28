"""What one request cost in provider fees, in US dollars (FASTAPI-TEXT2SQL-337).

The response already reported the tokens of every LLM task (`llm_usage`, FASTAPI-TEXT2SQL-296),
but turning tokens into money was left to whoever read them, with a price table copied into
each analysis script. This module is that table, kept once, and the arithmetic that goes with
it, so that every response, every log file and every campaign carries its own cost.

The figure is a list-price ESTIMATE, not an invoice line: the bill stays the reference, and
the evaluator's campaigns are what check the two agree (Sol within 1.4 % on 2026-10-03, Opus
within 0.6 % on 2026-10-10). Three rules:

- **Unknown is not zero.** A model missing from PRICES gets `cost_usd: None` on its task and
  is named in `unpriced_models`; the request total then covers the priced tasks only, and says
  so. A guessed price would be worse than a hole, because nothing downstream would show it.
- **Flex is half price, and only when every call of the task was served Flex.** A task whose
  calls mixed tiers (`service_tier` = "flex,default") is priced at the standard tier: the
  accumulator sums the calls, so the split is lost, and the higher figure is the safe one.
- **Change a price here, with its source and date.** A restart applies it; nothing is cached.
"""
from typing import Optional

# US dollars per MILLION tokens, standard tier, prompts under 272K tokens (all of ours: the
# largest, text2sql on Opus, is about 55K). Keys are matched on the model name as the pipeline
# normalizes it, longest prefix first, so "gpt-6.1-sol" never falls into "gpt-6-sol"'s row.
# Sources, checked 2026-10-21: openai.com/api/pricing as reported by morphllm.com and
# aipricing.guru (GPT-6 family, cache-write rates included), developers.openai.com model page
# (text-embedding-3-large), Anthropic's pricing page (Opus 5.5, 5-minute cache write). The
# gpt-6-sol cached rate ($0.20) was confirmed by the 2026-10-03 invoice to 1.4 %.
# gpt-6.1-terra (released 2026-10-26), added 2026-10-28 so a campaign on it is priced live:
# input, cached and output from OpenAI's launch page as quoted by eesel.ai and datacamp.com;
# cache write is the 30-minute retention rate ($2.50 for 12 hours), eesel.ai only.
PRICES = {
    "gpt-6.1-terra": {"input": 1.00, "cached": 0.05, "cache_write": 1.25, "output": 5.00},
    "gpt-6.1-sol": {"input": 2.00, "cached": 0.10, "cache_write": 2.50, "output": 10.00},
    "gpt-6-sol": {"input": 2.00, "cached": 0.20, "cache_write": 2.50, "output": 10.00},
    "gpt-6-luna": {"input": 0.10, "cached": 0.01, "cache_write": 0.125, "output": 0.50},
    "gpt-6-astra": {"input": 10.00, "cached": 1.00, "cache_write": 12.50, "output": 50.00},
    "gpt-4o-mini": {"input": 0.15, "cached": 0.075, "cache_write": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "cached": 1.25, "cache_write": 2.50, "output": 10.00},
    "claude-opus-5-5": {"input": 4.00, "cached": 0.20, "cache_write": 5.00, "output": 20.00},
    "text-embedding-3-large": {"input": 0.13, "cached": 0.13, "cache_write": 0.13, "output": 0.0},
}

# OpenAI Flex processing bills at Batch API rates: half the standard price on the GPT-6 line.
FLEX_FACTOR = 0.5

# The server, in euros excluding VAT (FASTAPI-TEXT2SQL-338). OVH VPS Elite 8-32-640
# (vps-adacb908.vps.ovh.net, 8 vCores, 32 GB, 640 GB), 93.50 € a month on the October 2026
# invoice, committed until 2028-06-01. A fixed cost: a call adds nothing to the bill until the
# server saturates, so a call's share is an ALLOCATION of a cost already paid, by the CPU
# seconds it occupied, priced at the capacity of an average month.
VPS_EUR_PER_MONTH = 93.50
VPS_VCORES = 8
EUR_PER_CPU_SECOND = VPS_EUR_PER_MONTH / (VPS_VCORES * 30.4375 * 86_400)

_PRICE_KEYS = sorted(PRICES, key=len, reverse=True)


def price_for(model: str) -> Optional[dict]:
    """Return the price row of `model` ($ per million tokens), None when it is not listed."""
    name = str(model or "").strip().lower()
    for key in _PRICE_KEYS:
        if name.startswith(key):
            return PRICES[key]
    return None


def task_cost_usd(entry: dict) -> Optional[float]:
    """Cost in dollars of one `llm_usage` entry, None when its model has no price.

    The entry follows OpenAI's convention, which the Anthropic and Gemini loggers also fill:
    prompt_tokens INCLUDES cached_tokens and cache_write_tokens, completion_tokens INCLUDES
    reasoning_tokens (billed at the output rate). An entry served by two models (the Gemini
    fallback chain, "a,b") cannot be split and is left unpriced.
    """
    model = str(entry.get("model") or "")
    if "," in model:
        return None
    price = price_for(model)
    if price is None:
        return None
    prompt = int(entry.get("prompt_tokens") or 0)
    cached = int(entry.get("cached_tokens") or 0)
    write = int(entry.get("cache_write_tokens") or 0)
    output = int(entry.get("completion_tokens") or 0)
    uncached = max(prompt - cached - write, 0)
    cost = (uncached * price["input"] + cached * price["cached"]
            + write * price["cache_write"] + output * price["output"]) / 1_000_000
    if str(entry.get("service_tier") or "") == "flex":
        cost *= FLEX_FACTOR
    return cost


def server_cost_eur(cpu_time, sql_time=0.0, chroma_time=0.0) -> Optional[float]:
    """The server's share of a request in euros: its CPU seconds at EUR_PER_CPU_SECOND.

    cpu_time is the API process; sql_time and chroma_time stand in for MariaDB and ChromaDB,
    which run in other containers and whose own CPU the API cannot read (an upper bound: see
    logs.server_usage). None when the request clock did not run.
    """
    if not isinstance(cpu_time, (int, float)):
        return None
    return (cpu_time + (sql_time or 0.0) + (chroma_time or 0.0)) * EUR_PER_CPU_SECOND


def request_cost(llm_usage: Optional[dict], embedding_usage: Optional[dict]) -> Optional[dict]:
    """Price a request: cost_usd added to each task entry, and the request summary.

    Returns None when nothing was called (a cache hit costs no tokens: its summary would be
    all zeros and would be read as "measured free" in places where None means "no call").
    The summary is {"total_usd", "llm_usd", "embeddings_usd", "unpriced_models"}.
    Mutates the entries of `llm_usage` (a snapshot copy) by adding their "cost_usd".
    """
    if not llm_usage and not embedding_usage:
        return None
    unpriced = []
    llm_total = 0.0
    for entry in (llm_usage or {}).values():
        cost = task_cost_usd(entry)
        entry["cost_usd"] = cost
        if cost is None:
            unpriced.append(str(entry.get("model")))
        else:
            llm_total += cost
    embeddings_total = 0.0
    if embedding_usage:
        cost = task_cost_usd(embedding_usage)
        embedding_usage["cost_usd"] = cost
        if cost is None:
            unpriced.append(str(embedding_usage.get("model")))
        else:
            embeddings_total = cost
    return {
        "total_usd": llm_total + embeddings_total,
        "llm_usd": llm_total,
        "embeddings_usd": embeddings_total,
        "unpriced_models": sorted(set(unpriced)),
    }
