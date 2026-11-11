# `highlight_author.py`: the project with one author's words highlighted

## In plain words

This script produces the whole project as it was at a chosen moment, as one LaTeX file.  When
compiled, it looks like the project, except that every word one author wrote that is still
in it has a colored background:

- **light** for common words such as "the", "of", "let" or "assume", which say little about
  authorship;
- **strong** for all other words, and for short formulas written mostly by the author.

Git, which keeps the project, records every change anybody made; the script follows every
word of the project through that record back to the person who typed it.  **Moving text does
not count**: a paragraph moved by someone else keeps its writer's highlighting.

So, at a glance, you can see where the author's text is, and whether it is substance or
small connecting words.

### What is not highlighted

Some places cannot be highlighted without breaking the document, so they are left as
they are even if the author wrote them:

- headings (chapter and section titles), captions, footnotes, the title page;
- displayed formulas, and short formulas mostly written by others;
- references, citations, labels, URLs;
- tables, pictures (TikZ), program code and verbatim text;
- options in square brackets (such as the name of a theorem in `\begin{lemma}[...]`);
- words containing commands other than simple formatting (`\emph`, `\textbf`, ...), for
  example the author's own macros;
- the preamble (the setup part of the main file), even with `--include-preamble`.

The file starts with a comment saying how many of the author's words were highlighted and
how many were left out this way.

### Caveats

- Only what Git records counts: text the author wrote but someone else committed is not
  highlighted.
- A "word" is anything between spaces, so a word whose punctuation someone changed
  (`word` to `word,`) is no longer the author's.
- When someone heavily rewrites a sentence, small words that happen to stay in place
  keep their original author, so scattered "the" and "a" may be highlighted in sentences
  that are otherwise someone else's.

## Usage

    ./highlight_author.py --repo ~/books/graphs --main book.tex --author 'kowalski'
    ./highlight_author.py --repo ~/books/graphs --main book.tex --author 'kowalski' \
        --commit v1.0 --light-color 'green!15' --strong-color 'green!50'

The script prints the command to compile the file, for example

    TEXINPUTS=/home/me/books/graphs--contrib--v1-0-1a2b3c4//: \
      BIBINPUTS=/home/me/books/graphs--contrib--v1-0-1a2b3c4//: \
      lualatex highlight-author-jan-kowalski-v1-0.tex

The two variables let LaTeX find the project's other files (images, bibliography, classes) as
they were at the chosen commit; the working copy keeps them in its `tree/` directory.  Run
`bibtex` (or `biber`) between two `lualatex` runs if the project has a bibliography.

Options common to all scripts are described by `--help`; `--author` is required, and
`--format` does not exist here (the output is always LaTeX).  `--light-color` and
`--strong-color` take xcolor expressions (defaults `yellow!25` and `orange!55`).

### LuaLaTeX or pdfLaTeX

With LuaLaTeX and the packages `lua-ul` and `luacolor` installed, words are highlighted
with `lua-ul`'s `\highLight`, which keeps hyphenation, and the spaces between highlighted
words are colored too, so a highlighted passage reads as one band.  Otherwise (pdfLaTeX,
or missing packages) every highlighted word is a colored box and the spaces stay white;
highlighted words are never hyphenated, so some lines may come out a little loose.
Packages the project loads for pdfLaTeX (`inputenc`, for example) are usually harmless under
LuaLaTeX.

## How it works

The working copy, the replay of the history and the definitions of words, formulas and
units are those of the other scripts (see `docs/author_shares.md`).  The replay gives the
writer of every word in the project; a move keeps the writer.

### Flattening

Starting from the main file, every `\input` and `\include` (found as in the other
scripts) is replaced by the included file's text, recursively; `\include` becomes
`\clearpage`, the file, `\clearpage`.  A comment line marks where each file starts; the
inlined text ends with exactly one newline, as an input file does.  An `\endinput` in an
included file is honored: the rest of its line is kept, the rest of the file dropped.
Comments and everything else are kept as they are.

Nothing is highlighted in a file included from the preamble, or from a place where
highlighting is unsafe (inside a picture, display math, a fragile argument, and so on),
however it is included elsewhere.

Just before `\begin{document}`, the script adds `xcolor`, the two colors
(`contriblight`, `contribstrong`) and two macros.  `\contribhl{color}{text}` is
`\highLight[color]{text}` when LuaTeX, `lua-ul` and `luacolor` are available, and
`\colorbox{color}{\strut text}` otherwise.  `\contribgap{color}` replaces the blank
between two neighboring highlighted pieces when it is made of spaces and tabs with at most
one line break (no comment, no no-break or thin space, no form feed).  It is
`\highLight[color]{ }` -- strong between two strong pieces, light otherwise -- or a plain
space without `lua-ul`.  A real space keeps TeX's wider space after a sentence.

### What gets highlighted

Each highlighted piece is one word or one inline formula, wrapped in `\contribhl`, so that
a line can break between any two pieces.

- **Inline formulas** (`$...$`, `\(...\)`, `math`) are highlighted as a whole, strongly,
  when more than half of their words are the author's.  Words inside an inline formula
  are never highlighted one by one.
- **Words** are the author's words in the body (not the preamble).  A word is common when
  it is in the common-words list (`common-words.txt` or `--common-words`) once surrounding
  non-letters are stripped.

A word is left out when:

- it is part of a heading, a displayed formula, or a block of structural macros
  (`\label{...}`, `\end{proof}`);
- it contains `$ & # ^ _ [ ] %` (unescaped), a macro other than the text-formatting ones
  (`\emph`, `\textbf`, `\textit`, `\texttt`, `\ldots`, accented letters and the like),
  or a backslash followed by anything but a letter or a safe escape (`\,`, `\%`, `\&`,
  `\-`, accents ...) -- so `\\`, `\=` and a control space (`e.g.\ `) are out;
- its braces do not balance (as in `\emph{two` of `\emph{two words}`);
- it lies inside verbatim text or inline code (`\verb`, `\lstinline`, `\mintinline`),
  display math, an optional argument in square brackets after a command, the arguments of
  a fragile or non-text command (headings, `\caption`, `\footnote`, `\title`, `\author`,
  `\label`, `\ref`, `\cite`, `\url`, `\href`, `\mbox`, `\text`, definitions such as
  `\newcommand` or `\definecolor`, ...), or inside a `tikzpicture`, `tabular`, `array`,
  `tabbing`, `picture` and similar environment.  The command owning an argument is found
  by walking back over all its earlier arguments, however long.

The comment at the top of the file counts the author's words in the body and how many
were highlighted (inline formulas count with all their author's words).

### Trade-offs

- Highlighting is conservative: when in doubt a word is left alone, so that the file
  compiles.  The count of words left out shows how much that matters for the project.
- Each word is highlighted on its own (so that lines break between words even with the
  colored-box fallback); with `lua-ul` the spaces between them are colored separately.
- `\includeonly` in the preamble has no effect on the flattened file.
- A project whose packages do not work under LuaLaTeX can still be compiled with pdfLaTeX,
  with the colored-box fallback.
