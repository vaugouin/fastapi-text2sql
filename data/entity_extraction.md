# Entity Extraction for Movie and TV Series Questions

## Your Task
Extract named entities from the user question and anonymize the question with placeholders.

The goal is to support:
- caching of similar questions
- semantic similarity matching
- entity resolution in a later step

Do not generate SQL.
Do not explain your reasoning.
Do not add any text outside the JSON object.

## Output Format
Return exactly one JSON object.

The JSON object must contain:
- `question`: the anonymized question with placeholders
- one key per extracted entity placeholder

Rules:
- Return only valid JSON
- Do not use markdown or code fences
- Do not add comments
- Do not invent entities that are not clearly present in the user question
- If uncertain, leave the text in `question` and do not extract it
- For every placeholder used in `question`, include the corresponding key and value
- Do not include entity keys that are not used in `question`
- Preserve the original surface form of the extracted value unless a rule below says otherwise

## Placeholder Types

### Person_name
Names of actors, directors, writers, composers, creators, and other crew members.
Examples: `Humphrey Bogart`, `Stanley Kubrick`, `Akira Kurosawa`, `Edith Head`

### Movie_title
Movie titles in any language.
Include articles if they are part of the title.
Examples: `The Big Lebowski`, `The African Queen`, `The Big Sleep`

### Serie_title
TV series titles.
Examples: `Game of Thrones`, `Breaking Bad`

### Company_name
Production or distribution company names.
Examples: `Lucasfilm`, `Warner Bros`, `Studio Ghibli`

### Network_name
TV networks or streaming platforms.
Examples: `Netflix`, `HBO`, `BBC`

### Character_name
Character names.
Examples: `James Bond`, `Sherlock Holmes`, `R2-D2`, `Hamlet`

### Location_name
Location names used as story locations or filming locations.
Examples: `New York City`, `South America`, `Moon`, `France`, `Gotham City`, `British Columbia`, `Hollywood`

### IMDb_ID
IMDb identifiers for movies or series.
Examples: `tt0038355`, `tt0108778`

### IMDb_person_ID
IMDb identifiers for persons.
Examples: `nm0000007`, `nm0424060`

### Wikidata_ID
Wikidata identifiers.
Examples: `Q28385`, `Q1445474`, `Q188825`

### Wikidata_property_ID
Wikidata property identifiers.
Examples: `P17`, `P136`, `P161`

### TMDb_ID
TMDb identifiers for movies, series, or persons.
Examples: `550`, `1399`, `1289813`

### Criterion_spine_ID
Criterion Collection spine identifiers when explicitly referenced as an identifier.
Examples: `1`, `2`, `3`

### Birth_year
A 4-digit year representing a person's year of birth.
Extract only when the question filters or reasons about a person's birth year (e.g., "actors born in 1962", "directors born in 1899").
Examples: `1899`, `1962`, `2000`

### Death_year
A 4-digit year representing a person's year of death.
Extract only when the question filters or reasons about a person's death year (e.g., "directors who died in 1980", "actresses who passed away in 2020").
Examples: `1980`, `1999`, `2020`

### List_name
Notable curated film lists or TV series lists.
Examples: `Sight and Sound greatest films of all time`, `IMDb top 250 tv shows`, `Roger Ebert's Great Movies List`

### Award_name
Award or recognition received by a person, movie, TV series, or organization.
Examples: `Academy Award for Best Picture`, `Palme d'Or`, `Primetime Emmy Award`

### Nomination_name
Award nomination received by a person, movie, TV series, or organization.
Examples: `Academy Award for Best Picture`, `Palme d'Or`, `Primetime Emmy Award`

### Collection_name
Trilogies, named series of works, universes, and franchises (named groupings of movies and/or TV series).
Examples: `Dollars Trilogy`, `James Bond Collection`, `Kill Bill - Saga`, `Star Wars`, `Marvel Cinematic Universe`, `DC Extended Universe`, `Batman universe`, `Middle-Earth`, `Harry Potter movies`, `James Bond films`

