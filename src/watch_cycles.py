"""Watch public cycles on a cloud runner; submit once per cycle, then hand over."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from predict import APIClient, ROOT, accepted_cycle


def utc_now():
    return datetime.now(timezone.utc)


def deliver():
    return subprocess.run(
        [sys.executable, "-u", str(ROOT / "src/predict.py"), "--submit", "--yes"],
        cwd=ROOT, timeout=480, check=False,
    ).returncode


def watch(api, *, until, seconds=2700, interval=60, send=deliver,
          monotonic=time.monotonic, sleep=time.sleep, now=utc_now):
    deadline = monotonic() + seconds
    while monotonic() < deadline and now() < until:
        try:
            cycle = api.current_cycle()
            if cycle is None:
                print("Sin ciclo abierto; siguiente consulta en 60 segundos.", flush=True)
            elif accepted_cycle(cycle["cycle_id"]):
                print(f"Ciclo {cycle['cycle_id']} ya entregado.", flush=True)
            else:
                print(f"Ciclo detectado: {cycle['cycle_id']}; iniciando entrega.", flush=True)
                code = send()
                if code:
                    print(f"::warning::El proceso de entrega terminó con código {code}; se conserva el estado para reintentar.", flush=True)
        except Exception as exc:
            # Never print environment variables, authorization headers or credentials.
            print(f"::warning::Consulta/entrega interrumpida ({type(exc).__name__}); se reintentará.", flush=True)
        remaining = min(deadline - monotonic(), (until - now()).total_seconds())
        if remaining > 0:
            sleep(min(interval, remaining))
    return now() < until


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=int, default=45)
    parser.add_argument("--until", required=True)
    args = parser.parse_args(argv)
    if not 1 <= args.minutes <= 45:
        parser.error("minutes debe estar entre 1 y 45")
    until = datetime.fromisoformat(args.until.replace("Z", "+00:00"))
    if until.tzinfo is None:
        parser.error("until debe incluir zona horaria")
    if not os.getenv("PULSO_API_KEY"):
        parser.error("falta el Secret PULSO_API_KEY")
    with APIClient() as api:
        renew = watch(api, until=until, seconds=args.minutes * 60)
    if output := os.getenv("GITHUB_OUTPUT"):
        with Path(output).open("a") as stream:
            stream.write(f"renew={'true' if renew else 'false'}\n")
    print("Turno terminado; renovar proceso." if renew else "Fecha de cierre alcanzada; vigilancia detenida.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
