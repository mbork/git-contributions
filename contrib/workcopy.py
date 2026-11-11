# * Overview
"""The working copy: a rewritten copy of the measured repository in a sibling directory.

The measured repository is only ever read.  The copy lives in
`<repo>--contrib--<ref>-<hash7>` next to it and holds:

- `repo.git/` -- a plain copy of the original `.git` (not a clone; no remotes, hooks or other
  configuration of the original; no symbolic links into it), reduced to the history of the
  measured commit and rewritten so that every `.tex` file has its comments dropped and one
  word per line;
- `tree/` -- the files of the measured commit, byte for byte as committed;
- `mailmap` -- `.mailmap` of the measured commit, if it has one;
- `meta.json` -- written last; a copy without it, or made by a different version of the
  rewrite, is rebuilt.

All scripts share the copy and reuse it on later runs.
"""

# * Imports
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from contrib import latex
from contrib.cli import ContribError, slug

# * Constants
LAYOUT_VERSION = 1          # bump when the layout of the copy changes
MARKER = '.contrib-workcopy'
TARGET_BRANCH = 'refs/heads/contrib-target'
SCRIPTS_ROOT = str(Path(__file__).resolve().parent.parent)


def rewrite_fingerprint():
    """A digest of the code that rewrites blobs: a copy made by other code is stale."""
    parts = [inspect.getsource(function) for function in
             (latex.rewrite_blob, latex.tokenize, latex.blank_comments, latex.verbatim_end,
              latex.decode, latex.encode)]
    parts += [repr(latex.VERBATIM_ENVS), latex.BEGIN_ENV.pattern, latex.VERB.pattern,
              latex.WORD.pattern, str(LAYOUT_VERSION)]
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()[:16]


# * Running git
def clean_environment():
    """The environment without GIT_* variables, which could point git at another repo."""
    return {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}


def git_command(args, git_dir=None):
    command = ['git']
    if git_dir is not None:
        command.append(f'--git-dir={git_dir}')
    return command + ['-c', 'core.quotePath=false', *args]


def git_failure(args, stderr):
    """A ContribError naming the git subcommand of ARGS (after any -c options)."""
    words = list(args)
    while len(words) >= 2 and words[0] == '-c':
        words = words[2:]
    message = stderr.decode(errors='replace').strip()
    return ContribError(f'git {" ".join(words[:2])} failed: {message}')


def mailmap_options(mailmap):
    """git options making MAILMAP (a path, or None for none) the only mailmap."""
    path = str(mailmap) if mailmap is not None else os.devnull
    return ['-c', f'mailmap.file={path}', '-c', 'mailmap.blob=']


def run_git(*args, cwd=None, git_dir=None, stdin=None):
    """Output of a git command as bytes; a failure becomes a ContribError."""
    result = subprocess.run(git_command(args, git_dir), cwd=cwd, input=stdin,
                            capture_output=True, env=clean_environment())
    if result.returncode != 0:
        raise git_failure(args, result.stderr)
    return result.stdout


def stream_git(*args, cwd=None, git_dir=None):
    """Lines (bytes, without the newline) of a git command's output, as it runs."""
    # stderr goes to a file: a full pipe nobody reads would block git.
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(git_command(args, git_dir), cwd=cwd,
                                   stdout=subprocess.PIPE, stderr=errors,
                                   env=clean_environment())
        for line in process.stdout:
            yield line.rstrip(b'\n')
        returncode = process.wait()
        errors.seek(0)
        error = errors.read()
    if returncode != 0:
        raise git_failure(args, error)


def run_git_text(*args, **kwargs):
    output = run_git(*args, **kwargs)
    return output.decode('utf-8', errors='replace').strip()


# * The rewrite
def filter_file_info(filename, mode, blob_id, value):
    """filter-repo callback: rewrite regular .tex files, keep everything else."""
    is_regular = mode in (b'100644', b'100755')
    if not is_regular or not filename.lower().endswith(b'.tex'):
        return (filename, mode, blob_id)
    contents = value.get_contents_by_identifier(blob_id)
    rewritten = latex.rewrite_blob(contents)
    return (filename, mode, value.insert_file_with_contents(rewritten))


CALLBACK = f"""
import sys
if {SCRIPTS_ROOT!r} not in sys.path:
    sys.path.insert(0, {SCRIPTS_ROOT!r})
from contrib.workcopy import filter_file_info
return filter_file_info(filename, mode, blob_id, value)
"""


