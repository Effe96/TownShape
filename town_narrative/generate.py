from town_db.generate import generate_town_database
from town_db.schema import connect

from town_narrative.parameters import TownParameters


def generate_town_from_parameters(params: TownParameters, db_path: str) -> None:
    generate_town_database(
        params.seed,
        params.target_population,
        db_path,
        area_per_resident_multiplier=params.area_per_resident_multiplier,
        density_multiplier=params.density_multiplier,
        rich_proportion=params.rich_proportion,
        num_rivers=params.num_rivers,
        has_coastline=params.has_coastline,
        has_port=params.has_port,
        magic_prevalence=params.magic_prevalence,
        aggression=params.aggression,
    )

    conn = connect(db_path)
    conn.execute(
        "INSERT INTO generation_parameters (id, seed, target_population, area_per_resident_multiplier, "
        "density_multiplier, rich_proportion, num_rivers, has_coastline, has_port, magic_prevalence, aggression) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, str(params.seed), params.target_population, params.area_per_resident_multiplier,
         params.density_multiplier, params.rich_proportion, params.num_rivers,
         int(params.has_coastline), int(params.has_port), params.magic_prevalence, params.aggression),
    )
    conn.commit()
    conn.close()
