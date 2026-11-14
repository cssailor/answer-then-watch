#!/usr/bin/env python3
"""生成四年级下册题库：数学 / 语文 / 英语，每科约 200 道选择题。"""

import json
import os
import sys

from bank_math import build as build_math
from bank_chinese import build as build_chinese
from bank_english import build as build_english


def main():
    questions = build_math() + build_chinese() + build_english()

    ids = set()
    for q in questions:
        if q["id"] in ids:
            raise SystemExit("重复 id: %s" % q["id"])
        ids.add(q["id"])
        if len(q["options"]) != 4:
            raise SystemExit("选项数不是 4: %s" % q["id"])
        if not (0 <= q["answer"] < 4):
            raise SystemExit("答案下标越界: %s" % q["id"])
        if not (1 <= q["difficulty"] <= 5):
            raise SystemExit("难度越界: %s" % q["id"])

    from collections import Counter
    by_subject = Counter(q["subject"] for q in questions)
    by_diff = Counter((q["subject"], q["difficulty"]) for q in questions)
    by_kp = Counter((q["subject"], q["kp"]) for q in questions)

    print("总题数:", len(questions))
    for subject in ("数学", "语文", "英语"):
        print("\n%s: %d 题" % (subject, by_subject[subject]))
        for d in range(1, 6):
            print("  难度 %d: %d" % (d, by_diff[(subject, d)]))
        kps = sorted((kp, n) for (s, kp), n in by_kp.items() if s == subject)
        print("  知识点:", "、".join("%s×%d" % (kp, n) for kp, n in kps))

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "questions.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": 2, "grade": "四年级下册",
                   "note": "课标同步仿真题，非版权试卷原文",
                   "questions": questions}, f, ensure_ascii=False, indent=2)
    print("\n已写入:", path)


if __name__ == "__main__":
    main()
