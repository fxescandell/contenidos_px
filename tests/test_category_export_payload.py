from app.services.categories.service import (
    build_strict_payload_from_example,
    normalize_strict_payload_municipality_fields,
    normalize_strict_payload_consells_fields,
    normalize_strict_payload_exact_fields,
    resolve_consells_type,
)


def test_build_strict_payload_only_marks_matching_municipality():
    example_payload = {
        "municipi-maresme": "",
        "municipi-cerdanya": "",
        "municipi-bergueda": "",
        "municipality": "",
    }

    payload = build_strict_payload_from_example(example_payload, {
        "municipality": "Maresme",
    })

    assert payload["municipi-maresme"] == "Maresme"
    assert payload["municipi-cerdanya"] == ""
    assert payload["municipi-bergueda"] == ""
    assert payload["municipality"] == "Maresme"


def test_normalize_strict_payload_repairs_municipality_slots_from_direct_payload():
    payload = {
        "municipi-maresme": "Maresme",
        "municipi-cerdanya": "Maresme",
        "municipi-bergueda": "Maresme",
        "nested": {
            "municipi-maresme": "Maresme",
            "municipi-cerdanya": "Maresme",
        },
    }

    normalized = normalize_strict_payload_municipality_fields(payload, "Cerdanya")

    assert normalized["municipi-maresme"] == ""
    assert normalized["municipi-cerdanya"] == "Cerdanya"
    assert normalized["municipi-bergueda"] == ""
    assert normalized["nested"]["municipi-maresme"] == ""
    assert normalized["nested"]["municipi-cerdanya"] == "Cerdanya"


def test_normalize_strict_payload_repairs_consells_type():
    payload = {
        "maresme-001": {
            "consell": "Jardineria",
            "municipi-consells": "MARESME",
        }
    }

    normalized = normalize_strict_payload_consells_fields(payload, "Professionals")

    assert normalized["maresme-001"]["consell"] == "Professionals"
    assert normalized["maresme-001"]["municipi-consells"] == "MARESME"


def test_resolve_consells_type_uses_allowed_values_and_fallback():
    assert resolve_consells_type("Mascotes", "") == "Mascotes"
    assert resolve_consells_type("Jardineria", "Consells de manteniment de jardins i poda") == "Professionals"
    assert resolve_consells_type("", "Guia per cuidar el teu gos i el teu gat a casa") == "Mascotes"


def test_resolve_consells_type_defaults_to_professionals_for_generic_services_topics():
    text = "Consells de jardineria sostenible, manteniment de piscines i serveis professionals per a la llar."

    assert resolve_consells_type("Bellesa", text) == "Professionals"
    assert resolve_consells_type("", text) == "Professionals"


def test_resolve_consells_type_keeps_specific_category_only_with_clear_evidence():
    beauty_text = "Centre d'estetica, tractaments de bellesa, maquillatge i perruqueria professional."

    assert resolve_consells_type("Bellesa", beauty_text) == "Bellesa"


def test_build_strict_payload_uses_exact_seo_fields_without_polluting_empty_template_fields():
    example_payload = {
        "post_content": "",
        "rank_math_title": "",
        "rank_math_pillar_content": "",
        "elementor_library_category": "",
        "contentUrl": "",
        "article-destacat": "",
    }

    payload = build_strict_payload_from_example(example_payload, {
        "body_html": "<p>Cos optimitzat</p>",
        "rank_math_title": "Titol SEO correcte",
        "rank_math_pillar_content": "",
        "content_url": "",
        "article_destacat": "1",
    })

    assert payload["post_content"] == "<p>Cos optimitzat</p>"
    assert payload["rank_math_title"] == "Titol SEO correcte"
    assert payload["rank_math_pillar_content"] == ""
    assert payload["elementor_library_category"] == ""
    assert payload["contentUrl"] == ""
    assert payload["article-destacat"] == "1"


def test_build_strict_payload_populates_agenda_activities_field():
    example_payload = {
        "activitats": "",
    }

    activities = [{"title": "Concert", "image_ref": "https://example.com/concert.jpg"}]
    payload = build_strict_payload_from_example(example_payload, {
        "activities": activities,
    })

    assert payload["activitats"] == activities


def test_normalize_strict_payload_exact_fields_repairs_seo_and_fixed_template_fields():
    payload = {
        "post_content": "incorrecte",
        "rank_math_description": "massa llarga i incorrecta",
        "elementor_library_category": "CONSELLS",
        "article-destacat": "0",
    }

    normalized = normalize_strict_payload_exact_fields(payload, {
        "body_html": "<p>Cos final</p>",
        "rank_math_description": "Descripcio SEO final.",
        "elementor_library_category": "",
        "article_destacat": "1",
    })

    assert normalized["post_content"] == "<p>Cos final</p>"
    assert normalized["rank_math_description"] == "Descripcio SEO final."
    assert normalized["elementor_library_category"] == ""
    assert normalized["article-destacat"] == "1"
