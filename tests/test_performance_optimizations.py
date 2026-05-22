import json
import time
from copy import deepcopy
from uuid import uuid4

from app.services.categories.service import (
    build_strict_payload_from_example,
    get_category_export_config,
    get_category_export_configs,
    _CATEGORY_EXPORT_CACHE,
)
from app.services.settings.service import SettingsResolver


EXAMPLE_PAYLOAD = {
    "ID": "{{ID}}",
    "post_title": "{{title}}",
    "post_content": "{{body_html}}",
    "post_excerpt": "{{summary}}",
    "municipality": "{{municipality}}",
    "category": "{{category}}",
    "subtype": "{{subtype}}",
    "featured_image": "{{featured_image_path}}",
    "rank_math_title": "{{title}}",
    "rank_math_description": "{{summary}}",
    "rank_math_focus_keyword": "{{title}}",
    "nested": {
        "inner_title": "{{title}}",
        "inner_body": "{{body_html}}",
        "deep": {
            "deep_id": "{{ID}}",
            "deep_slug": "{{slug}}",
        },
    },
    "items": [
        {"item_title": "{{title}}", "item_date": "{{event_date}}"},
        {"item_title": "{{title}}", "item_date": "{{start_date}}"},
    ],
}

VALUES = {
    "id": "12345",
    "title": "Test Article Title",
    "summary": "This is a test summary",
    "body_html": "<p>Test body content</p>",
    "body_text": "Test body content",
    "municipality": "Maresme",
    "category": "NOTICIES",
    "subtype": "",
    "featured_image_path": "/images/test.jpg",
    "event_date": "2026-04-24",
    "start_date": "2026-04-24",
    "end_date": "2026-04-25",
    "slug": "test-article-title",
    "consell_type": "Professionals",
    "publish_date": "2026-04-24T10:00:00",
}


def test_settings_resolver_ttl_cache_avoids_redundant_reloads():
    SettingsResolver._cache.clear()
    SettingsResolver._cache_loaded = False
    SettingsResolver._cache_timestamp = 0.0

    class FakeSetting:
        def __init__(self, key, value):
            self.key = key
            self.value_json = {"value": value}

    class FakeRepo:
        call_count = 0
        def get_all(self, db):
            FakeRepo.call_count += 1
            return [
                FakeSetting("test_key_1", "val1"),
                FakeSetting("test_key_2", "val2"),
            ]

    import app.services.settings.service as srv
    original_repo = srv.system_setting_repo
    srv.system_setting_repo = FakeRepo()

    try:
        class FakeDb:
            pass
        db = FakeDb()

        srv.SettingsResolver._cache.clear()
        srv.SettingsResolver._cache_loaded = False
        srv.SettingsResolver._cache_timestamp = 0.0

        srv.SettingsResolver.reload(db)
        assert FakeRepo.call_count == 1

        srv.SettingsResolver.reload(db)
        assert FakeRepo.call_count == 1, "reload within TTL should not query DB"

        srv.SettingsResolver.force_reload(db)
        assert FakeRepo.call_count == 2, "force_reload should query DB"

        srv.SettingsResolver._cache_timestamp = 0.0
        srv.SettingsResolver.reload(db)
        assert FakeRepo.call_count == 3, "reload after TTL expiry should query DB"
    finally:
        srv.system_setting_repo = original_repo


def test_settings_resolver_force_reload_clears_cache():
    SettingsResolver._cache.clear()
    SettingsResolver._cache_loaded = False
    SettingsResolver._cache_timestamp = 0.0

    class FakeSetting:
        def __init__(self, key, value):
            self.key = key
            self.value_json = {"value": value}

    class FakeRepo:
        def get_all(self, db):
            return [FakeSetting("key_a", "alpha")]

    import app.services.settings.service as srv
    original_repo = srv.system_setting_repo
    srv.system_setting_repo = FakeRepo()

    try:
        class FakeDb:
            pass
        db = FakeDb()

        srv.SettingsResolver.reload(db)
        assert srv.SettingsResolver.get("key_a") == "alpha"

        srv.SystemSettingRepo = FakeRepo
        FakeRepo.get_all = lambda self, db: [FakeSetting("key_a", "beta")]
        srv.system_setting_repo = FakeRepo()
        srv.SettingsResolver.force_reload(db)
        assert srv.SettingsResolver.get("key_a") == "beta"
    finally:
        srv.system_setting_repo = original_repo