# * The copy
@dataclass
class WorkCopy:
    original: Path          # top level of the measured repository
    ref: str                # --commit as given
    original_hash: str
    path: Path
    rewritten_hash: str = ''

    @property
    def git_dir(self):
        return self.path / 'repo.git'

    @property
    def tree(self):
        return self.path / 'tree'

    @property
    def mailmap(self):
        mailmap = self.path / 'mailmap'
        return mailmap if mailmap.is_file() else None

    def git(self, *args, **kwargs):
        """Run git in the copy."""
        return run_git(*args, git_dir=self.git_dir, **kwargs)

    def read_original(self, rel_path):
        """Text of REL_PATH at the measured commit, or None if there is no such file."""
        tree = self.tree.resolve()
        target = (tree / rel_path).resolve()
        if not target.is_relative_to(tree) or not target.is_file():
            return None
        return latex.decode(target.read_bytes())

    def original_of(self):
        """Mapping from rewritten commit hashes to the original ones."""
        mapping = {}
        commit_map = self.git_dir / 'filter-repo' / 'commit-map'
        for line in commit_map.read_text().splitlines()[1:]:
            old, new = line.split()
            mapping[new] = old
        return mapping


def copy_name(top, ref, commit):
    """Name of the sibling directory for REF (resolved to COMMIT) of the repo at TOP."""
    short = commit[:7]
    is_hex = re.fullmatch(r'[0-9a-fA-F]{4,40}', ref) is not None
    if is_hex and commit.startswith(ref.lower()):
        return f'{top.name}--contrib--{short}'
    return f'{top.name}--contrib--{slug(ref)}-{short}'


def locate(repo, ref):
    """The WorkCopy for REF of REPO, without building it."""
    repo_path = Path(repo).expanduser()
    if not repo_path.is_dir():
        raise ContribError(f'{repo} is not a directory')
    if ref.startswith('-'):
        raise ContribError(f'{ref!r} is not a valid revision')
    top = Path(run_git_text('rev-parse', '--show-toplevel', cwd=repo_path))
    try:
        commit = run_git_text('rev-parse', '--verify', '--quiet', ref + '^{commit}', cwd=top)
    except ContribError:
        raise ContribError(f'{ref!r} is not a commit in {top}') from None
    path = top.parent / copy_name(top, ref, commit)
    return WorkCopy(top, ref, commit, path)


def load_meta(work_copy):
    """The rewritten hash recorded by a complete, current copy, or None."""
    meta_file = work_copy.path / 'meta.json'
    if not meta_file.is_file():
        return None
    try:
        meta = json.loads(meta_file.read_text())
    except ValueError:
        return None
    if not isinstance(meta, dict) or not isinstance(meta.get('rewritten_hash'), str):
        return None
    if (meta.get('fingerprint') != rewrite_fingerprint()
            or meta.get('original_hash') != work_copy.original_hash):
        return None
    return meta['rewritten_hash']


def prepare(repo, ref, progress):
    """The working copy for REF of REPO, built if needed."""
    work_copy = locate(repo, ref)
    rewritten_hash = load_meta(work_copy)
    if rewritten_hash is not None:
        work_copy.rewritten_hash = rewritten_hash
        progress.log(f'reusing the working copy {work_copy.path}')
        return work_copy
    if work_copy.path.exists():
        if not (work_copy.path / MARKER).is_file():
            raise ContribError(f'{work_copy.path} exists but is not a working copy made by'
                               ' these scripts; move it away first')
        progress.log(f'removing the outdated or incomplete working copy {work_copy.path}')
        shutil.rmtree(work_copy.path)
    build(work_copy, progress)
    return work_copy


# * Building
def build(work_copy, progress):
    progress.log(f'creating the working copy {work_copy.path}')
    work_copy.path.mkdir()
    (work_copy.path / MARKER).write_text('Working copy of the contribution scripts; safe to'
                                         ' delete.\n')
    common_dir = Path(run_git_text('rev-parse', '--path-format=absolute', '--git-common-dir',
                                   cwd=work_copy.original))
    progress.log('copying the repository')
    # Symbolic links are followed, never copied: a link into the original would let the
    # writes below reach it.
    shutil.copytree(common_dir, work_copy.git_dir, symlinks=False)
    check_no_links(work_copy.git_dir)
    isolate(work_copy, common_dir)
    progress.log('rewriting the history (one word per line); this may take a while')
    try:
        work_copy.git('filter-repo', '--force', '--quiet', '--prune-empty', 'never',
                      '--prune-degenerate', 'never', '--file-info-callback', CALLBACK,
                      cwd=work_copy.git_dir)
    except ContribError as error:
        raise ContribError(f'{error} (is git-filter-repo 2.47 or later installed?)') from None
    work_copy.rewritten_hash = run_git_text('rev-parse', '--verify', TARGET_BRANCH,
                                            git_dir=work_copy.git_dir)
    progress.log('extracting the files of the measured commit')
    extract_tree(work_copy)
    write_meta(work_copy)


