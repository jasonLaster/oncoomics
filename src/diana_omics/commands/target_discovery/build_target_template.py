from __future__ import annotations

from ...paths import path_from_root
from ...target_discovery import (
    CANDIDATE_COLUMNS,
    TARGET_DISCOVERY_CANDIDATES,
    TARGET_DISCOVERY_RESULTS,
    TARGET_DISCOVERY_TEMPLATE,
    TARGET_INPUT_COLUMNS,
    candidate_rows,
    target_input_rows,
    validate_candidate_rows,
)
from ...utils import ensure_dir, iso_now, write_csv, write_json


def main() -> None:
    candidates = candidate_rows()
    errors = validate_candidate_rows(candidates)
    if errors:
        raise SystemExit("\n".join(errors))

    ensure_dir(path_from_root(TARGET_DISCOVERY_RESULTS))
    write_csv(path_from_root(TARGET_DISCOVERY_CANDIDATES), candidates, CANDIDATE_COLUMNS)
    write_csv(path_from_root(TARGET_DISCOVERY_TEMPLATE), target_input_rows(), TARGET_INPUT_COLUMNS)
    write_json(
        path_from_root(f"{TARGET_DISCOVERY_RESULTS}/input_contract.json"),
        {
            "generatedAt": iso_now(),
            "status": "template_ready",
            "candidateManifest": TARGET_DISCOVERY_CANDIDATES,
            "inputTemplate": TARGET_DISCOVERY_TEMPLATE,
            "targetCount": len(candidates),
            "boundary": "WES/WGS is first-pass support or blocker evidence only; expression, protein abundance, and drug context stay no_call until their own evidence lanes pass.",
        },
    )
    print(f"Target discovery template written: {TARGET_DISCOVERY_TEMPLATE}")


if __name__ == "__main__":
    main()
