# data/ : the hot-reloaded prompts and configuration

## Role

The six files an LLM call actually reads. Each is registered in `data_watcher` by the module
that consumes it, reloaded within about 5 seconds of an mtime change, and **sent to a provider
on every request that uses it**.

That last point is why this file exists. A note addressed to a human or to a coding agent, put
inside a prompt, is paid for on every call and read by the model as if it were an instruction.
So the notes live here, and the prompts stay addressed to the model alone.

| File | Loaded by | What it MUST keep |
|---|---|---|
| `text_to_sql.md` | [text2sql.py](../text2sql.py) | `{user_question}`, `{ui_language}`, `<!--CACHE_BOUNDARY-->` |
| `complex_question.md` | [text2sql.py](../text2sql.py) | `{user_question}`, `<!--CACHE_BOUNDARY-->` |
| `vision_identification.md` | [text2sql.py](../text2sql.py) | `{user_question}`, `{ui_language}`, `<!--CACHE_BOUNDARY-->` |
| `entity_extraction.md` | [entity.py](../entity.py) | `{user_question}`, `<!--CACHE_BOUNDARY-->` |
| `entity_resolution.json` | [entity.py](../entity.py) | the schema documented in [../AGENTS.md](../AGENTS.md) |
| `closed_vocabularies.json` | [closed_vocab.py](../closed_vocab.py) | the alias dictionaries keyed by placeholder prefix |

A placeholder dropped by accident does not raise: the substitution simply finds nothing, and
the model answers a prompt with a hole in it. `<!--CACHE_BOUNDARY-->` marks the end of the
byte-stable prefix and is where the Anthropic cache breakpoint is placed; everything after it
is the per-request part, so it stays last.

## The twinned rules of `complex_question.md` and `vision_identification.md`

**Three rules exist in both files, and they must NOT be made identical.** They share a motive
and nothing else, because the two tasks fill opposite fields: the complex-question resolver
emits a `question` (its `items` are optional metadata), while the vision task emits `items` and
**never** a question, the composition being done in code so that a cached identification and a
fresh one produce the same question (FASTAPI-TEXT2SQL-114, see *The vision pre-stage* in
[../AGENTS.md](../AGENTS.md)).

| Rule | Shared | Why the wording must differ |
|---|---|---|
| A relation question is not an identity lookup | The motive: flattening `In which city does the action of Pulp Fiction take place?` into `Movie Pulp Fiction (1994)` returns the film and answers nothing (defect **-263**) | `complex_question` says *keep the interrogative in the `question` you emit*. Vision says *do not answer it yourself, set `about_image: false`, the application keeps the question*. Vision has no `question` field to keep an interrogative in |
| The credited name, never the alias | The principle, and the confidence guard that outranks it | `complex_question` requires the canonical name in **both** `question` and the item's `value`; one of those fields does not exist in vision. The examples change modality (a typed birth name against a Polish poster or a recognised face), and vision has a third way out, `confidence`, which the other does not |
| A franchise is never enumerated | The principle, almost word for word: return the collection, the catalogue holds the authoritative member list, strip the generic words | The instruction is **inverted**. `complex_question`: emit a `Collection X` question and *keep `items` empty*. Vision: emit a *single item* of type `collection`. Each fills the field the other must leave empty |

**Measured on 2026-09-20**, the confidence guard is the closest the two ever get: 72 % of words
in common, and the divergence sits in every clause that carries weight (*the input* against
*the image* designates, *leave the name unchanged* against *return no item at all*, *turns an
empty result* against *turns an "I do not know"* into a plausible wrong answer). Sharing that
text would mean writing it at the level where both are true, which means dropping the field
names and the examples: exactly the shape this repository already measured as losing, in
FASTAPI-TEXT2SQL-255, where a rule stated once in the spec lost to the shape demonstrated by
the examples.

**The one divergence that would be dangerous, and the reason for this section.** Weakening the
confidence guard in one file and not the other does not break anything visibly: it produces a
confidently wrong entity on one path only, which is the single failure both prompts exist to
prevent. So when you touch a guard, a rule about aliases, or a rule about franchises in one of
these two files, **go and read the twin**, decide explicitly whether it moves too, and say so
in the commit message. They are meant to agree on the principle and to disagree on the
instruction.

## Three things that bite when editing anything here

**A change is live in about 5 seconds, and a cache row can hide it.** No restart is needed, but
lookups in `T_WC_T2S_CACHE` are scoped by API version: a question already answered under the
current version keeps serving its stored SQL until the version is bumped or the row is retired.
The same holds for the vision recognition cache, `T_WC_T2S_VISION_CACHE`, scoped the same way.
See *Version management workflow* in [../AGENTS.md](../AGENTS.md), and say so when you ship a
prompt change without a bump.

**A missing file kills the container at boot.** `data_watcher.register()` reads each file
eagerly at import time and raises if one is absent, so renaming a file here without changing
the module that registers it does not degrade, it stops the API from starting.

**Keep everything UTF-8.** These files carry non-ASCII titles, names and multilingual examples.
An editor or a terminal that rewrites them in another encoding turns them into mojibake that
the model then reads as content.
