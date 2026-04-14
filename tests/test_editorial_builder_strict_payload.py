from uuid import uuid4

from app.services.editorial.builder import EditorialBuilderService
from app.schemas.all_schemas import ImageProcessingResult
from app.schemas.classification import FinalClassificationResult
from app.core.enums import Municipality, ContentCategory, ContentSubtype


def test_merge_strict_payload_fills_blank_featured_image_from_template():
    service = EditorialBuilderService()

    base_payload = {
        "maresme-consell": {
            "post_title": "Titol base",
            "featured_image": "https://panxing.net/json-import-content/Maresme/images/foto-jardi-2_opt.jpg",
            "rank_math_title": "Titol base",
            "types_title": "Titol base",
        }
    }
    override_payload = {
        "maresme-001": {
            "post_title": "Titol LLM",
            "featured_image": "",
            "rank_math_title": "",
            "types_title": "",
        }
    }

    merged = service._merge_strict_payload(base_payload, override_payload)

    assert list(merged.keys()) == ["maresme-001"]
    assert merged["maresme-001"]["post_title"] == "Titol LLM"
    assert merged["maresme-001"]["featured_image"] == "https://panxing.net/json-import-content/Maresme/images/foto-jardi-2_opt.jpg"
    assert merged["maresme-001"]["rank_math_title"] == "Titol base"
    assert merged["maresme-001"]["types_title"] == "Titol base"


def test_merge_strict_payload_keeps_non_empty_llm_values():
    service = EditorialBuilderService()

    base_payload = {
        "item": {
            "featured_image": "https://panxing.net/json-import-content/Maresme/images/base_opt.jpg",
            "types_title": "Titol base",
        }
    }
    override_payload = {
        "item": {
            "featured_image": "https://panxing.net/json-import-content/Maresme/images/llm_opt.jpg",
            "types_title": "Titol LLM",
        }
    }

    merged = service._merge_strict_payload(base_payload, override_payload)

    assert merged["item"]["featured_image"] == "https://panxing.net/json-import-content/Maresme/images/llm_opt.jpg"
    assert merged["item"]["types_title"] == "Titol LLM"


def test_merge_strict_payload_drops_extra_keys_and_preserves_template_order():
    service = EditorialBuilderService()

    base_payload = {
        "item-base": {
            "post_title": "Base title",
            "featured_image": "base-image",
            "rank_math_title": "base seo",
        }
    }
    override_payload = {
        "item-final": {
            "featured_image": "final-image",
            "custom_field": "should disappear",
            "post_title": "Final title",
            "another_extra": "should disappear too",
        }
    }

    merged = service._merge_strict_payload(base_payload, override_payload)

    assert list(merged.keys()) == ["item-final"]
    assert list(merged["item-final"].keys()) == ["post_title", "featured_image", "rank_math_title"]
    assert merged["item-final"]["post_title"] == "Final title"
    assert merged["item-final"]["featured_image"] == "final-image"
    assert merged["item-final"]["rank_math_title"] == "base seo"
    assert "custom_field" not in merged["item-final"]
    assert "another_extra" not in merged["item-final"]


def test_prepare_source_text_removes_trailing_author_marker():
    service = EditorialBuilderService()

    source_context = service._prepare_source_text("Titol\n\nCos del text\n\nAMIC")

    assert source_context["cleaned_text"] == "Titol\n\nCos del text"
    assert source_context["author_source"] == "AMIC"


def test_sanitize_body_html_formats_highlight_block_and_author_note():
    service = EditorialBuilderService()

    sanitized = service._sanitize_body_html(
        "<p>Introduccio</p><h2>Destacat: Lavanda</h2><p>Text destacat</p><p>AMIC</p>",
        "Introduccio\n\nDestacat: Lavanda\n\nText destacat",
        "Introduccio",
        {"author_source": "AMIC"},
    )

    assert 'class="panxing-destacat"' in sanitized
    assert "<h4" in sanitized
    assert ">Destacat<" not in sanitized
    assert ">Destacat:" not in sanitized
    assert "Article original d'Amic adaptat per Pànxing." in sanitized
    assert "<p>AMIC</p>" not in sanitized


