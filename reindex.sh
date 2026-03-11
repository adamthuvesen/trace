#!/bin/bash

# Convenient index rebuild script for local knowledge bases
#
# Usage:
#   ./reindex.sh --kb-path ~/docs                # Rebuild index for a local folder
#   ./reindex.sh --kb-path ~/docs --model ...    # Use a specific embedding model
#   ./reindex.sh published-docs                  # Example preset (edit paths in this script)
#   ./reindex.sh all                             # Rebuild every configured preset
#   ./reindex.sh                                 # Show usage and available presets
#
# Options:
#   -k, --kb-path PATH          Folder to index
#   -i, --index-path PATH       Store indexes outside the knowledge-base folder
#   -e, --exclude-patterns CSV  Comma-separated exclude patterns
#   -m, --model MODEL           Use specific model (default: all-MiniLM-L6-v2)
#   -l, --list                  List legacy preset repositories
#   -h, --help                  Show this help

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Default model (best quality based on benchmarks)
DEFAULT_MODEL="all-MiniLM-L6-v2"

# ─────────────────────────────────────────────────────────────────────────────
# Repository configurations
# ─────────────────────────────────────────────────────────────────────────────

get_repo_config() {
    local name=$1
    case "$name" in
        published-docs)
            echo "$HOME/knowledge/published|target/compiled"
            ;;
        app-context)
            echo "$HOME/knowledge/app-context|node_modules,.venv,__pycache__,.next,.git,.mcp-search,target/compiled"
            ;;
        notes)
            echo "$HOME/knowledge/notes|.obsidian"
            ;;
        *)
            echo ""
            ;;
    esac
}

ALL_REPOS="published-docs app-context notes"

# ─────────────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────────────

show_help() {
    cat << EOF
Semantic Search Index Rebuild Tool

Usage:
  ./reindex.sh --kb-path PATH [OPTIONS]
  ./reindex.sh [OPTIONS] <preset|all>

Generic mode:
  --kb-path PATH        Folder to index
  --index-path PATH     Optional external index location
  --exclude-patterns    Optional comma-separated excludes

Example presets (edit get_repo_config() to match your machine):
  published-docs   Primary documentation tree
  app-context      Secondary repo with build artifacts excluded
  notes            Personal notes (e.g. Obsidian vault)
  all              Rebuild all preset repositories

Options:
  -k, --kb-path PATH          Folder to index
  -i, --index-path PATH       Store indexes outside the knowledge-base folder
  -e, --exclude-patterns CSV  Comma-separated exclude patterns
  -m, --model MODEL           Embedding model (default: $DEFAULT_MODEL)
  -l, --list                  List legacy presets with paths
  -h, --help                  Show this help

Examples:
  ./reindex.sh --kb-path ~/docs
  ./reindex.sh --kb-path ~/docs --index-path ~/.cache/mcp-search/docs
  ./reindex.sh --kb-path ~/docs --exclude-patterns node_modules,.git,.venv
  ./reindex.sh published-docs    # Example preset
  ./reindex.sh notes             # Example preset
  ./reindex.sh all               # Rebuild all presets
EOF
}

list_repos() {
    echo "Legacy Preset Repositories:"
    echo ""
    printf "%-10s %s\n" "NAME" "PATH"
    echo "─────────────────────────────────────────────────────────────────────"

    for name in $ALL_REPOS; do
        config=$(get_repo_config "$name")
        path="${config%%|*}"
        printf "%-10s %s\n" "$name" "$path"
    done
    echo ""
}

run_index_build() {
    local label=$1
    local kb_path=$2
    local index_path=$3
    local excludes=$4
    local model=$5
    local env_vars

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Rebuilding: $label"
    echo "  Path: $kb_path"
    echo "  Index: $index_path"
    echo "  Model: $model"
    [ -n "$excludes" ] && echo "  Excludes: $excludes"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    mkdir -p "$index_path"

    env_vars=(
        "EMBEDDING_MODEL=$model"
        "KB_PATH=$kb_path"
        "INDEX_PATH=$index_path"
    )

    if [ -n "$excludes" ]; then
        env_vars+=("EXCLUDE_PATTERNS=$excludes")
    fi

    env "${env_vars[@]}" uv run python -c "
from trace_search.indexer import WikiIndexer
from datetime import datetime
import os

start = datetime.now()
indexer = WikiIndexer(os.environ['KB_PATH'])
count = indexer.build_index(force=True)
elapsed = (datetime.now() - start).total_seconds()
docs = len(indexer.load_documents())

print(f'✅ {count:,} chunks from {docs:,} documents in {elapsed:.1f}s')
"

    echo ""
}

