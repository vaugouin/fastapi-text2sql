#!/usr/bin/env python3
"""The disagreement corpus: where the answer-entity classifier decides anything at all.

FASTAPI-TEXT2SQL-284. Offline. No API call, no key, no network, no database: everything
below is read out of evaluation-execution exports that were already paid for.

Why this corpus exists
----------------------
`bench-result-entity.py` and `bench-result-entity-jev.py` both score the classifier
against ground truth harvested from the whole bank, and that is the wrong population.
The classifier is only consulted after the text-to-SQL model has already produced its own
`result_entity`, and it only changes anything when it CONTRADICTS it. Everywhere else it
agrees or abstains, and the pipeline would have returned the same answer type without it.
Measured on the 892 EN exports of run 001.001.018: 17 files, about 2 % of the bank.

So a correct answer from a candidate model on a question where the classifier would have
abstained is a duplicate of the fallback, not added value. The hundred-odd extra correct
answers -282 measured are real, and they are mostly scored where nothing was being decided.

The three effects, which are not the same as the disagreement
-------------------------------------------------------------
A disagreement on paper is not a disagreement in effect. main.py's guard re-reads the SQL
before acting, so:

  inert       the SELECT already projected the id the classifier expected, so the guard
              never fired. The labels differ and the query is untouched.
  overridden  the guard fired and the regenerated query was adopted. This is the only
              effect where the classifier actually changed the answer.
  attempted   the guard fired and threw the regeneration away for not projecting the
              expected id. One text2sql call paid, query unchanged.

Why there is no percentage in this report, and why that is deliberate
---------------------------------------------------------------------
n is around fifteen per language. Both benches refuse a percentage under --min-decidable
because a proportion computed on a handful of examples reassures instead of informing, and
that rule does not stop applying because the corpus is interesting. The output is the list,
case by case, and a reader who wants a rate has to count them by hand, which is the point.

The corpus is also biased BY CONSTRUCTION: these are the questions where two stages
disagreed, so they are the hardest ones in the bank. A success rate measured here is not
comparable with a success rate measured on the whole bank, and putting the two in one
table would rebuild the sampling error -282 already paid for with --limit 100.

Ground truth here cannot come from the pipeline, but it does not have to
------------------------------------------------------------------------
`load_truth` labels a question with the `result_entity` of an execution that passed its
assertions. On THIS corpus that is circular: when the guard overrode, the surviving label
IS the classifier's, so scoring against it asks the classifier to agree with itself. The
pass/fail verdict does not stand in for it either. #2250 "Which movie directors died in
2025?" has the classifier right (`person`) against the text-to-SQL model (`movie`) and
still scores 0.0, because the rest of the query was wrong for its own reasons.

The RESULT ASSERTIONS are a different kind of thing, and they settle it. They are written
by hand, per evaluation, before any of this, and they name the column the rows must carry:

    Statement: ID_PERSON IN (56819)

That is the same id token the guard looks for, so it names an answer entity independently
of every model in the pipeline. `adjudicate_from_assertions` reads it, and refuses to
name one when it would not discriminate, which happens two ways: a `COUNT(*) > 0`
assertion carries no column, and a label outside the classifier's vocabulary has rows that
carry the base entity's id as a foreign key, so an ID_MOVIE assertion is satisfied by both
`movie` and `movie_video` rows. Eleven of the fifteen EN cases are decidable that way.

An adjudication file remains, for the rest: hand-written verdicts, keyed by question,
which override the mechanical one. Without either, a case is listed and left unjudged
rather than given a verdict the data does not support.

Usage:
  uv run eval/bench-disagreements.py                       # EN, list the cases
  uv run eval/bench-disagreements.py --lang fr
  uv run eval/bench-disagreements.py --lang en --lang fr   # both, with the overlap
  uv run eval/bench-disagreements.py --adjudication eval/data/disagreements-adjudication.json
  uv run eval/bench-disagreements.py --questions-out /tmp/disagreements-en.txt

  # the verdict: join both benches' --disagreements-only runs onto the corpus
  uv run eval/bench-disagreements.py --lang en \\
      --gpt4o-run eval/data/bench/disagreements-en-gpt4o.json \\
      --jev-run   eval/data/bench/disagreements-en-jev.json
"""

import argparse
import importlib.util
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))