### Movement_name
Film movements or styles.
Examples: `Film Noir`, `French New Wave`, `New Hollywood`, `Cinéma vérité`, `Surrealism`, `Pre-Code movies`

### Group_name
Organization, club, or musical group to which a person belongs or works/worked for.
Examples: `The Beatles`, `The Monty Python`, `Les Cahiers du Cinéma`

### Death_name
Underlying or immediate cause of death (medical term) or general circumstance of a person's death (legal term).
Examples: `liver cirrhosis`, `car collision`, `homicide`

### Topic_name
Extract `Topic_name` only for recognizable movie/series-related topics such as:
- clear thematic topics such as `World War II` or `biographical films`
- notable recurring character-based collections

Do NOT extract universes or franchises (e.g. `Star Wars`, `Marvel Cinematic Universe`, `DC Extended Universe`, `Batman universe`, `Middle-Earth`, `Harry Potter movies`, `James Bond films`) as `Topic_name` — they are now extracted as `Collection_name`.

Examples:
- `World War II`
- `Christmas`
- `kidnapping`
- `Philip Marlowe`

### Genre_name
Extract `Genre_name` when the user question mentions a movie or TV series genre by its standard name.
The value MUST be one of the following supported genre names (case-insensitive, keep the original surface form when possible):

Movie genres:
- `Action`, `Adventure`, `Animation`, `Comedy`, `Crime`, `Drama`, `Family`, `Fantasy`, `History`, `Horror`, `Music`, `Mystery`, `Romance`, `Science Fiction`, `Sci-Fi`, `Thriller`, `TV Movie`, `War`, `Western`

TV series genres:
- `Action & Adventure`, `Animation`, `Comedy`, `Crime`, `Drama`, `Family`, `History`, `Kids`, `Mystery`, `News`, `Reality`, `Romance`, `Sci-Fi & Fantasy`, `Soap`, `Talk`, `War & Politics`, `Western`

Examples:
- `war` (movie genre)
- `comedy`
- `Science Fiction`
- `Sci-Fi & Fantasy` (series genre)
- `War & Politics` (series genre)

Disambiguation:
- If the user writes a simple word that matches a supported genre (e.g., `war movies`, `comedy series`), extract it as `Genre_name`, NOT as `Topic_name`.
- If the user writes a compound topic that includes a genre word but refers to a specific theme (e.g., `Vietnam war`, `World War II`, `cold war`), extract it as `Topic_name`, NOT as `Genre_name`.
- If the surface form is not in the supported lists above, do NOT extract it as `Genre_name`. Leave it in the anonymized question unchanged, or treat it as a topic if appropriate.

### Status_name
Production lifecycle status of a movie or TV series.
The value MUST be one of the following supported status names (case-insensitive, keep the original surface form):
- `Canceled`, `In Production`, `Planned`, `Post Production`, `Released`, `Rumored`

Examples:
- `released`
- `canceled`
- `in production`
- `post production`

Disambiguation:
- Extract `Status_name` only when the question filters by lifecycle status (e.g., "released movies", "canceled series", "movies in production").
- Common synonyms ("cancelled", "annulé", "sorti", "post-production") are accepted at resolution time and resolve to the canonical value above.

### Serie_type
Type of a TV series. The value MUST be one of exactly:
- `Documentary`, `Miniseries`, `News`, `Reality`, `Scripted`, `Talk Show`, `Video`

Examples:
- `Documentary`
- `Miniseries`
- `Talk Show`

Disambiguation:
- Only extract `Serie_type = Documentary` when the question **explicitly** mentions a TV series, show, or series context (e.g., "documentary series", "documentary TV shows", "documentary shows").
- If the user writes "documentary" or "documentaries" **without** explicit series/TV context (e.g., "List documentaries", "best documentaries of 2020"), do **NOT** extract it as `Serie_type` or `Genre_name`. Leave the word in the question unchanged so the text-to-SQL step can handle it directly.
- Common synonyms ("doc", "documentaire", "mini-série", "talk-show") are accepted at resolution time and resolve to the canonical value above.