def test_build_seo_fields_generates_rank_math_values():
    service = EditorialBuilderService()

    seo_fields = service._build_seo_fields(
        title="Jardins sostenibles i de baix manteniment: una aposta per al futur",
        summary="Descobreix com reduir el consum d'aigua i mantenir un jardi atractiu durant tot l'any.",
        body_html="<p>Cos optimitzat del contingut.</p>",
        featured_image_path="https://panxing.net/json-import-content/Maresme/images/foto-jardi-2_opt.jpg",
        author_source="AMIC",
    )

    assert seo_fields["rank_math_focus_keyword"] == "Jardins sostenibles i de baix manteniment"
    assert seo_fields["rank_math_pillar_content"] == ""
    assert len(seo_fields["rank_math_title"]) <= 60
    assert len(seo_fields["rank_math_description"]) <= 160
    assert seo_fields["rank_math_facebook_image"] == "https://panxing.net/json-import-content/Maresme/images/foto-jardi-2_opt.jpg"
    assert seo_fields["rank_math_twitter_card_type"] == "summary_large_image"
    assert seo_fields["creator_name"] == "Amic / Pànxing"


def test_select_featured_image_prefers_ai_choice_when_available():
    service = EditorialBuilderService()
    first_id = uuid4()
    second_id = uuid4()
    editorial_images = [
        ImageProcessingResult(source_file_id=first_id, optimized_path="https://example.com/one.jpg", width=1000, height=700),
        ImageProcessingResult(source_file_id=second_id, optimized_path="https://example.com/two.jpg", width=900, height=900),
    ]

    service._select_featured_image_with_ai = lambda *args, **kwargs: second_id

    featured = service._select_featured_image("Titol", "Resum", "Cos", editorial_images, editorial_images)

    assert featured.source_file_id == second_id


def test_select_featured_image_fallback_prefers_poster_like_filename():
    service = EditorialBuilderService()
    regular_id = uuid4()
    poster_id = uuid4()
    images = [
        ImageProcessingResult(source_file_id=regular_id, optimized_path="https://example.com/xaranga-magic_opt.jpg", width=1400, height=900),
        ImageProcessingResult(source_file_id=poster_id, optimized_path="https://example.com/fefanet-ok_opt.jpg", width=900, height=1300),
    ]

    featured = service._select_featured_image_fallback(images)

    assert featured.source_file_id == poster_id


def test_insert_inline_images_embeds_non_featured_images_in_body_html():
    service = EditorialBuilderService()
    featured_id = uuid4()
    inline_id = uuid4()
    images = [
        ImageProcessingResult(source_file_id=featured_id, optimized_path="https://example.com/featured.jpg", width=1200, height=800),
        ImageProcessingResult(source_file_id=inline_id, optimized_path="https://example.com/inline.jpg", width=800, height=600),
    ]

    third_id = uuid4()
    images.append(ImageProcessingResult(source_file_id=third_id, optimized_path="https://example.com/inline-2.jpg", width=700, height=500))

    body_html, inserted = service._insert_inline_images(
        "<p>Paragraf 1</p><p>Paragraf 2</p><p>Paragraf 3</p>",
        images,
        featured_id,
        "Titol de prova",
    )

    assert "https://example.com/inline.jpg" in body_html
    assert "https://example.com/inline-2.jpg" in body_html
    assert 'class="panxing-inline-image"' in body_html
    assert inserted == ["https://example.com/inline.jpg", "https://example.com/inline-2.jpg"]
    assert body_html.index("<p>Paragraf 1</p>") < body_html.index("https://example.com/inline.jpg")


