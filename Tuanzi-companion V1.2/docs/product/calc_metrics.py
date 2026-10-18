"""
团子陪伴 · 可用性测试指标复算脚本

读取 docs/product/usability_raw.csv（17 份有效样本），
复算 SUS / NPS / 任务完成率 / 满意度，并与简历口径数字校验。

用法：python docs/product/calc_metrics.py
"""

import csv
import os

CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "usability_raw.csv")

SUS_QUESTIONS = [
    "1. 我愿意经常使用这个产品",
    "2. 我觉得这个产品复杂难用",
    "3. 我觉得这个产品容易上手",
    "4. 我需要他人帮助才能使用这个产品",
    "5. 我觉得各功能整合得很好",
    "6. 我觉得功能之间不一致",
    "7. 大多数人能很快学会使用",
    "8. 我觉得使用起来很繁琐",
    "9. 使用时我感到有信心",
    "10. 我需要先学很多东西才能上手",
]

TASKS = [
    "任务1：双击打开 AI 对话并发送一条消息",
    "任务2：开启轻度专注模式",
    "任务3：在无提示情况下找到并打开待办清单",
    "任务4：完成一次喝水打卡",
    "任务5：找到设置入口并给宠物改名",
]


def load_rows():
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def sus_score(row):
    """单用户 SUS：奇数题 a-1，偶数题 5-a，合计 ×2.5"""
    total = 0
    for i in range(1, 11):
        a = int(row[f"SUS_Q{i}"])
        total += (a - 1) if i % 2 == 1 else (5 - a)
    return total * 2.5


def main():
    rows = load_rows()
    n = len(rows)

    sus_scores = [sus_score(r) for r in rows]
    sus_mean = sum(sus_scores) / n

    nps_vals = [int(r["NPS评分"]) for r in rows]
    promoters = sum(1 for v in nps_vals if v >= 9)
    detractors = sum(1 for v in nps_vals if v <= 6)
    nps = (promoters - detractors) / n * 100

    task_done = sum(int(r[f"任务{i}"]) for r in rows for i in range(1, 6))
    task_total = n * 5
    completion = task_done / task_total * 100

    visual = sum(int(r["视觉满意度"]) for r in rows) / n
    ai = sum(int(r["AI对话满意度"]) for r in rows) / n
    entry_fail = sum(int(r["入口发现失败"]) for r in rows) / n * 100

    print(f"有效样本量：{n}（学生 {sum(1 for r in rows if r['画像']=='学生')} / "
          f"职场轻办公 {sum(1 for r in rows if r['画像']=='职场轻办公')}）")
    print(f"SUS 平均分：{sus_mean:.2f}（行业基准 68）")
    print(f"NPS：{nps:+.1f}（推荐者 {promoters} / 贬损者 {detractors}）")
    print(f"任务完成率：{completion:.1f}%（{task_done}/{task_total}）")
    print(f"视觉满意度：{visual:.2f}/5")
    print(f"AI 对话满意度：{ai:.2f}/5")
    print(f"入口发现失败占比：{entry_fail:.1f}%")

    # 与简历口径校验（四舍五入一致）
    checks = [
        ("SUS 71.5", round(sus_mean, 1) == 71.5),
        ("NPS +17.6", round(nps, 1) == 17.6),
        ("任务完成率 89.4%", round(completion, 1) == 89.4),
        ("视觉满意度 4.2", round(visual, 1) == 4.2),
        ("AI 满意度 3.4", round(ai, 1) == 3.4),
        ("入口发现失败 59%", round(entry_fail) == 59),
    ]
    print("\n口径校验：")
    ok = True
    for name, passed in checks:
        print(f"  {'✅' if passed else '❌'} {name}")
        ok = ok and passed
    if not ok:
        raise SystemExit(1)
    print("\n全部指标与简历口径一致 ✅")


if __name__ == "__main__":
    main()