### Aspect_ratio
A movie aspect ratio, expressed in decimal form, in `width:height` form, or by a well-known named convention.
Common surface forms include (non-exhaustive): `1.33`, `1.37`, `1.66`, `1.78`, `1.85`, `2.35`, `2.39`, `Academy ratio`, `4:3`, `16:9`, `widescreen`, `anamorphic`, `scope`, `Academy`, `flat`, `fullscreen`, `2.35:1`, `2.40:1`.

Examples:
- `2.35`
- `1.85:1`
- `Academy ratio`
- `16:9`
- `anamorphic`
- `widescreen`

Disambiguation:
- Extract `Aspect_ratio` only when the question filters or asks about the movie's aspect ratio (e.g., "movies shot in 2.35:1", "Academy ratio films", "widescreen movies", "16:9 films").
- Common surface variants (`2,35` with comma decimal, `2.35:1` with `:1` suffix, named forms `Academy`, `widescreen`, `anamorphic`, `scope`, `4:3`, `16:9`) are accepted at resolution time and resolve to the canonical decimal value (e.g. `1.37`, `1.85`, `2.35`).
- Do NOT extract a numeric value as `Aspect_ratio` when the context clearly refers to something else (a release year, a runtime, an IMDb rating, a budget, etc.).
- If the value is not in the supported list above and not a known named alias, do NOT extract it as `Aspect_ratio`. Leave it in the question unchanged.

### Department_name
A film/TV **crew** department classification. **Crew-only — never Acting/Actors.** Cast (acting) credits are handled by a separate rule and never produce a `Department_name` placeholder.

The value MUST be one of the following canonical crew values (case-insensitive, keep the original surface form when possible):
- `Art`, `Camera`, `Costume & Make-Up`, `Creator`, `Crew`, `Directing`, `Editing`, `Lighting`, `Production`, `Sound`, `Visual Effects`, `Writing`

Examples:
- `Directing`
- `Camera`
- `Visual Effects`
- `Sound`
- `Writing`

Disambiguation:
- Extract `Department_name` when the question explicitly references a **crew** department or job category by name (e.g., "people in the Camera department", "show me cinematographers", "list directors", "films with the Sound department").
- Common crew synonyms ("directors", "writers", "editors", "cinematographers", "producers", "creators", "VFX", "réalisateurs", "scénaristes", "monteurs", "producteurs", "créateurs") and their canonical forms are accepted at resolution time and resolve to the canonical value above.
- **Never extract `Acting`, `Actor`, `Actors`, `Actress`, `Actresses`, `Acteur(s)`, `Actrice(s)`, or any acting/cast role as `Department_name`.** Cast queries are handled by the text-to-SQL step via `CREDIT_TYPE = 'cast'`, not via this placeholder. Leave such words in the question unchanged.
- Do NOT extract `Department_name` from verb phrasings already covered by other rules (e.g., "directed by X", "written by X", "edited by X") — those are handled inline by the text-to-SQL step from the verb itself together with the `Person_name` placeholder. Extract `Department_name` only when the department/job category itself is the filter.
- If the surface form is not in the supported crew list above and not a known crew synonym, do NOT extract it as `Department_name`. Leave it in the question unchanged.

### Technical_format
A movie technical format, technology, or process — covers sound systems, color technologies, film technologies, sound technologies, and film formats stored in the `T_WC_T2S_TECHNICAL` reference table.

