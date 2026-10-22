from __future__ import annotations

from audit_helpers import run_full_audit


def _fmt(value, width: int) -> str:
    text = str(value)
    if len(text) > width:
        return text[: width - 1] + "..."
    return text.ljust(width)


def main() -> int:
    rows = run_full_audit()
    columns = [
        ("minute", 6),
        ("quarter", 7),
        ("score", 11),
        ("pace", 7),
        ("momentum", 17),
        ("master", 7),
        ("confidence", 10),
        ("edge", 17),
        ("projected_total", 15),
    ]

    print(" ".join(_fmt(name, width) for name, width in columns))
    print(" ".join("-" * width for _, width in columns))

    total_problems = []
    for row in rows:
        snapshot = row["snapshot"]
        possession = row["possession"]
        momentum = row["momentum"]
        projection = row["projection"]
        values = {
            "minute": row["minute"],
            "quarter": f"Q{snapshot['period']}",
            "score": f"{snapshot['score_away']}-{snapshot['score_home']}",
            "pace": possession["pace_per_48"],
            "momentum": momentum["momentum_signal"],
            "master": projection["master_live_factor"],
            "confidence": projection["confidence_score"],
            "edge": projection["edge_signal"],
            "projected_total": projection["projected_quarter_total"],
        }
        print(" ".join(_fmt(values[name], width) for name, width in columns))

        for problem in row["problems"]:
            total_problems.append(f"minute {row['minute']}: {problem}")

    print()
    if total_problems:
        print(f"FAIL: {len(total_problems)} issue(s) detected")
        print("Detected problems:")
        for problem in total_problems:
            print(f"- {problem}")
        return 1

    print(f"PASS: {len(rows)} replay minute(s) audited")
    print("Detected problems: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
