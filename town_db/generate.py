import json
import os
from datetime import date, timedelta
from typing import Dict, Optional

from town_shaper.assignment import DEFAULT_RICH_PROPORTION
from town_shaper.generate import generate_town

from town_db.economy import add_yearly_income, seed_starting_wealth, subtract_yearly_spend
from town_db.enrollment import generate_school_enrollments
from town_db.goods import insert_goods
from town_db.households import DEFAULT_INTERMARRIAGE_RATE, build_households_and_residents
from town_db.military import generate_military_service
from town_db.names import RACE_WEIGHTS
from town_db.persistence import (
    insert_births,
    insert_deaths,
    insert_disease_events,
    insert_military_service,
    insert_purchases,
    insert_residents,
    insert_school_enrollments,
    insert_skirmish_events,
    insert_tax_payments,
    update_household_wealth,
)
from town_db.purchases import SHOP_BUILDING_TYPES, generate_purchases
from town_db.schema import connect, create_schema
from town_db.taxes import generate_tax_payments
from town_db.unrest import generate_skirmish_casualties, generate_skirmish_events
from town_db.vital_records import (
    DEFAULT_BIRTH_RATE,
    DEFAULT_DEATH_RATE_BY_AGE,
    generate_births_and_deaths,
    generate_disease_events,
)

DEFAULT_YEAR_START = date(1300, 1, 1)
YEAR_LENGTH_DAYS = 365


def _water_feature_rings(feature):
    polygon = feature.polygon
    return [list(polygon.exterior.coords)[:-1]] + [
        list(interior.coords)[:-1] for interior in polygon.interiors
    ]


