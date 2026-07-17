import os
from pathlib import Path


def extract_photo(cv_pdf_path: str, output_dir: str) -> str | None:
    """
    Extrae la imagen más grande de la primera página de un PDF (foto del CV).
    Devuelve la ruta del PNG guardado, o None si no hay imagen.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("[Photo] PyMuPDF no instalado — pip install PyMuPDF")
        return None

    if not os.path.exists(cv_pdf_path):
        print(f"[Photo] PDF no encontrado: {cv_pdf_path}")
        return None

    try:
        doc = fitz.open(cv_pdf_path)
        if len(doc) == 0:
            doc.close()
            return None

        page = doc[0]
        images = page.get_images(full=True)
        if not images:
            doc.close()
            print("[Photo] No se encontraron imágenes en la primera página del CV")
            return None

        # Encontrar la imagen más grande (probablemente la foto)
        largest_area = 0
        largest_xref = None
        for img in images:
            xref = img[0]
            base_image = doc.extract_image(xref)
            w = base_image.get("width", 0)
            h = base_image.get("height", 0)
            area = w * h
            if area > largest_area:
                largest_area = area
                largest_xref = xref

        if largest_xref is None:
            doc.close()
            return None

        base_image = doc.extract_image(largest_xref)
        doc.close()

        img_bytes = base_image["image"]
        ext = base_image.get("ext", "png")

        # Convertir a PNG para compatibilidad con fpdf2
        from PIL import Image
        import io

        pil_img = Image.open(io.BytesIO(img_bytes))
        if pil_img.mode in ("RGBA", "P"):
            pil_img = pil_img.convert("RGB")

        os.makedirs(output_dir, exist_ok=True)
        photo_path = os.path.join(output_dir, "photo.png")
        pil_img.save(photo_path, "PNG")

        print(f"[Photo] Foto extraída: {pil_img.size[0]}x{pil_img.size[1]}px → {photo_path}")
        return photo_path

    except Exception as e:
        print(f"[Photo] Error extrayendo foto: {e}")
        return None
