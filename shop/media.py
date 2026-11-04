import logging
import uuid
from io import BytesIO

from cloudinary import uploader
from cloudinary.exceptions import Error
from cloudinary.utils import cloudinary_url
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)
MAX_UPLOAD = 6 * 1024 * 1024
CLOUD_PREFIX = "cloudinary:"


class ImageError(ValueError):
    pass


def sanitized_image(upload: UploadedFile) -> bytes:
    if upload.size is None or upload.size > MAX_UPLOAD:
        raise ImageError("Choose an image no larger than 6 MB.")
    try:
        with Image.open(upload, formats=["JPEG", "PNG", "WEBP"]) as original:
            if original.width * original.height > 16_000_000 or getattr(original, "is_animated", False):
                raise ImageError("Use a still image of up to 16 megapixels.")
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail((1800, 1800))
            result = BytesIO()
            image.save(result, "JPEG", quality=87, optimize=True)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ImageError("Upload a valid JPEG, PNG or WebP image.") from None
    return result.getvalue()


def store_image(data: bytes) -> str:
    public_id = "ez-e-commerce/products/" + uuid.uuid4().hex
    if not settings.CLOUDINARY_CLOUD_NAME:
        if not settings.DEBUG:
            raise ImageError("Persistent image storage is not configured.")
        return default_storage.save(public_id + ".jpg", ContentFile(data))
    try:
        response = uploader.upload(
            data, public_id=public_id, resource_type="image", overwrite=False, timeout=12,
            cloud_name=settings.CLOUDINARY_CLOUD_NAME, api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
        )
    except (Error, OSError):
        raise ImageError("The image provider did not accept the upload. Try again shortly.") from None
    if response.get("public_id") != public_id:
        raise ImageError("The image provider returned an unexpected result.")
    return CLOUD_PREFIX + public_id


def get_image_url(asset: str) -> str:
    if asset.startswith(CLOUD_PREFIX):
        url, _ = cloudinary_url(
            asset.removeprefix(CLOUD_PREFIX), cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            secure=True, quality="auto", fetch_format="auto", width=1000, crop="limit",
        )
        return url
    return default_storage.url(asset)


def delete_image(asset: str) -> None:
    try:
        if asset.startswith(CLOUD_PREFIX):
            uploader.destroy(
                asset.removeprefix(CLOUD_PREFIX), resource_type="image", invalidate=True, timeout=12,
                cloud_name=settings.CLOUDINARY_CLOUD_NAME, api_key=settings.CLOUDINARY_API_KEY,
                api_secret=settings.CLOUDINARY_API_SECRET,
            )
        else:
            default_storage.delete(asset)
    except (Error, OSError):
        logger.warning("Image cleanup failed for asset %s", asset)
