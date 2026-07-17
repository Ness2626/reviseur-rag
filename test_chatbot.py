import pytest

import chatbot


@pytest.mark.parametrize("line, expected", [
    ("3. EUF-CMA — la sécurité d’une signature", "EUF-CMA — la sécurité d’une signature"),
    ("8. Modes symétriques : ECB, CBC, CTR, AEAD", "Modes symétriques : ECB, CBC, CTR, AEAD"),
    ("11. Attaques par canaux auxiliaires : le temps", "Attaques par canaux auxiliaires : le temps"),
    ("2. Vérification de l’identité de Bob", "Vérification de l’identité de Bob"),
])
def test_detect_section_title_accepts_numbered_titles(line, expected):
    assert chatbot.detect_section_title(line) == expected


@pytest.mark.parametrize("line", [
    "2017 (ROBOT).",                                    # année, pas un numéro de section
    "s=d(m,LA)",                                        # fragment de schéma, aucun numéro
    "LA LB",                                            # bruit de slide
    "Réponse. On ne prouve jamais qu’un schéma…",      # prose, pas numérotée
    "2. Le déterminisme n’est pas un défaut en soi (Ed25519 est déterministe et",  # item de liste trop long
    "➢ d’identifier l’expéditeur du message",          # puce
    "",                                                 # ligne vide
    "3.",                                              # numéro sans texte
])
def test_detect_section_title_rejects_non_titles(line):
    assert chatbot.detect_section_title(line) is None


def test_detect_section_title_strips_trailing_hyphen_from_wrapped_title():
    assert chatbot.detect_section_title("2. IND-CPA, IND-CCA — la sécurité d’un chiffre‐") == \
        "IND-CPA, IND-CCA — la sécurité d’un chiffre"


def test_chunk_pages_prefixes_body_with_section_title():
    pages = ["1. RSA — signatures\nLa signature repose sur la clé privée."]
    chunks = chatbot.chunk_pages(pages, "cours.pdf")
    assert len(chunks) == 1
    assert chunks[0].text == "[Section : RSA — signatures] La signature repose sur la clé privée."
    assert chunks[0].page == 1


def test_chunk_pages_carries_title_across_pages():
    pages = ["2. Certificats\nUn certificat lie une clé.", "La CA signe le certificat."]
    chunks = chatbot.chunk_pages(pages, "cours.pdf")
    assert [c.page for c in chunks] == [1, 2]
    assert all(c.text.startswith("[Section : Certificats] ") for c in chunks)


def test_chunk_pages_without_titles_matches_plain_chunking():
    pages = ["Un paragraphe sans titre.", "Un autre paragraphe."]
    chunks = chatbot.chunk_pages(pages, "cours.pdf")
    assert [(c.text, c.page) for c in chunks] == [
        ("Un paragraphe sans titre.", 1),
        ("Un autre paragraphe.", 2),
    ]


def test_chunk_pages_skips_empty_section_between_two_titles():
    pages = ["1. Premier\n2. Second\nLe corps du second."]
    chunks = chatbot.chunk_pages(pages, "cours.pdf")
    assert len(chunks) == 1
    assert chunks[0].text == "[Section : Second] Le corps du second."


def test_chunk_pages_long_section_shares_prefix_across_chunks():
    body = " ".join(f"mot{i}" for i in range(chatbot.CHUNK_SIZE + 200))
    pages = [f"1. Grande section\n{body}"]
    chunks = chatbot.chunk_pages(pages, "cours.pdf")
    assert len(chunks) > 1
    assert all(c.text.startswith("[Section : Grande section] ") for c in chunks)


def test_cache_signature_includes_version_and_keeps_file_signature_pure(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 contenu")
    file_sig = chatbot.file_signature(str(pdf))
    cache_sig = chatbot.cache_signature(str(pdf))
    assert len(file_sig) == 64 and all(c in "0123456789abcdef" for c in file_sig)
    assert cache_sig == f"{chatbot.CHUNKER_VERSION}:{file_sig}"
