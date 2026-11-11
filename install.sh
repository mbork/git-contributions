#!/bin/sh
# * Overview
# Install git contrib for the current user: link git-contrib into ~/.local/bin and its
# manual page into ~/.local/share/man/man1.  Linux only, standard paths only; anything
# unusual aborts with a message instead of being worked around.

# * Settings
set -eu
# CDPATH would make cd print the directory, which would end up in $here.
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
bin_dir=$HOME/.local/bin
man_root=$HOME/.local/share/man
man_dir=$man_root/man1
command_source=$here/git_contrib.py
command_link=$bin_dir/git-contrib
page_source=$here/man/git-contrib.1
page_link=$man_dir/git-contrib.1

# * Helpers
usage() {
    cat >&2 <<EOF
usage: install.sh --install | --uninstall | --help

--install    link git-contrib into $bin_dir and its manual page into $man_dir
--uninstall  remove those two links
--help       show this message
EOF
}

die() {
    echo "install.sh: $*" >&2
    exit 1
}

# Whether $1 is a symbolic link pointing at $2.
is_our_link() {
    [ -L "$1" ] && [ "$(readlink "$1")" = "$2" ]
}

check_system() {
    [ "$(uname -s)" = Linux ] || die "only Linux is supported"
    for program in python3 git git-filter-repo manpath; do
        command -v "$program" >/dev/null 2>&1 || die "$program not found on PATH"
    done
    [ -d "$bin_dir" ] || die "$bin_dir does not exist; create it and put it on PATH"
    case ":$PATH:" in
        *":$bin_dir:"*) ;;
        *) die "$bin_dir is not on PATH; add it (in your shell's startup file) and retry" ;;
    esac
    [ -d "$man_root" ] || die "$man_root does not exist; create it and retry"
    hint="with $bin_dir on PATH, man-db normally adds it; or add it to MANPATH"
    case ":$(manpath 2>/dev/null):" in
        *":$man_root:"*) ;;
        *) die "$man_root is not on the manual path (see manpath): $hint" ;;
    esac
}

# Link $2 to $1, unless it already is; refuse to replace anything else.
link_ours() {
    if is_our_link "$2" "$1"; then
        echo "already installed: $2"
        return
    fi
    if [ -e "$2" ] || [ -L "$2" ]; then
        die "$2 exists and is not a link to $1; remove it first"
    fi
    ln -s "$1" "$2"
    echo "installed: $2 -> $1"
}

# Remove the link $2 if it points at $1; refuse to remove anything else.
unlink_ours() {
    if is_our_link "$2" "$1"; then
        rm "$2"
        echo "removed: $2"
    elif [ -e "$2" ] || [ -L "$2" ]; then
        die "$2 is not a link to $1; leaving it alone"
    else
        echo "not installed: $2"
    fi
}

# * Main
if [ $# -ne 1 ]; then
    usage
    exit 2
fi
case $1 in
    --install)
        check_system
        [ -d "$man_dir" ] || mkdir "$man_dir"
        link_ours "$command_source" "$command_link"
        link_ours "$page_source" "$page_link"
        echo "try: git contrib -h; man git-contrib"
        ;;
    --uninstall)
        unlink_ours "$command_source" "$command_link"
        unlink_ours "$page_source" "$page_link"
        ;;
    --help)
        usage
        ;;
    *)
        usage
        exit 2
        ;;
esac
