from uuid import uuid4

from app.services.editorial.builder import EditorialBuilderService
from app.schemas.all_schemas import ImageProcessingResult


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
