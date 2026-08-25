# Entity resolution thresholds: how each number was obtained

Reference for `min_fuzz_ratio` in [data/entity_resolution.json](../data/entity_resolution.json).
Written 2026-08-25, FASTAPI-TEXT2SQL-206. Read this before changing any threshold, and re-run the
bench rather than adjusting a value by intuition: every number here is the midpoint of a measured
interval, not a preference.

## 1. The problem these thresholds solve

Of the fourteen resolvers, **one** carried a rejection threshold before this work: `Collection_name`,
with `min_fuzz_ratio = 72`. The other thirteen had none, and an embeddings search always returns a
nearest neighbour: with no threshold it is accepted, however far it sits.

Measured in production on 2026-08-24 and 2026-08-25:

```
"Wagonlit collection"  -> "Life Collection"     accepted, three films returned
"Zamboni-Trask"        -> "Massimo Zamboni"     accepted, an invented person
"Star Wars"            -> "Leonard Maltin's Four Stars Movies"   accepted, as a list
"oscar"                -> "oz"                  accepted, as a topic
```

None of these produced any signal. A wrong answer stated with confidence is the failure mode that
nobody notices, which is what makes it worse than an empty one.

**The two errors do not cost the same, and that asymmetry decides the direction of the cursor.**
A false rejection degrades into a raw fallback, then an empty result, then the complex-question
retry (FASTAPI-TEXT2SQL-156): expensive in latency and tokens, but visible and caught. A false
acceptance produces a confidently wrong answer nobody sees. Prefer the strict side. The retry is
precisely what makes strictness affordable, and the two mechanisms are complements: while the
resolver could not fail, the retry had nothing to catch.

## 2. Why the corpus alone could not answer

Calibrating a threshold needs scores for matches that SHOULD pass and for matches that SHOULD NOT.
The first half comes from real usage. The second half **does not exist and cannot**: with no
threshold, everything resolved, so nothing was ever recorded as a rejection.

That is survivorship bias in its textbook form, the Wald aircraft problem: only the planes that
came back can be studied. The negative class therefore has to be **manufactured**, and the bench
does exactly that.

A second obstacle compounded it. The code computed a distance **only when a threshold was already
configured**, so the thirteen types needing one were the thirteen never measured. The measurement
was made unconditional first ([entity.py](../entity.py)), on both the embeddings and the rapidfuzz
paths, using `fuzz.ratio` on both sides so the two scales stay comparable.

## 3. The classes, in decreasing order of certainty

Produced by [eval/bench-entity-resolution.py](../eval/bench-entity-resolution.py).

| class | origin | ground truth |
|---|---|---|
| `positive-catalogue` | drawn from the resolver's own **ChromaDB collection** | strongest: such a value must resolve to itself |
| `positive-real` | pairs whose evaluation always scored 1 | the assertions, not the resolver |
| `positive-*-typo` | the above, mutated on purpose | holds by construction |
| `negative-cross` | a value of type A fed to the resolver of type B | non-membership, with the caveat in §5 |
| `negative-invent` | made-up names (the Zorglub family) | absolute |
| `observed-*` | values seen in the logs, never arbitrated | **none, and they are excluded from the arithmetic** |

**Typos are the class a threshold must never break**, since correcting them is what the resolver is
for. Mutation is one edit inside a word, never on the first character: a first-letter error is a
different problem, it defeats prefix indexes, and would muddy the measurement.

**`observed-*` is not a positive class, and that was a correction.** Counting log values as
legitimate dragged the recommended cut for `Collection_name` from 84.9 down to 45.5, because many
of those resolutions **are** the defect being hunted: "Collection Criterion" resolved to "Ex
Collection" at 18.2. The class is still produced, because its low tail is an excellent **detector**
of false acceptances already in production, but it calibrates nothing.

## 4. Data actually used

| source | volume | role |
|---|---|---|
| ChromaDB collections | 40 values per type | catalogue positives |
| `eval/data/evaluation_execution/` | 6 828 files, 1 202 scored pairs | assertion-arbitrated positives |
| VPS archived logs, both colours | 24 040 files, 3 404 distinct values | value pool, and negatives by cross injection |
| local `logs/` | 510 files | same |

The archive is harvested by
[eval/harvest-archived-entities.py](../eval/harvest-archived-entities.py) into a local cache, the
share reading at about 35 files per second. It lifted `Topic_name` from 48 to 236 values and
`Collection_name` from 36 to 128, and **did nothing for the tail, as it could not**: across those
24 040 requests `Network_name` shows seven distinct values, because nobody asks about a network by
name. The scarcity is in the usage, not in the sampling, which is why thin types are fed from the
catalogue instead.

