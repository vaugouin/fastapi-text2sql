-- FASTAPI-TEXT2SQL-371 step 4: characters named by a nickname or a title, the shape of eval 2220
-- ("Who starred as the Six Million Dollar Man?"). Character_name has no resolver: the raw value
-- is substituted, the SQL compares it to CAST_CHARACTER, finds nothing, and the -221 gate takes
-- the empty result as authoritative. Measures, before writing the evaluations:
--   1. how many credits carry each nickname literally (0 = the first pass can only fail on it);
--   2. the intended persons, with the credits that prove the role (the assertion ids).
-- Voie 1 (SELECT only).

-- 1. Literal matches of each nickname, movie and series credits, on the folded key.
SELECT k.NICK,
       (SELECT COUNT(*) FROM T_WC_T2S_PERSON_MOVIE m WHERE m.CAST_CHARACTER_KEY = k.K) AS movie_credits,
       (SELECT COUNT(*) FROM T_WC_T2S_PERSON_SERIE s WHERE s.CAST_CHARACTER_KEY = k.K) AS serie_credits
FROM (
  SELECT 'Six Million Dollar Man' AS NICK, 'sixmilliondollarman' AS K UNION ALL
  SELECT 'The Six Million Dollar Man', 'thesixmilliondollarman' UNION ALL
  SELECT 'Bionic Woman', 'bionicwoman' UNION ALL
  SELECT 'The Bionic Woman', 'thebionicwoman' UNION ALL
  SELECT 'The Dude', 'thedude' UNION ALL
  SELECT 'Dude', 'dude' UNION ALL
  SELECT 'Dirty Harry', 'dirtyharry' UNION ALL
  SELECT 'Inspecteur Harry', 'inspecteurharry' UNION ALL
  SELECT 'The Fonz', 'thefonz' UNION ALL
  SELECT 'Fonz', 'fonz' UNION ALL
  SELECT 'Man with No Name', 'manwithnoname' UNION ALL
  SELECT 'The Man with No Name', 'themanwithnoname' UNION ALL
  SELECT 'Homme sans nom', 'hommesansnom' UNION ALL
  SELECT 'Little Tramp', 'littletramp' UNION ALL
  SELECT 'The Tramp', 'thetramp' UNION ALL
  SELECT 'Tramp', 'tramp' UNION ALL
  SELECT 'Charlot', 'charlot' UNION ALL
  SELECT 'Caped Crusader', 'capedcrusader' UNION ALL
  SELECT 'The Caped Crusader', 'thecapedcrusader' UNION ALL
  SELECT 'Man of Steel', 'manofsteel' UNION ALL
  SELECT 'Fresh Prince', 'freshprince' UNION ALL
  SELECT 'The Fresh Prince', 'thefreshprince' UNION ALL
  SELECT 'Prince de Bel-Air', 'princedebelair' UNION ALL
  SELECT 'Mad Max', 'madmax' UNION ALL
  SELECT 'Indy', 'indy' UNION ALL
  SELECT 'Dark Knight', 'darkknight' UNION ALL
  SELECT 'The Dark Knight', 'thedarkknight' UNION ALL
  SELECT 'The Bride', 'thebride' UNION ALL
  SELECT 'Bionic Man', 'bionicman' UNION ALL
  SELECT 'Steve Austin', 'steveaustin'
) k;

-- 2. The intended persons and the credits that prove the role.
SELECT t.NICK, p.ID_PERSON, p.PERSON_NAME, ROUND(p.POPULARITY, 1) AS pop, 'movie' AS kind,
       c.ID_MOVIE AS ID_WORK, w.MOVIE_TITLE AS title, LEFT(c.CAST_CHARACTER, 60) AS cast_character
