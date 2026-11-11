# `surviving_text.py`: everything one author wrote that is still in the project

## In plain words

This script shows, sentence by sentence, the text one author wrote that is still in the
project.  Git, which keeps the project, records every change anybody made; the script follows
every word of the project through that record back to the person who typed it.

The report starts with statistics -- how many of the project's words, sentences, formulas and
paragraphs are the author's -- and then lists every sentence, heading and displayed formula
that contains at least one of the author's words, one per line, in the order of the project,
grouped by chapter and section.
Each line says which file and line of the source it comes from.

Words by other authors are replaced by `[...]`.  For example, if Alice wrote

    We prove the lemma by induction on the number of vertices.

and Bob later changed it to

    We prove the lemma by a simple counting argument.

then Alice's line in her report is

    We prove the lemma by [...]

and Bob's is

    [...] a simple counting argument.

**Moving text does not count here.**  If Carol wrote a paragraph and Bob moved it to
another chapter, the paragraph is still Carol's, and appears in Carol's report (in its new
place), not in Bob's.

Formulas, commands and headings appear as they are typed in the LaTeX source, with one
space between words.

### Caveats

- Only what Git records counts: text the author wrote but someone else committed is not
  theirs here.
- A "word" is anything between spaces, so changing `word` to `word,` makes the whole word
  belong to whoever changed it.
- When someone heavily rewrites a sentence, small common words such as "the" or "a" that
  happen to stay in place keep their original author.  So a sentence that is really
  someone else's may show up as `[...] a [...] the [...]` in the original author's report.
- Text deleted in one commit and re-added in a later one belongs to whoever re-added it.

## Usage

    ./surviving_text.py --repo ~/books/graphs --main book.tex --author 'kowalski'
    ./surviving_text.py --repo ~/books/graphs --main book.tex --author 'kowalski' \
        --commit v1.0 --format latex

Options common to all scripts are described by `--help`; `--author` is required.

## How it works

The working copy, the replay of the history and the definitions of words, sentences,
formulas and paragraphs are those of `author_shares.py` and `author_profile.py` (see
their docs).  The replay gives the writer of every word in the project; a move keeps the
writer, so moves are never contributions here.

### Statistics

- words by the author, all and without common words (`common-words.txt` or
  `--common-words`);
- sentences and formulas written entirely by the author, and partly (some but not all
  words);
- paragraphs with at least one word by the author;
- the number of lines in the list.

Every share is of the corresponding total in the project.

### The list

The listed units are sentences, headings and displayed formulas, in project order.  A unit
is listed when at least one of its words is the author's.  Its line shows the author's
words joined by single spaces; every maximal run of other authors' words becomes one
`[...]`.  Units made only of structural macros (`\label{...}`, `\end{proof}`) are not listed,
though their words count in the statistics.

Lines are grouped by chapter (`\chapter`, or `\section` in a project without chapters) and,
inside it, by the innermost `\section` or `\subsection`; text directly under a chapter
heading is listed under the chapter itself.  Text before the first chapter (title page,
table of contents) is listed under "(before the first chapter)", and text right after a
`\part` heading under that part.  The location is the file and line of the unit's first
word.

### Trade-offs

- Sentence splitting is heuristic (abbreviations such as "e.g." are known; unusual ones
  may split a sentence in two).
- The source is shown with single spaces, so line breaks inside a sentence and LaTeX
  comments are not shown.  Verbatim text is shown as typed (including anything that looks
  like a comment in it).
