-- FASTAPI-TEXT2SQL-371 step 4, second pass of check-371-character-nicknames.sql: five more
-- nicknames, literal matches and the intended persons. Voie 1 (SELECT only).

SELECT k.NICK,
       (SELECT COUNT(*) FROM T_WC_T2S_PERSON_MOVIE m WHERE m.CAST_CHARACTER_KEY = k.K) AS movie_credits,
       (SELECT COUNT(*) FROM T_WC_T2S_PERSON_SERIE s WHERE s.CAST_CHARACTER_KEY = k.K) AS serie_credits
FROM (
  SELECT 'Merc with a Mouth' AS NICK, 'mercwithamouth' AS K UNION ALL
  SELECT 'The Merc with a Mouth', 'themercwithamouth' UNION ALL
  SELECT 'Web-Slinger', 'webslinger' UNION ALL
  SELECT 'The Web-Slinger', 'thewebslinger' UNION ALL
  SELECT 'Hannibal the Cannibal', 'hannibalthecannibal' UNION ALL
  SELECT 'Boy Wonder', 'boywonder' UNION ALL
  SELECT 'The Boy Wonder', 'theboywonder' UNION ALL
  SELECT 'The Gipper', 'thegipper' UNION ALL
  SELECT 'Gipper', 'gipper' UNION ALL
  SELECT 'Bionic Man', 'bionicman' UNION ALL
  SELECT 'The Bionic Man', 'thebionicman' UNION ALL
  SELECT 'Little Tramp', 'littletramp' UNION ALL
  SELECT 'The Little Tramp', 'thelittletramp' UNION ALL
  SELECT 'Petit Vagabond', 'petitvagabond' UNION ALL
  SELECT 'Femme bionique', 'femmebionique' UNION ALL
  SELECT 'Homme de fer', 'hommedefer' UNION ALL
  SELECT 'Homme d''acier', 'hommedacier' UNION ALL
  SELECT 'Chevalier noir', 'chevaliernoir'
) k;

SELECT t.NICK, p.ID_PERSON, p.PERSON_NAME, ROUND(p.POPULARITY, 1) AS pop,
       c.ID_MOVIE, w.MOVIE_TITLE, LEFT(c.CAST_CHARACTER, 60) AS cast_character
FROM (
  SELECT 'Merc with a Mouth' AS NICK, 'Ryan Reynolds' AS PNAME, '%Deadpool%' AS PAT UNION ALL
  SELECT 'Web-Slinger', 'Tobey Maguire', '%Spider-Man%' UNION ALL
  SELECT 'Web-Slinger', 'Andrew Garfield', '%Spider-Man%' UNION ALL
  SELECT 'Web-Slinger', 'Tom Holland', '%Spider-Man%' UNION ALL
  SELECT 'Hannibal the Cannibal', 'Anthony Hopkins', '%Lecter%' UNION ALL
  SELECT 'Hannibal the Cannibal', 'Mads Mikkelsen', '%Lecter%' UNION ALL
  SELECT 'Boy Wonder', 'Burt Ward', '%Robin%' UNION ALL
  SELECT 'Boy Wonder', 'Chris O''Donnell', '%Robin%' UNION ALL
  SELECT 'The Gipper', 'Ronald Reagan', '%Gipp%'
) t
JOIN T_WC_T2S_PERSON p ON p.PERSON_NAME = t.PNAME
JOIN T_WC_T2S_PERSON_MOVIE c ON c.ID_PERSON = p.ID_PERSON AND c.CREDIT_TYPE = 'cast' AND c.CAST_CHARACTER LIKE t.PAT
JOIN T_WC_T2S_MOVIE w ON w.ID_MOVIE = c.ID_MOVIE
ORDER BY 1, 3, 5;

SELECT PERSON_NAME, COUNT(*) AS n, GROUP_CONCAT(ID_PERSON ORDER BY POPULARITY DESC) AS ids
FROM T_WC_T2S_PERSON
WHERE PERSON_NAME IN ('Ryan Reynolds', 'Tobey Maguire', 'Andrew Garfield', 'Tom Holland', 'Anthony Hopkins',
                      'Mads Mikkelsen', 'Burt Ward', 'Chris O''Donnell', 'Ronald Reagan')
GROUP BY PERSON_NAME;
