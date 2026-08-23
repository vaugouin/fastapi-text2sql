-- Make the entity-extraction assertions language-neutral.
--
-- APPLIED 2026-08-23, ahead of this file being written down. The four UPDATEs below are
-- guarded on the assertion still being in its pinned form, so re-running them now changes
-- nothing; the file is kept as the record of what was changed and why. Two things went
-- differently from what is proposed here, both noted at the bottom.
--
-- WHY THIS FILE EXISTS
-- Four assertions pin the exact ENGLISH anonymized question with eq($.question, "..."),
-- so they fail on the French pass for a reason that has nothing to do with extraction
-- quality: the French question is a different sentence. Running the bench or the evaluator
-- with --lang fr therefore reports four false regressions, on both the single-prompt and
-- the split-prompt path alike.
--
-- The fix is to drop the eq($.question, ...) clause and keep the entity checks, which is
-- what the other 320 assertions in the bank already do. Layer 1 of the harness
-- (entity_extraction_eval_functions.ee_eval_two_layer) already enforces that the
-- placeholders in `question` and the entity keys match exactly and that every value is a
-- non-empty string, so pinning the whole sentence adds nothing that Layer 1 does not
-- already guarantee. The value checks move from eq() to matches(/^...$/i) for the case
-- tolerance the rest of the file uses.
--
-- TWO ASSERTIONS DELIBERATELY LEFT ALONE
-- #2235 "Tommy (1975)" and #2244 "Ginza cosmetics" also pin the question, but their
-- QUESTION and QUESTION_FR are the same string, so they behave identically in both
-- languages. #2235 is moreover the only assertion in the bank that exercises the
-- Title (Year) shape end to end. Left as they are.
--
-- IDEMPOTENT
-- Every UPDATE is guarded on the assertion still being in its pinned form, so re-running
-- this file changes nothing and it never overwrites a later hand edit.
--
-- AFTER APPLYING
-- The scores already stored in T_WC_T2S_EVALUATION_EXECUTION keep their old values until
-- the evaluator's scoring phase is re-run. That phase reads the stored JSON_RESULT and
-- spends no LLM tokens, so re-scoring is cheap and needs no new API run.

-- ===== The four that break in French =====

-- #12 EN: Which movies are starring Lauren Bacall and Humphrey Bogart?
--     FR: Quels films mettent en vedette Lauren Bacall et Humphrey Bogart ?
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;,&quot;Person_name2&quot;]) AND matches($.Person_name1, /^Lauren Bacall$/i) AND matches($.Person_name2, /^Humphrey Bogart$/i)'
  WHERE ID_T2S_EVALUATION = 12
    AND ASSERTIONS_ENTITY_EXTRACTION LIKE 'eq($.question,%';

-- #13 EN: List movies directed by Sergio Leone and starring Clint Eastwood
--     FR: Listez les films réalisés par Sergio Leone et mettant en vedette Clint Eastwood.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Person_name1&quot;,&quot;Person_name2&quot;]) AND matches($.Person_name1, /^Sergio Leone$/i) AND matches($.Person_name2, /^Clint Eastwood$/i)'
  WHERE ID_T2S_EVALUATION = 13
    AND ASSERTIONS_ENTITY_EXTRACTION LIKE 'eq($.question,%';

-- #2215 EN: List all actors that played the role of Sherlock Holmes in movies
--       FR: Listez tous les acteurs qui ont joué le rôle de Sherlock Holmes dans des films.
-- Same form as #2218, its series-side twin, which was already language-neutral.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Character_name1&quot;]) AND matches($.Character_name1, /^Sherlock Holmes$/i)'
  WHERE ID_T2S_EVALUATION = 2215
    AND ASSERTIONS_ENTITY_EXTRACTION LIKE 'eq($.question,%';

-- #2158 EN: James Bond collection
--       FR: Collection James Bond
-- The word order flips between the two languages, so the pinned question could never hold
-- in both. Language-only fix; the type question is separate, see below.
UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Topic_name1&quot;]) AND matches($.Topic_name1, /^James Bond$/i)'
  WHERE ID_T2S_EVALUATION = 2158
    AND ASSERTIONS_ENTITY_EXTRACTION LIKE 'eq($.question,%';


-- ===== What was actually applied on 2026-08-23, and one thing still open =====
--
-- #2158 was corrected in one step: not only delanguaged but retyped to Collection_name,
-- which is the right call (the prompt moved franchises out of Topic_name years ago and the
-- result assertion targets ID_T2S_COLLECTION). The regex applied is /^James Bond$/i, and
-- that one still fails: the whole phrase "James Bond collection" is the entity, so both the
-- single prompt and the split prompt return Collection_name1 = "James Bond collection",
-- which /^James Bond$/i rejects. Verified against both observed payloads. The tolerant form
-- below passes for both. Compare with #2277 "List James Bond movies ordered by release
-- date", where the value really is just "James Bond" and /^James Bond$/i is correct.
--
-- UPDATE T_WC_T2S_EVALUATION SET ASSERTIONS_ENTITY_EXTRACTION = 'seteq(entity_keys($), [&quot;Collection_name1&quot;]) AND matches($.Collection_name1, /^James Bond( ?collection)?$/i)'
--   WHERE ID_T2S_EVALUATION = 2158;
--
-- #2221 "Who starred as Rocky Balboa?" had its malformed expression removed rather than
-- rewritten, so the row no longer scores entity extraction at all. That is a defensible
-- choice. Note only that both prompts return exactly
-- {"question": "Who starred as {{Character_name1}}?", "Character_name1": "Rocky Balboa"},
-- so the row would have passed had the expression been written in the right dialect.

-- ===== Verification =====
-- Should return zero rows once the four UPDATEs above have run.
-- SELECT ID_T2S_EVALUATION, QUESTION, ASSERTIONS_ENTITY_EXTRACTION
-- FROM T_WC_T2S_EVALUATION
-- WHERE IS_EVAL = 1 AND DELETED = 0
--   AND ASSERTIONS_ENTITY_EXTRACTION LIKE 'eq($.question,%'
--   AND QUESTION <> QUESTION_FR;
