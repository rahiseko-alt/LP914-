#!/bin/sh
# 引き継ぎメモを新しい順に KEEP 件だけ残す。追記したら必ず実行する。
set -u

KEEP=5

dir="${CLAUDE_PROJECT_DIR:-.}"
f="$dir/docs/agents/handover.md"
[ -f "$f" ] || exit 0

tmp="$f.trim.tmp"
awk -v keep="$KEEP" '
  /^```/            { fence = !fence }
  !fence && /^## /  { n++ }
  n > keep          { exit }
                    { print }
' "$f" > "$tmp" && mv "$tmp" "$f"

echo "引き継ぎメモを最新 $KEEP 件に整理しました。"
