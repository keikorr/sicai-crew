"""Obtenção do PDF (pasta local ou Garage) e extração de texto por página."""

from pathlib import Path

from sicai import config


def baixar_pdf(document_id: str) -> bytes:
    """Lê o PDF da pasta local, se existir lá; senão, busca no Garage."""
    if config.DOCS_FOLDER:
        raiz = Path(config.DOCS_FOLDER).resolve()
        caminho = (raiz / document_id).resolve()
        # O document_id vem da requisição: não pode apontar para fora da pasta.
        if raiz in caminho.parents and caminho.is_file():
            return caminho.read_bytes()

    if not (config.GARAGE_ENDPOINT and config.GARAGE_BUCKET):
        raise FileNotFoundError(
            f"Documento '{document_id}' não está em DOCS_FOLDER e o Garage não "
            "está configurado (GARAGE_ENDPOINT, GARAGE_BUCKET)."
        )

    import boto3

    cliente = boto3.client(
        "s3",
        endpoint_url=config.GARAGE_ENDPOINT,
        region_name=config.GARAGE_REGION,
        aws_access_key_id=config.GARAGE_ACCESS_KEY,
        aws_secret_access_key=config.GARAGE_SECRET_KEY,
    )
    # Premissa: a chave do objeto no bucket é o próprio document_id.
    objeto = cliente.get_object(Bucket=config.GARAGE_BUCKET, Key=document_id)
    return objeto["Body"].read()


def extrair_paginas(pdf: bytes) -> list[dict]:
    """Texto de cada página. Páginas sem texto passam por OCR, se habilitado."""
    import fitz  # PyMuPDF

    paginas = []
    with fitz.open(stream=pdf, filetype="pdf") as doc:
        for numero, pagina in enumerate(doc, start=1):
            texto = pagina.get_text("text")
            ocr = False
            if len(texto.strip()) < 50 and config.OCR_ENABLED:
                try:
                    camada = pagina.get_textpage_ocr(language=config.OCR_LANGUAGE, dpi=300)
                    texto = pagina.get_text("text", textpage=camada)
                    ocr = True
                except Exception as erro:  # Tesseract ausente ou página ilegível
                    print(f"OCR falhou na página {numero}: {erro}")
            paginas.append({"pagina": numero, "texto": texto, "ocr": ocr})
    return paginas
