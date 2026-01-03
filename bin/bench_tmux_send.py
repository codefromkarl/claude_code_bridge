#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time


def _pctl(samples: list[float], p: float) -> float:
    if not samples:
        return 0.0
    if p <= 0:
        return min(samples)
    if p >= 100:
        return max(samples)
    s = sorted(samples)
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    d0 = s[f] * (c - k)
    d1 = s[c] * (k - f)
    return d0 + d1


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark tmux send_text latency in CCB")
    parser.add_argument("--target", required=True, help="tmux target, e.g. session:window.pane or session name")
    parser.add_argument("-n", type=int, default=200, help="number of sends")
    parser.add_argument("--persist", action="store_true", help="enable persistent tmux control mode (CCB_TMUX_PERSIST=1)")
    parser.add_argument("--force-paste", action="store_true", help="force paste path (CCB_FORCE_PASTE=1)")
    parser.add_argument("--cmd", default=":", help="command to send (default ':' noop)")
    args = parser.parse_args()

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sys.path.insert(0, os.path.join(repo_root, "lib"))

    if args.persist:
        os.environ["CCB_TMUX_PERSIST"] = "1"
    if args.force_paste:
        os.environ["CCB_FORCE_PASTE"] = "1"

    from terminal import TmuxBackend  # noqa

    try:
        import resource  # type: ignore
    except Exception:
        resource = None

    backend = TmuxBackend()

    cpu_start = None
    if resource is not None:
        r = resource.getrusage(resource.RUSAGE_SELF)
        cpu_start = r.ru_utime + r.ru_stime

    durations: list[float] = []
    for i in range(max(0, args.n)):
        payload = args.cmd.replace("{i}", str(i))
        t0 = time.perf_counter()
        backend.send_text(args.target, payload)
        durations.append(time.perf_counter() - t0)

    cpu_total = None
    if resource is not None and cpu_start is not None:
        r = resource.getrusage(resource.RUSAGE_SELF)
        cpu_total = (r.ru_utime + r.ru_stime) - cpu_start

    p50 = _pctl(durations, 50)
    p95 = _pctl(durations, 95)
    mean = statistics.mean(durations) if durations else 0.0

    print(f"n={len(durations)} target={args.target} persist={args.persist} force_paste={args.force_paste}")
    print(f"mean={mean*1000:.2f}ms p50={p50*1000:.2f}ms p95={p95*1000:.2f}ms max={max(durations)*1000:.2f}ms")
    if cpu_total is not None:
        print(f"cpu={cpu_total:.3f}s (self user+sys)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

