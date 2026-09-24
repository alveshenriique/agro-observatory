import importlib


def test_package_is_importable() -> None:
    module = importlib.import_module("agro_observatory")
    assert module.__name__ == "agro_observatory"
