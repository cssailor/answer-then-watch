"""四年级下册数学仿真题生成器（人教版课标）。"""

import random


def _fmt(x):
    if isinstance(x, float):
        if abs(x - round(x)) < 1e-9:
            return str(int(round(x)))
        return ("%.2f" % x).rstrip("0").rstrip(".")
    return str(x)


def build():
    random.seed(20250401)
    out, seen = [], set()
    counter = [0]

    def add(kp, difficulty, stem, correct, distractors, explain=""):
        if stem in seen:
            return
        seen.add(stem)
        correct_s = _fmt(correct)
        opts = [correct_s]
        for d in distractors:
            ds = _fmt(d)
            if ds not in opts:
                opts.append(ds)
        n = 1
        while len(opts) < 4:
            cand = _fmt(correct + n)
            if cand not in opts:
                opts.append(cand)
            n += 1
        opts = opts[:4]
        random.shuffle(opts)
        counter[0] += 1
        out.append({
            "id": "g4m-%03d" % counter[0],
            "subject": "数学", "grade": 4, "kp": kp,
            "difficulty": difficulty, "stem": stem,
            "options": opts, "answer": opts.index(correct_s),
            "explain": explain,
        })

    # 1. 四则运算
    for i in range(44):
        a = random.randint(12, 99)
        b = random.randint(2, 9)
        c = random.randint(10, 60)
        t = i % 8
        if t == 0:
            add("四则运算", 1, "%d × %d + %d = ?" % (a, b, c), a * b + c,
                [a * (b + c), (a + b) * c, a * b * c], "先算乘法，再算加法。")
        elif t == 1:
            add("四则运算", 1, "%d + %d × %d = ?" % (a, b, c), a + b * c,
                [(a + b) * c, a * b + c, a * b * c], "先算乘法，再算加法。")
        elif t == 2:
            add("四则运算", 2, "(%d + %d) × %d = ?" % (a, b, c), (a + b) * c,
                [a + b * c, a * b + c, a * b * c], "先算括号里的加法。")
        elif t == 3:
            add("四则运算", 2, "%d × (%d - %d) = ?" % (a, b + c, c), a * (b + c - c),
                [a * b - c, a * b + c, a * b * c], "先算括号里的减法。")
        elif t == 4:
            b2 = random.randint(2, 9)
            a2 = b2 * random.randint(3, 12)
            add("四则运算", 2, "%d ÷ %d + %d = ?" % (a2, b2, c), a2 // b2 + c,
                [a2 // b2 * c, a2 // b2 - c, a2 // b2 + c + 1], "先算除法，再算加法。")
        elif t == 5:
            add("四则运算", 2, "%d - %d ÷ %d = ?" % (a * b, a, b), a * b - a // b,
                [a * b - a, a * b // b, a * b + a // b], "先算除法，再算减法。")
        elif t == 6:
            add("四则运算", 3,
                "学校买了 %d 箱书，每箱 %d 本，又买来 %d 本，一共多少本？" % (a, b, c),
                a * b + c, [a * (b + c), (a + b) * c, a * b * c],
                "先求箱里的书，再加上另外买的本数。")
        else:
            add("四则运算", 3,
                "果园有 %d 棵苹果树，每棵收 %d 千克，卖出 %d 千克，还剩多少千克？"
                % (a, b, c), a * b - c, [a * (b - c), a * b + c, (a - b) * c],
                "先求总产量，再减去卖出的。")

    # 2. 运算定律
    for i in range(28):
        a = random.choice([25, 125, 5, 50, 20])
        b = random.choice([4, 8, 2, 5, 10])
        c = random.randint(3, 19)
        t = i % 5
        if t == 0:
            add("运算定律", 2, "%d × %d × %d = ?" % (a, b, c), a * b * c,
                [a * b + c, a * (b + c), a + b * c], "利用乘法结合律，先算能凑整的两个数。")
        elif t == 1:
            add("运算定律", 3, "99 × %d = ?" % c, 100 * c - c,
                [100 * c, 100 * c + c, 99 + c], "把 99 看成 100 - 1，用乘法分配律。")
        elif t == 2:
            add("运算定律", 3, "101 × %d = ?" % c, 100 * c + c,
                [100 * c, 100 * c - c, 101 + c], "把 101 看成 100 + 1，用乘法分配律。")
        elif t == 3:
            add("运算定律", 2, "%d × %d + %d × %d = ?" % (a, b, a, c), a * (b + c),
                [a * b + c, a * (b - c), a + b + c], "提取公因数，用乘法分配律。")
        else:
            add("运算定律", 2, "%d + %d + %d = ?" % (a, b, c), a + b + c,
                [a + b - c, a * b + c, (a + b) * c], "利用加法交换律和结合律凑整。")

    # 3. 小数的意义和性质
    for i in range(36):
        d = random.randint(1, 9)
        n = random.randint(10, 99)
        t = i % 6
        if t == 0:
            add("小数的意义", 1, "0.%d 里面有 ___ 个 0.1" % d, d,
                [d * 10, d + 1, 10 - d], "0.1 是十分位上的计数单位。")
        elif t == 1:
            add("小数的意义", 2, "%d.%d 的十分位上的数字是 ___" % (n // 10, d), d,
                [n // 10, n % 10 + 1, d + 1], "小数点后第一位是十分位。")
        elif t == 2:
            add("小数的意义", 2, "把 0.%d 改写成以百分之一为单位的数是 ___" % d,
                "0.%d0" % d, ["0.0%d" % d, "%d.00" % d, "0.%d00" % d],
                "小数的末尾添上 0，大小不变。")
        elif t == 3:
            add("小数的意义", 2, "把 %d.%d 扩大到原来的 10 倍是 ___" % (n // 10, d),
                (n // 10) * 10 + d, [(n // 10) * 10 + d * 10, (n // 10) + d / 10,
                                     (n // 10) * 100 + d], "小数点向右移动一位。")
        elif t == 4:
            add("小数的意义", 3, "把 %d.%d 缩小到原来的 1/100 是 ___" % (n, d),
                "%.3f" % ((n + d / 10) / 100),
                ["%.2f" % ((n + d / 10) / 10), "%.2f" % ((n + d / 10) * 100),
                 "%.3f" % ((n + d / 10) / 10)],
                "小数点向左移动两位。")
        else:
            nums = [round(random.uniform(0.1, 9.9), 2) for _ in range(4)]
            nums = list(dict.fromkeys(nums))
            while len(nums) < 4:
                nums.append(round(random.uniform(10, 99), 1))
            nums = nums[:4]
            biggest = max(nums)
            add("小数的意义", 2, "下面各数中最大的是 ___", _fmt(biggest),
                [_fmt(x) for x in nums if x != biggest],
                "先比较整数部分，再比较小数部分。")

    # 4. 小数的加法和减法
    for i in range(36):
        a = round(random.uniform(1, 20), 2)
        b = round(random.uniform(0.1, 9.99), 2)
        t = i % 4
        if t == 0:
            add("小数加减法", 2, "%s + %s = ?" % (_fmt(a), _fmt(b)),
                round(a + b, 2),
                [round(a + b + 0.1, 2), round(a + b - 0.1, 2), round(a * b, 2)],
                "小数点对齐，从末位算起。")
        elif t == 1:
            add("小数加减法", 2, "%s - %s = ?" % (_fmt(a + b), _fmt(b)),
                round(a, 2),
                [round(a + 0.1, 2), round(a - 0.1, 2), round(a * 2, 2)],
                "小数点对齐，从末位算起。")
        elif t == 2:
            add("小数加减法", 3,
                "一支笔 %s 元，一个本子 %s 元，买一支笔和一个本子共多少元？"
                % (_fmt(a), _fmt(b)), round(a + b, 2),
                [round(a + b + 0.5, 2), round(a - b, 2), round(a * b, 2)],
                "求一共多少，用加法。")
        else:
            add("小数加减法", 4,
                "妈妈带了 20 元，买水果用了 %s 元，还剩多少元？" % _fmt(a),
                round(20 - a, 2),
                [round(20 + a, 2), round(a - 20, 2), round(20 - a + 0.1, 2)],
                "求还剩多少，用减法。")

    # 5. 三角形
    for i in range(26):
        a = random.randint(35, 80)
        b = random.randint(30, 90 - (a - 30) if a > 60 else 80)
        b = min(b, 145 - a)
        if b < 25:
            b = 25
        c = 180 - a - b
        if c <= 0:
            continue
        t = i % 4
        if t == 0:
            add("三角形", 2, "一个三角形有两个角分别是 %d° 和 %d°，第三个角是 ___°"
                % (a, b), c, [180 - a, 180 - b, a + b],
                "三角形内角和是 180°。")
        elif t == 1:
            add("三角形", 1, "等边三角形的每个角是 ___°", 60,
                [30, 90, 45], "等边三角形三个角都相等，180 ÷ 3 = 60°。")
        elif t == 2:
            add("三角形", 2, "直角三角形中，一个锐角是 %d°，另一个锐角是 ___°" % a,
                90 - a, [180 - a, a, 90 + a], "直角三角形两个锐角的和是 90°。")
        else:
            sets = [("3 cm、4 cm、5 cm", True), ("1 cm、2 cm、3 cm", False),
                    ("2 cm、3 cm、6 cm", False), ("4 cm、5 cm、9 cm", False)]
            random.shuffle(sets)
            add("三角形", 3, "下面哪组线段能围成一个三角形？",
                [s for s, ok in sets if ok][0], [s for s, ok in sets if not ok],
                "三角形任意两边之和大于第三边。")

    # 6. 图形的运动（二）
    for i in range(10):
        t = i % 3
        if t == 0:
            add("图形的运动", 1, "正方形有几条对称轴？", 4, [1, 2, 3],
                "正方形有 4 条对称轴。")
        elif t == 1:
            add("图形的运动", 1, "长方形有几条对称轴？", 2, [1, 3, 4],
                "长方形有 2 条对称轴。")
        else:
            add("图形的运动", 2, "下面图形中，不是轴对称图形的是 ___",
                "平行四边形", ["长方形", "正方形", "等腰三角形"],
                "平行四边形不是轴对称图形。")

    # 7. 平均数与统计
    for i in range(16):
        base = random.randint(70, 95)
        nums = [base, base + random.randint(-5, 5), base + random.randint(-3, 8),
                base + random.randint(-6, 4)]
        avg = sum(nums) / 4
        t = i % 3
        if t == 0:
            add("平均数", 2, "小明四次数学成绩分别是 %s，平均分是 ___ 分"
                % "、".join(str(x) for x in nums), round(avg, 1),
                [round(avg + 1, 1), round(avg - 1, 1), sum(nums)],
                "平均数 = 总数 ÷ 份数。")
        elif t == 1:
            x = random.randint(8, 16)
            a = random.randint(6, 14)
            c = 3 * x - a - x
            add("平均数", 3, "三个数的平均数是 %d，其中两个是 %d 和 %d，第三个数是 ___"
                % (x, a, x), c, [c + 1, c - 1, 3 * x],
                "先求三个数的和，再减去已知的两个数。")
        else:
            a = random.randint(8, 20)
            b = random.randint(8, 20)
            c = random.randint(8, 20)
            add("平均数", 2,
                "某班喜欢苹果的有 %d 人，喜欢香蕉的有 %d 人，喜欢橙子的有 %d 人，"
                "平均每种水果有多少人喜欢？" % (a, b, c),
                round((a + b + c) / 3, 1),
                [a + b + c, round((a + b) / 2, 1), round((a + b + c) / 2, 1)],
                "平均数 = 总人数 ÷ 3。")

    # 8. 数学广角——鸡兔同笼
    for i in range(12):
        rabbits = random.randint(2, 18)
        chickens = random.randint(2, 20)
        heads = rabbits + chickens
        legs = rabbits * 4 + chickens * 2
        add("鸡兔同笼", 4,
            "笼子里有鸡和兔共 %d 只，一共有 %d 条腿，兔有 ___ 只。" % (heads, legs),
            rabbits, [chickens, rabbits + 1, rabbits - 1],
            "假设全是鸡，多出的腿数 ÷ (4 - 2) = 兔的只数。")

    # 9. 单位换算
    for i in range(18):
        t = i % 4
        if t == 0:
            x = round(random.uniform(0.5, 9.9), 2)
            add("单位换算", 2, "%s 米 = ___ 厘米" % _fmt(x), round(x * 100, 2),
                [round(x * 10, 2), round(x * 1000, 2), round(x / 100, 2)],
                "1 米 = 100 厘米。")
        elif t == 1:
            x = random.randint(1, 9)
            y = random.randint(10, 900)
            add("单位换算", 2, "%d 吨 %d 千克 = ___ 千克" % (x, y), x * 1000 + y,
                [x * 100 + y, x * 1000 - y, x + y], "1 吨 = 1000 千克。")
        elif t == 2:
            x = round(random.uniform(0.5, 9.9), 2)
            add("单位换算", 3, "%s 平方米 = ___ 平方分米" % _fmt(x), round(x * 100, 2),
                [round(x * 10, 2), round(x * 1000, 2), round(x / 100, 2)],
                "1 平方米 = 100 平方分米。")
        else:
            minutes = random.choice([15, 20, 30, 45])
            add("单位换算", 3, "%d 分 = ___ 时" % minutes,
                round(minutes / 60, 2), [round(minutes / 100, 2), minutes,
                                          round(minutes * 60, 2)],
                "1 时 = 60 分。")

    return out
