from typing import Any, Dict, List

# A representative slice of medieval-demographics-made-easy.pdf's Support
# Value table: population needed to support one business of this type.
# Lower sv = more common = more frequently purchased.
GOODS_CATALOG: List[Dict[str, Any]] = [
    {"name": "bread", "category": "food", "typical_price": 0.05, "sv": 800},
    {"name": "meat", "category": "food", "typical_price": 0.20, "sv": 1200},
    {"name": "fish", "category": "food", "typical_price": 0.15, "sv": 1200},
    {"name": "ale", "category": "drink", "typical_price": 0.10, "sv": 1400},
    {"name": "wine", "category": "drink", "typical_price": 0.30, "sv": 900},
    {"name": "cloth garment", "category": "clothing", "typical_price": 2.0, "sv": 250},
    {"name": "shoes", "category": "clothing", "typical_price": 1.0, "sv": 150},
    {"name": "candles", "category": "household", "typical_price": 0.10, "sv": 700},
    {"name": "spices", "category": "luxury", "typical_price": 3.0, "sv": 1400},
    {"name": "tools", "category": "tools", "typical_price": 2.5, "sv": 1500},
    {"name": "furniture", "category": "household", "typical_price": 5.0, "sv": 550},
    {"name": "jewelry", "category": "luxury", "typical_price": 15.0, "sv": 400},
    {"name": "healing potion", "category": "magic", "typical_price": 4.0, "sv": 500},
    {"name": "spell scroll", "category": "magic", "typical_price": 8.0, "sv": 300},
    {"name": "arcane reagents", "category": "magic", "typical_price": 1.5, "sv": 700},
]


def insert_goods(conn) -> Dict[str, int]:
    ids: Dict[str, int] = {}
    for good in GOODS_CATALOG:
        cursor = conn.execute(
            "INSERT INTO goods (name, category, typical_price, sv) VALUES (?, ?, ?, ?)",
            (good["name"], good["category"], good["typical_price"], good["sv"]),
        )
        ids[good["name"]] = cursor.lastrowid
    return ids