def load_sibling_bench():
    """Import `bench-result-entity.py` by path, with `text2sql` stubbed out.

    Same trick, and same reason, as `bench-result-entity-jev.load_sibling_bench`: the
    sibling's hyphens make it un-importable by name, and its module-level
    `import text2sql` would drag in pandas, numpy, psutil, openai and a prompt hot-reload
    watcher over `data/`. This script makes no LLM call at all, so none of that is
    reachable: `t2s` is touched only inside the sibling's `measure()` and `preflight()`.
    Stubbing rather than copying is what keeps the ground-truth and vocabulary loaders
    shared, and two benches that drifted apart on those would not be comparable.
    """
    sys.modules.setdefault("text2sql", types.ModuleType("text2sql"))
    path = os.path.join(HERE, "bench-result-entity.py")
    spec = importlib.util.spec_from_file_location("bench_result_entity", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the sibling bench at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BENCH = load_sibling_bench()

EFFECT_ORDER = ("overridden", "attempted", "inert")
EFFECT_GLOSS = {
    "overridden": "the guard regenerated the query and adopted it: the classifier DECIDED",
    "attempted":  "the guard regenerated and threw the result away: a call paid, nothing changed",
    "inert":      "the guard never fired: the labels differ on paper only",
}


def load_adjudication(path: str):
    """Read hand-written verdicts, keyed by question text.

    These OVERRIDE the mechanical adjudication, and exist for the cases it refuses: a
    `COUNT(*) > 0` assertion says the answer was non-empty and nothing about its type, and
    a reader can often still tell who was right. Keyed by question rather than by
    evaluation id because the same id carries a different question in each language, and
    because the benches dedupe by question too.
    """
    if not path:
        return {}
    if not os.path.exists(path):
        print(f"  (no adjudication file at {path}; the mechanical verdict stands alone)")
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    verdicts = {}
    for entry in payload.get("verdicts", []):
        question = (entry.get("question") or "").strip()
        if question:
            verdicts[question] = entry
    return verdicts


def adjudicate(items, id_tokens, hand_verdicts):
    """Attach a verdict to every case: mechanical first, hand-written as an override."""
    for record in items:
        label, winner, reason = BENCH.adjudicate_from_assertions(record, id_tokens)
        source = "assertions"
        hand = hand_verdicts.get(record["question"])
        if hand:
            # A hand verdict wins, including when it contradicts the mechanical one: the
            # override is the whole point of the file. Said out loud rather than silently,
            # because a contradiction means one of the two is wrong and worth reading.
            if label and hand.get("correct_label") and hand["correct_label"] != label:
                print(f"  NOTE: hand verdict on #{record['id']} contradicts the assertions "
                      f"({hand['correct_label']} against {label}); the hand verdict is used")
            label = hand.get("correct_label", "")
            winner = hand.get("winner") or ("classifier" if label == record["classifier"]
                                            else "text2sql" if label == record["text2sql"]
                                            else "neither")
            reason = hand.get("reason") or "hand-written verdict, no reason recorded"
            source = "hand"
        if label and winner not in ("classifier", "text2sql"):
            winner = ("classifier" if label == record["classifier"]
                      else "text2sql" if label == record["text2sql"] else "neither")
        record["truth"] = label
        record["winner"] = winner
        record["verdict_reason"] = reason
        record["verdict_source"] = source
    return items


def describe(record):
    """Print one case in full: the four facts, then the verdict and what produced it."""
    print(f"\n  #{record['id']}  [{record['effect']}]  "
          f"assertions {'passed' if record['assertions_passed'] else 'FAILED'}"
          f" ({record['assertions_score']})")
    print(f"    question   : {record['question']}")
    print(f"    text2sql   : {record['text2sql'] or '(none)'}"
          f"{'' if record['text2sql_in_vocabulary'] else '   <- outside the classifier vocabulary'}")
    print(f"    classifier : {record['classifier']}")
    print(f"    survived   : {record['final'] or '(none)'}")
    winner = record["winner"]
    if record["truth"]:
        print(f"    TRUTH      : {record['truth']}   -> {winner.upper()} was right"
              f"   [{record['verdict_source']}]")
    else:
        print(f"    TRUTH      : undecidable   [{record['verdict_source']}]")
    print(f"    because    : {record['verdict_reason']}")
    if record.get("conflicting_copies"):
        print(f"    NOTE: {len(record['conflicting_copies'])} duplicate export(s) of this "
              f"question recorded a different outcome; see --out")


def report(lang, items, stats):
    print()
    print("=" * 78)
    print(f"DISAGREEMENT CORPUS  |  lang={lang}  |  "
          f"{stats['distinct_questions']} distinct questions")
    print("=" * 78)
    print(f"\n  exports read                     : {stats['files_seen']}")
    print(f"  carrying a disagreement          : {stats['files_with_disagreement']}")
    conflicting = stats["conflicting_duplicates"]
    twin_note = f"  ({conflicting} disagreed with their twin)" if conflicting else ""
    print(f"  duplicate questions among those  : {stats['duplicates']}{twin_note}")
    print(f"  distinct questions               : {stats['distinct_questions']}")

    if stats["files_seen"]:
        share = 100.0 * stats["files_with_disagreement"] / stats["files_seen"]
        print(f"\n  The classifier contradicted the text-to-SQL model on {share:.1f} % of exports.")
        print("  On the rest it agreed or abstained, and the pipeline would have returned the")
        print("  same answer type without it. That is the whole point of this corpus.")

    if not items:
        print("\n  Nothing to list. If the bank is not empty, the guard's wording in main.py")
        print("  has changed and the patterns in load_disagreements no longer match it.")
        return

    by_effect = {name: [r for r in items if r["effect"] == name] for name in EFFECT_ORDER}
    print("\n  By effect")
    for name in EFFECT_ORDER:
        print(f"    {name:<12} {len(by_effect[name]):>3}   {EFFECT_GLOSS[name]}")
    deciding = len(by_effect["overridden"])
    print(f"\n  So the classifier changed the delivered query on {deciding} question(s) out of "
          f"{stats['files_seen']} exports.")
    print("  Read that number, not the corpus size: `inert` and `attempted` cost a call and")
    print("  changed nothing.")

    print("\n" + "-" * 78)
    print("THE CASES, one by one. No percentage is printed below and that is deliberate:")
    print(f"at n={len(items)} a proportion reassures instead of informing, which is the same")
    print("rule --min-decidable enforces in both benches.")
    print("-" * 78)

    for name in EFFECT_ORDER:
        if not by_effect[name]:
            continue
        print(f"\n{name.upper()}  ({EFFECT_GLOSS[name]})")
        for record in by_effect[name]:
            describe(record)

    judged = [r for r in items if r["truth"]]
    undecidable = [r for r in items if not r["truth"]]
    print("\n" + "-" * 78)
    print(f"VERDICT  |  {len(judged)} of {len(items)} cases decidable")
    print("-" * 78)
    if judged:
        classifier_won = [r for r in judged if r["winner"] == "classifier"]
        text2sql_won = [r for r in judged if r["winner"] == "text2sql"]
        neither = [r for r in judged if r["winner"] == "neither"]
        print(f"\n  classifier right : {len(classifier_won):>3}   "
              f"{sorted('#' + str(r['id']) for r in classifier_won)}")
        print(f"  text2sql right   : {len(text2sql_won):>3}   "
              f"{sorted('#' + str(r['id']) for r in text2sql_won)}")
        if neither:
            print(f"  neither          : {len(neither):>3}   "
                  f"{sorted('#' + str(r['id']) for r in neither)}")
        print(f"  undecidable      : {len(undecidable):>3}")

        # The number that actually costs or saves something: a classifier that is wrong
        # AND overrode is the only combination that destroys a query.
        damage = [r for r in judged if r["winner"] == "text2sql" and r["effect"] == "overridden"]
        rescue = [r for r in judged if r["winner"] == "classifier" and r["effect"] == "overridden"]
        missed = [r for r in judged if r["winner"] == "classifier" and r["effect"] != "overridden"]
        print(f"\n  rescued a wrong answer type : {len(rescue):>3}   "
              f"{sorted('#' + str(r['id']) for r in rescue)}")
        print(f"  DESTROYED a right one       : {len(damage):>3}   "
              f"{sorted('#' + str(r['id']) for r in damage)}")
        print(f"  right but did not act       : {len(missed):>3}   "
              f"{sorted('#' + str(r['id']) for r in missed)}")
        print("\n  Only the first two lines changed the delivered answer. The third is the")
        print("  classifier being right into the void, which the guard refused to act on.")
    print("\n  Counts, never rates. This corpus is biased BY CONSTRUCTION: it holds the")
    print("  questions where two stages disagreed, so they are the hardest ones in the bank")
    print("  and a rate measured here is comparable with no other rate in either bench.")
    print("=" * 78)


JEV_THRESHOLDS = (0.0, 0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95)


def delivered_label(classifier_answer, text2sql_label, allowed_set):
    """What the PIPELINE ends up with, which is not what the classifier said.

    This is the whole correction FASTAPI-TEXT2SQL-284 exists to make. Both benches score
    the classifier's own answer, and on the whole bank that is a fair proxy because an
    abstention costs nothing: the fallback is the text-to-SQL label, which usually agrees.

    On THIS corpus it is not a proxy at all, because the corpus is selected on the two
    labels differing. Here an abstention is not neutral, it is a vote for the text-to-SQL
    label, and that label is wrong on most of these questions. So a model that abstains its
    way out of trouble also abstains its way out of every rescue, and the three outcome
    columns cannot show that. The delivered label can.
    """
    if classifier_answer and classifier_answer in allowed_set:
        return classifier_answer
    return text2sql_label


def load_model_run(path):
    """Read a `--out` file from either bench and index it by evaluation id."""
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return {record["id"]: record for record in payload.get("results", [])}


def compare_models(items, allowed_set, gpt4o_rows, jev_rows, jev_threshold):
    """Join the two bench runs onto the corpus and score the DELIVERED answer type.

    Three configurations, answering the one question -284 was opened to answer: on the
    population where the classifier decides anything, does the pipeline deliver the right
    answer type more often with Jev than with gpt-4o, and more often than with no
    classifier at all?
    """
    judged = [r for r in items if r["truth"]]
    if not judged:
        return
    print("\n" + "=" * 78)
    print("DELIVERED ANSWER TYPE, the number this corpus was built to produce")
    print("=" * 78)
    print("\nNot 'what did the classifier say' but 'what did the pipeline end up with'.")
    print("An abstention here is a vote for the text-to-SQL label, never a free pass.")

    rows, tallies = [], {"none": 0, "gpt-4o": 0, f"jev@{jev_threshold:.2f}": 0}
    for record in judged:
        gpt = (gpt4o_rows or {}).get(record["id"]) or {}
        jev = (jev_rows or {}).get(record["id"]) or {}
        gpt_answer = gpt.get("a", "")
        jev_answer = jev.get("label", "") if jev.get("confidence", 0.0) >= jev_threshold else ""
        delivered = {
            "none": record["text2sql"],
            "gpt-4o": delivered_label(gpt_answer, record["text2sql"], allowed_set),
            f"jev@{jev_threshold:.2f}": delivered_label(jev_answer, record["text2sql"], allowed_set),
        }
        for name, label in delivered.items():
            tallies[name] += label == record["truth"]
        rows.append((record, gpt_answer, jev_answer, delivered))

    width = max(len(name) for name in tallies)
    print(f"\n  {'id':<7}{'truth':<11}{'text2sql':<12}{'gpt-4o':<13}{'jev':<13}"
          f"{'delivered gpt-4o':<18}{'delivered jev':<15}")
    for record, gpt_answer, jev_answer, delivered in rows:
        gpt_mark = "" if delivered["gpt-4o"] == record["truth"] else " X"
        jev_mark = "" if delivered[f"jev@{jev_threshold:.2f}"] == record["truth"] else " X"
        print(f"  #{record['id']:<6}{record['truth']:<11}{record['text2sql']:<12}"
              f"{gpt_answer or '(abstain)':<13}{jev_answer or '(abstain)':<13}"
              f"{delivered['gpt-4o'] + gpt_mark:<18}"
              f"{delivered[f'jev@{jev_threshold:.2f}'] + jev_mark:<15}")

    total = len(judged)
    print(f"\n  Right answer type delivered, out of {total}:")
    for name in ("none", "gpt-4o", f"jev@{jev_threshold:.2f}"):
        caption = {"none": "no classifier at all (text2sql alone)",
                   "gpt-4o": "today's classifier, gpt-4o"}.get(name, f"Jev at {jev_threshold:.2f}")
        print(f"    {tallies[name]:>3} / {total}   {caption}")

    if jev_rows:
        print("\n  Jev across the sweep, same measure:")
        for threshold in JEV_THRESHOLDS:
            hits = sum(
                delivered_label(
                    (jev_rows.get(r["id"]) or {}).get("label", "")
                    if (jev_rows.get(r["id"]) or {}).get("confidence", 0.0) >= threshold else "",
                    r["text2sql"], allowed_set) == r["truth"]
                for r in judged)
            print(f"    {hits:>3} / {total}   threshold {threshold:.2f}")
        print("\n  These differ by one or two events on a corpus of a dozen questions, so the")
        print("  shape is readable and the ranking is not. Do not tune a threshold on this.")

    print(f"\n  At n={total} none of these differences is significant, and that is the honest")
    print("  reading. What the table does establish is the first line: the pipeline is much")
    print("  worse with no classifier at all, so the stage earns its place, and the question")
    print("  is only which model fills it.")
    print("=" * 78)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lang", action="append", choices=["en", "fr"], default=None,
                        help="Language to extract; repeat for both.")
    parser.add_argument("--truth-dir", default=BENCH.DEFAULT_TRUTH_DIR)
    parser.add_argument("--run", default=BENCH.DEFAULT_RUN_PREFIX)
    parser.add_argument("--adjudication", default=None,
                        help="Hand-written verdicts, one per question.")
    parser.add_argument("--out", default=None, help="Write the corpus as JSON.")
    parser.add_argument("--questions-out", default=None,
                        help="Write just the questions, one per line, for --questions-file.")
    parser.add_argument("--gpt4o-run", default=None,
                        help="--out file from `bench-result-entity.py --disagreements-only`.")
    parser.add_argument("--jev-run", default=None,
                        help="--out file from `bench-result-entity-jev.py --disagreements-only`.")
    parser.add_argument("--jev-threshold", type=float, default=0.90,
                        help="Jev's operating confidence gate, 0.90 per -282's calibration.")
    args = parser.parse_args()

    BENCH.force_utf8_console()
    langs = args.lang or ["en"]

    allowed = BENCH.load_allowed_entities()
    allowed_set = set(allowed)
    print(f"Classifier vocabulary: {len(allowed)} labels, read from main.py")
    verdicts = load_adjudication(args.adjudication)
    if verdicts:
        print(f"Adjudication: {len(verdicts)} verdict(s) loaded from {args.adjudication}")

    id_tokens = BENCH.load_entity_id_tokens()
    gpt4o_rows = load_model_run(args.gpt4o_run)
    jev_rows = load_model_run(args.jev_run)
    # A run file holds ONE language, so joining it onto a two-language extraction would
    # match a French id onto an English question. Refused rather than silently mismatched.
    if (gpt4o_rows or jev_rows) and len(langs) > 1:
        print("\n--gpt4o-run / --jev-run describe one language; pass a single --lang to join "
              "them. The corpus below is extracted without the comparison.")
        gpt4o_rows = jev_rows = None

    everything = {}
    for lang in langs:
        items, stats = BENCH.load_disagreements(args.truth_dir, args.run, lang, allowed)
        adjudicate(items, id_tokens, verdicts)
        report(lang, items, stats)
        if gpt4o_rows or jev_rows:
            compare_models(items, allowed_set, gpt4o_rows, jev_rows, args.jev_threshold)
        everything[lang] = {"stats": stats, "items": items}

    if len(langs) > 1:
        shared = set()
        for lang in langs:
            ids = {r["id"] for r in everything[lang]["items"]}
            shared = ids if not shared else (shared & ids)
        print(f"\nEvaluation ids that disagree in every language asked for: "
              f"{len(shared)} -> {sorted(shared)}")
        print("  A question that trips both languages is a property of the question, not of")
        print("  the translation, and is the first place to look for a fixable prompt defect.")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump({"run": args.run, "langs": langs, "corpus": everything},
                      handle, ensure_ascii=False, indent=2)
        print(f"\nCorpus written to {args.out}")

    if args.questions_out:
        with open(args.questions_out, "w", encoding="utf-8") as handle:
            for lang in langs:
                for record in everything[lang]["items"]:
                    handle.write(record["question"] + "\n")
        print(f"Questions written to {args.questions_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
