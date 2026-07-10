"""Generate the zenoh router + session configs from the image defaults.

Neutrality: we start from rmw_zenoh's shipped defaults and apply only the minimal
documented toggles:
  - router  : listen endpoint  tcp/[::]:7447   -> tcp/127.0.0.1:7887  (isolation)
  - session : connect endpoint tcp/localhost:7447 -> tcp/127.0.0.1:7887 (isolation)
  - session : shared_memory.enabled false -> true  (SHM variant only)
Everything else is left at the vendor default. Defaults are read from files the
caller extracted from the image (default_router.json5 / default_session.json5).
"""
import re
import sys
from pathlib import Path

CFG = Path(__file__).resolve().parent / "configs"


def flip_shm(text: str) -> str:
    """Flip the first `enabled: false` inside the shared_memory block to true."""
    idx = text.index("shared_memory: {")
    head, tail = text[:idx], text[idx:]
    tail = tail.replace("enabled: false", "enabled: true", 1)
    return head + tail


def main() -> None:
    router = (CFG / "default_router.json5").read_text()
    session = (CFG / "default_session.json5").read_text()

    router = router.replace('"tcp/[::]:7447"', '"tcp/127.0.0.1:7887"')
    session = session.replace('"tcp/localhost:7447"', '"tcp/127.0.0.1:7887"')

    (CFG / "zenoh_router.json5").write_text(router)
    (CFG / "zenoh_session_noshm.json5").write_text(session)
    (CFG / "zenoh_session_shm.json5").write_text(flip_shm(session))

    # Sanity: confirm the edits actually landed (quoted endpoint form; the old
    # port still appears in doc comments, which is fine).
    assert '"tcp/127.0.0.1:7887"' in router and '"tcp/[::]:7447"' not in router
    assert '"tcp/127.0.0.1:7887"' in session and '"tcp/localhost:7447"' not in session
    shm = (CFG / "zenoh_session_shm.json5").read_text()
    shm_block = shm[shm.index("shared_memory: {"):]
    assert re.search(r"shared_memory: \{[^}]*enabled: true", shm_block, re.S), "SHM flip failed"
    print("zenoh configs written: router(7887), session noshm+shm")


if __name__ == "__main__":
    sys.exit(main())
