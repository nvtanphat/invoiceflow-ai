_ARTIFACT_REPLACEMENTS = {
    # PyMuPDF/MuPDF substitutes a soft hyphen (U+00AD) for a plain ASCII
    # hyphen-minus when text is inserted through an embedded simple TTF
    # font (reproduced with a bare "DELL-XPS-13" string + arial.ttf). SKU
    # codes and invoice numbers rely on literal hyphens, so the character
    # that was actually typed is restored rather than silently dropped.
    "­": "-",
    " ": " ",  # non-breaking space
}


def normalize_extracted_text(text: str) -> str:
    """Normalizes PDF text-layer artifacts from font embedding/shaping so
    downstream parsing sees the characters a human reader would. Never
    alters visible content.
    """
    for artifact, replacement in _ARTIFACT_REPLACEMENTS.items():
        text = text.replace(artifact, replacement)
    return text
