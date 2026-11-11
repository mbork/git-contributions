# * Overview
"""Common words: loading the list and telling whether a word is common.

Words are raw LaTeX tokens, so `$a$` counts as the common word "a" and `\\emph{the` as
uncommon; both are rare enough not to matter.  Contractions (don't, it's) are not in the
default list; the project is formal prose."""

# * Imports
from pathlib import Path

from contrib.cli import ContribError

# * Constants
DEFAULT_FILE = Path(__file__).resolve().parent.parent / 'common-words.txt'


# * Loading
def load(path=None):
    """The set of common words in PATH (default: the shipped list), lowercased.

    One word per line; text after # is a comment; blank lines are ignored."""
    file_path = Path(path) if path is not None else DEFAULT_FILE
    try:
        text = file_path.read_text(encoding='utf-8')
    except OSError as error:
        raise ContribError(f'cannot read the common-words file {file_path}: {error}') from None
    words = set()
    for line in text.splitlines():
        word = line.split('#', 1)[0].strip().lower()
        if word:
            words.add(word)
    return words


# * Matching
def core(token):
    """TOKEN without its leading and trailing non-letters, lowercased."""
    start = 0
    end = len(token)
    while start < end and not token[start].isalpha():
        start += 1
    while end > start and not token[end - 1].isalpha():
        end -= 1
    return token[start:end].lower()


def is_common(token, common):
    """Whether TOKEN is in COMMON once stripped of surrounding non-letters."""
    return core(token) in common