def check_no_links(git_dir):
    for root, dirs, files in os.walk(git_dir):
        for name in dirs + files:
            if os.path.islink(os.path.join(root, name)):
                raise ContribError(f'{os.path.join(root, name)} is a symbolic link; refusing'
                                   ' to use a copy that could write into the original')


def isolate(work_copy, common_dir):
    """Cut the copy off from the original: a fresh configuration (no remotes, includes,
    filters or hooks), no worktrees, no earlier filter-repo state, only the target ref."""
    git_dir = work_copy.git_dir
    format_version = original_config(common_dir, 'core.repositoryformatversion') or '0'
    extensions = original_config_regexp(common_dir, r'^extensions\.')
    shutil.rmtree(git_dir / 'worktrees', ignore_errors=True)
    shutil.rmtree(git_dir / 'filter-repo', ignore_errors=True)
    (git_dir / 'config').write_text('')
    settings = [('core.repositoryformatversion', format_version), ('core.bare', 'true'),
                ('core.hooksPath', os.devnull), *extensions]
    for key, value in settings:
        run_git('config', key, value, git_dir=git_dir)
    absolutize_alternates(git_dir, common_dir)
    refs = run_git_text('for-each-ref', '--format=%(refname)', git_dir=git_dir).split()
    commands = ''.join(f'delete {ref}\n' for ref in refs)
    commands += f'create {TARGET_BRANCH} {work_copy.original_hash}\n'
    run_git('update-ref', '--no-deref', '--stdin', git_dir=git_dir, stdin=commands.encode())
    run_git('symbolic-ref', 'HEAD', TARGET_BRANCH, git_dir=git_dir)


def original_config(common_dir, key):
    config = common_dir / 'config'
    result = subprocess.run(['git', 'config', '--file', str(config), '--get', key],
                            capture_output=True, env=clean_environment())
    return result.stdout.decode().strip() if result.returncode == 0 else None


def original_config_regexp(common_dir, pattern):
    """(key, value) pairs of the original's own config file whose keys match PATTERN."""
    config = common_dir / 'config'
    result = subprocess.run(['git', 'config', '--file', str(config), '--null',
                             '--get-regexp', pattern], capture_output=True,
                            env=clean_environment())
    pairs = []
    for entry in result.stdout.decode().split('\0'):
        if entry:
            key, _, value = entry.partition('\n')
            pairs.append((key, value))
    return pairs


def absolutize_alternates(git_dir, common_dir):
    """Relative alternates point into the original's object store; make them absolute."""
    alternates = git_dir / 'objects' / 'info' / 'alternates'
    if not alternates.is_file():
        return
    original_objects = common_dir / 'objects'
    lines = []
    for line in alternates.read_text().splitlines():
        if line and not line.startswith('#') and not os.path.isabs(line):
            line = str((original_objects / line).resolve())
        lines.append(line)
    alternates.write_text('\n'.join(lines) + '\n')


def extract_tree(work_copy):
    """The files of the measured commit into tree/, exactly as committed (no attributes,
    filters or line-ending conversion), and .mailmap next to it.  Symbolic links and
    submodules are skipped."""
    listing = run_git('ls-tree', '-r', '-z', '--full-tree', work_copy.original_hash,
                      cwd=work_copy.original)
    entries = []
    for entry in listing.split(b'\0'):
        if not entry:
            continue
        meta, _, name = entry.partition(b'\t')
        mode, kind, blob = meta.split()
        if kind == b'blob' and mode in (b'100644', b'100755'):
            entries.append((blob.decode(), name.decode('utf-8', errors='surrogateescape')))
    work_copy.tree.mkdir()
    names = '\n'.join(blob for blob, _ in entries).encode()
    contents = run_git('cat-file', '--batch', cwd=work_copy.original, stdin=names + b'\n')
    position = 0
    for blob, name in entries:
        header_end = contents.index(b'\n', position)
        size = int(contents[position:header_end].split()[2])
        data = contents[header_end + 1:header_end + 1 + size]
        position = header_end + 1 + size + 1
        target = work_copy.tree / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    mailmap = work_copy.tree / '.mailmap'
    if mailmap.is_file():
        shutil.copyfile(mailmap, work_copy.path / 'mailmap')


def write_meta(work_copy):
    meta = {'fingerprint': rewrite_fingerprint(), 'original_repo': str(work_copy.original),
            'ref': work_copy.ref, 'original_hash': work_copy.original_hash,
            'rewritten_hash': work_copy.rewritten_hash}
    temporary = work_copy.path / 'meta.json.tmp'
    temporary.write_text(json.dumps(meta, indent=2) + '\n')
    temporary.replace(work_copy.path / 'meta.json')