def test_category_export_configs_cache_returns_same_object():
    _CATEGORY_EXPORT_CACHE["configs"] = None
    _CATEGORY_EXPORT_CACHE["timestamp"] = 0.0
    _CATEGORY_EXPORT_CACHE["settings_hash"] = None

    first = get_category_export_configs()
    second = get_category_export_configs()
    assert first is second, "Cached call should return the same list object"


def test_category_export_config_returns_correct_category():
    config = get_category_export_config("AGENDA")
    assert config["category"] == "AGENDA"
    assert config["label"] == "Agenda"
    assert "json_example" in config
    assert len(config["json_example"]) > 0


def test_category_export_config_case_insensitive():
    config_lower = get_category_export_config("agenda")
    config_upper = get_category_export_config("AGENDA")
    assert config_lower["category"] == config_upper["category"]


def test_build_strict_payload_no_dict_copy_overhead():
    values = {**VALUES, "__current_key": "", "__resolving_key": False}
    result = build_strict_payload_from_example(EXAMPLE_PAYLOAD, values)

    assert result["ID"] == "12345"
    assert result["post_title"] == "Test Article Title"
    assert result["post_content"] == "<p>Test body content</p>"
    assert result["post_excerpt"] == "This is a test summary"
    assert result["municipality"] == "Maresme"
    assert result["category"] == "NOTICIES"
    assert result["nested"]["inner_title"] == "Test Article Title"
    assert result["nested"]["deep"]["deep_id"] == "12345"
    assert result["nested"]["deep"]["deep_slug"] == "test-article-title"
    assert result["items"][0]["item_title"] == "Test Article Title"
    assert result["items"][1]["item_date"] == "2026-04-24"


def test_build_strict_payload_preserves_non_placeholder_values():
    example = {
        "title_field": "{{title}}",
        "static_field": "this stays the same",
        "number_field": 42,
        "bool_field": True,
        "list_field": [1, 2, 3],
    }
    values = {"title": "My Title", "__current_key": "", "__resolving_key": False}
    result = build_strict_payload_from_example(example, values)
    assert result["title_field"] == "My Title"
    assert result["static_field"] == "this stays the same"
    assert result["number_field"] == 42
    assert result["bool_field"] is True
    assert result["list_field"] == [1, 2, 3]


def test_build_strict_payload_municipality_slots():
    example = {
        "municipi_maresme": "{{municipi_maresme}}",
        "municipi_cerdanya": "{{municipi_cerdanya}}",
        "municipi_bergueda": "{{municipi_bergueda}}",
    }
    values_maresme = {
        "municipality": "Maresme",
        "__current_key": "",
        "__resolving_key": False,
    }
    result = build_strict_payload_from_example(example, values_maresme)
    assert result["municipi_maresme"] == "Maresme"
    assert result["municipi_cerdanya"] == ""
    assert result["municipi_bergueda"] == ""

    values_bergueda = {
        "municipality": "Bergueda",
        "__current_key": "",
        "__resolving_key": False,
    }
    result2 = build_strict_payload_from_example(example, values_bergueda)
    assert result2["municipi_maresme"] == ""
    assert result2["municipi_bergueda"] == "Berguedà"


def test_performance_settings_resolver_reload_throughput():
    SettingsResolver._cache.clear()
    SettingsResolver._cache_loaded = False
    SettingsResolver._cache_timestamp = 0.0

    class FakeSetting:
        def __init__(self, key, value):
            self.key = key
            self.value_json = {"value": value}

    class FakeRepo:
        def get_all(self, db):
            return [FakeSetting(f"key_{i}", f"val_{i}") for i in range(40)]

    import app.services.settings.service as srv
    original_repo = srv.system_setting_repo
    srv.system_setting_repo = FakeRepo()

    try:
        class FakeDb:
            pass
        db = FakeDb()

        srv.SettingsResolver._cache.clear()
        srv.SettingsResolver._cache_loaded = False
        srv.SettingsResolver._cache_timestamp = 0.0

        iterations = 500

        start = time.perf_counter()
        for _ in range(iterations):
            srv.SettingsResolver.reload(db)
        elapsed_with_cache = time.perf_counter() - start

        srv.SettingsResolver._cache_timestamp = 0.0

        start = time.perf_counter()
        for _ in range(iterations):
            srv.SettingsResolver._cache_timestamp = 0.0
            srv.SettingsResolver.reload(db)
        elapsed_without_cache = time.perf_counter() - start

        assert elapsed_with_cache < elapsed_without_cache
        speedup = elapsed_without_cache / max(elapsed_with_cache, 1e-9)
        assert speedup > 5, f"Expected >5x speedup from TTL cache, got {speedup:.1f}x"
    finally:
        srv.system_setting_repo = original_repo


