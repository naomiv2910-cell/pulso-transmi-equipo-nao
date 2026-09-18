"""Descarga y verifica los datos iniciales de Pulso TransMi."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen


BASE_URL = "https://pulso-transmi.72-60-245-2.sslip.io"
FILES = ("stations.csv", "observations.csv", "context.csv", "metadata.json")
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"


def download(url: str, destination: Path) -> None:
    request = Request(url, headers={"User-Agent": "pulso-transmi-equipo-nao/1.0"})
    with urlopen(request, timeout=60) as response:  # noqa: S310 - URL controlada
        destination.write_bytes(response.read())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for filename in FILES:
        destination = OUTPUT_DIR / filename
        download(f"{BASE_URL}/v1/downloads/{filename}", destination)
        print(f"Descargado: {destination.relative_to(OUTPUT_DIR.parents[1])}")

    metadata = json.loads((OUTPUT_DIR / "metadata.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    for filename, expected in metadata["files"].items():
        actual_hash = sha256(OUTPUT_DIR / filename)
        if actual_hash != expected["sha256"]:
            errors.append(f"{filename}: hash SHA-256 diferente")

    if errors:
        raise RuntimeError("Falló la verificación:\n" + "\n".join(errors))

    print(
        "Verificación correcta: "
        f"{metadata['station_count']} estaciones, "
        f"{metadata['observation_rows']:,} observaciones y "
        f"{metadata['context_rows']:,} registros de contexto."
    )


if __name__ == "__main__":
    main()

