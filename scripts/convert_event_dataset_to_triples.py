#!/usr/bin/env python3
"""Convert military event extraction data into full relation triples (chapter3 schema)."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# chapter3 event types
EVENT_TYPE_MAP = {
    "Deploy": "deploy",
    "Exhibit": "exhibit",
    "Experiment": "experiment",
    "Manoeuvre": "manoeuvre",
    "Accident": "accident",
    "Conflict": "conflict",
    "Support": "support",
}

# Direct role -> relation/entity mappings that do not require event-specific disambiguation.
DIRECT_ROLE_MAP: Dict[str, Tuple[str, str]] = {
    "Date": ("hasTime", "Time"),
    "Location": ("hasLocation", "Location"),
    "Area": ("hasLocation", "Location"),
    "Quantity": ("hasQuantity", "QuantityValue"),
    "Content": ("hasTaskContent", "TaskContent"),
    "Result": ("hasEventResult", "EventResult"),
}

# Lightweight lexical hints for role disambiguation.
ACTOR_HINTS = [
    "海军",
    "空军",
    "陆军",
    "军队",
    "部队",
    "舰队",
    "司令部",
    "政府",
    "国防部",
    "公司",
    "集团",
    "实验室",
    "组织",
    "机构",
    "武装",
    "军方",
    "士兵",
    "水兵",
    "飞行员",
    "军人",
]

ASSET_HINTS = [
    "战机",
    "战斗机",
    "轰炸机",
    "直升机",
    "运输机",
    "无人机",
    "导弹",
    "拦截弹",
    "火箭",
    "炮",
    "鱼雷",
    "雷达",
    "系统",
    "平台",
    "航母",
    "潜艇",
    "驱逐舰",
    "护卫舰",
    "巡逻舰",
    "战舰",
    "舰",
    "艇",
    "坦克",
    "装甲",
    "车辆",
    "战车",
    "发射器",
    "武器",
    "卫星",
]

RESOURCE_HINTS = [
    "燃料",
    "补给",
    "物资",
    "资源",
    "数据",
    "软件",
    "硬件",
    "技术",
    "成果",
    "经费",
    "保障",
]

COMMON_COUNTRY_OR_SIDE = {
    "美国",
    "俄罗斯",
    "乌克兰",
    "英国",
    "法国",
    "德国",
    "日本",
    "韩国",
    "朝鲜",
    "中国",
    "印度",
    "伊朗",
    "伊拉克",
    "阿富汗",
    "叙利亚",
    "土耳其",
    "以色列",
    "巴基斯坦",
    "加拿大",
    "澳大利亚",
    "北约",
    "美方",
    "俄方",
    "乌方",
}


def has_any(text: str, keywords: List[str]) -> bool:
    return any(k in text for k in keywords)


def is_military_asset(text: str) -> bool:
    if has_any(text, ASSET_HINTS):
        return True
    # Typical equipment naming patterns: B-52H, T129, 052D, XM25, etc.
    if re.search(r"[A-Za-z]{1,5}[- ]?\d{1,4}[A-Za-z]*", text):
        return True
    if re.search(r"\d+式", text):
        return True
    return False


def is_actor(text: str) -> bool:
    if text in COMMON_COUNTRY_OR_SIDE:
        return True
    if has_any(text, ACTOR_HINTS):
        return True
    if text.endswith(("国", "方", "军", "军队", "部队", "政府")):
        return True
    return False


def is_material_resource(text: str) -> bool:
    return has_any(text, RESOURCE_HINTS) and not is_military_asset(text)


def normalize_event_type(raw_event_type: str, injure_policy: str) -> Optional[str]:
    if raw_event_type == "Injure":
        if injure_policy == "skip":
            return None
        if injure_policy == "keep":
            return "injure"
        return "accident"
    if raw_event_type in EVENT_TYPE_MAP:
        return EVENT_TYPE_MAP[raw_event_type]
    return raw_event_type.lower()


def map_argument_to_relation(
    event_type_raw: str, role: str, value: str
) -> Optional[Tuple[str, str]]:
    if role in DIRECT_ROLE_MAP:
        return DIRECT_ROLE_MAP[role]

    if role in {"Militaryforce", "Equipment"}:
        if event_type_raw == "Support":
            return "hasDeliveredAsset", "MilitaryAsset"
        return "hasMilitaryAsset", "MilitaryAsset"

    if role == "Subject":
        if event_type_raw == "Support":
            if is_military_asset(value) and not is_actor(value):
                return "hasCarrierAsset", "MilitaryAsset"
            return "hasActor", "Actor"
        if event_type_raw == "Conflict":
            if is_military_asset(value) and not is_actor(value):
                return "hasCarrierAsset", "MilitaryAsset"
            return "hasActor", "Actor"
        if event_type_raw in {"Accident", "Injure"}:
            if is_actor(value) and not is_military_asset(value):
                return "hasActor", "Actor"
            return "hasMilitaryAsset", "MilitaryAsset"
        return "hasActor", "Actor"

    if role == "Object":
        if event_type_raw == "Support":
            if is_military_asset(value) and not is_actor(value):
                return "hasTargetAsset", "MilitaryAsset"
            return "hasRecipient", "Actor"
        if event_type_raw == "Conflict":
            if is_military_asset(value) and not is_actor(value):
                return "hasTargetAsset", "MilitaryAsset"
            return "hasTargetActor", "Actor"
        if is_military_asset(value):
            return "hasTargetAsset", "MilitaryAsset"
        return "hasTargetActor", "Actor"

    if role == "Materials":
        if is_military_asset(value):
            return "hasDeliveredAsset", "MilitaryAsset"
        if is_material_resource(value):
            return "hasMaterialResource", "MaterialResource"
        # Default fallback for ambiguous materials in support-like narratives.
        return "hasMaterialResource", "MaterialResource"

    return None


def build_triple(
    event_id: str, event_type: str, predicate: str, object_type: str, object_value: str
) -> Dict[str, Any]:
    return {
        "predicate": predicate,
        "subject": {"MilitaryNewsEvent": {"event_id": event_id, "event_type": event_type}},
        "object": {object_type: object_value},
    }


def convert_dataset(
    records: List[Dict[str, Any]], injure_policy: str, drop_empty: bool
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    out_records: List[Dict[str, Any]] = []
    event_counter: Counter[str] = Counter()
    relation_counter: Counter[str] = Counter()
    unmapped_role_counter: Counter[str] = Counter()

    total_events = 0
    skipped_events = 0
    total_triples = 0
    deduped_triples = 0

    for record in records:
        event_list = record.get("event_list", []) or []
        out_item = {"id": record.get("id"), "text": record.get("text", ""), "triple_list": []}

        for event_idx, event in enumerate(event_list, start=1):
            total_events += 1
            raw_event_type = str(event.get("event_type", "")).strip()
            norm_event_type = normalize_event_type(raw_event_type, injure_policy)
            if norm_event_type is None:
                skipped_events += 1
                continue

            event_counter[norm_event_type] += 1
            event_id = f"E{event_idx}"
            seen_keys = set()

            for arg in event.get("arguments", []) or []:
                role = str(arg.get("role", "")).strip()
                value = str(arg.get("text", "")).strip()
                if not role or not value:
                    continue

                mapped = map_argument_to_relation(raw_event_type, role, value)
                if mapped is None:
                    unmapped_role_counter[role] += 1
                    continue

                predicate, object_type = mapped
                dedupe_key = (event_id, norm_event_type, predicate, object_type, value)
                if dedupe_key in seen_keys:
                    deduped_triples += 1
                    continue
                seen_keys.add(dedupe_key)

                triple = build_triple(
                    event_id=event_id,
                    event_type=norm_event_type,
                    predicate=predicate,
                    object_type=object_type,
                    object_value=value,
                )
                out_item["triple_list"].append(triple)
                relation_counter[predicate] += 1
                total_triples += 1

        if drop_empty and not out_item["triple_list"]:
            continue
        out_records.append(out_item)

    stats = {
        "records_in": len(records),
        "records_out": len(out_records),
        "events_in": total_events,
        "events_skipped": skipped_events,
        "triples_out": total_triples,
        "triples_deduped": deduped_triples,
        "event_type_distribution": dict(event_counter),
        "relation_distribution": dict(relation_counter),
        "unmapped_role_distribution": dict(unmapped_role_counter),
    }
    return out_records, stats


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert event extraction annotations into entity-relation triples "
            "aligned with chapter3 full relation schema."
        )
    )
    parser.add_argument(
        "-i",
        "--input",
        default="军事新闻知识抽取数据集.json",
        help="Input event extraction dataset JSON path.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="军事新闻知识三元组抽取数据集.json",
        help="Output triples dataset JSON path.",
    )
    parser.add_argument(
        "--injure-policy",
        choices=["map_to_accident", "keep", "skip"],
        default="map_to_accident",
        help=(
            "How to handle event_type=Injure: "
            "map_to_accident (default), keep (as injure), or skip."
        ),
    )
    parser.add_argument(
        "--drop-empty",
        action="store_true",
        help="Drop records that have no triples after conversion.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Write compact JSON (no indentation).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    input_data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(input_data, list):
        raise ValueError("Input JSON must be a list of records.")

    converted, stats = convert_dataset(
        records=input_data,
        injure_policy=args.injure_policy,
        drop_empty=args.drop_empty,
    )

    if args.compact:
        serialized = json.dumps(converted, ensure_ascii=False, separators=(",", ":"))
    else:
        serialized = json.dumps(converted, ensure_ascii=False, indent=2)
    output_path.write_text(serialized, encoding="utf-8")

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"output_path: {output_path.resolve()}")


if __name__ == "__main__":
    main()