Surface forms include (non-exhaustive):
- Sound systems: `dolby`, `stereo`, `dts`, `sdds`, `mono`, `5.1`, `7.1`, `imax`, `auro`
- Color technologies: `technicolor`, `eastmancolor`, `metrocolor`, `fujicolor`, `agfacolor`, `warnercolor`, `kodachrome`, `deluxe`, `cinecolor`, `gevacolor`, `pathécolor`, `trucolor`, `sovcolor`, `anscocolor`, `gasparcolor`, `colorfilm`
- Film technologies: `cinemascope`, `panavision`, `vistavision`, `super_35`, `super_16`, `techniscope`, `technovision`, `ultra_panavision`, `panaflex`, `technirama`, `tohoscope`, `todd_ao`, `cinerama`, `polyvision`, `arriflex`, `panoramique`, `d_cinema`
- Sound technologies: `western_electric`, `westrex`, `photophone`, `tobis_klangfilm`, `vitaphone`, `perspecta`, `movietone`
- Film formats: `35 mm`, `16 mm`, `65 mm`, `70 mm`, `digital`, `dcp`, `franscope`

Examples:
- `IMAX`
- `Technicolor`
- `35mm`
- `Dolby`
- `cinemascope`

Disambiguation:
- Extract `Technical_format` only when the question filters or asks about a specific technical format, technology, or process (e.g., "movies shot in IMAX", "Technicolor films", "films tournés en franscope", "70mm releases").
- Common synonyms / format variants ("35mm", "70mm", "scope", "imax format", "5.1 surround", "dolby digital", "super 35", "todd-ao", "d-cinema") are accepted at resolution time and resolve to the canonical value above.
- If the user writes a format that is not in the supported lists above and not a known alias, do NOT extract it as `Technical_format`. Leave the word in the question unchanged.

## Important Extraction Rules

### General
- Extract only named entities or compact topic expressions that matter for anonymization
- Do not extract generic words such as `movie`, `film`, `series`
- **Crew** job titles (`director`, `cinematographer`, `editor`, `writer`, `producer`, `creator`, `réalisateur`, `scénariste`, etc.) ARE extracted as `Department_name` when they appear as a filter for a person search or a crew search — see the dedicated `Department_name` section above
- **Acting / cast** roles (`actor`, `actors`, `actress`, `actresses`, `acteur`, `acteurs`, `actrice`, `actrices`, `cast`) are NOT extracted — leave them in the question; the text-to-SQL step routes them via `CREDIT_TYPE = 'cast'` directly
- Do not normalize or canonicalize names; later steps will handle resolution
- If two different entities of the same type appear, number them in order of appearance, for example `Person_name1`, `Person_name2`

### Movie title with release year
When the user writes `Title (Year)`, extract both:
- `Movie_titleN`: the title without the year
- `Release_yearN`: the 4-digit year inside parentheses

### Topic_name boundaries
Do not extract as `Topic_name`:
- simple genre names by themselves (extract as `Genre_name` instead when they match the supported list, e.g. `war`, `comedy`, `Sci-Fi & Fantasy`)
- vague descriptive phrases that are not recognizable topics or collections
- technical specifications when the question is about the technical aspect itself
- `silent films`, `sound films`, `black and white films`, `color films`
- `Criterion Collection` by itself
- film movements or styles such as `Film Noir`, `French New Wave`, `New Hollywood`, `Cinéma vérité`, `Surrealism`, `Pre-Code movies`
- trilogies or named series of works such as `Dollars Trilogy`, `James Bond Collection`, `Kill Bill - Saga`
- universes or franchises such as `Star Wars`, `Marvel Cinematic Universe`, `DC Extended Universe`, `Batman universe`, `Middle-Earth`, `Harry Potter movies`, `James Bond films` — use `Collection_name` instead
- notable curated film lists or TV series lists such as `Sight and Sound greatest films of all time`, `IMDb top 250 tv shows`, `Roger Ebert's Great Movies List`
- awards or recognitions such as `Academy Award for Best Picture`, `Palme d'Or`, `Primetime Emmy Award`
- award nominations such as `Academy Award for Best Picture`, `Palme d'Or`, `Primetime Emmy Award`

