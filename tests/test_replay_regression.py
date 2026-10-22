from __future__ import annotations

from audit_helpers import REPLAY_MINUTES, build_audit_row, validate_audit_row


def test_replay_minute(minute: int) -> None:
    row = build_audit_row(minute)
    problems = validate_audit_row(row)
    if problems:
        raise AssertionError(f"minute {minute}: " + "; ".join(problems))


def main() -> int:
    failures = []
    for minute in REPLAY_MINUTES:
        try:
            test_replay_minute(minute)
            print(f"PASS minute={minute}")
        except Exception as exc:
            failures.append((minute, str(exc)))
            print(f"FAIL minute={minute} {exc}")

    if failures:
        print(f"\nRegression failed: {len(failures)}/{len(REPLAY_MINUTES)} replay minutes failed")
        return 1

    print(f"\nRegression passed: {len(REPLAY_MINUTES)}/{len(REPLAY_MINUTES)} replay minutes passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
