#!/usr/bin/env bash
# Move the floating major-version tag (e.g. v0) onto a release tag (e.g. v0.17.0).
#
# docs/ci.md and docs/getting-started.md tell users to pin CI to
# stbenjam/skillsaw@v0. Both that action and stbenjam/skillsaw/review@v0
# resolve through this one tag, and the root action installs skillsaw from the
# checked-out action source -- so until the floating tag moves, every @v0 user
# keeps running the previous release.
set -euo pipefail

usage() {
    cat >&2 <<'EOF'
Usage: move-floating-tag.sh <release-tag> [--dry-run]

  release-tag   A vX.Y.Z tag that already exists locally (e.g. v0.17.0).
  --dry-run     Show what would happen without moving or pushing the tag.

Moves v<major> to the release tag's commit and force-pushes it to origin.
EOF
    exit 1
}

release_tag=""
dry_run=false

for arg in "$@"; do
    case "$arg" in
        --dry-run) dry_run=true ;;
        -h|--help) usage ;;
        -*) echo "Error: unknown option '$arg'" >&2; usage ;;
        *)
            if [[ -n "$release_tag" ]]; then
                echo "Error: unexpected extra argument '$arg'" >&2
                usage
            fi
            release_tag="$arg"
            ;;
    esac
done

[[ -n "$release_tag" ]] || usage

if [[ ! "$release_tag" =~ ^v([0-9]+)\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: '$release_tag' is not a vX.Y.Z release tag" >&2
    exit 1
fi

major="${BASH_REMATCH[1]}"
floating_tag="v$major"

# ^{commit} resolves both annotated and lightweight tags to the commit itself.
if ! target=$(git rev-parse --verify --quiet "${release_tag}^{commit}"); then
    echo "Error: release tag '$release_tag' not found locally -- run 'git fetch --tags' first" >&2
    exit 1
fi

if previous=$(git rev-parse --verify --quiet "${floating_tag}^{commit}"); then
    if [[ "$previous" == "$target" ]]; then
        echo "$floating_tag already points at $release_tag ($(git rev-parse --short "$target")) -- nothing to do"
        exit 0
    fi
    echo "Moving $floating_tag: $(git rev-parse --short "$previous") -> $(git rev-parse --short "$target") ($release_tag)"
else
    echo "Creating $floating_tag at $(git rev-parse --short "$target") ($release_tag)"
fi

if [[ "$dry_run" == true ]]; then
    echo "(dry run -- no tag written, nothing pushed)"
    exit 0
fi

git tag -f -a "$floating_tag" -m "Floating tag for latest v$major.x.x release" "$target"
git push -f origin "refs/tags/$floating_tag"

echo "Pushed $floating_tag -> $release_tag"
