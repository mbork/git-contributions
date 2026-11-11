# `author_profile.py`: one author's contribution, measured many ways

## In plain words

This script looks at **one author** and measures their part of the project in several ways,
because no single number tells the whole story.  Git, which keeps the project, records every
change anybody made; the script follows every word of the project through that record and
finds out who typed it.

It reports:

- **Words**: how many of the words in the project the author typed, and what share that is.
  The same once more without common words such as "the", "of", "let" or "assume" -- if
  the second share is much lower, the author's words are mostly the small ones.
- **Sentences, formulas, paragraphs**, each counted four ways: written entirely by the
  author; mostly (more than half of the words); with at least one word by the author; and
  "word-weighted", where a sentence half written by the author counts as half a sentence.
- **A fair estimate**: the same measure as `author_shares.py` -- writing a word that is in
  the project counts most, rewriting someone else's text a bit less, moving text little, and
  a draft someone else later rewrote still counts half.
- **A maximal estimate**: a figure that resolves every doubt in the author's favor, so that
  the author's share cannot exceed it under any reasonable definition.
- The author's words per chapter, and the names and e-mail addresses counted as theirs.

### The maximal estimate

The maximal estimate answers the question "could this author's share be bigger than X?"
with a figure nobody can reasonably dispute.  It is the largest of:

- the shares in the report (words, uncommon words, sentences, formulas and paragraphs
  with at least one word by the author, the fair share; the other shares are never
  larger),
- the **word-based estimate** (below), and
- the **line-based upper bound**: every word on every line the author ever added or
  changed, divided by the number of words in the project now.  In a project written one
  paragraph per line, fixing one typo counts the whole paragraph; text the author wrote and
  someone later deleted counts too; so does text in comments and in the preamble.

Why nobody can exceed it: say the author typed *T* words over the whole history, of which
some survived.  Even the most generous definition -- everything the author ever wrote,
compared with only what the others wrote that survived -- gives at most *T* / *N*, where *N*
is the number of words in the project.  The line-based count is at least *T*.

The **word-based estimate** is every word the author actually typed (counted word by word,
including text later deleted) divided by *N*.  It is closer to the truth, but on its own
it is not guaranteed: a word-level comparison can occasionally miss a word.  If the line-based bound
is much larger, the author did a lot of light editing across many paragraphs.

### An example

The project has 10 000 words.  Over the years the author wrote 500 words that are still in
the project and 300 that someone else later rewrote, and fixed one typo in each of 20
paragraphs of 100 words.

- Words: 500 + 20 = 520, so 5.2%.
- Word-based estimate: 500 + 300 + 20 = 820 words typed, so 8.2%.
- Line-based upper bound: 500 + 300 + 20 x 100 = 2 800 (if the 800 words the author wrote
  sat on lines containing no other words), so 28%.
- Maximal estimate: 28% (or more, if some other share in the report is higher).

### Caveats

- The author is defined by a regular expression matched against the names and e-mail
  addresses in the commits.  An identity it misses is not counted at all; check the list
  of identities at the end of the report.
- Text the author wrote but someone else committed is not theirs here, except that with
  `--all-branches` the maximal estimate also counts the author's commits on every branch
  still in the repository (work squash-merged by someone else, for example).
- Ideas, proofs worked out in discussion and reviewing are invisible.
- A word is any run of non-blank characters (`\emph{word},` and `$x^2$` are one word each).
  When someone heavily rewrites a sentence, common words that stay in place keep their
  original author.

## Usage

    ./author_profile.py --repo ~/books/graphs --main book.tex --author 'kowalski'
    ./author_profile.py --repo ~/books/graphs --main book.tex \
        --author 'Jan Kowalski|jkowalski@example\.org' --all-branches --format latex

Options common to all scripts are described by `--help`.  Specific to this script:
`--author` (required), `--all-branches`, and the weights of the fair measure
(`--weight-rewrite`, `--weight-move`, `--weight-removed`, as in `author_shares.py`).

## How it works

### The author

`--author` is a case-insensitive regular expression searched in `Name <email>` of every
commit's author, both as recorded and after `.mailmap`.  Every matching commit counts as
the author's; everybody else is grouped by name after `.mailmap`.

### Words and units

The working copy, the replay of the history and the definition of a word are those of
`author_shares.py` (see `docs/author_shares.md`).  The replay gives the writer of every word
in the project; moving text does not change it.

- **Common words** come from `common-words.txt` (or `--common-words`): one word per line,
  matched case-insensitively after stripping non-letters around the word.
- **Sentences** end at `.`, `?` or `!` followed (after closing brackets, quotes or `$`) by
  a space, except after known abbreviations (e.g., i.e., cf., Fig., ...) and inside
  formulas; a paragraph end also ends a sentence.  Headings are sentences of their own.
- **Formulas** are `$...$`, `\(...\)`, `$$...$$`, `\[...\]` and math environments
  (`equation`, `align`, `gather`, `multline`, `eqnarray`, ..., starred too).
- **Paragraphs** are separated by blank lines, `\par`, `\item`, headings, display formulas,
  `\begin` and `\end` of environments, and file boundaries.  Paragraphs made only of
  structural macros (`\label{...}`, `\end{proof}`) are not counted.

A unit's fraction is the share of its words written by the author.  "Entirely" means
fraction 1, "mostly" more than 1/2, "at least one word" more than 0, and "word-weighted" is
the sum of the fractions.

### The line-based upper bound

Read from the original repository (never modified): `git log -p -M --diff-merges=remerge`
over all `.tex` files in the history of the measured commit, counting the words on every
added line of every commit whose author matches.  For a merge, `remerge` shows what the
merge's author changed compared with an automatic merge, that is, the conflict
resolutions.  With `--all-branches`, the same is added for every commit reachable from any
ref, not in the history of the measured commit, and committed no later than it.

The preamble and comments are counted here even without `--include-preamble`: the bound
must never come out too low, so it counts everything.  Words are split exactly as the
replay splits them.  Every option that shapes the output is explicit (`--root`, no
signatures, no external diff), so that no Git configuration can make the bound smaller.
The candidates are capped at 100%.

### The word-based estimate

From the replay: every word the author typed in any commit of the history (comments
excluded, preamble excluded unless `--include-preamble`), including words later removed by
anybody and conflict resolutions in the author's merges.  Moved words are not typed.

### Trade-offs

- "At least one word" shares are generous by design: they feed the maximal estimate.
- The line-based bound can be far above the truth for an author who made many small edits;
  that is the price of being indisputable.
- Without `--all-branches`, work the author did on a branch that someone else squash-merged
  is credited to the person who squash-merged it.