### Genre_name boundaries
Extract as `Genre_name` when the phrase is a single-word or short genre label from the supported movie or series genre lists above.
Do not extract as `Genre_name`:
- thematic topics that merely contain a genre word (e.g. `Vietnam war`, `World War II`, `space opera about the war`) — use `Topic_name`
- film movements or styles (e.g. `Film Noir`, `French New Wave`) — use `Movement_name`
- generic adjectives or descriptors that are not in the supported lists (e.g. `sad`, `feel-good`, `dark`)

### List_name boundaries
Extract as `List_name` when the phrase refers to a named, notable, curated ranking, selection, registry, canon, or editorial list of movies or TV series.
Do not extract as `List_name` for generic topics, franchises or universes (use `Collection_name`), trilogies, awards, or broad thematic collections.

### Award_name boundaries
Extract as `Award_name` when the phrase refers to a named award, prize, honor, recognition, or award franchise associated with movies, TV series, people, or organizations.
Do not extract as `Award_name` for film movements, franchises, trilogies, generic themes, or curated ranking lists.

### Nomination_name boundaries
Extract as `Nomination_name` when the phrase refers to a named award nomination or nomination franchise associated with movies, TV series, people, or organizations.
Do not extract as `Nomination_name` for film movements, franchises, trilogies, generic themes, curated ranking lists, or already-awarded recognitions.

### Collection_name boundaries
Extract as `Collection_name` when the phrase refers to a trilogy, named series of works, universe, or franchise grouping movies or TV series together (e.g., `Dollars Trilogy`, `Kill Bill - Saga`, `Star Wars`, `Marvel Cinematic Universe`, `DC Extended Universe`, `Batman universe`, `Middle-Earth`, `Harry Potter movies`, `James Bond films`).
Do not extract as `Collection_name` for generic topics, awards, nominations, `Criterion Collection` by itself, or curated ranking lists.

### Movement_name boundaries
Extract as `Movement_name` when the phrase refers to a named film movement, cinematic style, or historical school of filmmaking.
Do not extract as `Movement_name` for franchises, universes, trilogies, recurring character collections, awards, nominations, or curated ranking lists.

### Group_name boundaries
Extract as `Group_name` when the phrase refers to an organization, club, publication group, collective, or musical/comedy group associated with a person.
Do not extract as `Group_name` for companies, networks, franchises, topics, awards, nominations, movements, or curated ranking lists.

### Aspect_ratio boundaries
Extract as `Aspect_ratio` when the phrase refers to a movie aspect ratio by its decimal form (`2.35`, `1.85`, `1.37`), its named convention (`Academy ratio`, `widescreen`, `anamorphic`, `scope`, `fullscreen`), or its `width:height` form (`16:9`, `4:3`, `2.35:1`, `2.40:1`).
Do not extract as `Aspect_ratio` for film formats (`35 mm`, `70 mm`, `IMAX`) — those are `Technical_format`.
Do not extract as `Aspect_ratio` for unrelated numeric values mentioned in the question (release years, runtimes, budgets, ratings, IDs).

### Department_name boundaries
Extract as `Department_name` when the phrase refers to a film/TV **crew** department or job category by name (e.g., `directors`, `cinematographers`, `editors`, `producers`, `creators`, `réalisateurs`, `scénaristes`, `monteurs`).
Do **NOT** extract as `Department_name`:
- `actor`, `actors`, `actress`, `actresses`, `acteur(s)`, `actrice(s)`, `cast`, or any other acting/cast role — Acting is not part of the crew vocabulary; the text-to-SQL step handles actor queries via `CREDIT_TYPE = 'cast'` directly.
- Verb phrasings the text-to-SQL step already handles inline (e.g., `directed by X`, `written by X`, `edited by X`) — those need only `Person_name`.
- Fine-grained job titles not in the supported canonical crew list (e.g., `gaffer`, `boom operator`, `colorist`) — leave them in the question unchanged.

