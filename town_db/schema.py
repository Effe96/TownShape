import sqlite3

SCHEMA_SQL = """
CREATE TABLE districts (
    id INTEGER PRIMARY KEY,
    zone_type TEXT NOT NULL,
    polygon TEXT NOT NULL
);

CREATE TABLE buildings (
    id INTEGER PRIMARY KEY,
    district_id INTEGER NOT NULL REFERENCES districts(id),
    zone_type TEXT NOT NULL,
    building_type TEXT NOT NULL,
    x REAL NOT NULL,
    y REAL NOT NULL,
    capacity INTEGER NOT NULL,
    name TEXT,
    width REAL NOT NULL DEFAULT 0,
    height REAL NOT NULL DEFAULT 0,
    rotation REAL NOT NULL DEFAULT 0,
    footprint TEXT
);

CREATE TABLE road_nodes (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    anchor_id INTEGER REFERENCES districts(id),
    is_hub INTEGER NOT NULL DEFAULT 0,
    x REAL NOT NULL,
    y REAL NOT NULL
);

CREATE TABLE road_edges (
    id INTEGER PRIMARY KEY,
    from_node_id INTEGER NOT NULL REFERENCES road_nodes(id),
    to_node_id INTEGER NOT NULL REFERENCES road_nodes(id),
    road_type TEXT NOT NULL
);

CREATE TABLE households (
    id INTEGER PRIMARY KEY,
    family_name TEXT NOT NULL,
    race TEXT NOT NULL,
    wealth REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE residents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id),
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    gender TEXT NOT NULL,
    race TEXT NOT NULL,
    birth_date TEXT NOT NULL,
    death_date TEXT,
    ses TEXT NOT NULL,
    is_noble INTEGER NOT NULL DEFAULT 0,
    has_magical_talent INTEGER NOT NULL DEFAULT 0,
    home_building_id INTEGER REFERENCES buildings(id),
    workplace_building_id INTEGER REFERENCES buildings(id),
    occupation TEXT
);

CREATE TABLE goods (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    typical_price REAL NOT NULL,
    sv INTEGER NOT NULL
);

CREATE TABLE purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    shop_building_id INTEGER NOT NULL REFERENCES buildings(id),
    good_id INTEGER NOT NULL REFERENCES goods(id),
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    total_price REAL NOT NULL,
    purchase_date TEXT NOT NULL
);

CREATE TABLE tax_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    tax_type TEXT NOT NULL,
    amount REAL NOT NULL,
    period TEXT NOT NULL,
    payment_date TEXT NOT NULL
);

CREATE TABLE disease_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    affected_zone_type TEXT,
    severity REAL NOT NULL
);

CREATE TABLE illnesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    disease_event_id INTEGER REFERENCES disease_events(id),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    severity REAL NOT NULL
);

CREATE TABLE skirmish_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    skirmish_date TEXT NOT NULL,
    severity REAL NOT NULL
);

CREATE TABLE births (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    child_resident_id INTEGER NOT NULL REFERENCES residents(id),
    mother_resident_id INTEGER NOT NULL REFERENCES residents(id),
    father_resident_id INTEGER REFERENCES residents(id),
    birth_date TEXT NOT NULL,
    reported_by_building_id INTEGER NOT NULL REFERENCES buildings(id)
);

CREATE TABLE deaths (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL UNIQUE REFERENCES residents(id),
    death_date TEXT NOT NULL,
    cause TEXT NOT NULL,
    disease_event_id INTEGER REFERENCES disease_events(id),
    skirmish_event_id INTEGER REFERENCES skirmish_events(id),
    reported_by_building_id INTEGER REFERENCES buildings(id)
);

CREATE TABLE school_enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    school_building_id INTEGER NOT NULL REFERENCES buildings(id),
    enrollment_type TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT
);

CREATE TABLE military_service (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    garrison_building_id INTEGER NOT NULL REFERENCES buildings(id),
    rank TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT
);

CREATE TABLE generation_parameters (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    seed TEXT NOT NULL,
    target_population INTEGER NOT NULL,
    area_per_resident_multiplier REAL NOT NULL,
    density_multiplier REAL NOT NULL,
    rich_proportion REAL NOT NULL,
    num_rivers INTEGER NOT NULL,
    has_coastline INTEGER NOT NULL,
    has_port INTEGER NOT NULL,
    magic_prevalence REAL NOT NULL,
    aggression REAL NOT NULL,
    has_citadel INTEGER NOT NULL DEFAULT 0,
    has_walls INTEGER NOT NULL DEFAULT 1,
    river_bearings TEXT NOT NULL DEFAULT '[]',
    road_bearings TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE water_features (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    polygon TEXT NOT NULL
);

CREATE TABLE town_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    year_start TEXT NOT NULL,
    current_date TEXT NOT NULL,
    aggression REAL NOT NULL,
    magic_prevalence REAL NOT NULL,
    svg_min_x REAL,
    svg_min_y REAL,
    svg_max_x REAL,
    svg_max_y REAL
);
"""


