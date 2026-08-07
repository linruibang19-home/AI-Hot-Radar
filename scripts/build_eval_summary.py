"""Turn the evaluation JSONs into one summary the web app can render (T1-2).

Ten rounds of retrieval evaluation, plus generation and latency runs, live in
`docs/status/` as per-question JSON. None of it is reachable from the site. A
project with numbers and a project without numbers are different projects in an
interview, and right now this one looks like the second from the outside.

**Why a generated file rather than reading the JSONs at request time.** The web
image is built from `apps/web` alone, so it cannot reach `docs/`, and the raw
files are 90 questions deep — three megabytes to render a table of sixteen rows.
This writes the summary once, into the app's own source tree, where the build
picks it up like any other module.

**Why the narrative is here and not derived.** What a round changed, what it was
required to beat, and what the result meant are the parts worth reading, and
none of them are recoverable from a metrics blob. They are transcribed from the
markdown reports next to each JSON, which stay the long-form record.

Re-run after any new evaluation:

    python scripts/build_eval_summary.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "docs" / "status"
TARGET = ROOT / "apps" / "web" / "src" / "data" / "eval-summary.json"

# The story of each round, in the order it happened. `file` is the JSON that
# carries the numbers; everything else is the reasoning that produced it.
#
# `criterion` is written down because several rounds were pre-registered — B4
# had to beat a stated MRR *and* hold a stated Recall@20 before the reranker was
# allowed into the pipeline. A threshold decided afterwards is not a threshold.
ROUNDS: list[dict[str, Any]] = [
    {
        "id": "B1",
        "file": "m4-rag-eval-B1-20260803.json",
        "title": "纯稠密基线",
        "changed": "bge-m3 向量检索，无融合、无重排。先测基线，再加任何东西。",
        "criterion": "无门槛——这一轮的目的是产出后续所有轮次的比较对象。",
        "finding": (
            "总分掩盖了三件事：recent_updates 是最弱类别（MRR 0.468，最差两题首个命中排"
            "第 16、17 位），因为稠密向量里没有时间；MXFP4 单题 Recall@20 只有 0.33，"
            "被 fact_check 整体 0.9556 盖住；可答题最低分 0.5778 与不可答题最高分 0.7205 "
            "重叠 0.1427，说明拒答不可能靠相似度阈值决定。"
        ),
        "verdict": "baseline",
    },
    {
        "id": "B2",
        # The union is the row that belongs in the trend: it is the pipeline
        # B2 actually proposed. Sparse-on-its-own is a channel measurement, and
        # putting it in the trend column made the delta read as a catastrophic
        # regression rather than "this is what one channel can do alone".
        "file": "m4-rag-eval-B2-union-20260803.json",
        "alt": {"file": "m4-rag-eval-B2-sparse-20260803.json", "label": "纯稀疏通道单独测"},
        "title": "稀疏通道",
        "changed": "加入 Postgres tsvector 关键词通道，先用轮转交错与稠密合并。",
        "criterion": "修好 B1 点名的精确词失败（MXFP4 题 Recall@20 0.33）。",
        "finding": (
            "预测被证实：MXFP4 题 R@20 0.33 → 1.00、排名 4 → 1。没预测到的是"
            "**并集比纯稠密还差**——轮转交错无条件给弱通道一半名额，好结果被挤出去了。"
            "RRF 因此从「验证权重」升级为必需项。另量到中文缺口 52.1 个百分点：稀疏通道"
            "对含 ASCII 专名的问句 R@20 = 0.5798，纯中文只有 0.0588。"
        ),
        "verdict": "mixed",
    },
    {
        "id": "B3",
        "file": "m4-rag-eval-B3-rrf-20260803.json",
        "title": "RRF 融合 + 时间过滤",
        "changed": "加权 RRF 取代轮转交错；解析出的时间窗作为两个通道的过滤器。",
        "criterion": "把 B1 点名的最大缺口 recent_updates 关上。",
        "finding": (
            "recent_updates MRR 0.4676 → 0.7333（+26.6pt），R@20 做到 0.9036 击败 B1 与 B2。"
            "起作用的是把时间窗当**过滤器**，而不是加一条独立的时间通道（实测只贡献 "
            "+0.004 Recall）。但其余五类 MRR 下降——答案进了候选集却排得靠后，"
            "这正是 reranker 的适用场景，B4 因此有了可证伪的门槛。"
        ),
        "verdict": "mixed",
    },
    {
        "id": "B4",
        "file": "m4-rag-eval-B4-rerank40-20260803.json",
        "alt": {"file": "m4-rag-eval-B4-rerank100-20260803.json", "label": "100 候选"},
        "title": "交叉编码器重排",
        "changed": "bge-reranker-v2-m3 对融合后的前 40 个候选重排序。",
        "criterion": "**先立后测**：MRR 需 > 0.7630 且 R@20 ≥ 0.9036，两条都达标才准进 MVP。",
        "finding": (
            "MRR 0.8574、R@20 0.9126、nDCG +23.7%，全部达标。B3「Recall 升、MRR 降」"
            "的形态被完全纠正。候选数 40 比 100 在四项指标上都略高，而且快 3.2 倍"
            "（1376ms vs 4378ms）——融合排在 40 名之后的候选几乎不含答案，喂进去只是"
            "给交叉编码器加噪声。唯一退化的是 recent_updates（MRR 0.7333 → 0.6484）："
            "交叉编码器不知道时间。"
        ),
        "verdict": "pass",
    },
    {
        "id": "B7",
        "file": "m4-rag-eval-B7-20260804.json",
        "title": "时效融合",
        "changed": "对 freshness_required 为真的问题，在重排之后把新近度与相关性融合，权重 0.30。",
        "criterion": "补回 B4 唯一的退化，且不得影响其他类别。",
        "finding": (
            "recent_updates MRR +10.4pt，其余五类**逐位相同**——不是影响很小，是没有影响。"
            "这是作用域正确的改动应有的样子。权重刻意只占 0.30：相关性仍主导，"
            "「只是新」不能压过真正回答问题的。"
        ),
        "verdict": "pass",
    },
    {
        "id": "B8",
        "file": "m4-rag-eval-B8-incumbent-20260804.json",
        "alt": {"file": "m4-rag-eval-B8-swept-20260804.json", "label": "网格最优权重"},
        "title": "融合权重网格调优",
        "changed": "42 组 dense/sparse/temporal 权重组合全扫一遍。",
        "criterion": "规格要求权重必须用评测集调优，而不是拍脑袋。",
        "finding": (
            "**负结果，保持原权重不变。** 网格确实找到更好的融合序（融合前 MRR +5.9 点），"
            "但接上重排后两组权重的差距塌缩到 **0.0004**，四个类别逐位完全相同。"
            "→ 融合前指标是个**会骗人的优化目标**，它测的是一个马上会被交叉编码器覆盖的"
            "中间态。网格的真正价值是证明现行值在平台区（全网格 R@40 只波动 0.0043）"
            "而非悬崖边（sparse ≥ 0.8 才开始伤 R@20）。"
        ),
        "verdict": "no-change",
    },
    {
        "id": "B9",
        "file": "m4-rag-eval-B9-20260804.json",
        "title": "§6 directness / source_fit",
        "changed": "在交叉编码器之后补上两个重排维度：问题词项在标题中的覆盖率、信源等级与问题类型的亲和度。",
        "criterion": "增益应落在 timeline 与 explainer，其余类别不得退化。",
        "finding": (
            "timeline MRR +4.45pt、explainer R@10 +3.34pt，其余类别在噪声内（最差 −0.07pt），"
            "abstention 逐位相同。R@20 不变是对的——这两维只在重排结果内部重排序，不引入新文档。"
            "写这个模块时踩到中文分词坑：`MIN_TERM_CHARS = 2` 把中文全删了，"
            "directness 对每道纯中文问题稳定返回 0.0 且不报错。"
        ),
        "verdict": "pass",
    },
    {
        "id": "B10",
        "file": "m4-rag-eval-B10-20260804.json",
        "title": "§6 entity_subject / repost",
        "changed": "补上最后两条元数据调整：目标实体为主语 +0.05、重复转载 −0.10。",
        "criterion": "此前判定为「拿不到数据」，本轮先回库核对该判定。",
        "finding": (
            "**先前的「拿不到数据」是错判，从没去库里核对过。** 实际查：item_entity.role 有 "
            "subject 1848 / mention 2593 / object 1496，`duplicate_of_id` 也一直在写——"
            "数据从 M2 起就在库里。修完后 timeline R@10 +1.66pt、recent_updates +1.33pt、"
            "abstention nDCG +2.31pt，**没有任何一个类别、任何一项指标下降**，"
            "这在十轮评测里是第一次。至此 §6 的五条调整全部实现。"
        ),
        "verdict": "pass",
    },
    {
        "id": "B12",
        "file": "m4-rag-eval-B12-depth40-20260807.json",
        "alt": {"file": "m4-rag-eval-B12-depth20-20260807.json", "label": "重排深度 20"},
        "title": "自适应重排深度",
        "changed": "把重排候选数按问题类型路由：两类走 20，其余保持 40。",
        "criterion": "只有在某一类的指标**逐位不变**时才允许减半，任何下降都保持 40。",
        "finding": (
            "**先死掉两个直觉规则，才找到能站住的那个。** 规则一「简单事实题跳过重排」——"
            "B3→B4 实测 fact_check 从重排拿到 **+0.2195 MRR**，是收益第二大的类别，"
            "直觉完全反了；唯一不受重排影响的是 abstention，而 B1 已证明不可答题"
            "无法事先识别（与可答题的相似度区间重叠 0.14）。规则二「候选少时跳过重排」"
            "逻辑上成立——候选数不超过证据预算时，重排改变不了模型读到哪些段落——"
            "但 128 次真实查询里融合候选数**从未低于 60**，规则永远不触发。"
            "真正成立的是**深度**而不是**有无**：depth 20 整体掉 2.9 个点，"
            "但 comparison 与 recent_updates **逐位完全相同**，"
            "而 explainer −6.3pt、fact_check −5.9pt、timeline −3.6pt。"
            "于是只对那两类减半，形状与 B7 一致：在测过有效的地方生效，其余原样不动。"
            "样本量写在明处：每类 15 题。"
        ),
        "verdict": "pass",
    },
    {
        "id": "B13",
        "file": "m4-rag-eval-B13-20260807.json",
        "alt": {"file": "m4-rag-eval-B12-depth40-20260807.json", "label": "修复前（无 bigram）"},
        "title": "中文分词：修好了通道，系统没动",
        "changed": "Postgres `simple` 把整段中文切成一个词元。加 CJK 字符 bigram，索引与查询共用同一个 IMMUTABLE 函数（ADR-0018）。",
        "criterion": "B2 量到纯中文问句稀疏 R@20 仅 0.0588（含 ASCII 专名 0.5798），本轮应把这个差距关上。",
        "finding": (
            "**通道确实修好了，端到端却没动。** MRR ±0.0000，R@10 −0.0043，"
            "六类里五类逐位相同。原因 B2 自己就写过、当时没被当回事："
            "「稠密通道对中文只低 4.9 个百分点——缺口在通道设计边界内，不在系统层」。"
            "稀疏通道的中文失败一直被稠密通道兜住了。"
            "但**站内搜索是另一回事**，它只有 FTS 没有稠密兜底，实测："
            "「开源」4 → 130 条、「量化」5 → 48、「融资」2 → 18、「智谱」0 → 2，"
            "而 ASCII 查询「GLM」15 → 15 不变。"
            "所以改动保留——收益在另一个界面上，且是真的；"
            "RAG 侧记为负结果，代价是索引 15MB → 18MB。"
        ),
        "verdict": "no-change",
    },
]

# How this project's metrics line up with the vocabulary the field uses.
#
# Written down because the names differ while the quantities mostly do not, and
# "we measure groundedness" and "we measure faithfulness" being the same
# sentence is only obvious once someone says so. Where there is no equivalent in
# either direction, that is stated rather than papered over — three of the
# metrics here have no RAGAS counterpart, and one RAGAS metric has no honest
# equivalent here.
RAGAS_MAPPING: list[dict[str, Any]] = [
    {
        "ragas": "Faithfulness",
        "asks": "答案有没有说出证据里没有的东西",
        "ours": "support_mean / support_supported（交叉编码器对「论断 × 被引段落」打分）",
        "value": "0.8330 / 0.8986",
        "note": (
            "另有一条硬约束不在指标里：`check_invariants` 会把「有 [n] 却解析不到引用」"
            "或「零引用却不是拒答」的回答直接判为不可发布。指标衡量程度，不变量划定底线。"
        ),
    },
    {
        "ragas": "Answer Relevancy",
        "asks": "答案是不是在回答这个问题",
        "ours": "must_contain_hit + over_refusal_rate",
        "value": "0.9091 / 0.0128",
        "note": (
            "误拒率必须与拒答率一起看：**全都拒答的系统在拒答指标上满分且毫无用处**。"
            "把「该答的没答」算作最严重的一种不切题。"
        ),
    },
    {
        "ragas": "Context Precision",
        "asks": "检索到的上下文里相关的占比，且相关的是否排在前面",
        "ours": "citation_precision + MRR + nDCG@10",
        "value": "0.5883 / 0.8741 / 0.8203",
        "note": (
            "拆成两个数：引用精度看**模型选了什么**，MRR/nDCG 看**检索排了什么**。"
            "B8 那一轮的教训是这两者会分离——融合前的排序指标提升 5.9 点，"
            "接上重排后差距塌缩到 0.0004。"
        ),
    },
    {
        "ragas": "Context Recall",
        "asks": "该被检索到的内容有没有被检索到",
        "ours": "Recall@10 / Recall@20（对黄金集标注）",
        "value": "0.8669 / 0.8923",
        "note": "标注是人工的，127 个 item 全部经库校验；零分块的条目会被守卫拦下并计数。",
    },
    {
        "ragas": "（无对应）",
        "asks": "同一事件被多少家独立信源覆盖",
        "ours": "story_coverage",
        "value": "0.7797",
        "note": (
            "RAGAS 没有这一项，因为它假设文档之间彼此独立。资讯语料不是："
            "四家媒体报道同一次披露是**一条**证据不是四条，M3 的事件聚类就是为此存在的。"
        ),
    },
    {
        "ragas": "（无对应）",
        "asks": "答案里带引用的句子占比",
        "ours": "citation_coverage",
        "value": "0.7431",
        "note": "本项目的核心主张是「每条事实可回原文」，所以句级覆盖率是一个独立的验收项。",
    },
    {
        "ragas": "Noise Sensitivity（暂未测）",
        "asks": "混入无关上下文时答案会不会被带偏",
        "ours": "—",
        "value": "—",
        "note": (
            "**诚实标注为未测。** 需要构造带噪上下文的对照集，"
            "当前黄金集是按真实语料标注的，没有这个维度。"
        ),
    },
]

EXTRA: list[dict[str, Any]] = [
    {
        "id": "GEN",
        "file": "m4-rag-eval-GEN-20260807-judged.json",
        "title": "生成侧评测（含拒答判定）",
        "changed": (
            "90 题端到端真实生成。本轮新增**拒答判定**：对 12 道诱导题，"
            "用受控的二值判官问「这段回答有没有把那个假前提当事实陈述出来」。"
        ),
        "finding": (
            "**先修指标，再读结果。** 原来的 `refusal_rate_on_unanswerable` 从 66.67% "
            "掉到 8.33%，看着像核心能力崩了。查下去发现它测的是**形式不是正确性**："
            "拒答被定义为「文本为空或零引用」，而 §3.13 刻意把死胡同式拒答改成了"
            "**有据可查的否认**——「证据里没有提到罚款，也没有任何监管机构开出罚单的记载」"
            "并附上检索到的内容。这类回答有引用，于是被判成「没拒答」。"
            "另一个信号 `must_not_claim` 是子串匹配，它自己的注释就写着「否认时提到该词也算命中」，"
            "而且只覆盖 15 题里的 4 题。**两个信号都在测表面形态。**"
            "新增判官后：**12 道诱导题里断言假前提的为 0**，"
            "支持度 0.8330 → 0.8313 基本不动，引用覆盖率 +12.5pt。"
            "**结论：拒答能力没有退化，退化的是衡量它的方式。**"
            "本轮同时暴露一条真问题：**误拒率 1.28% → 7.69%**（1 题变 6 题）、"
            "Story 覆盖 −8.2pt。当时记下的假设是「语料涨到 1473 条后证据位竞争加剧」，"
            "并写明那是假设不是结论——下一轮证明它是错的。"
        ),
    },
    {
        "id": "GEN-FIX",
        "file": "m4-rag-eval-GEN-20260807-fixed.json",
        "title": "生成侧复测：误拒归零",
        "changed": (
            "同样 90 题，只改了一处：解析模型输出时的**失败分支**。"
            "把上一轮那六道误拒的原始模型响应抓出来看了之后改的。"
        ),
        "finding": (
            "**语料竞争那个假设是错的，六道题一道都不是检索问题。** "
            "抓原始响应发现两条各自独立的失效路径，都在出口处："
            "①**模型直接用 markdown 回答、没套 JSON**——答案完整、`[E1][E2]` 一个不缺，"
            "只是 `json.loads` 失败，于是正文被清空、判成拒答；"
            "②**模型把证据编号只写进 `claims[].evidence_ids`、正文里不标**——"
            "而绑定只扫正文，四条论断六个编号绑出零条引用。"
            "两条都是「模型偶发偏离输出契约，而每次偏离赔上整个答案」，"
            "也解释了为什么两轮之间会从 1 题跳到 6 题：这是随机脱靶，不是某类问题的固定缺陷。"
            "修法是给失败分支加**带守卫的回退**（不像 JSON 且至少有一个编号，才按正文解析；"
            "正文一个编号都没有，才回退到 claims），**核验一寸不放**——"
            "两条路径照走同一套绑定与不变量检查，编造的编号照样剥掉。"
            "结果：**误拒率 7.69% → 0.00%**（78 道可答题零误拒，比 08-04 基线还低），"
            "Story 覆盖收回 5.6pt，引用覆盖率 90.7%，must_contain 命中 100%，"
            "而**断言假前提仍是 0**——放宽没有换来幻觉。"
            "唯一下行的是支持度 −2.2pt：被救回的六题分数确实偏低（0.7046 对 0.7707），"
            "但它们的 Story 覆盖是 **0.8889**、远高于全体的 0.7419，"
            "救回来的是覆盖面更宽的实质答案；其余 72 题代码路径逐字未变却也动了 −2.0pt，"
            "那是模型自身的轮间抖动。**多发表六个答案换来均值略降，这是正确的代价。**"
        ),
    },
    {
        "id": "LAT",
        "file": "m4-rag-eval-LAT-20260804.json",
        "title": "端到端延迟",
        "changed": "24 题实测 p50 / p95 与各阶段耗时占比。",
        "finding": (
            "**这组数字推翻了此前的一个判断。** 原以为「父块/折叠是打磨项，检索是大头」，"
            "数据说反了：本地计算（dense + sparse + fuse + select + parent）合计不到 1%，"
            "99% 的时间花在三次外部 API 往返上。直接后果是压延迟只能动网络侧，"
            "而任何「多算几路」的实验成本可以忽略。"
        ),
    },
]


def _load(name: str) -> dict[str, Any]:
    return json.loads((STATUS / name).read_text(encoding="utf-8"))


def _retrieval_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    overall = payload.get("summary", {}).get("overall", {})
    return {
        "recall10": overall.get("recall@10"),
        "recall20": overall.get("recall@20"),
        "mrr": overall.get("mrr"),
        "ndcg10": overall.get("ndcg@10"),
        "questions": overall.get("questions"),
        "scored": overall.get("scored"),
    }


def _by_category(payload: dict[str, Any]) -> dict[str, Any]:
    categories = payload.get("summary", {}).get("by_category", {})
    return {
        name: {
            "recall10": row.get("recall@10"),
            "mrr": row.get("mrr"),
            "ndcg10": row.get("ndcg@10"),
        }
        for name, row in categories.items()
    }


def build() -> dict[str, Any]:
    rounds = []
    for entry in ROUNDS:
        payload = _load(entry["file"])
        record = {
            "id": entry["id"],
            "title": entry["title"],
            "runId": payload.get("run_id"),
            "variant": payload.get("config", {}).get("variant"),
            "changed": entry["changed"],
            "criterion": entry["criterion"],
            "finding": entry["finding"],
            "verdict": entry["verdict"],
            "metrics": _retrieval_metrics(payload),
            "byCategory": _by_category(payload),
        }
        if alt := entry.get("alt"):
            other = _load(alt["file"])
            record["alt"] = {
                "label": alt["label"],
                "runId": other.get("run_id"),
                "metrics": _retrieval_metrics(other),
            }
        rounds.append(record)

    extra = []
    for entry in EXTRA:
        payload = _load(entry["file"])
        summary = payload.get("summary", {})
        extra.append(
            {
                "id": entry["id"],
                "title": entry["title"],
                "runId": payload.get("run_id"),
                "changed": entry["changed"],
                "finding": entry["finding"],
                "overall": summary.get("overall") or summary.get("end_to_end") or {},
                "stages": summary.get("stages") or {},
                "tokens": summary.get("tokens") or {},
            }
        )

    return {
        "generatedFrom": "docs/status/m4-rag-eval-*.json",
        "ragas": RAGAS_MAPPING,
        "goldenQuestions": _load(ROUNDS[0]["file"]).get("config", {}).get("golden_questions"),
        "rounds": rounds,
        "extra": extra,
    }


def main() -> int:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    payload = build()
    TARGET.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {TARGET.relative_to(ROOT)}: {len(payload['rounds'])} rounds, "
          f"{len(payload['extra'])} extra runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
