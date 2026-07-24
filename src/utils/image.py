import io
from PIL import Image

MAX_TWEET_IMAGE_BYTES = 15_000_000

def ensure_uploadable_image(image_data: bytes, max_bytes: int = MAX_TWEET_IMAGE_BYTES) -> bytes:
    """
    Ensure the image is uploadable to Twitter by checking its size and compressing it if necessary.
    """
    if len(image_data) <= max_bytes:
        return image_data, None

    # Open the image using PIL
    with Image.open(io.BytesIO(image_data)) as img:
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.load()

        # Compress the image by reducing quality
        quality = 90
        while quality >= 40:
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            data = buffer.getvalue()
            if len(data) <= max_bytes:
                return data, "jpg"
            quality -= 10

    while max(img.size) > 1000:
        img = img.resize((int(img.width * 0.85), int(img.height * 0.85)), Image.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85, optimize=True)
        data = buffer.getvalue()

        if len(data) <= max_bytes:
            return data, "jpg"

    return data, "jpg"