rebuild_repo() {
    local name=$1
    local model=$2
    local config
    local kb_path
    local excludes
    local index_path

    config=$(get_repo_config "$name")
    if [ -z "$config" ]; then
        echo "Error: Unknown repository '$name'"
        echo "Run './reindex.sh --list' to see available repositories"
        return 1
    fi

    kb_path="${config%%|*}"
    kb_path="${kb_path/#\~/$HOME}"
    excludes="${config#*|}"
    index_path="$kb_path/.mcp-search/indexes"

    run_index_build "$name" "$kb_path" "$index_path" "$excludes" "$model"
}

# ─────────────────────────────────────────────────────────────────────────────
# Parse arguments
# ─────────────────────────────────────────────────────────────────────────────

MODEL="$DEFAULT_MODEL"
TARGETS=""
KB_PATH_OVERRIDE=""
INDEX_PATH_OVERRIDE=""
EXCLUDE_PATTERNS_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        -l|--list)
            list_repos
            exit 0
            ;;
        -k|--kb-path)
            KB_PATH_OVERRIDE="$2"
            shift 2
            ;;
        -i|--index-path)
            INDEX_PATH_OVERRIDE="$2"
            shift 2
            ;;
        -e|--exclude-patterns)
            EXCLUDE_PATTERNS_OVERRIDE="$2"
            shift 2
            ;;
        -m|--model)
            MODEL="$2"
            shift 2
            ;;
        -*)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
        *)
            TARGETS="$TARGETS $1"
            shift
            ;;
    esac
done

# Trim leading space
TARGETS="${TARGETS# }"

# ─────────────────────────────────────────────────────────────────────────────
# Main execution
# ─────────────────────────────────────────────────────────────────────────────

if [ -n "$KB_PATH_OVERRIDE" ]; then
    if [ ! -d "$KB_PATH_OVERRIDE" ]; then
        echo "Error: KB path does not exist or is not a directory: $KB_PATH_OVERRIDE"
        exit 1
    fi

    if [ -n "$TARGETS" ]; then
        echo "Error: Don't mix --kb-path with preset targets."
        echo "Use either './reindex.sh --kb-path /path/to/data' or './reindex.sh wiki'."
        exit 1
    fi

    if [ -n "$INDEX_PATH_OVERRIDE" ]; then
        index_path="$INDEX_PATH_OVERRIDE"
    else
        index_path="$KB_PATH_OVERRIDE/.mcp-search/indexes"
    fi

    run_index_build "local-kb" "$KB_PATH_OVERRIDE" "$index_path" "$EXCLUDE_PATTERNS_OVERRIDE" "$MODEL"
    exit $?
fi

if [ -z "$TARGETS" ]; then
    show_help
    exit 0
fi

FAILED=""
SUCCESS=""

for target in $TARGETS; do
    if [ "$target" = "all" ]; then
        for name in $ALL_REPOS; do
            if rebuild_repo "$name" "$MODEL"; then
                SUCCESS="$SUCCESS $name"
            else
                FAILED="$FAILED $name"
            fi
        done
    else
        if rebuild_repo "$target" "$MODEL"; then
            SUCCESS="$SUCCESS $target"
        else
            FAILED="$FAILED $target"
        fi
    fi
done

# Trim leading spaces
SUCCESS="${SUCCESS# }"
FAILED="${FAILED# }"

# Final summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -z "$FAILED" ]; then
    echo "✅ All done! Rebuilt: $SUCCESS"
else
    echo "⚠️  Some failed: $FAILED"
    echo "   Succeeded: $SUCCESS"
    exit 1
fi
