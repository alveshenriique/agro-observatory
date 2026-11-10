import importlib


def test_package_is_importable() -> None:
    module = importlib.import_module("atlas_da_lavoura")
    assert module.__name__ == "atlas_da_lavoura"