# The social sim's state (social-sim-demo/docs/townshape-brief.md). Only the
# sim writes these; TownShape creates them empty and otherwise leaves them
# alone, except that a resident with a departures row has left town alive.
SIM_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS resident_traits (
    resident_id INTEGER PRIMARY KEY REFERENCES residents(id),
    religiousness REAL,
    skepticism REAL,
    cunning REAL,
    loyalty REAL,
    is_ex_soldier INTEGER,
    same_sex_attracted INTEGER,
    stress REAL,
    hungry_months INTEGER,
    is_beggar INTEGER
);

CREATE TABLE IF NOT EXISTS household_economy (
    household_id INTEGER PRIMARY KEY REFERENCES households(id),
    cash REAL,
    property REAL,
    rent_behind REAL,
    usual_income REAL
);

CREATE TABLE IF NOT EXISTS house_tenure (
    building_id INTEGER PRIMARY KEY REFERENCES buildings(id),
    owner_household_id INTEGER REFERENCES households(id),
    owner_kind TEXT NOT NULL,
    value REAL NOT NULL,
    room INTEGER NOT NULL,
    cost_left REAL
);

CREATE TABLE IF NOT EXISTS departures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resident_id INTEGER NOT NULL UNIQUE REFERENCES residents(id),
    departure_date TEXT NOT NULL,
    reason TEXT NOT NULL
);

-- Things that happened somewhere in town (social-sim-demo/docs/
-- townshape-brief-events-2026-10-13.md). One place per row: a building, or a
-- district when there's no single building (riots); both NULL when it
-- happened off the map. kind is an open list, like deaths.cause.
CREATE TABLE IF NOT EXISTS town_events (
    id INTEGER PRIMARY KEY,
    event_date TEXT NOT NULL,
    kind TEXT NOT NULL,
    building_id INTEGER REFERENCES buildings(id),
    district_id INTEGER REFERENCES districts(id),
    actor_resident_id INTEGER REFERENCES residents(id),
    target_resident_id INTEGER REFERENCES residents(id),
    detail TEXT
);

CREATE TABLE IF NOT EXISTS sim_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Nullable columns the sim adds to existing tables; NULL until it sets them.
# relationships only exists once derive_relationships has run, so its columns
# are added whenever it's (re)created.
SIM_COLUMNS = {
    "town_state": ["loyalty REAL", "religiosity REAL", "strictness REAL"],
    "relationships": [
        "time REAL", "intimacy REAL", "services REAL",
        "valence_a_to_b REAL", "valence_b_to_a REAL", "former_type TEXT",
    ],
}


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    ensure_sim_schema(conn)


def ensure_sim_schema(conn: sqlite3.Connection) -> None:
    """Adds whatever of the social sim's tables and columns a town lacks --
    idempotent, so towns generated before them can be brought up to date."""
    conn.executescript(SIM_SCHEMA_SQL)
    for table, columns in SIM_COLUMNS.items():
        have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not have:
            continue  # table not created yet
        for column in columns:
            if column.split()[0] not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column}")


def sim_has_run(conn: sqlite3.Connection) -> bool:
    """True once the social sim has taken a town over (it keeps its state in
    sim_state). From then on TownShape mustn't advance the town or re-derive
    relationships -- the sim owns its people."""
    have = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'sim_state'").fetchone()
    return bool(have) and conn.execute("SELECT 1 FROM sim_state LIMIT 1").fetchone() is not None


class SimOwnedTownError(RuntimeError):
    pass


def refuse_if_sim_owned(conn: sqlite3.Connection, action: str) -> None:
    if sim_has_run(conn):
        raise SimOwnedTownError(
            f"The social sim runs this town (sim_state has rows); TownShape won't {action} -- "
            "it would overwrite the sim's people and ties."
        )