**The catalogue is the collection, never the SQL table.** `Location_name` looks its rows up in
`T_WC_T2S_ITEM`, the whole Wikidata referential, while the `locations` collection is a subset
filtered elsewhere. Drawing from the table produced "-M- discography" and "...And Now Miguel" as
locations, none of which resolved, and made the resolver look broken when the bench was: its
catalogue positives sat at a median ratio of 38.3, against 100.0 once corrected.

## 5. Traps the measurement walked into, and how each is handled

Every one of these was found by the bench contradicting itself, not by reading the code.

**The indexed document is not the name.** Collections carrying `name + " : " + description` made
`fuzz.ratio` grade a perfect match at 2.3, "Blaxploitation" against "Blaxploitation: Here is the
list of...". 97% of `Death_name` candidates carry a description, 82% of `Nomination_name`, 81% of
`Award_name`. Descriptions **stay** in the embeddings, deliberately: they are what lets "crise
cardiaque" find "cardiac arrest". `document_name_separator` is declared per entity and only the
part before it is compared. Per entity and never globally, because a name can legitimately contain
a colon and blind splitting truncates "Star Trek: The Next Generation".

**A shared descriptor word inflates the similarity.** "wagonlit collection" against "life
collection" scores 76.5, "wagonlit" against "life" scores 33.3, and the threshold sat at 72.
`score_stopwords` neutralises the entity's own descriptors on both sides before scoring. It closes
both errors at once: the false positive falls from 76.5 to 33.3, and "star wars universe" against
"Star Wars Collection" rises from 57.9 to 100, where 57.9 sat below the threshold and would have
been refused.

**Cross injection is not a guaranteed negative.** A series title often has its collection, and
"Star Trek: The Next Generation" resolves to its collection quite correctly. Such a case is flagged
`contaminated` and dropped, on **equality** after descriptors are stripped, never on mere
inclusion: inclusion caught "suicide" against "Suicide Squad Collection", which is a genuine false
acceptance, not a legitimate one.

**Cross injection is also not always realistic.** "Roger Ebert list" and "Dziga Vertov Group" reach
the `List_name` and `Group_name` resolvers in production, never the person one, because entity
extraction types them first. Keeping them as negatives raised the `Person_name` interval from
66.7-87.5 to 81.5-87.5. Both give zero errors, so the retained value stays inside either, and
treating them as negatives simply errs on the strict side.

**A recommendation is an interval, not a point.** Classification only changes at observed values,
while a threshold is a real number. The optimal cut came out at 93.3 where anything above 76.5 did
just as well. The bench reports the range of equivalent thresholds and keeps its **midpoint**, the
point furthest from both distributions.

**Silence beats a number the data cannot support.** Below thirty measured positives on a field, no
recommendation is emitted. On `Collection_name`, 98 of 119 positives resolve through rapidfuzz and
carry no vector distance at all, and the 21 that do are precisely the ones rapidfuzz missed: a
sample both small and biased towards the hard cases, whose flattering cut means nothing.

## 6. Ratio, not distance, and it was measured

Total errors over the twelve embeddings types, at each metric's own optimum:

| gate | total errors |
|---|---|
| **`fuzz_ratio` alone** | **42** |
| vector `distance` alone | 94 |
| both conjoined | 35 |

The expectation was that the vector distance would separate better on the vector path. It is the
opposite, by more than double. The conjunction gains seven errors out of roughly 1 500 cases, at the
price of a second parameter per entity, and that gain concentrates on `Death_name` and
`Network_name` where the optimiser lowers the ratio sharply to let the distance work, which smells
of fitting the noise of a small sample.

**One parameter per entity, `min_fuzz_ratio`.** Simpler, decisively better than the distance, and
nearly as good as the pair.

## 7. The thresholds in force

Midpoint of the measured equivalence interval. "refused" counts legitimate matches turned away,
"admitted" counts strangers let through, both at that threshold on the bench population.

| entity | `min_fuzz_ratio` | refused / admitted | note |
|---|---|---|---|
| `Serie_title` | 87.85 | 4 / 1 | |
| `Movie_title` | 85.85 | 8 / 3 | |
| `Person_name` | 84.50 | 0 / 0 | perfect separation |
| `Person_name` (aliases) | 90.00 | not measured | **provisional**, see §8 |
| `Network_name` | 78.45 | 6 / 0 | |
| `Company_name` | 77.50 | 2 / 0 | |
| `Group_name` | 77.50 | 2 / 0 | |
| `Award_name` | 74.45 | 3 / 0 | |
| `Collection_name` | 72 | 1 / 3 | value already in service, kept |
| `Location_name` | 71.80 | 3 / 0 | |
| `Topic_name` | 69.10 | 1 / 3 | |
| `List_name` | 67.10 | 0 / 0 | wide interval, 46.7 to 87.5 |
| `Nomination_name` | 57.15 | 1 / 1 | |
| `Movement_name` | 56.10 | 0 / 0 | |
| `Death_name` | 54.05 | 4 / 0 | |

