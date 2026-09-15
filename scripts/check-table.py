#!/usr/bin/env python3
"""固定表の検品。表そのものに穴が無いかだけを見る。

対象アプリには一切触れない。読むのは同梱した公式データと `docs/safety-check/table/` だけ。
確かめるのは次の6点。

  1. 表に載っている項目 ID が、ASVS 公式データの L1 に実在すること
  2. 表を作った章については、その章の L1 項目が漏れなく1回ずつ載っていること
  3. 同じ項目 ID が2か所に載っていないこと
  4. 必須の欄が空でないこと
  5. 「判定のしかた」が `機械` か `読む` のどちらかであること
  6. 「判定のしかた」が `読む` の項目には「見る場所」があること
     （探索範囲を固定しないと、判定が回すたびに揺れるため）
     `機械` の項目には「命令の種類」があり、決められた3つのどれかであること
     （0件の意味が種類で逆になるため。`docs/adr/0006`）
  7. 「原文」が公式データの原文と**一字一句一致**すること
     （途中で切ると、標準が条件付きで求めている部分を落としたまま合格を出してしまう）

同梱した公式データ自体が壊れている場合は、検品の前提が崩れているため即座に止める。
終了コードは、問題が1件でもあれば 1、無ければ 0。
"""
import csv
import pathlib
import re
import sys
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parent.parent
OFFICIAL = ROOT / "docs" / "safety-check" / "asvs-5.0.0-l1.csv"
TABLE_DIR = ROOT / "docs" / "safety-check" / "table"

REQUIRED_FIELDS = ["原文", "日本語", "判定のしかた", "合格基準", "該当しない条件", "根拠として出すもの"]
READING_ONLY_FIELD = "見る場所"
MACHINE_ONLY_FIELD = "命令の種類"
COMMAND_KINDS = ("危険な書き方を探す命令", "備えを探す命令", "対象の一覧を作る命令")
BY_MACHINE = "機械"
BY_READING = "読む"
JUDGEMENT_METHODS = (BY_MACHINE, BY_READING)

ITEM_HEADING = re.compile(r"^### +(v5\.0\.0-[\d.]+) *$")
ITEM_FIELD = re.compile(r"^- \*\*(.+?)\*\*: *(.*)$")


@dataclass
class Item:
    """固定表に載っている1項目。"""

    item_id: str
    line: int
    fields: dict = field(default_factory=dict)

    def value(self, name):
        return self.fields.get(name, "")


def official_l1():
    """同梱した公式データを読み、項目 ID -> (章 ID, 原文) の対応を返す。"""
    with OFFICIAL.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    stray = [row["req_id"] for row in rows if row["L"] != "1"]
    if stray:
        raise SystemExit(f"公式データに L1 以外の行がある（検品の前提が崩れている）: {', '.join(stray)}")
    return {
        "v5.0.0-" + row["req_id"].lstrip("V"): (row["chapter_id"], row["req_description"])
        for row in rows
    }


def normalize(text):
    """比べる前にそろえる。原文は公式データのまま書く決まりだが、
    強調記号を避けて `\*` `\_` と書いてしまった場合も通す。"""
    return text.replace("\\*", "*").replace("\\_", "_").strip()


def parse_table(path):
    """1つの表から Item を順に取り出す。"""
    items = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        heading = ITEM_HEADING.match(line)
        if heading:
            items.append(Item(item_id=heading.group(1), line=lineno))
            continue
        pair = ITEM_FIELD.match(line)
        if pair and items:
            items[-1].fields.setdefault(pair.group(1), pair.group(2).strip())
    return items


def check_item(item, rel, official, seen, problems):
    where = f"{rel}:{item.line} {item.item_id}"

    if item.item_id not in official:
        problems.append(f"{where} は公式データの L1 に無い")
        return

    expected = official[item.item_id][1]
    if normalize(item.value("原文")) != normalize(expected):
        problems.append(
            f"{where} の「原文」が公式データと一致しない"
            f"（途中で切っていないか確認する。公式は {len(expected)} 字）"
        )

    if item.item_id in seen:
        problems.append(f"{where} は {seen[item.item_id]} にも載っている")
    else:
        seen[item.item_id] = rel

    for name in REQUIRED_FIELDS:
        if not item.value(name):
            problems.append(f"{where} の「{name}」が空")

    method = item.value("判定のしかた")
    if method and method not in JUDGEMENT_METHODS:
        problems.append(
            f"{where} の「判定のしかた」が `{method}`。{' か '.join(JUDGEMENT_METHODS)} のどちらかにする"
        )
    if method == BY_READING and not item.value(READING_ONLY_FIELD):
        problems.append(f"{where} は `{BY_READING}` なのに「{READING_ONLY_FIELD}」が無い")
    if method == BY_MACHINE:
        kind = item.value(MACHINE_ONLY_FIELD)
        if not kind:
            problems.append(f"{where} は `{BY_MACHINE}` なのに「{MACHINE_ONLY_FIELD}」が無い")
        elif kind not in COMMAND_KINDS:
            problems.append(
                f"{where} の「{MACHINE_ONLY_FIELD}」が `{kind}`。"
                f"{' / '.join(COMMAND_KINDS)} のどれかにする"
            )


def report_coverage(official, seen):
    print(f"公式データ: L1 {len(official)} 項目")
    print(f"表に載っている項目: {len(seen)} / {len(official)}")
    for chapter in sorted({official[i][0] for i in seen}, key=lambda c: int(c[1:])):
        done = sum(1 for i in seen if official[i][0] == chapter)
        total = sum(1 for value in official.values() if value[0] == chapter)
        print(f"  {chapter}: {done} / {total}")


def main():
    official = official_l1()
    problems = []
    seen = {}

    tables = sorted(TABLE_DIR.glob("V*.md"))
    if not tables:
        problems.append(f"{TABLE_DIR.relative_to(ROOT)} に表が1つも無い")

    for path in tables:
        rel = path.relative_to(ROOT)
        items = parse_table(path)
        if not items:
            problems.append(f"{rel}: 項目が1つも読み取れない（見出しが `### v5.0.0-X.Y.Z` の形か確認）")
            continue

        for item in items:
            check_item(item, rel, official, seen, problems)

        present = {item.item_id for item in items}
        for chapter in sorted({official[i][0] for i in present if i in official}):
            missing = {i for i, value in official.items() if value[0] == chapter} - present
            for item_id in sorted(missing):
                problems.append(f"{rel}: {chapter} の {item_id} が載っていない")

    report_coverage(official, seen)

    if problems:
        print(f"\n問題 {len(problems)} 件")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\n問題なし")
    return 0


if __name__ == "__main__":
    sys.exit(main())
