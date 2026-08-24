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
    )

    conn = connect(db_path)
    conn.execute(
        "INSERT INTO generation_parameters (seed, target_population, area_per_resident_multiplier, "
        "density_multiplier, rich_proportion) VALUES (?, ?, ?, ?, ?)",
        (str(params.seed), params.target_population, params.area_per_resident_multiplier,
         params.density_multiplier, params.rich_proportion),
    )
    conn.commit()
    conn.close()