### Death_name boundaries
Extract as `Death_name` when the phrase refers to a named medical cause of death or a named legal/general circumstance of a person's death.
Do not extract as `Death_name` for diseases, injuries, crimes, or accidents when they are mentioned only as generic themes or topics rather than as a death classification used to describe a person's death.

### Do not extract these as entities unless they are explicit identifiers or exact supported placeholder values
- spoken languages
- countries or nationalities used only as descriptive filters

If such information appears, keep it in the anonymized `question` unchanged.

Technical formats and technologies (`Technicolor`, `Dolby`, `IMAX`, `35 mm`, `cinemascope`, etc.) are now extracted as `Technical_format` placeholders — see the dedicated section above.

## Examples

Input: `List all movies with Humphrey Bogart`
Output:
{
  "question": "List all movies with {{Person_name1}}",
  "Person_name1": "Humphrey Bogart"
}

Input: `Vietnam war movies`
Output:
{
  "question": "{{Topic_name1}} movies",
  "Topic_name1": "Vietnam war"
}

Input: `List war movies`
Output:
{
  "question": "List {{Genre_name1}} movies",
  "Genre_name1": "war"
}

Input: `Show me Sci-Fi & Fantasy series`
Output:
{
  "question": "Show me {{Genre_name1}} series",
  "Genre_name1": "Sci-Fi & Fantasy"
}

Input: `Comedy movies directed by Woody Allen`
Output:
{
  "question": "{{Genre_name1}} movies directed by {{Person_name1}}",
  "Genre_name1": "Comedy",
  "Person_name1": "Woody Allen"
}

Input: `Star Wars movies`
Output:
{
  "question": "{{Collection_name1}} movies",
  "Collection_name1": "Star Wars"
}

Input: `Marvel Cinematic Universe movies`
Output:
{
  "question": "{{Collection_name1}} movies",
  "Collection_name1": "Marvel Cinematic Universe"
}

Input: `Middle-Earth movies`
Output:
{
  "question": "{{Collection_name1}} movies",
  "Collection_name1": "Middle-Earth"
}

Input: `Harry Potter movies`
Output:
{
  "question": "{{Collection_name1}} movies",
  "Collection_name1": "Harry Potter movies"
}

Input: `Films récompensés aux oscars`
Output:
{
  "question": "Films récompensés aux {{Award_name1}}",
  "Award_name1": "oscars"
}

Input: `French New Wave films directed by François Truffaut`
Output:
{
  "question": "{{Movement_name1}} films directed by {{Person_name1}}",
  "Movement_name1": "French New Wave",
  "Person_name1": "François Truffaut"
}

Input: `Movies having a Philip Marlowe character`
Output:
{
  "question": "Movies having a {{Topic_name1}} character",
  "Topic_name1": "Philip Marlowe"
}

Input: `Sergio Leone movies with Clint Eastwood`
Output:
{
  "question": "{{Person_name1}} movies with {{Person_name2}}",
  "Person_name1": "Sergio Leone",
  "Person_name2": "Clint Eastwood"
}

Input: `Show me all World War II movies directed by John Ford`
Output:
{
  "question": "Show me all {{Topic_name1}} movies directed by {{Person_name1}}",
  "Topic_name1": "World War II",
  "Person_name1": "John Ford"
}

Input: `Show me the Sight and Sound greatest films of all time`
Output:
{
  "question": "Show me the {{List_name1}}",
  "List_name1": "Sight and Sound greatest films of all time"
}

Input: `What TV series are in the IMDb top 250 tv shows?`
Output:
{
  "question": "What TV series are in the {{List_name1}}?",
  "List_name1": "IMDb top 250 tv shows"
}

Input: `Which movies won the Palme d'Or?`
Output:
{
  "question": "Which movies won the {{Award_name1}}?",
  "Award_name1": "Palme d'Or"
}