Titles demand the most, which follows: two films can carry nearly identical names. Causes of death
and movements settle for low thresholds because their vocabulary is short and distinctive.

`Collection_name` keeps 72 by decision, not by omission: the bench suggested 84.9, but on 40
positives of a single type, and 72 proved nearly optimal there (one error more than the best
possible over 89 cases). What that agreement validates is the **method** rather than the number,
since the bench rediscovers on its own the order of magnitude of a threshold chosen independently.

## 8. What remains open

**The alias table has never been measured.** `Person_name` declares two rapidfuzz strategies,
`T_WC_T2S_PERSON` restricted to the Latin language family, then
`T_WC_TMDB_PERSON_ALSO_KNOWN_AS` with no restriction. Without a threshold the first always
resolved, so the second was structurally **unreachable** for a Latin name and served only Arabic,
Thai or Korean ones. Opened to Latin names it used to produce perverse effects, "Bruce Lee" and
"Sid Vicious" resolving to wrong entities, which is why a threshold is the condition that makes it
usable at all. The expected gain is real: "Maurice Schérer" should find Éric Rohmer where the
persons table returns a wrong entity today.

Its 90.0 is **provisional and unmeasured**, set deliberately stricter because that table is the
noisier one. An exact normalized match always passes the gate regardless, so "Maurice Schérer"
keeps being served. Calibrating it needs a second bench run **after** this deployment, since a
strategy that cannot be reached cannot be measured. That two-stage sequence cannot be collapsed.

**`min_fuzz_ratio` was read only on the embeddings path** until 2026-08-25. Declaring it on a
rapidfuzz strategy did strictly nothing, which is why `Person_name` could never fail. The gate now
exists on both paths with identical semantics: an exact normalized match always passes, a rejection
falls through to the next strategy and, failing that, to the raw fallback.

**Two types still show real false acceptances in production**, and they are not artefacts:
`List_name` with 32 resolutions below 50 and `Topic_name` with 24. Their thresholds cut those, but
the `observed` tail is worth re-reading after deployment to confirm it.

## 9. Re-running the bench

Inside the API image, which is the only one carrying both the resolution stack and the bench.
`BKTREE_ENABLED=0` skips the BK-tree prebuild, which the twelve embeddings-only types never touch
and which costs 34 minutes for the 6 000 769-entry alias index alone.

```bash
# The twelve embeddings types
docker run -d --rm --network="host" \
  --env-file /home/debian/docker/fastapi-text2sql-blue/.env \
  -e BKTREE_ENABLED=0 \
  -v /home/debian/docker/fastapi-text2sql-blue:/app \
  --memory=6g --name t2s-bench \
  fastapi-text2sql-blue-app \
  python eval/bench-entity-resolution.py \
    --types Movie_title,Serie_title,Company_name,Network_name,Topic_name,List_name,Award_name,Nomination_name,Movement_name,Location_name,Group_name,Death_name \
    --catalogue-per-type 40 --out eval/data/bench-embeddings.json

# Person_name, which needs its BK-trees
docker run -d --rm --network="host" \
  --env-file /home/debian/docker/fastapi-text2sql-blue/.env \
  -v /home/debian/docker/fastapi-text2sql-blue:/app \
  --memory=6g --name t2s-bench \
  fastapi-text2sql-blue-app \
  python eval/bench-entity-resolution.py --types Person_name \
    --catalogue-per-type 40 --out eval/data/bench-personnes.json
```

`--seed` defaults to a fixed value, so the corpus is identical between runs and a difference in the
output comes from the code, not from the draw. `--build-only` assembles the corpus with no database
at all, which is enough to check what the bench is about to measure.

A three-question production probe, [eval/verif-206.sh](../eval/verif-206.sh), covers the perfect
match, the false positive and the true rejection. It reads the key from `.env` and needs neither
`curl` nor `bash`, the container image carrying neither.

## 10. Changing a threshold

Do not adjust a value by hand on the strength of one bad case. Re-run the bench, read the interval,
and take its midpoint. If a single case bothers you, look first at whether it is the measurement
that is wrong: on this work the bench contradicted itself four times before producing a usable
number, and each time the defect was in the instrument.
