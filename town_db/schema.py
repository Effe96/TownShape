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
    aggression REAL NOT NULL
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
    magic_prevalence REAL NOT NULL
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
