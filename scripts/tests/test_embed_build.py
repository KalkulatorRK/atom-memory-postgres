from embed_build import build_embed_text, compute_content_hash


def test_build_embed_text_skips_image():
    atom = {"atom_type": "image", "content": "[изображение: x.png]", "metadata": {}}
    text, skip = build_embed_text(atom, "Doc")
    assert text is None
    assert skip == "image_no_caption"


def test_build_embed_text_with_caption():
    atom = {
        "atom_type": "image",
        "content": "[изображение: x.png]",
        "metadata": {"caption": "Схема установки"},
    }
    text, skip = build_embed_text(atom, "ГОСТ 1")
    assert skip is None
    assert "Схема" in text
    assert "ГОСТ 1" in text


def test_content_hash_changes_with_content():
    h1 = compute_content_hash("fake:hash-v1", 768, "a")
    h2 = compute_content_hash("fake:hash-v1", 768, "b")
    assert h1 != h2
