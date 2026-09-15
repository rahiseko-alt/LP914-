#!/usr/bin/env python3
"""固定表の検品。表そのものに穴が無いかだけを見る。

対象アプリを検査する道具ではない。確かめるのは次の5点のみ。

  1. 表に載っている項目 ID が、ASVS 公式データの L1 に実在すること
  2. 表を作った章については、その章の L1 項目が漏れなく1回ずつ載っていること
  3. 同じ項目 ID が2か所に載っていないこと
  4. 必須の欄が空でないこと
  5. 「判定のしかた」が `機械` か `読む` のどちらかであること

終了コードは、問題が1件でもあれば 1、無ければ 0。
"""
import csv
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OFFICIAL = ROOT / "docs" / "safety-check" / "asvs-5.0.0-l1.csv"
TABLE_DIR = ROOT / "docs" / "safety-check" / "table"

REQUIRED_FIELDS = ["原文", "日本語", "判定のしかた", "合格条件", "該当しない条件", "根拠として出すもの"]
JUDGEMENT_METHODS = {"機械", "読む"}

ITEM_RE = re.compile(r"^### +(v5\.0\.0-[\d.]+) *$")
FIELD_RE = re.compile(r"^- \*\*(.+?)\*\*: *(.*)$")


def official_l1():
    """公式データを読み、項目 ID -> 章 ID の対応を返す。"""
    with OFFICIAL.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    items = {}
    for row in rows:
        if row["L"] != "1":
            raise SystemExit(f"公式データに L1 以外の行がある: {row['req_id']}")
        items["v5.0.0-" + row["req_id"].lstrip("V")] = row["chapter_id"]
    return items


def parse_table(path):
    """1つの表から、項目 ID -> {欄名: 値} を取り出す。"""
    items = {}
    current = None
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        heading = ITEM_RE.match(line)
        if heading:
            current = heading.group(1)
            items[current] = {"_line": lineno}
            continue
        field = FIELD_RE.match(line)
        if field and current:
            items[current][field.group(1)] = field.group(2).strip()
    return items


def main():
    official = official_l1()
    problems = []
    seen = {}

    tables = sorted(TABLE_DIR.glob("V*.md"))
    if not tables:
        problems.append(f"{TABLE_DIR} に表が1つも無い")

    for path in tables:
        rel = path.relative_to(ROOT)
        items = parse_table(path)
        if not items:
            problems.append(f"{rel}: 項目が1つも読み取れない（見出しが `### v5.0.0-X.Y.Z` の形か確認）")
            continue

        chapters = set()
        for item_id, fields in items.items():
            if item_id not in official:
                problems.append(f"{rel}:{fields['_line']} {item_id} は公式データの L1 に無い")
                continue
            chapters.add(official[item_id])

            if item_id in seen:
                problems.append(f"{rel}:{fields['_line']} {item_id} は {seen[item_id]} にも載っている")
            else:
                seen[item_id] = rel

            for name in REQUIRED_FIELDS:
                if not fields.get(name):
                    problems.append(f"{rel}:{fields['_line']} {item_id} の「{name}」が空")

            method = fields.get("判定のしかた")
            if method and method not in JUDGEMENT_METHODS:
                problems.append(
                    f"{rel}:{fields['_line']} {item_id} の「判定のしかた」が `{method}`。"
                    f"{' か '.join(sorted(JUDGEMENT_METHODS))} のどちらかにする"
                )

        for chapter in sorted(chapters):
            expected = {i for i, c in official.items() if c == chapter}
            missing = expected - set(items)
            for item_id in sorted(missing):
                problems.append(f"{rel}: {chapter} の {item_id} が載っていない")

    print(f"公式データ: L1 {len(official)} 項目")
    print(f"表に載っている項目: {len(seen)} / {len(official)}")
    for chapter in sorted({official[i] for i in seen}, key=lambda c: int(c[1:])):
        done = sum(1 for i in seen if official[i] == chapter)
        total = sum(1 for c in official.values() if c == chapter)
        print(f"  {chapter}: {done} / {total}")

    if problems:
        print(f"\n問題 {len(problems)} 件")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\n問題なし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
