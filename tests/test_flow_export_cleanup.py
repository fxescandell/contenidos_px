from unittest.mock import patch

from app.services.export.flow_export import FlowExporter


@patch("app.services.export.flow_export.SettingsResolver.get")
def test_upload_image_assets_local_cleans_temp_files(mock_get, tmp_path):
    export_dir = tmp_path / "editorial_export"
    outfolder_dir = tmp_path / "export_folder"
    export_dir.mkdir()
    outfolder_dir.mkdir()

    optimized_file = export_dir / "image_opt.jpg"
    thumbnail_file = export_dir / "image_thumb.jpg"
    optimized_file.write_bytes(b"optimized")
    thumbnail_file.write_bytes(b"thumbnail")

    def resolver(key, default=None):
        values = {
            "export_output_path": str(export_dir),
        }
        return values.get(key, default)

    mock_get.side_effect = resolver

    exporter = FlowExporter()

    with patch.object(exporter, "_get_active_mode", return_value="local"), patch.object(exporter, "_get_local_outfolder_base", return_value=str(outfolder_dir)):
        ok, _msg, uploaded = exporter.upload_image_assets("Maresme", [{
            "optimized_local_path": str(optimized_file),
            "thumbnail_local_path": str(thumbnail_file),
            "optimized_remote_path": "/maresme/images/image_opt.jpg",
            "thumbnail_remote_path": "/maresme/images/image_thumb.jpg",
        }])

    assert ok is True
    assert len(uploaded) == 1
    assert not optimized_file.exists()
    assert not thumbnail_file.exists()
    assert (outfolder_dir / "maresme" / "images" / "image_opt.jpg").exists()
    assert (outfolder_dir / "maresme" / "images" / "image_thumb.jpg").exists()


@patch("app.services.export.flow_export.SettingsResolver.get")
def test_cleanup_temp_asset_keeps_files_outside_export_dir(mock_get, tmp_path):
    export_dir = tmp_path / "editorial_export"
    other_dir = tmp_path / "other"
    export_dir.mkdir()
    other_dir.mkdir()

    other_file = other_dir / "image_opt.jpg"
    other_file.write_bytes(b"optimized")

    mock_get.side_effect = lambda key, default=None: str(export_dir) if key == "export_output_path" else default

    exporter = FlowExporter()
    exporter._cleanup_temp_asset(str(other_file))

    assert other_file.exists()


def test_move_local_processed_moves_nested_files_to_processed_folder(tmp_path):
    source_dir = tmp_path / "Maresme" / "Consells"
    processed_dir = source_dir / "processed"
    gardens_dir = source_dir / "JARDINS"
    pool_dir = source_dir / "PISCINA"
    gardens_dir.mkdir(parents=True)
    pool_dir.mkdir(parents=True)

    gardens_doc = gardens_dir / "jardins.docx"
    gardens_img = gardens_dir / "foto-jardi.jpg"
    pool_doc = pool_dir / "piscina.docx"
    gardens_doc.write_text("doc")
    gardens_img.write_text("img")
    pool_doc.write_text("doc")

    exporter = FlowExporter()
    ok, msg = exporter._move_local_processed(str(source_dir), [
        "JARDINS/jardins.docx",
        "JARDINS/foto-jardi.jpg",
        "PISCINA/piscina.docx",
    ])

    assert ok is True, msg
    assert (processed_dir / "JARDINS" / "jardins.docx").exists()
    assert (processed_dir / "JARDINS" / "foto-jardi.jpg").exists()
    assert (processed_dir / "PISCINA" / "piscina.docx").exists()
    assert not gardens_doc.exists()
    assert not gardens_img.exists()
    assert not pool_doc.exists()
    assert not gardens_dir.exists()
    assert not pool_dir.exists()
