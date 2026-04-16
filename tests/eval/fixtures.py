"""Fixtures — in-memory SQLite setup and a deterministic stub embedder.

The embedder is the only thing that needs thinking. Real retrieval uses a
384-dim sentence-transformers vector; for offline eval we need a function
that is:

    1. Deterministic (same input → same vector, across processes)
    2. Content-aware (queries that mention Mochi retrieve Mochi events)
    3. Cheap (no model loading)

Strategy: maintain a fixed keyword → axis mapping. Each text's vector sums
the axes for any keywords it contains (case-insensitive substring match).
Normalized to unit length. Unknown text still gets a nonzero fallback axis
so vectors never collapse to all-zero.
"""

from __future__ import annotations

import math

from sqlalchemy import Engine
from sqlmodel import Session as DbSession

from echovessel.memory import Persona, User, create_all_tables, create_engine
from echovessel.memory.backends.sqlite import SQLiteBackend

EMBED_DIM = 384

# Keyword → axis index. Each axis is a semantic "slot"; overlapping queries
# and events on the same axis get nonzero cosine similarity. The axis layout
# is intentional: one row per tracked ground-truth concept, so that retrieve
# can distinguish facts/peaks without collisions.
#
# Keep axis numbers < EMBED_DIM. Sorted here for readability, not required.
KEYWORD_AXES: dict[str, int] = {
    # --- fact_001 / peak_001 side channel -------------------------------
    "mochi": 0,
    "橘猫": 0,
    "猫": 0,
    "那只猫": 0,
    # --- fact_002 ------------------------------------------------------
    "软件工程师": 1,
    "软件": 1,
    "后端": 1,
    "工程师": 1,
    "写代码": 1,
    "工作": 1,
    "职业": 1,
    "做什么": 1,
    # --- fact_003 ------------------------------------------------------
    "公寓": 2,
    "独居": 2,
    "一个人住": 2,
    "住在": 2,
    "住哪": 2,
    "住在哪": 2,
    "我住": 2,
    # --- fact_004 / family --------------------------------------------
    "妈妈": 3,
    "我妈": 3,
    "母亲": 3,
    "家里": 3,
    "小城": 3,
    "高铁": 3,
    "妈住": 3,
    "家人": 3,
    # --- shared scaffolding between residence and family -------------
    "南方": 40,
    "城市": 40,
    # --- fact_005 ------------------------------------------------------
    "香菜": 4,
    "过敏": 4,
    # --- fact_006 / 跑步 ----------------------------------------------
    "跑步": 5,
    "公园": 5,
    "每周": 5,
    # --- fact_007 / 左撇子 --------------------------------------------
    "左撇子": 6,
    "左手": 6,
    # --- fact_008 / id_003 ---------------------------------------------
    "机械": 7,
    "大学": 7,
    "转行": 7,
    "自学": 7,
    # --- fact_009 / 黑咖啡 --------------------------------------------
    "黑咖": 8,
    "咖啡": 8,
    "不加糖": 8,
    # --- fact_010 / 深夜 ----------------------------------------------
    "深夜": 9,
    "半夜": 9,
    "23": 9,
    "晚上聊": 9,
    # --- fact_011 / mochi age already covered by axis 0 (pet) ---------
    # --- fact_012 / 茴香饺子 ------------------------------------------
    "茴香": 10,
    "饺子": 10,
    # --- peak_001 / id_001 · father ------------------------------------
    "父亲": 11,
    "爸": 11,
    "去世": 11,
    "两年前": 11,
    "冬天": 11,
    "冷白色": 11,
    "冷灯": 11,
    "医院": 11,
    "走廊": 11,
    # --- peak_002 / id_002 · depression --------------------------------
    "抑郁": 12,
    "那盒药": 12,
    "吃了": 12,
    "确诊": 12,
    # --- peak_003 · Mochi vet -----------------------------------------
    "疫苗": 13,
    "打针": 13,
    "蔫": 13,
    "自责": 13,
    # --- peak_004 / id_004 · offer -------------------------------------
    "offer": 14,
    "心仪": 14,
    "面试": 14,
    "配得上": 14,
    "impostor": 14,
    "冒名": 14,
    "不是高兴": 14,
    # --- peak_005 · sunset --------------------------------------------
    "天光": 15,
    "傍晚": 15,
    "橙子色": 15,
    "薄紫": 15,
    # --- peak_006 / turn_003 · gratitude -------------------------------
    "谢谢你": 16,
    "熬过": 16,
    "低谷": 16,
    "一直在": 16,
    # --- turn_001 (shares axis 12 with peak_002) ----------------------
    # --- turn_002 · first joke ----------------------------------------
    "铲屎": 17,
    "最好的情绪管理": 17,
    # --- del_001 · ex -------------------------------------------------
    "橙子": 18,
    "前任": 18,
    "糖炒栗子": 18,
    "雨夜": 18,
    # --- del_002 · coworker -------------------------------------------
    "t 哥": 19,
    "t哥": 19,
    "同事": 19,
    "评审": 19,
    "抢了": 19,
    "抢": 19,
    # --- del_003 · job change -----------------------------------------
    "跳槽": 20,
    "ai 陪伴": 20,
    "ai陪伴": 20,
    "早期公司": 20,
    "换工作": 20,
    # --- del_004 · karaoke --------------------------------------------
    "karaoke": 21,
    "卡拉ok": 21,
    "跑调": 21,
    "聚会": 21,
    "唱": 21,
    # --- red herrings (distinct axes so they can never collide with
    #     facts or peaks by accident). These are far from everything else.
    "三明治": 30,
    "便利店": 30,
    "地铁": 31,
    "晚点": 31,
    "牙线": 32,
    "天气预报": 33,
    "周末": 33,
    "下雨": 33,
    "空调": 34,
    "冷冻柜": 34,
    "usb-c": 35,
    "快递": 36,
    "小狗": 36,
    "podcast": 37,
    "海盐": 38,
    "拿铁": 38,
    # --- day/time scaffolding (weak signal so generic text still embeds)
    "今天": 50,
    "早": 51,
    "晚": 52,
}

# Fallback axis used when a text has no keyword hits at all, so vectors are
# never all-zero (which would make cosine distance undefined for some paths).
FALLBACK_AXIS = 383


def build_engine() -> Engine:
    """Create a fresh in-memory SQLite engine with full schema."""
    engine = create_engine(":memory:")
    create_all_tables(engine)
    return engine


def seed_persona(db: DbSession, persona_id: str = "p_eval", user_id: str = "self") -> None:
    db.add(Persona(id=persona_id, display_name="Eval Persona"))
    db.add(User(id=user_id, display_name="Eval User"))
    db.commit()


def build_backend(engine: Engine) -> SQLiteBackend:
    return SQLiteBackend(engine)


def stub_embed(text: str) -> list[float]:
    """Deterministic keyword-based embedder.

    Lower-cased substring match against KEYWORD_AXES. Sums 1.0 per hit onto
    each matched axis, then L2-normalises. Zero matches → a unit weight on
    FALLBACK_AXIS so the vector never collapses.
    """
    vec = [0.0] * EMBED_DIM
    lowered = text.lower()
    hit = False
    for kw, axis in KEYWORD_AXES.items():
        if kw in lowered:
            vec[axis] += 1.0
            hit = True
    if not hit:
        vec[FALLBACK_AXIS] = 1.0

    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec
