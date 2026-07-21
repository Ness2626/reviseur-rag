"""Transcrit un PDF scanné (pages en images) en PDF texte, via un modèle de vision.

Les cours photographiés ne contiennent aucun texte extractible : pypdf n'en tire
rien et le RAG les ignore. Ce script envoie chaque page au modèle de vision et
écrit un PDF qui garde l'image d'origine, avec la transcription posée par-dessus
en couche invisible. Le document reste donc le scan : la transcription ne sert
qu'à retrouver la page, jamais à la remplacer, et une citation du RAG
(« cours.pdf p.5 ») ouvre la vraie page du cours, vérifiable à l'œil.

La transcription est écrite au fil de l'eau dans un fichier texte voisin : si le
script est interrompu, le relancer reprend là où il s'était arrêté sans repayer
les pages déjà faites.

Usage : python ocr.py mon-cours-scanne.pdf [destination.pdf]
"""

import base64
import os
import sys
import time
from collections import Counter

import pymupdf
from dotenv import load_dotenv
from groq import Groq

VISION_MODEL = "qwen/qwen3.6-27b"
RENDER_MAX_PX = 1300
JPEG_QUALITY = 75
PAGE_DELAY_S = 15
MAX_COMPLETION_TOKENS = 1200
MAX_LINE_REPEATS = 2
MIN_WORDS_PER_PAGE = 20
SCAN_PAGE_RATIO = 0.5
PAGE_SEPARATOR = "\n\n===PAGE===\n\n"
FONT_NAME = "helv"
PAGE_MARGIN_PT = 20
OUTPUT_MAX_PX = 1600
OUTPUT_JPEG_QUALITY = 75
OUTPUT_PAGE_WIDTH_PT = 595
HIDDEN_TEXT_SIZES = (8, 6, 4, 3, 2)
INVISIBLE_RENDER_MODE = 3
PROMPT = (
    "Transcris fidèlement tout le texte de cette page de cours, y compris les annotations "
    "manuscrites et les formules (en notation texte). Ne commente pas, ne résume pas, "
    "n'ajoute aucun titre : rends uniquement le texte de la page."
)


def render_page(page):
    scale = RENDER_MAX_PX / max(page.rect.width, page.rect.height)
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
    return pixmap.tobytes("jpeg", jpg_quality=JPEG_QUALITY)


def transcribe(client, jpeg_bytes):
    encoded = base64.b64encode(jpeg_bytes).decode("ascii")
    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
        ]}],
        temperature=0,
        reasoning_effort="none",
        max_completion_tokens=MAX_COMPLETION_TOKENS,
    )
    return (response.choices[0].message.content or "").strip()


def strip_repetitions(text):
    """Coupe les boucles du modèle, qui répète parfois une ligne jusqu'à épuiser son budget."""
    seen = Counter()
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            seen[stripped] += 1
            if seen[stripped] > MAX_LINE_REPEATS:
                break
        kept.append(line)
    return "\n".join(kept).strip()


def load_done_pages(sidecar_path):
    if not os.path.exists(sidecar_path):
        return []
    with open(sidecar_path, encoding="utf-8") as handle:
        content = handle.read()
    return [strip_repetitions(page) for page in content.split(PAGE_SEPARATOR)] if content else []


def append_page(sidecar_path, text, is_first):
    with open(sidecar_path, "a", encoding="utf-8") as handle:
        handle.write(text if is_first else PAGE_SEPARATOR + text)


def page_text(page):
    return page.get_text().strip()


def needs_vision(page):
    return len(page_text(page).split()) < MIN_WORDS_PER_PAGE


def is_scan(document):
    """Un scan, c'est un document dont la plupart des pages ne rendent aucun texte."""
    blank = sum(1 for page in document if needs_vision(page))
    return blank > len(document) * SCAN_PAGE_RATIO


def transcribe_document(client, source_path, sidecar_path):
    document = pymupdf.open(source_path)
    if not is_scan(document):
        return None
    pages = load_done_pages(sidecar_path)
    if pages:
        print(f"Reprise : {len(pages)} page(s) déjà transcrite(s).")
    called = False
    for index in range(len(pages), len(document)):
        page = document[index]
        if needs_vision(page):
            if called:
                time.sleep(PAGE_DELAY_S)
            text = strip_repetitions(transcribe(client, render_page(page)))
            called = True
            origin = "vision"
        else:
            text = page_text(page)
            origin = "texte du PDF"
        append_page(sidecar_path, text, index == 0)
        pages.append(text)
        print(f"  page {index + 1}/{len(document)} : {len(text.split())} mots ({origin})")
    return pages


def _page_size(source_page):
    ratio = source_page.rect.height / source_page.rect.width
    return OUTPUT_PAGE_WIDTH_PT, OUTPUT_PAGE_WIDTH_PT * ratio


def _output_image(source_page):
    scale = OUTPUT_MAX_PX / max(source_page.rect.width, source_page.rect.height)
    pixmap = source_page.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
    return pixmap.tobytes("jpeg", jpg_quality=OUTPUT_JPEG_QUALITY)


def _insert_hidden_text(page, text):
    """Pose la transcription en couche invisible : elle sert à l'index, jamais à l'affichage."""
    box = pymupdf.Rect(PAGE_MARGIN_PT, PAGE_MARGIN_PT,
                       page.rect.width - PAGE_MARGIN_PT, page.rect.height - PAGE_MARGIN_PT)
    for size in HIDDEN_TEXT_SIZES:
        if page.insert_textbox(box, text, fontsize=size, fontname=FONT_NAME,
                               render_mode=INVISIBLE_RENDER_MODE) >= 0:
            return True
    return False


def write_searchable_pdf(source_path, pages, destination):
    """Écrit le scan d'origine avec sa transcription en couche invisible par-dessus."""
    source = pymupdf.open(source_path)
    output = pymupdf.open()
    dropped = []
    for index, text in enumerate(pages):
        source_page = source[index]
        width, height = _page_size(source_page)
        page = output.new_page(width=width, height=height)
        page.insert_image(page.rect, stream=_output_image(source_page))
        if text and not _insert_hidden_text(page, text):
            dropped.append(index + 1)
    output.save(destination, deflate=True, garbage=4)
    output.close()
    if dropped:
        print(f"Texte trop long pour la couche invisible en page(s) {dropped} : "
              f"transcription tronquée à l'affichage de l'index.", file=sys.stderr)


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        sys.exit(1)
    source = sys.argv[1]
    if not os.path.isfile(source):
        print(f"Fichier introuvable : {source}", file=sys.stderr)
        sys.exit(1)
    destination = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        "docs", os.path.basename(source))
    load_dotenv()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("Erreur : GROQ_API_KEY introuvable dans le fichier .env", file=sys.stderr)
        sys.exit(1)

    sidecar = os.path.splitext(destination)[0] + ".ocr.txt"
    os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
    started = time.time()
    pages = transcribe_document(Groq(api_key=api_key, max_retries=5), source, sidecar)
    if pages is None:
        print("Ce PDF contient déjà du texte : place-le directement dans docs/.")
        return
    write_searchable_pdf(source, pages, destination)
    words = sum(len(page.split()) for page in pages)
    print(f"\n{len(pages)} page(s), {words} mots, {(time.time() - started) / 60:.1f} min.")
    print(f"Écrit dans {destination} — relance l'appli pour l'indexer.")


if __name__ == "__main__":
    main()
