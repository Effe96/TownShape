# town_shaper/seeding.py
import hashlib
import random


def derive_seed(base_seed, *parts) -> int:
    key = repr((base_seed,) + parts).encode("utf-8")
    digest = hashlib.sha256(key).hexdigest()
    return int(digest[:16], 16)


def rng_for(base_seed, *parts) -> random.Random:
    return random.Random(derive_seed(base_seed, *parts))