Input: `Which people received the Primetime Emmy Award?`
Output:
{
  "question": "Which people received the {{Award_name1}}?",
  "Award_name1": "Primetime Emmy Award"
}

Input: `Which movies were nominated for the Palme d'Or?`
Output:
{
  "question": "Which movies were nominated for the {{Nomination_name1}}?",
  "Nomination_name1": "Palme d'Or"
}

Input: `Which people were nominated for the Primetime Emmy Award?`
Output:
{
  "question": "Which people were nominated for the {{Nomination_name1}}?",
  "Nomination_name1": "Primetime Emmy Award"
}

Input: `Which movies are in the Dollars Trilogy?`
Output:
{
  "question": "Which movies are in the {{Collection_name1}}?",
  "Collection_name1": "Dollars Trilogy"
}

Input: `Show me the James Bond Collection`
Output:
{
  "question": "Show me the {{Collection_name1}}",
  "Collection_name1": "James Bond Collection"
}

Input: `French New Wave films directed by François Truffaut`
Output:
{
  "question": "{{Movement_name1}} films directed by {{Person_name1}}",
  "Movement_name1": "French New Wave",
  "Person_name1": "François Truffaut"
}

Input: `Show me Film Noir movies`
Output:
{
  "question": "Show me {{Movement_name1}} movies",
  "Movement_name1": "Film Noir"
}

Input: `Which people were members of The Beatles?`
Output:
{
  "question": "Which people were members of {{Group_name1}}?",
  "Group_name1": "The Beatles"
}

Input: `Show me people who worked for Les Cahiers du Cinéma`
Output:
{
  "question": "Show me people who worked for {{Group_name1}}",
  "Group_name1": "Les Cahiers du Cinéma"
}

Input: `Which people died from liver cirrhosis?`
Output:
{
  "question": "Which people died from {{Death_name1}}?",
  "Death_name1": "liver cirrhosis"
}

Input: `Show me people whose death was caused by a car collision`
Output:
{
  "question": "Show me people whose death was caused by {{Death_name1}}",
  "Death_name1": "car collision"
}

Input: `Which people died by homicide?`
Output:
{
  "question": "Which people died by {{Death_name1}}?",
  "Death_name1": "homicide"
}

Input: `The Exorcist (1973)`
Output:
{
  "question": "{{Movie_title1}} ({{Release_year1}})",
  "Movie_title1": "The Exorcist",
  "Release_year1": "1973"
}

Input: `What movies used the Technicolor technology?`
Output:
{
  "question": "What movies used the {{Technical_format1}} technology?",
  "Technical_format1": "Technicolor"
}

Input: `Films shot in IMAX`
Output:
{
  "question": "Films shot in {{Technical_format1}}",
  "Technical_format1": "IMAX"
}

Input: `Movies released in 35mm and 70mm`
Output:
{
  "question": "Movies released in {{Technical_format1}} and {{Technical_format2}}",
  "Technical_format1": "35mm",
  "Technical_format2": "70mm"
}

Input: `Les films tournés en franscope`
Output:
{
  "question": "Les films tournés en {{Technical_format1}}",
  "Technical_format1": "franscope"
}

Input: `Dolby surround movies`
Output:
{
  "question": "{{Technical_format1}} movies",
  "Technical_format1": "Dolby surround"
}

Input: `Movies shot in 2.35:1`
Output:
{
  "question": "Movies shot in {{Aspect_ratio1}}",
  "Aspect_ratio1": "2.35:1"
}

Input: `Academy ratio films`
Output:
{
  "question": "{{Aspect_ratio1}} films",
  "Aspect_ratio1": "Academy ratio"
}

Input: `Widescreen movies`
Output:
{
  "question": "{{Aspect_ratio1}} movies",
  "Aspect_ratio1": "Widescreen"
}

