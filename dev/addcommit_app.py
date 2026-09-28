#!/usr/bin/env python3
# 더블클릭용 진입점. 대상 git 폴더를 받아 스케줄을 만들고 커밋한다.

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Optional, Sequence

from commit_schedule_apply import (
    ApplyError,
    apply_commits,
    build_plan,
    confirm_apply,
    ensure_clean,
    ensure_repo,
    load_commit_settings,
    load_schedule,
    print_plan,
)
from commit_schedule_generator import (
    ConfigError,
    app_dir,
    generate_schedule,
    load_config,
    parse_date,
    print_summary,
    summarize,
)


def clean_path(value: str) -> str:
    return value.strip().strip('"').strip("'")


def ask(label: str, default: Optional[str] = None) -> str:
    hint = f" [{default}]" if default else ""
    while True:
        try:
            raw = input(f"{label}{hint}: ")
        except EOFError as exc:
            raise ApplyError("error: input closed") from exc
        text = clean_path(raw)
        if text:
            return text
        if default is not None:
            return default
        print("값을 입력하세요.")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="대상 폴더에 스케줄대로 더미 커밋을 만듭니다."
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="대상 git 폴더. 실행 파일에 폴더를 끌어다 놓아도 됩니다.",
    )
    parser.add_argument("--target", dest="target_flag", help="대상 git 폴더")
    parser.add_argument("--start", help="시작일 YYYY-MM-DD")
    parser.add_argument("--end", help="종료일 YYYY-MM-DD")
    parser.add_argument("--seed", type=int, default=42, help="난수 시드")
    parser.add_argument("--config", help="설정 JSON 경로")
    parser.add_argument("--dry-run", action="store_true", help="커밋하지 않고 계획만 출력")
    parser.add_argument("--yes", action="store_true", help="확인 없이 커밋")
    return parser


def run(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    target_text = args.target_flag or args.target
    if target_text:
        target_text = clean_path(target_text)
    else:
        print("커밋을 넣을 git 폴더 경로를 입력하세요.")
        print("폴더를 이 창에 끌어다 놓아도 됩니다.")
        target_text = ask("대상 폴더")

    start_text = args.start or ask("시작일 YYYY-MM-DD", "2025-07-14")
    end_text = args.end or ask("종료일 YYYY-MM-DD", "2025-10-08")
    try:
        start = parse_date(start_text)
        end = parse_date(end_text)
    except ValueError as exc:
        raise ApplyError("error: 날짜는 YYYY-MM-DD 형식이어야 합니다.") from exc
    if end < start:
        raise ApplyError("error: 종료일은 시작일보다 빠를 수 없습니다.")

    config_path = Path(args.config) if args.config else app_dir() / "schedule_config.json"
    try:
        weights, max_weekday_gap, dated_holidays = load_config(config_path)
        settings = load_commit_settings(config_path)
    except ConfigError as exc:
        raise ApplyError(str(exc)) from exc

    schedule = generate_schedule(
        start=start,
        end=end,
        seed=args.seed,
        weights=weights,
        max_weekday_gap=max_weekday_gap,
        dated_holidays=dated_holidays,
    )
    print_summary(summarize(schedule), file=sys.stdout)
    if not schedule:
        print("커밋할 활동일이 없습니다.")
        return 0

    payload = json.dumps(
        [day.to_dict() for day in schedule], ensure_ascii=False, indent=2
    )
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".json", delete=False
    ) as handle:
        handle.write(payload)
        schedule_path = Path(handle.name)
    try:
        rows = load_schedule(schedule_path)
        planned = build_plan(rows, settings)
    finally:
        schedule_path.unlink(missing_ok=True)

    repo = ensure_repo(Path(target_text))
    if args.dry_run:
        print_plan(planned, settings.dummy_file)
        return 0
    if not args.yes and not sys.stdin.isatty():
        raise ApplyError("error: confirmation needs a terminal, or pass --yes")
    ensure_clean(repo)
    if not args.yes and not confirm_apply(repo, settings, planned):
        print("취소했습니다.")
        return 1
    apply_commits(repo, settings, planned)
    print("커밋을 마쳤습니다. push는 직접 하면 됩니다.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    frozen = getattr(sys, "frozen", False)
    code = 2
    try:
        code = run(argv)
    except ApplyError as exc:
        print(str(exc), file=sys.stderr)
        code = 2
    finally:
        if frozen:
            try:
                input("엔터를 누르면 닫힙니다.")
            except EOFError:
                pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
