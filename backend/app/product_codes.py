def normalize_product_code(code: str) -> str:
    return " ".join(code.strip().casefold().split())
