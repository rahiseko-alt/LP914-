#!/usr/bin/env python3
"""固定表の検品。表そのものに穴が無いかを見る。

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
  8. 公式データの L1 項目が**1つ残らず**表に載っていること
     （章のファイルごと消えても、件数が減るだけで緑のまま通ってしまわないように）
  9. 同じ欄が1つの項目に2回書かれていないこと（先に書いたほうが黙って勝つのを防ぐ）
 10. 命令に `2>/dev/null` が無いこと、対象アプリ固有の置き場所の名前が無いこと
     （別のアプリに当てたとき、黙って0件＝合格になるのを防ぐ）

`--results` を付けると、判定結果（`docs/safety-check/results/<対象アプリ>/`）も見る。
判定結果の項目を数え、固定表と突き合わせ、`機械` と `読む` の内訳を出す。**目で数えない。**

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
    duplicated: set = field(default_factory=set)

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
            name = pair.group(1)
            if name in items[-1].fields:
                items[-1].duplicated.add(name)
            else:
                items[-1].fields[name] = pair.group(2).strip()
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
    for name in sorted(item.duplicated):
        problems.append(f"{where} の「{name}」が2回書かれている（先に書いたほうが黙って勝つ）")

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


BANNED_IN_COMMAND = {
    "2>/dev/null": "失敗を隠している。別のアプリに当てたとき黙って0件＝合格になる",
    "worker/src": "対象アプリ固有の置き場所の名前",
    "backend/js": "対象アプリ固有の置き場所の名前",
    "supabase/": "対象アプリ固有の置き場所の名前",
    "src/js": "対象アプリ固有の置き場所の名前",
}


def check_commands(path, problems):
    """表に書かれた命令が、README の決まりを守っているかを見る。"""
    rel = path.relative_to(ROOT)
    inside = False
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip().startswith("```"):
            inside = not inside
            continue
        if not inside:
            continue
        for banned, reason in BANNED_IN_COMMAND.items():
            if banned in line:
                problems.append(f"{rel}:{lineno} 命令に `{banned}` がある（{reason}）")


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
    methods = {}

    tables = sorted(TABLE_DIR.glob("V*.md"))
    if not tables:
        problems.append(f"{TABLE_DIR.relative_to(ROOT)} に表が1つも無い")

    for path in tables:
        rel = path.relative_to(ROOT)
        items = parse_table(path)
        if not items:
            problems.append(f"{rel}: 項目が1つも読み取れない（見出しが `### v5.0.0-X.Y.Z` の形か確認）")
            continue

        check_commands(path, problems)
        for item in items:
            check_item(item, rel, official, seen, problems)
            methods[item.item_id] = item.value("判定のしかた")

        present = {item.item_id for item in items}
        for chapter in sorted({official[i][0] for i in present if i in official}):
            missing = {i for i, value in official.items() if value[0] == chapter} - present
            for item_id in sorted(missing):
                problems.append(f"{rel}: {chapter} の {item_id} が載っていない")

    for item_id in sorted(set(official) - set(seen)):
        problems.append(f"{official[item_id][0]} の {item_id} が、どの表にも載っていない")

    report_coverage(official, seen)
    by_method = {}
    for value in methods.values():
        by_method[value] = by_method.get(value, 0) + 1
    print("判定のしかたの内訳: " + " / ".join(f"{k} {v}" for k, v in sorted(by_method.items())))

    if "--results" in sys.argv:
        problems += check_results(official, methods)

    if problems:
        print(f"\n問題 {len(problems)} 件")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    print("\n問題なし")
    return 0


RESULTS_DIR = ROOT / "docs" / "safety-check" / "results"
RESULT_HEADING = re.compile(r"^### (v5\.0\.0-[\d.]+)")
RESULT_VERDICT = re.compile(r"^\*\*判定: (.+?)\*\*")
VERDICTS = ("合格", "合格（該当機能なし）", "不合格", "判定不能")


def check_results(official, methods):
    """判定結果を数え、固定表と突き合わせる。目で数えないための仕組み。"""
    problems = []
    for app_dir in sorted(d for d in RESULTS_DIR.iterdir() if d.is_dir()):
        seen = {}
        counts = {}
        for path in sorted(app_dir.glob("*.md")):
            rel = path.relative_to(ROOT)
            current = None
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                heading = RESULT_HEADING.match(line)
                if heading:
                    current = (heading.group(1), rel, lineno)
                    continue
                verdict = RESULT_VERDICT.match(line)
                if verdict and current:
                    item_id, where, at = current
                    current = None
                    if item_id in seen:
                        problems.append(f"{rel}:{at} {item_id} は {seen[item_id]} にも判定がある")
                        continue
                    seen[item_id] = where
                    value = verdict.group(1)
                    if value not in VERDICTS:
                        problems.append(
                            f"{where}:{at} {item_id} の判定が `{value}`。"
                            f"{' / '.join(VERDICTS)} のどれかにする"
                        )
                    counts[value] = counts.get(value, 0) + 1

        print(f"\n対象アプリ: {app_dir.name}")
        print(f"  判定した項目: {len(seen)} / {len(official)}")
        for value in VERDICTS:
            if counts.get(value):
                print(f"    {value}: {counts[value]}")
        by_method = {}
        for item_id in seen:
            by_method[methods.get(item_id, "不明")] = by_method.get(methods.get(item_id, "不明"), 0) + 1
        print("  判定のしかたの内訳: " + " / ".join(f"{k} {v}" for k, v in sorted(by_method.items())))

        for item_id in sorted(set(official) - set(seen)):
            problems.append(f"{app_dir.name}: {item_id} が判定されていない")
        for item_id in sorted(set(seen) - set(official)):
            problems.append(f"{app_dir.name}: {item_id} は固定表に無い")
    return problems


if __name__ == "__main__":
    sys.exit(main())