def generate_town_database(
    seed,
    target_population: int,
    db_path: str,
    year_start: date = DEFAULT_YEAR_START,
    race_weights: Dict[str, float] = RACE_WEIGHTS,
    intermarriage_rate: float = DEFAULT_INTERMARRIAGE_RATE,
    birth_rate: float = DEFAULT_BIRTH_RATE,
    death_rate_by_age: Dict[str, float] = DEFAULT_DEATH_RATE_BY_AGE,
    area_per_resident_multiplier: float = 1.0,
    density_multiplier: float = 1.0,
    rich_proportion: float = DEFAULT_RICH_PROPORTION,
    num_rivers: int = 0,
    has_coastline: bool = False,
    has_port: bool = False,
    magic_prevalence: float = 0.0,
    aggression: float = 0.0,
    svg_path: Optional[str] = None,
) -> None:
    town = generate_town(
        seed, target_population,
        area_per_resident_multiplier=area_per_resident_multiplier,
        density_multiplier=density_multiplier,
        rich_proportion=rich_proportion,
        num_rivers=num_rivers,
        has_coastline=has_coastline,
        has_port=has_port,
        magic_prevalence=magic_prevalence,
    )

    if svg_path is None:
        svg_path = os.path.splitext(db_path)[0] + ".svg"
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(town.svg)

    conn = connect(db_path)
    create_schema(conn)

    conn.executemany(
        "INSERT INTO water_features (id, kind, polygon) VALUES (?, ?, ?)",
        [(feature.id, feature.kind, json.dumps(_water_feature_rings(feature)))
         for feature in town.water_features],
    )

    zone_type_by_building_id: Dict[int, str] = {
        building.id: district.zone_type.value
        for district in town.districts for building in district.buildings
    }
    conn.executemany(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (?, ?, ?)",
        [(district.id, district.zone_type.value, json.dumps(district.polygon_parts))
         for district in town.districts],
    )
    conn.executemany(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity, name, "
        "width, height, rotation, footprint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(building.id, district.id, district.zone_type.value, building.building_type,
          building.x, building.y, building.capacity, building.name,
          building.width, building.height, building.rotation,
          json.dumps(building.footprint) if building.footprint is not None else None)
         for district in town.districts for building in district.buildings],
    )

    conn.executemany(
        "INSERT INTO road_nodes (id, kind, anchor_id, is_hub, x, y) VALUES (?, ?, ?, ?, ?, ?)",
        [(node.id, node.kind, node.anchor_id, int(node.is_hub), node.x, node.y)
         for node in town.road_network.nodes],
    )
    conn.executemany(
        "INSERT INTO road_edges (id, from_node_id, to_node_id, road_type) VALUES (?, ?, ?, ?)",
        [(edge.id, edge.from_node_id, edge.to_node_id, edge.road_type) for edge in town.road_network.edges],
    )

    household_rows, resident_rows = build_households_and_residents(
        town, seed, year_start, race_weights, intermarriage_rate, magic_prevalence=magic_prevalence,
    )
    for row in resident_rows:
        row["home_zone_type"] = zone_type_by_building_id.get(row["home_building_id"])

    seed_starting_wealth(household_rows, resident_rows)

    conn.executemany(
        "INSERT INTO households (id, family_name, race, wealth) VALUES (?, ?, ?, ?)",
        [(h["id"], h["family_name"], h["race"], h["wealth"]) for h in household_rows],
    )

    insert_residents(conn, resident_rows)

    building_type_by_id = {
        b.id: b.building_type for d in town.districts for b in d.buildings
    }
    add_yearly_income(seed, household_rows, resident_rows, building_type_by_id)

    # Vital records run BEFORE purchases and taxes so that residents who die
    # partway through the year stop shopping and paying tax on their death
    # date, rather than transacting for the whole year regardless.
    disease_rows = generate_disease_events(seed, year_start)
    insert_disease_events(conn, disease_rows)

    temple_id = next((b.id for d in town.districts for b in d.buildings if b.building_type == "temple"), None)
    healer_id = next((b.id for d in town.districts for b in d.buildings if b.building_type == "healer"), None)

    births, deaths, new_resident_rows = generate_births_and_deaths(
        seed, household_rows, resident_rows, disease_rows, year_start,
        temple_id, healer_id, birth_rate, death_rate_by_age,
    )
    insert_residents(conn, new_resident_rows)
    insert_births(conn, births, new_resident_rows)
    insert_deaths(conn, deaths)

    guard_post_id = next((b.id for d in town.districts for b in d.buildings if b.building_type == "guard_post"), None)
    garrison_id = next((b.id for d in town.districts for b in d.buildings if b.building_type == "garrison"), None)
    reporting_building_id = guard_post_id if guard_post_id is not None else garrison_id

    skirmish_rows = generate_skirmish_events(seed, year_start, aggression)
    insert_skirmish_events(conn, skirmish_rows)

    skirmish_deaths = generate_skirmish_casualties(seed, resident_rows, skirmish_rows, reporting_building_id)
    insert_deaths(conn, skirmish_deaths)

    goods_ids = insert_goods(conn)

    shop_building_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type in SHOP_BUILDING_TYPES
    ]
    arcane_shop_building_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type == "arcane_shop"
    ]
    blacksmith_building_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type == "blacksmith"
    ]
    purchases = generate_purchases(
        seed, household_rows, resident_rows, goods_ids, shop_building_ids, year_start,
        magic_prevalence=magic_prevalence, arcane_shop_building_ids=arcane_shop_building_ids,
        blacksmith_building_ids=blacksmith_building_ids,
    )
    insert_purchases(conn, purchases)

    tax_payments = generate_tax_payments(seed, household_rows, resident_rows, year_start)
    insert_tax_payments(conn, tax_payments)

    subtract_yearly_spend(household_rows, resident_rows, purchases, tax_payments)
    update_household_wealth(conn, household_rows)

    all_resident_rows = resident_rows + new_resident_rows

    school_ids = [b.id for d in town.districts for b in d.buildings if b.building_type == "school"]
    university_ids = [b.id for d in town.districts for b in d.buildings if b.building_type == "university"]
    enrollments = generate_school_enrollments(seed, all_resident_rows, school_ids, university_ids, year_start)
    insert_school_enrollments(conn, enrollments)

    garrison_ids = [
        b.id for d in town.districts for b in d.buildings if b.building_type in {"garrison", "guard_post"}
    ]
    military = generate_military_service(all_resident_rows, garrison_ids, year_start)
    insert_military_service(conn, military)

    year_end = year_start + timedelta(days=YEAR_LENGTH_DAYS)
    conn.execute(
        "INSERT INTO town_state (id, year_start, current_date, aggression, magic_prevalence) "
        "VALUES (1, ?, ?, ?, ?)",
        (year_start.isoformat(), year_end.isoformat(), aggression, magic_prevalence),
    )

    conn.commit()
    conn.close()
