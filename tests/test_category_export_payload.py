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


def test_build_strict_payload_maps_bergueda_display_name_with_accent():
    example_payload = {
        "municipi-maresme": "",
        "municipi-cerdanya": "",
        "municipi-bergueda": "",
    }

    payload = build_strict_payload_from_example(example_payload, {
        "municipality": "BERGUEDA",
    })

    assert payload["municipi-maresme"] == ""
    assert payload["municipi-cerdanya"] == ""
    assert payload["municipi-bergueda"] == "Berguedà"


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


def test_build_strict_payload_uses_pipe_separator_for_agenda_search_dates_string():
    example_payload = {
        "dates-que-es-realitza-buscador": "{{search_dates_string}}",
    }

    payload = build_strict_payload_from_example(example_payload, {
        "search_dates": ["2026-04-17", "2026-04-18", "2026-04-19"],
    })

    assert payload["dates-que-es-realitza-buscador"] == "2026-04-17|2026-04-18|2026-04-19"


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


def test_normalize_strict_payload_exact_fields_repairs_agenda_program_fields():
    payload = {
        "categoria-d-agenda": "Concert",
        "data-esdeveniment": "",
        "data-inici": "",
        "data-final": "",
        "dates-que-es-realitza-buscador": "",
        "titol-activitat": "",
        "data-i-hora-activitat": "",
        "on-es-realitza-l-activitat": "",
        "descripcio-activitat": "",
        "informacio-adicional": "",
        "imatge-activitat": "",
        "activitats": "",
    }

    normalized = normalize_strict_payload_exact_fields(payload, {
        "agenda_category": "Agenda d'esports",
        "event_date": "2026-04-17",
        "start_date": "",
        "end_date": "",
        "search_dates": ["2026-04-17"],
        "search_dates_string": "2026-04-17",
        "activity_titles": "Cursa popular",
        "activity_dates": "04/17/2026",
        "activity_locations": "Plaça Major",
        "activity_descriptions": "<p>Recorregut urbà de 5 km.</p>",
        "activity_extra_info": "<p>Inscripció prèvia</p>",
        "activity_images": "https://example.com/cursa.jpg",
        "activities_backend": "Cursa popular",
    })

    assert normalized["categoria-d-agenda"] == "Agenda d'esports"
    assert normalized["data-esdeveniment"] == "2026-04-17"
    assert normalized["data-inici"] == ""
    assert normalized["data-final"] == ""
    assert normalized["dates-que-es-realitza-buscador"] == "2026-04-17"
    assert normalized["titol-activitat"] == "Cursa popular"
    assert normalized["data-i-hora-activitat"] == "04/17/2026"
    assert normalized["on-es-realitza-l-activitat"] == "Plaça Major"
    assert normalized["descripcio-activitat"] == "<p>Recorregut urbà de 5 km.</p>"
    assert normalized["informacio-adicional"] == "<p>Inscripció prèvia</p>"
    assert normalized["imatge-activitat"] == "https://example.com/cursa.jpg"
    assert normalized["activitats"] == "Cursa popular"
