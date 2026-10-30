"""Read-only capability diagnostics for the local native worker package."""
import json
import sys

from . import get_adapter


def main():
    # No client connection or content scan is performed by diagnostics. Real
    # collection is started through the backend's serialized durable job worker.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({kind: get_adapter(kind).probe_capabilities()
                      for kind in ("group", "moments", "upload")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
