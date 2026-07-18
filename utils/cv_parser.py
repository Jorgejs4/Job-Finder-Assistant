import json
from pathlib import Path
from pypdf import PdfReader
import docx

def parse_pdf(file_path: Path) -> str:
    """Extrae texto de un archivo PDF."""
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text

def parse_docx(file_path: Path) -> str:
    """Extrae texto de un archivo DOCX (Word)."""
    doc = docx.Document(file_path)
    text = []
    for paragraph in doc.paragraphs:
        if paragraph.text.strip():
            text.append(paragraph.text)
    return "\n".join(text)

def parse_json(file_path: Path) -> str:
    """Lee y formatea un archivo JSON de perfil."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return json.dumps(data, indent=2, ensure_ascii=False)

def parse_txt(file_path: Path) -> str:
    """Lee un archivo de texto plano."""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

def parse_cv(file_path_str: str) -> str:
    """
    Función principal que detecta la extensión del archivo y 
    extrae el contenido de texto correspondiente.
    """
    file_path = Path(file_path_str)
    if not file_path.exists():
        raise FileNotFoundError(f"El archivo CV no existe en la ruta: {file_path}")
    
    suffix = file_path.suffix.lower()
    
    if suffix == ".pdf":
        return parse_pdf(file_path)
    elif suffix == ".docx":
        return parse_docx(file_path)
    elif suffix == ".json":
        return parse_json(file_path)
    elif suffix in (".txt", ".md"):
        return parse_txt(file_path)
    else:
        raise ValueError(
            f"Formato de archivo no soportado: '{suffix}'. "
            "Soportados: .pdf, .docx, .json, .txt, .md"
        )