def test_finalize_editorial_output_stores_featured_image_ref_as_string():
    service = EditorialBuilderService()
    featured_id = uuid4()
    images = [
        ImageProcessingResult(source_file_id=featured_id, optimized_path="https://example.com/featured.jpg", width=1200, height=800),
    ]

    _title, _summary, _body_html, structured_fields = service._finalize_editorial_output(
        title="Titol",
        summary="Resum curt",
        body_html="<p>Cos</p>",
        body_text="Cos",
        images=images,
        structured_fields={},
        source_context={"author_source": "", "has_highlight_marker": False},
        metadata={},
    )

    assert structured_fields["featured_image_ref"] == str(featured_id)


def test_apply_final_review_updates_content_and_refreshes_seo_fields():
    service = EditorialBuilderService()
    service.final_review_service.review_content = lambda **kwargs: {
        "title": "Titol revisat SEO",
        "summary": "Resum revisat i correcte en catala.",
        "body_html": "<p>Cos revisat amb millor redaccio.</p>",
        "notes": ["Revisio aplicada"],
    }

    title, summary, body_html, structured_fields = service._apply_final_review(
        municipality="MARESME",
        category="NOTICIES",
        subtype="NONE",
        original_text="Text original de referencia.",
        vision_context_text="",
        title="Titol inicial",
        summary="Resum inicial",
        body_html="<p>Cos inicial</p>",
        structured_fields={"_featured_image_path": "https://example.com/featured.jpg"},
        images=[],
        source_context={"author_source": "", "has_highlight_marker": False},
        metadata={"category": "NOTICIES"},
    )

    assert title == "Titol revisat SEO"
    assert summary == "Resum revisat i correcte en catala."
    assert body_html == "<p>Cos revisat amb millor redaccio.</p>"
    assert structured_fields["rank_math_title"] == "Titol revisat SEO"
    assert structured_fields["rank_math_facebook_image"] == "https://example.com/featured.jpg"
    assert structured_fields["final_review_notes"] == ["Revisio aplicada"]


def test_enhance_html_structure_adds_headings_and_bold_labels():
    service = EditorialBuilderService()

    enhanced = service._enhance_html_structure(
        "<p>Organització i col·laboracions</p><p>Patrocinadors: Veolia, Banc Sabadell i Macusa.</p><p>Paragraf de desenvolupament.</p>",
        "NOTICIES",
    )

    assert "<h2" in enhanced or "<h3" in enhanced
    assert "Organització i col·laboracions" in enhanced
    assert "<strong>Patrocinadors:</strong>" in enhanced


def test_enhance_html_structure_promotes_markdown_heading_markers():
    service = EditorialBuilderService()

    enhanced = service._enhance_html_structure(
        "<p>[[H2]] Programa del cap de setmana</p><p>Text introductori.</p><p>[[H3]] Activitats familiars</p><p>Detall de les activitats.</p>",
        "AGENDA",
    )

    assert "<h2>Programa del cap de setmana</h2>" in enhanced
    assert "<h3>Activitats familiars</h3>" in enhanced


def test_enhance_html_structure_groups_markdown_list_markers_into_ul():
    service = EditorialBuilderService()

    enhanced = service._enhance_html_structure(
        "<p>[[LI]] Entrada gratuïta</p><p>[[LI]] Inscripció prèvia</p><p>Paragraf final.</p>",
        "AGENDA",
    )

    assert "<ul><li>Entrada gratuïta</li><li>Inscripció prèvia</li></ul>" in enhanced
    assert "<p>Paragraf final.</p>" in enhanced