def test_performance_build_strict_payload_throughput():
    values = {**VALUES, "__current_key": "", "__resolving_key": False}
    iterations = 500

    start = time.perf_counter()
    for _ in range(iterations):
        build_strict_payload_from_example(EXAMPLE_PAYLOAD, values)
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"build_strict_payload took {elapsed:.3f}s for {iterations} iterations"


def test_performance_category_export_configs_cached():
    _CATEGORY_EXPORT_CACHE["configs"] = None
    _CATEGORY_EXPORT_CACHE["timestamp"] = 0.0
    _CATEGORY_EXPORT_CACHE["settings_hash"] = None

    get_category_export_configs()
    iterations = 500

    start = time.perf_counter()
    for _ in range(iterations):
        get_category_export_configs()
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0, f"cached get_category_export_configs took {elapsed:.3f}s for {iterations} iterations"


def test_repository_filtered_queries_exist():
    from app.db.repositories.all_repos import (
        source_batch_repo,
        source_file_repo,
        content_candidate_repo,
        extracted_document_repo,
        canonical_content_repo,
        processing_event_repo,
    )

    assert hasattr(source_batch_repo, "get_by_municipality_and_category")
    assert hasattr(source_file_repo, "get_by_batch_id")
    assert hasattr(source_file_repo, "delete_by_batch_id")
    assert hasattr(content_candidate_repo, "get_by_batch_id")
    assert hasattr(extracted_document_repo, "get_by_candidate_id")
    assert hasattr(canonical_content_repo, "delete_by_candidate_ids")
    assert hasattr(processing_event_repo, "get_by_batch_id")


def test_assets_version_cache_exists():
    from app.api.routes.panel import _assets_version_cache, _ASSETS_VERSION_TTL
    assert _ASSETS_VERSION_TTL > 0
    assert "version" in _assets_version_cache
    assert "timestamp" in _assets_version_cache


def test_flow_exporter_has_ftp_reuse():
    from app.services.export.flow_export import FlowExporter
    exporter = FlowExporter()
    assert hasattr(exporter, "_get_ftp_connection")
    assert hasattr(exporter, "_close_ftp_connection")
    assert hasattr(exporter, "_upload_ftp_reuse")
    assert exporter._ftp_connection is None


def test_settings_initialize_defaults_uses_bulk_query():
    SettingsResolver._cache.clear()
    SettingsResolver._cache_loaded = False
    SettingsResolver._cache_timestamp = 0.0

    class FakeSetting:
        def __init__(self, key, value):
            self.key = key
            self.value_json = {"value": value}

    call_log = {"get_all": 0, "get_by_key": 0, "create": 0}

    class FakeSettingRepo:
        def get_all(self, db, **kw):
            call_log["get_all"] += 1
            return [FakeSetting("project_name", "Test")]

        def get_by_key(self, db, key):
            call_log["get_by_key"] += 1
            return FakeSetting(key, "val")

        def create(self, db, *, obj_in):
            call_log["create"] += 1
            return FakeSetting(obj_in["key"], obj_in["value_json"]["value"])

    class FakeAuditRepo:
        def create(self, db, *, obj_in):
            pass

    import app.services.settings.service as srv
    orig_setting_repo = srv.system_setting_repo
    orig_audit_repo = srv.settings_audit_repo
    srv.system_setting_repo = FakeSettingRepo()
    srv.settings_audit_repo = FakeAuditRepo()

    try:
        class FakeDb:
            pass
        db = FakeDb()
        srv.SettingsService.initialize_defaults(db)

        assert call_log["get_all"] == 1, f"Expected 1 get_all call, got {call_log['get_all']}"
        assert call_log["get_by_key"] == 0, f"Expected 0 get_by_key calls, got {call_log['get_by_key']}"
    finally:
        srv.system_setting_repo = orig_setting_repo
        srv.settings_audit_repo = orig_audit_repo
