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
Trilogies or named series of works.
Examples: `Dollars Trilogy`, `James Bond Collection`, `Kill Bill - Saga`

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
- universes or franchises
- notable recurring character-based collections

Examples:
- `World War II`
- `Christmas`
- `kidnapping`
- `Marvel Cinematic Universe`
- `Star Wars`
- `Philip Marlowe`

### Genre_name
Extract `Genre_name` when the user question mentions a movie or TV series genre by its standard name.
The value MUST be one of the following supported genre names (case-insensitive, keep the original surface form when possible):

Movie genres:
- `Action`, `Adventure`, `Animation`, `Comedy`, `Crime`, `Drama`, `Family`, `Fantasy`, `History`, `Horror`, `Music`, `Mystery`, `Romance`, `Science Fiction`, `Sci-Fi`, `Thriller`, `TV Movie`, `War`, `Western`

TV series genres:
- `Action & Adventure`, `Animation`, `Comedy`, `Crime`, `Documentary`, `Drama`, `Family`, `History`, `Kids`, `Mystery`, `News`, `Reality`, `Romance`, `Sci-Fi & Fantasy`, `Soap`, `Talk`, `War & Politics`, `Western`

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

## Important Extraction Rules

### General
- Extract only named entities or compact topic expressions that matter for anonymization
- Do not extract generic words such as `movie`, `film`, `series`, `actor`, `director`
- Do not normalize or canonicalize names; later steps will handle resolution
- If two different entities of the same type appear, number them in order of appearance, for example `Person_name1`, `Person_name2`

### Movie title with release year
When the user writes `Title (Year)`, extract both:
- `Movie_titleN`: the title without the year
- `Release_yearN`: the 4-digit year inside parentheses

### Serie_type
If a series type is explicitly mentioned and should be extracted, it must be one of exactly:
- `Documentary`
- `Miniseries`
- `News`
- `Reality`
- `Scripted`
- `Talk Show`
- `Video`

### Topic_name boundaries
Do not extract as `Topic_name`:
- simple genre names by themselves (extract as `Genre_name` instead when they match the supported list, e.g. `war`, `comedy`, `Sci-Fi & Fantasy`)
- vague descriptive phrases that are not recognizable topics or collections
- technical specifications when the question is about the technical aspect itself
- `silent films`, `sound films`, `black and white films`, `color films`
- `Criterion Collection` by itself
- film movements or styles such as `Film Noir`, `French New Wave`, `New Hollywood`, `Cinéma vérité`, `Surrealism`, `Pre-Code movies`
- trilogies or named series of works such as `Dollars Trilogy`, `James Bond Collection`, `Kill Bill - Saga`
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
Do not extract as `List_name` for generic topics, franchises, trilogies, awards, or broad thematic collections.

### Award_name boundaries
Extract as `Award_name` when the phrase refers to a named award, prize, honor, recognition, or award franchise associated with movies, TV series, people, or organizations.
Do not extract as `Award_name` for film movements, franchises, trilogies, generic themes, or curated ranking lists.

### Nomination_name boundaries
Extract as `Nomination_name` when the phrase refers to a named award nomination or nomination franchise associated with movies, TV series, people, or organizations.
Do not extract as `Nomination_name` for film movements, franchises, trilogies, generic themes, curated ranking lists, or already-awarded recognitions.

### Collection_name boundaries
Extract as `Collection_name` when the phrase refers to a trilogy or named series of works grouping movies or TV series together.
Do not extract as `Collection_name` for generic topics, broad franchises or universes, awards, nominations, or curated ranking lists.

### Movement_name boundaries
Extract as `Movement_name` when the phrase refers to a named film movement, cinematic style, or historical school of filmmaking.
Do not extract as `Movement_name` for franchises, universes, trilogies, recurring character collections, awards, nominations, or curated ranking lists.

### Group_name boundaries
Extract as `Group_name` when the phrase refers to an organization, club, publication group, collective, or musical/comedy group associated with a person.
Do not extract as `Group_name` for companies, networks, franchises, topics, awards, nominations, movements, or curated ranking lists.

### Death_name boundaries
Extract as `Death_name` when the phrase refers to a named medical cause of death or a named legal/general circumstance of a person's death.
Do not extract as `Death_name` for diseases, injuries, crimes, or accidents when they are mentioned only as generic themes or topics rather than as a death classification used to describe a person's death.

### Do not extract these as entities unless they are explicit identifiers or exact supported placeholder values
- spoken languages
- countries or nationalities used only as descriptive filters
- technical formats or technologies such as `Technicolor`, `Dolby`, `IMAX`, `35 mm`

If such information appears, keep it in the anonymized `question` unchanged.

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
  "question": "{{Topic_name1}} movies",
  "Topic_name1": "Star Wars"
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
  "question": "What movies used the Technicolor technology?"
}

Input: `What are Japanese speaking movies?`
Output:
{
  "question": "What are Japanese speaking movies?"
}

## User Question
{user_question}