def test_assign_activity_image_refs_matches_by_filename_tokens():
    service = EditorialBuilderService()
    activity_title_image = ImageProcessingResult(
        source_file_id=uuid4(),
        optimized_path="https://example.com/festival-jazz-calella_opt.jpg",
        width=1200,
        height=800,
    )
    other_image = ImageProcessingResult(
        source_file_id=uuid4(),
        optimized_path="https://example.com/platja-familiar_opt.jpg",
        width=1200,
        height=800,
    )
    activities = [{
        "title": "Festival de Jazz de Calella",
        "datetime_label": "12/08/2026",
        "location": "Calella",
        "description": "Concert principal del cap de setmana.",
        "extra_info": "",
        "image_ref": "",
    }]

    enriched = service._assign_activity_image_refs(
        activities,
        [activity_title_image, other_image],
        [activity_title_image, other_image],
        "Agenda cultural",
        "Resum",
        "Context",
    )

    assert enriched[0]["image_ref"] == "https://example.com/festival-jazz-calella_opt.jpg"


def test_extract_structured_fields_keeps_activities_from_llm():
    service = EditorialBuilderService()

    fields = service._extract_structured_fields({
        "activities": [{
            "title": "Fira del Vi",
            "datetime_label": "10/09/2026",
            "location": "Mataro",
            "description": "Tast i mostra de cellers",
            "extra_info": "Entrada gratuita",
            "image_ref": "",
        }]
    }, "AGENDA", "Text")

    assert len(fields["activities"]) == 1
    assert fields["activities"][0]["title"] == "Fira del Vi"


def test_insert_inline_images_places_listing_image_next_to_matching_section():
    service = EditorialBuilderService()
    body_html, inserted = service._insert_inline_images(
        "<h2>Introduccio</h2><p>Text inicial</p><h2>Restaurant Can Blau</h2><p>Cuina mediterrania.</p><h2>Hotel Mar i Cel</h2><p>Allotjament davant del mar.</p>",
        [],
        None,
        "Ruta gastronomica",
        [
            {
                "title": "Restaurant Can Blau",
                "datetime_label": "",
                "location": "Calella",
                "description": "Cuina mediterrania",
                "extra_info": "",
                "image_ref": "https://example.com/can-blau.jpg",
            }
        ],
    )

    assert inserted == ["https://example.com/can-blau.jpg"]
    assert body_html.index("Restaurant Can Blau") < body_html.index("https://example.com/can-blau.jpg")
    assert body_html.index("https://example.com/can-blau.jpg") < body_html.index("Hotel Mar i Cel")


def test_extract_structured_fields_keeps_content_items_from_llm():
    service = EditorialBuilderService()

    fields = service._extract_structured_fields({
        "content_items": [{
            "title": "Hotel Mar i Cel",
            "datetime_label": "",
            "location": "Calella",
            "description": "Hotel amb spa",
            "extra_info": "",
            "image_ref": "",
        }]
    }, "NOTICIES", "Text")

    assert len(fields["content_items"]) == 1
    assert fields["content_items"][0]["title"] == "Hotel Mar i Cel"


def test_extract_content_items_from_source_parses_agenda_sections():
    service = EditorialBuilderService()
    body_text = (
        "Musica i teatre familiar\n\n"
        "HORA DEL CONTE\n\n"
        "El Pais dels Guarananas, amb Eduard Costa.\n\n"
        "Divendres 8 de maig • 17 h\n\n"
        "Biblioteca P. Gual i Pujadas.\n\n"
        "MUSICA ITINERANT\n\n"
        "Xaranga Magic.\n\n"
        "Divendres 8 de maig • 18 h\n\n"
        "Riera Sant Domenec."
    )

    items = service._extract_content_items_from_source(body_text, "AGENDA")

    assert len(items) == 2
    assert items[0]["title"] == "El Pais dels Guarananas, amb Eduard Costa."
    assert items[0]["extra_info"] == "Hora del conte"
    assert items[0]["location"] == "Biblioteca P. Gual i Pujadas."
    assert items[1]["title"] == "Xaranga Magic."
    assert items[1]["extra_info"] == "Musica itinerant"