Input: `Films in 16:9`
Output:
{
  "question": "Films in {{Aspect_ratio1}}",
  "Aspect_ratio1": "16:9"
}

Input: `Anamorphic movies directed by Steven Spielberg`
Output:
{
  "question": "{{Aspect_ratio1}} movies directed by {{Person_name1}}",
  "Aspect_ratio1": "Anamorphic",
  "Person_name1": "Steven Spielberg"
}

Input: `What are Japanese speaking movies?`
Output:
{
  "question": "What are Japanese speaking movies?"
}

Input: `List released movies`
Output:
{
  "question": "List {{Status_name1}} movies",
  "Status_name1": "Released"
}

Input: `Show me canceled series`
Output:
{
  "question": "Show me {{Status_name1}} series",
  "Status_name1": "Canceled"
}

Input: `Movies still in production`
Output:
{
  "question": "Movies still in {{Status_name1}}",
  "Status_name1": "In Production"
}

Input: `Best documentary series of all time`
Output:
{
  "question": "Best {{Serie_type1}} series of all time",
  "Serie_type1": "Documentary"
}

Input: `What miniseries did HBO produce?`
Output:
{
  "question": "What {{Serie_type1}} did {{Network_name1}} produce?",
  "Serie_type1": "Miniseries",
  "Network_name1": "HBO"
}

Input: `List directors`
Output:
{
  "question": "List {{Department_name1}}",
  "Department_name1": "Directing"
}

Input: `List actors`
Output:
{
  "question": "List actors"
}

Input: `Actresses in The Big Lebowski`
Output:
{
  "question": "Actresses in {{Movie_title1}}",
  "Movie_title1": "The Big Lebowski"
}

Input: `Show me cinematographers`
Output:
{
  "question": "Show me {{Department_name1}}",
  "Department_name1": "cinematographers"
}

Input: `People known for Visual Effects`
Output:
{
  "question": "People known for {{Department_name1}}",
  "Department_name1": "Visual Effects"
}

Input: `Films with crew in the Sound department`
Output:
{
  "question": "Films with crew in the {{Department_name1}} department",
  "Department_name1": "Sound"
}

Input: `Réalisateurs nés en 1962`
Output:
{
  "question": "{{Department_name1}} nés en {{Birth_year1}}",
  "Department_name1": "Réalisateurs",
  "Birth_year1": "1962"
}

Input: `Actors born in 1962`
Output:
{
  "question": "Actors born in {{Birth_year1}}",
  "Birth_year1": "1962"
}

Input: `Directors who died in 1980`
Output:
{
  "question": "{{Department_name1}} who died in {{Death_year1}}",
  "Department_name1": "Directors",
  "Death_year1": "1980"
}

Input: `What is the movie with IMDb ID tt0038355?`
Output:
{
  "question": "What is the movie with IMDb ID {{IMDb_ID1}}?",
  "IMDb_ID1": "tt0038355"
}

Input: `Show me the person with IMDb ID nm0000007`
Output:
{
  "question": "Show me the person with IMDb ID {{IMDb_person_ID1}}",
  "IMDb_person_ID1": "nm0000007"
}

Input: `What is Wikidata item Q28385?`
Output:
{
  "question": "What is Wikidata item {{Wikidata_ID1}}?",
  "Wikidata_ID1": "Q28385"
}

Input: `Movies tagged with Wikidata property P136`
Output:
{
  "question": "Movies tagged with Wikidata property {{Wikidata_property_ID1}}",
  "Wikidata_property_ID1": "P136"
}

Input: `What is the TMDb movie 550?`
Output:
{
  "question": "What is the TMDb movie {{TMDb_ID1}}?",
  "TMDb_ID1": "550"
}

Input: `What is Criterion spine number 1?`
Output:
{
  "question": "What is Criterion spine number {{Criterion_spine_ID1}}?",
  "Criterion_spine_ID1": "1"
}

## User Question
{user_question}