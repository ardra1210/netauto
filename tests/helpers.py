from pathlib import Path

from app.source_of_truth import YamlSourceOfTruth

RACKS = Path(__file__).resolve().parent.parent / "data" / "racks"


def good_rack():
    return YamlSourceOfTruth(RACKS).get_rack("sjc01-r01")


def broken_rack():
    return YamlSourceOfTruth(RACKS).get_rack("sjc01-r02-broken")
