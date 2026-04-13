from unittest.mock import patch

from app.services.categories.service import get_category_export_configs, get_default_category_export_configs


def test_default_category_instructions_include_strict_json_rule():
    configs = get_default_category_export_configs()
    agenda = next(item for item in configs if item["category"] == "AGENDA")
    consells = next(item for item in configs if item["category"] == "CONSELLS")

    assert "estructura del JSON" in agenda["instructions"]
    assert "orden de claves" in agenda["instructions"]
    assert "Rank Math" in agenda["instructions"]
    assert "Destacat" in agenda["instructions"]
    assert "intercalar les imatges" in agenda["instructions"]
    assert "Professionals" in consells["instructions"]


@patch("app.services.categories.service.SettingsResolver.get")
def test_stored_category_instructions_keep_strict_json_rule(mock_get):
    mock_get.return_value = '[{"category":"AGENDA","json_example":"{}","instructions":"Prioritza dates confirmades."}]'

    configs = get_category_export_configs()
    agenda = next(item for item in configs if item["category"] == "AGENDA")

    assert "estructura del JSON" in agenda["instructions"]
    assert "Rank Math" in agenda["instructions"]
    assert "intercalar les imatges" in agenda["instructions"]
    assert "Prioritza dates confirmades." in agenda["instructions"]
