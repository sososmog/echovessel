"""Canned stub responses for the eval harness — replaces real LLM calls.

Three tables:

1. SESSION_EXTRACTIONS
   Per-corpus-session list of events the stub `extract_fn` should emit. Each
   entry is tagged with `gt_id` so the harness can build a
   (ground_truth_id → concept_node_id) mapping after consolidate runs. A
   session not listed here yields an empty extraction (valid; filler days).

2. FACT_KEYWORD_MATCHERS / PEAK_KEYWORD_MATCHERS
   Per-ground-truth-id lists of lowercase substrings. A retrieved memory
   description is considered to "cover" a fact/peak iff any of its matchers
   appears in the description. This replaces the real LLM judge for the
   baseline — deterministic and fast.

3. DELETION_CONTENT_KEYWORDS
   Per deletion_target id, lowercase substrings that must NOT appear in any
   retrieved memory after Day 13 deletion. Used for Deletion Compliance.

Everything here is hand-written for MVP. Thread E's corpus is the source of
truth; these tables are the "expected LLM behaviour" side of the stub.

The harness calls extract_fn / reflect_fn / embed_fn / stub_judge directly
— no StubProvider wrapper, no JSON serialisation round-trip, no
`hash(system+user)` keying. That would be necessary if we were replaying real
LLM responses; for MVP we're replaying *idealised* LLM responses, so the
simpler keying (session_id) is fine. Thread RT's StubProvider can plug in
later by wrapping these same dicts.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# SESSION_EXTRACTIONS — what each session's extract_fn should return
# ---------------------------------------------------------------------------
#
# Fields per entry:
#   gt_id          — ground_truth id this event corresponds to (or None)
#   description    — the event's ConceptNode.description
#   emotional_impact
#   emotion_tags
#   relational_tags
#
# The emotional_impact is the value that drives SHOCK triggering. Peak events
# with |impact|>=8 MUST keep that value so the reflection path fires.
# ---------------------------------------------------------------------------

SESSION_EXTRACTIONS: dict[str, list[dict]] = {
    # ---- Day 1 ----
    "s_001": [
        {
            "gt_id": "fact_001",
            "description": "用户养了一只叫 Mochi 的橘猫",
            "emotional_impact": 2,
            "emotion_tags": ["warmth"],
            "relational_tags": [],
        },
        {
            "gt_id": "fact_002",
            "description": "用户的职业是软件工程师，主要写后端",
            "emotional_impact": 0,
            "emotion_tags": [],
            "relational_tags": [],
        },
        {
            "gt_id": "fact_003",
            "description": "用户独居在南方一座城市的公寓里",
            "emotional_impact": 0,
            "emotion_tags": [],
            "relational_tags": [],
        },
        {
            "gt_id": "fact_004",
            "description": "用户的母亲住在另一座南方的小城，高铁两个多小时",
            "emotional_impact": 0,
            "emotion_tags": [],
            "relational_tags": [],
        },
    ],
    # ---- Day 2 ----
    "s_002": [
        {
            "gt_id": "fact_005",
            "description": "用户对香菜过敏",
            "emotional_impact": 0,
            "emotion_tags": [],
            "relational_tags": [],
        },
        {
            "gt_id": "del_001",
            "description": "用户提到一位叫橙子的前任，以及一次雨夜街边糖炒栗子的回忆",
            "emotional_impact": -1,
            "emotion_tags": ["nostalgia"],
            "relational_tags": [],
        },
    ],
    # ---- Day 3 · SHOCK peak ----
    "s_003b": [
        {
            "gt_id": "peak_001",
            "description": (
                "用户第一次对 persona 说起父亲两年前因病去世的事："
                "冬天，在医院的走廊里守了一个月，走廊的灯是冷白色的"
            ),
            "emotional_impact": -9,
            "emotion_tags": ["grief", "loss", "longing"],
            "relational_tags": ["identity-bearing", "vulnerability", "unresolved"],
        },
        {
            "gt_id": "fact_010",
            "description": "用户习惯在深夜 23 点到 1 点之间上线聊沉重话题",
            "emotional_impact": 0,
            "emotion_tags": [],
            "relational_tags": [],
        },
    ],
    # ---- Day 4 ----
    "s_004": [
        {
            "gt_id": "fact_007",
            "description": "用户是左撇子",
            "emotional_impact": 0,
            "emotion_tags": [],
            "relational_tags": [],
        },
    ],
    # ---- Day 5 · turning point + peak_002 ----
    "s_005": [
        {
            "gt_id": "peak_002",
            "description": (
                "用户坦白自己曾被确诊过一段轻度抑郁期，"
                "吃了四个月的那盒药，从未告诉过身边任何人"
            ),
            "emotional_impact": -7,
            "emotion_tags": ["shame", "vulnerability", "relief"],
            "relational_tags": [
                "identity-bearing",
                "vulnerability",
                "turning-point",
            ],
        },
        {
            "gt_id": "fact_008",
            "description": "用户大学学的是机械工程，毕业后自学转行写代码",
            "emotional_impact": 0,
            "emotion_tags": [],
            "relational_tags": [],
        },
    ],
    # ---- Day 6 · contra_001 fix + fact_009 + peak_005 + del_002 ----
    "s_006": [
        {
            "gt_id": "fact_011",
            "description": "Mochi 今年 3 岁（用户 Day 6 自己翻领养记录后纠正的年龄）",
            "emotional_impact": 0,
            "emotion_tags": [],
            "relational_tags": [],
        },
        {
            "gt_id": "fact_009",
            "description": "用户最喜欢的饮料是黑咖啡不加糖",
            "emotional_impact": 0,
            "emotion_tags": [],
            "relational_tags": [],
        },
        {
            "gt_id": "peak_005",
            "description": "用户在下班路上看到一场橙子色掺薄紫色的傍晚天光，觉得久违的安静",
            "emotional_impact": 5,
            "emotion_tags": ["calm", "awe"],
            "relational_tags": [],
        },
        {
            "gt_id": "del_002",
            "description": "用户吐槽同事 T 哥在一次项目评审上抢了自己写的方案的功劳",
            "emotional_impact": -4,
            "emotion_tags": ["frustration"],
            "relational_tags": [],
        },
    ],
    # ---- Day 7 ----
    "s_007a": [
        {
            "gt_id": "fact_012",
            "description": "用户最想念的是母亲做的用茴香做馅的饺子",
            "emotional_impact": 2,
            "emotion_tags": ["longing", "warmth"],
            "relational_tags": [],
        },
    ],
    "s_007b": [
        {
            "gt_id": "peak_003",
            "description": "Mochi 打完疫苗反应很大整夜蔫着，用户在猫窝旁自责一整晚",
            "emotional_impact": -6,
            "emotion_tags": ["worry", "guilt"],
            "relational_tags": ["vulnerability"],
        },
        {
            "gt_id": "fact_006",
            "description": "用户每周跑步 3 次（Day 7 自己纠正，之前说的 5 次是夸大）",
            "emotional_impact": 0,
            "emotion_tags": [],
            "relational_tags": [],
        },
    ],
    # ---- Day 8 · turn_002 + del_003 ----
    "s_008": [
        {
            "gt_id": "turn_002",
            "description": "用户第一次用自嘲的方式把烦恼讲成玩笑：'我最好的情绪管理就是给 Mochi 铲屎'",
            "emotional_impact": 3,
            "emotion_tags": ["relief", "playfulness"],
            "relational_tags": ["turning-point"],
        },
        {
            "gt_id": "del_003",
            "description": "用户透露自己在悄悄面试一家做 AI 陪伴产品的早期公司，考虑跳槽但还没决定",
            "emotional_impact": 1,
            "emotion_tags": ["anticipation"],
            "relational_tags": ["commitment"],
        },
    ],
    # ---- Day 9 · SHOCK positive peak_004 + id_004 ----
    "s_009b": [
        {
            "gt_id": "peak_004",
            "description": (
                "用户拿到了酝酿几个月的心仪 offer；"
                "他第一次觉得'转行这件事也许真的成了'"
            ),
            "emotional_impact": 8,
            "emotion_tags": ["joy", "pride", "relief"],
            "relational_tags": ["identity-bearing", "turning-point"],
        },
    ],
    "s_009c": [
        {
            "gt_id": "id_004",
            "description": (
                "用户承认自己长期有冒名顶替感："
                "收到 offer 的第一反应不是高兴而是'他们是不是看走眼了'"
            ),
            "emotional_impact": -4,
            "emotion_tags": ["self-doubt"],
            "relational_tags": ["identity-bearing"],
        },
    ],
    # ---- Day 10 · del_004 ----
    "s_010b": [
        {
            "gt_id": "del_004",
            "description": (
                "用户讲了一段大学毕业前的尴尬聚会故事："
                "在一个 karaoke 包间唱慢歌跑调，当场哭出来"
            ),
            "emotional_impact": -3,
            "emotion_tags": ["embarrassment"],
            "relational_tags": [],
        },
    ],
    # ---- Day 11 · peak_006 / turn_003 ----
    "s_011b": [
        {
            "gt_id": "peak_006",
            "description": (
                "用户第一次主动说'谢谢你这段时间一直在'，"
                "承认这些深夜聊天让他熬过了最近一段低谷"
            ),
            "emotional_impact": 6,
            "emotion_tags": ["gratitude", "warmth", "relief"],
            "relational_tags": ["turning-point"],
        },
    ],
}


# ---------------------------------------------------------------------------
# Keyword matchers for the stub judge
# ---------------------------------------------------------------------------
#
# A memory description `m.description.lower()` is considered to "cover" a
# ground-truth id iff any of that id's matcher strings (already lowercase) is
# a substring of the memory description.
# ---------------------------------------------------------------------------

FACT_KEYWORD_MATCHERS: dict[str, tuple[str, ...]] = {
    "fact_001": ("mochi", "橘猫"),
    "fact_002": ("软件工程师", "后端"),
    "fact_003": ("独居", "公寓"),
    "fact_004": ("母亲", "小城", "高铁"),
    "fact_005": ("香菜", "过敏"),
    "fact_006": ("跑步 3 次", "3 次"),
    "fact_007": ("左撇子",),
    "fact_008": ("机械", "转行", "自学"),
    "fact_009": ("黑咖", "不加糖"),
    "fact_010": ("深夜",),
    "fact_011": ("3 岁", "3岁"),
    "fact_012": ("茴香", "饺子"),
}

PEAK_KEYWORD_MATCHERS: dict[str, tuple[str, ...]] = {
    "peak_001": ("父亲", "去世", "冷白色", "医院"),
    "peak_002": ("抑郁", "那盒药"),
    "peak_003": ("疫苗", "蔫", "自责"),
    "peak_004": ("offer", "心仪", "转行"),
    "peak_005": ("天光", "傍晚", "橙子色"),
    "peak_006": ("谢谢你", "熬过", "低谷"),
}


# These are the strings that MUST NOT appear in any retrieved memory after a
# Day 13 deletion has been applied. Matched case-insensitively as substrings.
DELETION_CONTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    # "橙子" alone collides with "橙子色" (a color word that legitimately
    # appears in peak_005's sunset event), so we match on the more unique
    # phrases instead.
    "del_001": ("糖炒栗子", "雨夜", "前任"),
    "del_002": ("t 哥", "t哥", "抢了"),
    "del_003": ("ai 陪伴", "ai陪伴", "跳槽", "早期公司"),
    "del_004": ("karaoke", "跑调", "毕业前的尴尬"),
}


# ---------------------------------------------------------------------------
# Helpers used by the stub judge
# ---------------------------------------------------------------------------


def description_covers(description: str, matchers: tuple[str, ...]) -> bool:
    """True if any matcher appears as a substring of description (case-insensitive)."""
    lowered = description.lower()
    return any(m.lower() in lowered for m in matchers)
