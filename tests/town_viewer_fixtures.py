import json

from town_db.schema import connect, create_schema
from town_relationships.schema import create_relationships_schema


def build_full_town(db_path: str) -> None:
    """A small but complete town: 2 districts, 4 buildings, 1 household of
    4 (2 parents + 2 children), family relationships, and a shop_relationship
    for one resident."""
    conn = connect(db_path)
    create_schema(conn)
    create_relationships_schema(conn)

    conn.execute(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (1, 'civic', ?)",
        (json.dumps([[[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]]]),),
    )
    conn.execute(
        "INSERT INTO districts (id, zone_type, polygon) VALUES (2, 'poor_residential', ?)",
        (json.dumps([[[20.0, 0.0], [40.0, 0.0], [40.0, 20.0], [20.0, 20.0]]]),),
    )

    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (1, 1, 'civic', 'temple', 10.0, 10.0, 0)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (2, 1, 'civic', 'town_hall', 15.0, 5.0, 5)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (3, 2, 'poor_residential', 'shop', 25.0, 10.0, 0)"
    )
    conn.execute(
        "INSERT INTO buildings (id, district_id, zone_type, building_type, x, y, capacity) "
        "VALUES (4, 2, 'poor_residential', 'residence', 30.0, 15.0, 6)"
    )

    conn.execute(
        "INSERT INTO households (id, family_name, race, wealth) VALUES (1, 'Stonebrook', 'human', 120.0)"
    )

    # id 1 Mira (parent, works at the shop), id 2 Tomas (parent, works at town hall),
    # id 3 Elin and id 4 Rian (children, siblings, live at home with no job).
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, "
        "ses, home_building_id, workplace_building_id, occupation) VALUES "
        "(1, 1, 'Mira', 'Stonebrook', 'F', 'human', '1288-01-01', 'rich', 4, 3, 'merchant')"
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, "
        "ses, home_building_id, workplace_building_id, occupation) VALUES "
        "(2, 1, 'Tomas', 'Stonebrook', 'M', 'human', '1286-05-10', 'rich', 4, 2, 'clerk')"
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, "
        "ses, home_building_id, workplace_building_id, occupation) VALUES "
        "(3, 1, 'Elin', 'Stonebrook', 'F', 'human', '1315-03-01', 'rich', 4, NULL, NULL)"
    )
    conn.execute(
        "INSERT INTO residents (id, household_id, first_name, last_name, gender, race, birth_date, "
        "ses, home_building_id, workplace_building_id, occupation) VALUES "
        "(4, 1, 'Rian', 'Stonebrook', 'M', 'human', '1317-08-20', 'rich', 4, NULL, NULL)"
    )

    conn.execute(
        "INSERT INTO relationships (resident_a_id, resident_b_id, relationship_type, detail) "
        "VALUES (1, 2, 'spouse', NULL)"
    )
    conn.execute(
        "INSERT INTO relationships (resident_a_id, resident_b_id, relationship_type, detail) "
        "VALUES (1, 3, 'parent', NULL)"
    )
    conn.execute(
        "INSERT INTO relationships (resident_a_id, resident_b_id, relationship_type, detail) "
        "VALUES (2, 3, 'parent', NULL)"
    )
    conn.execute(
        "INSERT INTO relationships (resident_a_id, resident_b_id, relationship_type, detail) "
        "VALUES (1, 4, 'parent', NULL)"
    )
    conn.execute(
        "INSERT INTO relationships (resident_a_id, resident_b_id, relationship_type, detail) "
        "VALUES (2, 4, 'parent', NULL)"
    )
    conn.execute(
        "INSERT INTO relationships (resident_a_id, resident_b_id, relationship_type, detail) "
        "VALUES (3, 4, 'sibling', NULL)"
    )

    conn.execute(
        "INSERT INTO shop_relationships (resident_id, shop_building_id, purchase_count, total_spent, "
        "distance, need_score, customer_score, is_primary) VALUES (1, 3, 12, 340.5, 5.0, 0.8, 0.9, 1)"
    )

    conn.commit()
    conn.close()
