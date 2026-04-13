from app.services.editorial.agenda_parser import (
    agenda_events_to_content_items,
    normalize_event,
    parse_agenda,
    preprocess_agenda_text,
    render_agenda_html,
    render_highlight_box,
    split_events_by_time,
)


def test_split_events_by_time_splits_multiple_hours_in_one_block():
    block = "9 h Acreditacions i benvinguda 9:30 h Espectacle de magia 11 a 14 h Debat obert"

    fragments = split_events_by_time(block)

    assert len(fragments) == 3
    assert fragments[0].startswith("9 h")
    assert fragments[1].startswith("9:30 h")
    assert fragments[2].startswith("11 a 14 h")


def test_preprocess_agenda_text_inserts_breaks_for_days_spaces_and_times():
    raw = "DIVENDRES, 12 maig Sala Ateneu 9 h Benvinguda 10 h Concert"

    processed = preprocess_agenda_text(raw)

    assert "DIVENDRES, 12 maig\nSala Ateneu\n9 h Benvinguda\n10 h Concert" in processed


def test_parse_agenda_handles_text_without_clear_line_breaks():
    raw = "DIVENDRES, 12 maig Sala Ateneu 9 h Benvinguda 9:30 h Concert infantil 11 h Debat final"

    parsed = parse_agenda(raw)

    assert len(parsed["events"]) == 3
    assert parsed["events"][0]["datetime_label"] == "9 h"
    assert parsed["events"][1]["datetime_label"] == "9:30 h"
    assert parsed["events"][2]["datetime_label"] == "11 h"


def test_parse_agenda_groups_events_across_multiple_days_and_spaces():
    raw = (
        "DIVENDRES, 12 maig\n"
        "Sala Ateneu\n"
        "9 h Benvinguda\n"
        "10 h Concert acústic\n"
        "DISSABTE, 13 maig\n"
        "Espai Tallers\n"
        "11 h Taller familiar\n"
    )

    parsed = parse_agenda(raw)

    assert len(parsed["events"]) == 3
    assert parsed["events"][0]["day"] == "Divendres, 12 maig"
    assert parsed["events"][0]["space"] == "Sala Ateneu"
    assert parsed["events"][2]["day"] == "Dissabte, 13 maig"
    assert parsed["events"][2]["space"] == "Espai Tallers"


def test_normalize_event_extracts_free_labels_into_extra_info():
    event = normalize_event(
        "Concert principal\n19 h\nPlaça Major\nGratuït\nObert a tothom",
        {"current_day": "DIVENDRES", "current_space": "Plaça Major"},
    )

    assert event["datetime_label"] == "19 h"
    assert event["location"] == "Plaça Major"
    assert "Gratuït" in event["extra_info"]
    assert "Obert a tothom" in event["extra_info"]


def test_normalize_event_extracts_registration_into_extra_info():
    event = normalize_event(
        "Taller de dansa\nA partir de les 17 h\nEspai Jove\nInscripció prèvia",
        {"current_day": "DISSABTE", "current_space": "Espai Jove"},
    )

    assert event["datetime_label"] == "A partir de les 17 h"
    assert event["location"] == "Espai Jove"
    assert "Inscripció prèvia" in event["extra_info"]


def test_render_agenda_html_creates_clean_grouped_structure():
    html = render_agenda_html([
        {
            "day": "Divendres, 12 maig",
            "space": "Sala Ateneu",
            "title": "Benvinguda institucional",
            "datetime_label": "9 h",
            "location": "Sala Ateneu",
            "description": "Obertura de la jornada.",
            "extra_info": "Gratuït",
        },
        {
            "day": "Divendres, 12 maig",
            "space": "Sala Ateneu",
            "title": "Concert acústic",
            "datetime_label": "10 h",
            "location": "Sala Ateneu",
            "description": "Actuació principal.",
            "extra_info": "",
        },
    ])

    assert 'class="agenda-day"' in html
    assert 'Divendres, 12 maig' in html
    assert 'class="agenda-space"' in html
    assert 'Sala Ateneu' in html
    assert html.count('class="agenda-title"') == 2
    assert 'class="agenda-datetime"' in html
    assert 'class="agenda-location"' in html
    assert 'class="agenda-extra"' in html
    assert '<br>' not in html


def test_highlight_box_hides_literal_destacat_label():
    html = render_highlight_box("Activitat imprescindible per a tota la familia.")

    assert 'class="highlight-box"' in html
    assert 'Destacat' not in html


def test_parse_agenda_content_items_maps_one_item_per_time():
    parsed = parse_agenda("DIVENDRES Sala Ateneu 9 h Benvinguda 10 h Concert 11 h Debat")
    items = agenda_events_to_content_items(parsed["events"])

    assert len(items) == 3
    assert items[0]["datetime_label"] == "9 h"
    assert items[1]["datetime_label"] == "10 h"
    assert items[2]["datetime_label"] == "11 h"
