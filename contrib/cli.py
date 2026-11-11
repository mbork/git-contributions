# * Overview
"""Command-line handling shared by the scripts: options, usage, progress, timing, errors."""

# * Imports
import argparse
import re
import sys
import time
from pathlib import Path

# * Errors
class ContribError(Exception):
    """An error to report to the user without a traceback."""


# * Options
# Format names accepted by --format, the canonical name for each, and file extensions.
FORMATS = {'json': 'json', 'markdown': 'markdown', 'md': 'markdown',
           'latex': 'latex', 'tex': 'latex'}
EXTENSIONS = {'json': 'json', 'markdown': 'md', 'latex': 'tex'}


# The name shown in usage messages instead of the script's; git_contrib.py sets it to
# "git contrib <subcommand>".
PROG = None


def make_parser(prog, description, *, is_one_author, does_offer_format=True):
    """An argument parser with the options common to all scripts.

    PROG names the parser in usage messages; PROG (the module variable), when set,
    replaces it.

    Only long options; `--help` is added explicitly because argparse's default also
    defines `-h`."""
    shown_prog = PROG if PROG is not None else prog
    parser = argparse.ArgumentParser(prog=shown_prog, description=description, add_help=False,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_argument_group('common options')
    group.add_argument('--repo', metavar='DIR', default='.',
                       help='the measured repository, never modified (default: the one'
                            ' containing the current directory)')
    group.add_argument('--main', metavar='FILE',
                       help='the main .tex file, relative to the repository root (default:'
                            ' git config contrib.main of the repository)')
    group.add_argument('--commit', metavar='REV', default='HEAD',
                       help='branch, tag or hash to measure (default: %(default)s)')
    if is_one_author:
        group.add_argument('--author', metavar='REGEX', required=True,
                           help='case-insensitive regex matched against "Name <email>",'
                                ' both raw and after .mailmap; all matching identities'
                                ' count as one author')
    if does_offer_format:
        group.add_argument('--format', metavar='FORMAT', default='markdown',
                           choices=sorted(FORMATS),
                           help='json, markdown (md) or latex (tex) (default: %(default)s)')
    group.add_argument('--output', metavar='FILE',
                       help='output file (default: derived from the script, author and'
                            ' revision, in the current directory)')
    group.add_argument('--mailmap', metavar='FILE',
                       help='mailmap file (default: .mailmap at --commit, if any)')
    group.add_argument('--include-preamble', action='store_true',
                       help='also count the preamble as text')
    group.add_argument('--common-words', metavar='FILE',
                       help='list of common words, one per line (default: the'
                            ' common-words.txt shipped with the scripts)')
    group.add_argument('--help', action='help', help='show this message and exit')
    return parser


def parse_args(parser, argv=None):
    """Parse ARGV (default: the command line); print usage and exit when it is empty."""
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        parser.print_help(sys.stderr)
        sys.exit(2)
    args = parser.parse_args(argv)
    if getattr(args, 'format', None) is not None:
        args.format = FORMATS[args.format]
    return args


# * Output file names
def slug(text):
    """TEXT reduced to lowercase letters, digits and single dashes."""
    lowered = text.lower()
    dashed = re.sub(r'[^a-z0-9]+', '-', lowered)
    return dashed.strip('-') or 'x'


def output_path(args, script, ref, extension, author=None):
    """The --output file, or a default name built from the script, author and REF."""
    if args.output is not None:
        return Path(args.output)
    parts = [script.removesuffix('.py').replace('_', '-')]
    if author is not None:
        parts.append(slug(author))
    parts.append(slug(ref))
    return Path('-'.join(parts) + '.' + extension)


# * Progress
class Progress:
    """Progress messages on stderr, each stamped with the time elapsed since the start."""

    def __init__(self):
        self.start = time.monotonic()

    def elapsed(self):
        return time.monotonic() - self.start

    def log(self, message):
        print(f'[{self.elapsed():7.1f}s] {message}', file=sys.stderr, flush=True)

    def finish(self, path):
        self.log(f'report written to {path}')
        self.log(f'done in {self.elapsed():.1f} s')


# * Running a script
def run(main):
    """Call MAIN(progress), turning a ContribError or an interrupt into a short message."""
    progress = Progress()
    try:
        main(progress)
    except ContribError as error:
        print(f'error: {error}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print('interrupted', file=sys.stderr)
        sys.exit(130)