def test_ensure_source_text_is_preserved_rebuilds_short_agenda_body_from_source():
    service = EditorialBuilderService()
    source_text = (
        "Musica i teatre familiar\n\n"
        "HORA DEL CONTE\n\n"
        "El Pais dels Guarananas, amb Eduard Costa.\n\n"
        "Divendres 8 de maig • 17 h\n\n"
        "Biblioteca P. Gual i Pujadas.\n\n"
        "MUSICA ITINERANT\n\n"
        "Xaranga Magic.\n\n"
        "Divendres 8 de maig • 18 h\n\n"
        "Riera Sant Domenec.\n\n"
        "TEATRE CLOWN\n\n"
        "HOME de Cris Clown.\n\n"
        "Divendres 8 de maig • 19 h\n\n"
        "Placa 1 d'Octubre."
    )
    listing_items = service._extract_content_items_from_source(source_text, "AGENDA")

    rebuilt = service._ensure_source_text_is_preserved(
        "<p>Festival familiar amb activitats per a tothom.</p>",
        source_text,
        "Resum SEO del festival familiar.",
        "AGENDA",
        listing_items,
    )

    assert "Resum SEO del festival familiar." in rebuilt
    assert "Hora del conte" in rebuilt
    assert "Musica itinerant" in rebuilt
    assert "Teatre clown" in rebuilt
    assert "Xaranga Magic" in rebuilt
    assert "agenda-datetime" in rebuilt
    assert "agenda-location" in rebuilt


def test_build_source_preserving_agenda_body_keeps_ai_intro_blocks_and_program():
    service = EditorialBuilderService()
    source_text = (
        "Firhabitat\n\n"
        "PROGRAMACIÓ\n\n"
        "DIVENDRES, 24 ABRIL\n\n"
        "Sala Ateneu\n\n"
        "9 h Benvinguda\n\n"
        "10 h Concert acústic"
    )
    listing_items = service._extract_content_items_from_source(source_text, "AGENDA")

    body_html = service._build_source_preserving_body_html(
        source_text,
        "Resum SEO del certamen.",
        "AGENDA",
        listing_items,
        "<p>Firhabitat és la trobada de referència de la bioconstrucció al Berguedà.</p><p>Durant tres dies ofereix activitats professionals i familiars.</p>",
    )

    assert "Firhabitat és la trobada de referència" in body_html
    assert "Durant tres dies ofereix activitats" in body_html
    assert 'class="agenda-title"' in body_html
    assert 'Benvinguda' in body_html
    assert 'Concert acústic' in body_html


def test_build_editorial_content_uses_image_name_context_when_no_text_was_extracted():
    service = EditorialBuilderService()
    service._try_llm = lambda *args, **kwargs: None
    service.final_review_service.review_content = lambda **kwargs: {
        "title": kwargs["draft_title"],
        "summary": kwargs["draft_summary"],
        "body_html": kwargs["draft_body_html"],
        "notes": [],
    }
    classification = FinalClassificationResult(
        municipality=Municipality.BERGUEDA,
        category=ContentCategory.AGENDA,
        subtype=ContentSubtype.NONE,
        grouping_confidence=0.9,
        extraction_confidence=0.0,
        classification_confidence=0.9,
        confidence_band="high",
        requires_review=False,
        review_reasons=[],
        signals=[],
        reasoning_summary="test",
    )
    images = [
        ImageProcessingResult(
            source_file_id=uuid4(),
            optimized_path="https://example.com/41a-CAMINADA-POPULAR-DE-PUIG-REIG_opt.jpg",
            width=1200,
            height=1600,
        )
    ]

    result = service.build_editorial_content(
        classification,
        "",
        images,
        {"image_name_context": "41a-CAMINADA-POPULAR-DE-PUIG-REIG"},
    )

    assert result.final_title != "(Sin titulo)"
    assert "CAMINADA" in result.final_title.upper()
    assert result.final_body_html != ""
