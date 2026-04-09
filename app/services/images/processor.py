import logging
import os
from typing import List, Optional

from app.schemas.all_schemas import ImageProcessingResult
from app.db.models import SourceFile, ContentCandidate

logger = logging.getLogger(__name__)

MAX_WIDTH = 2000
JPG_QUALITY = 80
THUMB_MAX_WIDTH = 600
THUMB_QUALITY = 70


class ImageProcessingService:
    def __init__(self, export_directory: str):
        self.export_directory = export_directory

    def process_images(self, candidate: Optional[ContentCandidate], image_files: List[SourceFile]) -> List[ImageProcessingResult]:
        from PIL import Image

        results = []
        resampling_filter = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)
        os.makedirs(self.export_directory, exist_ok=True)

        for idx, img_file in enumerate(image_files):
            working_path = img_file.working_path
            if not working_path or not os.path.exists(working_path):
                continue

            try:
                with Image.open(working_path) as img:
                    original_format = img.format or "JPEG"
                    exif_bytes = img.info.get("exif")

                    if original_format.upper() in ("PNG", "WEBP"):
                        target_format = "PNG"
                        ext = ".png"
                    else:
                        target_format = "JPEG"
                        ext = ".jpg"

                    if img.mode in ("RGBA", "P", "LA"):
                        img = img.convert("RGB")

                    if img.width > MAX_WIDTH:
                        ratio = MAX_WIDTH / img.width
                        new_height = int(img.height * ratio)
                        img = img.resize((MAX_WIDTH, new_height), resampling_filter)

                    stem = os.path.splitext(img_file.file_name)[0]
                    opt_filename = f"{stem}_opt{ext}"
                    thumb_filename = f"{stem}_thumb{ext}"
                    opt_path = os.path.join(self.export_directory, opt_filename)
                    thumb_path = os.path.join(self.export_directory, thumb_filename)

                    if target_format == "JPEG":
                        save_kwargs = {"quality": JPG_QUALITY, "optimize": True, "progressive": True}
                        if exif_bytes:
                            save_kwargs["exif"] = exif_bytes
                    else:
                        save_kwargs = {"optimize": True}

                    img.save(opt_path, format=target_format, **save_kwargs)

                    thumb = img.copy()
                    if thumb.width > THUMB_MAX_WIDTH:
                        thumb_ratio = THUMB_MAX_WIDTH / thumb.width
                        thumb_height = int(thumb.height * thumb_ratio)
                        thumb = thumb.resize((THUMB_MAX_WIDTH, thumb_height), resampling_filter)

                    if target_format == "JPEG":
                        thumb_save_kwargs = {"quality": THUMB_QUALITY, "optimize": True, "progressive": True}
                    else:
                        thumb_save_kwargs = {"optimize": True}

                    thumb.save(thumb_path, format=target_format, **thumb_save_kwargs)

                    file_size = os.path.getsize(opt_path)

                    role = "FEATURED" if idx == 0 else "INLINE"
                    results.append(ImageProcessingResult(
                        source_file_id=img_file.id,
                        optimized_path=opt_path,
                        thumbnail_path=thumb_path,
                        width=img.width,
                        height=img.height,
                        original_format=original_format,
                        optimized_format=target_format,
                        optimized_file_size_bytes=file_size,
                        role=role
                    ))
            except Exception as e:
                from app.services.pipeline.events import event_logger
                from app.core.enums import EventLevel
                logger.exception("Error procesando imagen %s", img_file.file_name)
                event_logger.log(
                    None,
                    EventLevel.WARNING,
                    "IMAGE_PROCESS_FAILED",
                    "FLOW",
                    f"Error procesando {img_file.file_name}: {e}",
                    candidate_id=candidate.id if candidate else None,
                )

        return results