FROM (
  SELECT 'Bionic Woman' AS NICK, 'Lindsay Wagner' AS PNAME, '%Sommers%' AS PAT UNION ALL
  SELECT 'The Dude', 'Jeff Bridges', '%Dude%' UNION ALL
  SELECT 'Dirty Harry', 'Clint Eastwood', '%Callahan%' UNION ALL
  SELECT 'Man with No Name', 'Clint Eastwood', '%Blondie%' UNION ALL
  SELECT 'Man with No Name', 'Clint Eastwood', 'Joe' UNION ALL
  SELECT 'Man with No Name', 'Clint Eastwood', 'Manco%' UNION ALL
  SELECT 'Man with No Name', 'Clint Eastwood', '%No Name%' UNION ALL
  SELECT 'Little Tramp', 'Charles Chaplin', '%Tramp%' UNION ALL
  SELECT 'Little Tramp', 'Charlie Chaplin', '%Tramp%' UNION ALL
  SELECT 'Caped Crusader', 'Michael Keaton', '%Batman%' UNION ALL
  SELECT 'Caped Crusader', 'Christian Bale', '%Batman%' UNION ALL
  SELECT 'Caped Crusader', 'Adam West', '%Batman%' UNION ALL
  SELECT 'Man of Steel', 'Christopher Reeve', '%Superman%' UNION ALL
  SELECT 'Man of Steel', 'Henry Cavill', '%Superman%' UNION ALL
  SELECT 'Mad Max', 'Mel Gibson', '%Max%' UNION ALL
  SELECT 'Mad Max', 'Tom Hardy', '%Max%' UNION ALL
  SELECT 'Indy', 'Harrison Ford', '%Indiana%'
) t
JOIN T_WC_T2S_PERSON p ON p.PERSON_NAME = t.PNAME
JOIN T_WC_T2S_PERSON_MOVIE c ON c.ID_PERSON = p.ID_PERSON AND c.CREDIT_TYPE = 'cast' AND c.CAST_CHARACTER LIKE t.PAT
JOIN T_WC_T2S_MOVIE w ON w.ID_MOVIE = c.ID_MOVIE
UNION ALL
SELECT t.NICK, p.ID_PERSON, p.PERSON_NAME, ROUND(p.POPULARITY, 1), 'serie',
       c.ID_SERIE, w.SERIE_TITLE, LEFT(c.CAST_CHARACTER, 60)
FROM (
  SELECT 'Six Million Dollar Man' AS NICK, 'Lee Majors' AS PNAME, '%Austin%' AS PAT UNION ALL
  SELECT 'Bionic Woman', 'Lindsay Wagner', '%Sommers%' UNION ALL
  SELECT 'The Fonz', 'Henry Winkler', '%Fonz%' UNION ALL
  SELECT 'Fresh Prince', 'Will Smith', '%Will%' UNION ALL
  SELECT 'Caped Crusader', 'Adam West', '%Batman%'
) t
JOIN T_WC_T2S_PERSON p ON p.PERSON_NAME = t.PNAME
JOIN T_WC_T2S_PERSON_SERIE c ON c.ID_PERSON = p.ID_PERSON AND c.CAST_CHARACTER LIKE t.PAT
JOIN T_WC_T2S_SERIE w ON w.ID_SERIE = c.ID_SERIE
ORDER BY 1, 3, 6;

-- 3. Namesakes of the intended persons (the assertion must name the right id).
SELECT PERSON_NAME, COUNT(*) AS n, GROUP_CONCAT(ID_PERSON ORDER BY POPULARITY DESC) AS ids
FROM T_WC_T2S_PERSON
WHERE PERSON_NAME IN ('Lee Majors', 'Lindsay Wagner', 'Jeff Bridges', 'Clint Eastwood', 'Henry Winkler',
                      'Charlie Chaplin', 'Charles Chaplin', 'Michael Keaton', 'Christian Bale', 'Adam West',
                      'Christopher Reeve', 'Henry Cavill', 'Will Smith', 'Mel Gibson', 'Tom Hardy', 'Harrison Ford')
GROUP BY PERSON_NAME;
