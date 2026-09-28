#!/usr/bin/env python3
# 스케줄 JSON을 읽어 더미 파일 한 개에 줄을 추가하고 git add, commit 한다.
# push 와 git config 변경은 하지 않는다.

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence


def app_dir() -> Path:
    # exe로 실행하면 설정 파일은 실행 파일과 같은 폴더에 둔다.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


DEFAULT_CONFIG_PATH = app_dir() / "schedule_config.json"


class ApplyError(Exception):
    pass


@dataclass(frozen=True)
class CommitSettings:
    window_start_sec: int
    window_end_sec: int
    timezone: str
    dummy_file: str
    message: str


@dataclass(frozen=True)
class PlannedCommit:
    day: date
    clock: str
    index: int
    message: str
    author_date: str
    line: str


def parse_hhmm(value: object, label: str) -> int:
    if not isinstance(value, str):
        raise ApplyError(f"error: {label} must be HH:MM")
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ApplyError(f"error: {label} must be HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if hour > 23 or minute > 59 or len(parts[0]) != 2 or len(parts[1]) != 2:
        raise ApplyError(f"error: {label} must be HH:MM")
    return hour * 3600 + minute * 60


def format_clock(total_sec: int) -> str:
    hour, rem = divmod(total_sec, 3600)
    minute, second = divmod(rem, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def assign_clocks(count: int, start_sec: int, end_sec: int) -> List[str]:
    if count < 1:
        raise ApplyError("error: commits must be >= 1")
    if end_sec <= start_sec:
        raise ApplyError("error: window_end must be after window_start")
    if count == 1:
        seconds = [start_sec]
    else:
        span = end_sec - start_sec
        seconds = [start_sec + (span * i) // (count - 1) for i in range(count)]
        for i in range(1, len(seconds)):
            if seconds[i] <= seconds[i - 1]:
                seconds[i] = seconds[i - 1] + 1
        if seconds[-1] > end_sec:
            raise ApplyError(
                "error: commit window is too short for the number of commits"
            )
    return [format_clock(sec) for sec in seconds]


def load_commit_settings(path: Path) -> CommitSettings:
    if not path.is_file():
        raise ApplyError(f"error: config file not found: {path}")
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ApplyError(f"error: invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ApplyError("error: config root must be an object")
    commit = data.get("commit")
    if not isinstance(commit, dict):
        raise ApplyError("error: config key commit must be an object")

    start_sec = parse_hhmm(commit.get("window_start"), "window_start")
    end_sec = parse_hhmm(commit.get("window_end"), "window_end")
    if end_sec <= start_sec:
        raise ApplyError("error: window_end must be after window_start")

    timezone = commit.get("timezone", "+09:00")
    if not isinstance(timezone, str) or len(timezone) != 6:
        raise ApplyError("error: timezone must look like +09:00")
    sign, hh, colon, mm = timezone[0], timezone[1:3], timezone[3], timezone[4:6]
    if sign not in "+-" or colon != ":" or not hh.isdigit() or not mm.isdigit():
        raise ApplyError("error: timezone must look like +09:00")
    if int(hh) > 23 or int(mm) > 59:
        raise ApplyError("error: timezone must look like +09:00")

    dummy_file = commit.get("dummy_file")
    if not isinstance(dummy_file, str) or not dummy_file.strip():
        raise ApplyError("error: dummy_file must be a relative path inside the repo")
    dummy_path = Path(dummy_file)
    if dummy_path.is_absolute() or ".." in dummy_path.parts:
        raise ApplyError("error: dummy_file must be a relative path inside the repo")

    message = commit.get("message")
    if not isinstance(message, str) or not message.strip():
        raise ApplyError("error: message must be a non-empty string")

    return CommitSettings(
        window_start_sec=start_sec,
        window_end_sec=end_sec,
        timezone=timezone,
        dummy_file=dummy_file.replace("\\", "/"),
        message=message,
    )


def load_schedule(path: Path) -> List[dict]:
    if not path.is_file():
        raise ApplyError(f"error: schedule file not found: {path}")
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ApplyError(f"error: invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, list):
        raise ApplyError("error: schedule root must be a list")

    rows: List[dict] = []
    seen = set()
    for index, item in enumerate(data):
        label = f"schedule[{index}]"
        if not isinstance(item, dict):
            raise ApplyError(f"error: {label} must be an object")
        raw_date = item.get("date")
        if not isinstance(raw_date, str):
            raise ApplyError(f"error: {label}.date must be YYYY-MM-DD")
        try:
            day = datetime.strptime(raw_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ApplyError(f"error: {label}.date must be YYYY-MM-DD") from exc
        commits = item.get("commits")
        if isinstance(commits, bool) or not isinstance(commits, int) or commits < 1:
            raise ApplyError(f"error: {label}.commits must be an integer >= 1")
        if day in seen:
            raise ApplyError(f"error: duplicate schedule date: {day.isoformat()}")
        seen.add(day)
        rows.append({"date": day, "commits": commits})
    rows.sort(key=lambda row: row["date"])
    return rows


def render_message(template: str, day: date, clock: str, index: int) -> str:
    return (
        template.replace("{date}", day.isoformat())
        .replace("{time}", clock)
        .replace("{index}", str(index))
    )


def build_plan(rows: Sequence[dict], settings: CommitSettings) -> List[PlannedCommit]:
    planned: List[PlannedCommit] = []
    for row in rows:
        day: date = row["date"]
        clocks = assign_clocks(
            row["commits"], settings.window_start_sec, settings.window_end_sec
        )
        for index, clock in enumerate(clocks, start=1):
            message = render_message(settings.message, day, clock, index)
            author_date = f"{day.isoformat()}T{clock}{settings.timezone}"
            line = f"{day.isoformat()} {clock} {index}\n"
            planned.append(
                PlannedCommit(
                    day=day,
                    clock=clock,
                    index=index,
                    message=message,
                    author_date=author_date,
                    line=line,
                )
            )
    return planned


def git_cmd(
    repo: Path, args: Sequence[str], env: Optional[Dict[str, str]] = None
) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=merged,
    )


def ensure_repo(repo: Path) -> Path:
    repo = repo.resolve()
    if not repo.is_dir():
        raise ApplyError(f"error: repo is not a directory: {repo}")
    result = git_cmd(repo, ["rev-parse", "--is-inside-work-tree"])
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise ApplyError(f"error: not a git repository: {repo}")
    return repo


def ensure_clean(repo: Path) -> None:
    result = git_cmd(repo, ["status", "--porcelain"])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ApplyError(f"error: git status failed: {detail}")
    if result.stdout.strip():
        raise ApplyError("error: working tree is not clean")


def print_plan(planned: Sequence[PlannedCommit], dummy_file: str, file=sys.stdout) -> None:
    print(f"파일: {dummy_file}", file=file)
    print(f"총 커밋: {len(planned)}", file=file)
    for item in planned:
        print(f"{item.day.isoformat()} {item.clock}  {item.message}", file=file)


def confirm_apply(repo: Path, settings: CommitSettings, planned: Sequence[PlannedCommit]) -> bool:
    print(f"저장소: {repo}")
    print(f"파일: {settings.dummy_file}")
    print(f"총 커밋: {len(planned)}")
    if planned:
        print(f"첫 시각: {planned[0].author_date}")
        print(f"마지막 시각: {planned[-1].author_date}")
    try:
        answer = input("이 스케줄로 커밋할까요? [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer == "y"


def apply_commits(repo: Path, settings: CommitSettings, planned: Sequence[PlannedCommit]) -> None:
    dummy_path = repo / settings.dummy_file
    dummy_path.parent.mkdir(parents=True, exist_ok=True)
    for item in planned:
        with dummy_path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(item.line)
        added = git_cmd(repo, ["add", "--", settings.dummy_file])
        if added.returncode != 0:
            detail = (added.stderr or added.stdout).strip()
            raise ApplyError(f"error: git add failed: {detail}")
        committed = git_cmd(
            repo,
            ["commit", "-m", item.message],
            env={
                "GIT_AUTHOR_DATE": item.author_date,
                "GIT_COMMITTER_DATE": item.author_date,
            },
        )
        if committed.returncode != 0:
            detail = (committed.stderr or committed.stdout).strip()
            raise ApplyError(f"error: git commit failed: {detail}")
        print(f"committed {item.author_date}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="스케줄 JSON의 날짜와 설정 시간 구간으로 더미 파일을 커밋"
    )
    parser.add_argument("--schedule", required=True, help="생성기 JSON 경로")
    parser.add_argument(
        "--repo",
        default=".",
        help="git 저장소 경로 (기본: 현재 디렉터리)",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="설정 JSON 경로 (기본: 실행 파일 또는 스크립트 옆 schedule_config.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="커밋하지 않고 파일, 시각, 메시지만 출력",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="확인 질문을 건너뛰고 커밋",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        settings = load_commit_settings(Path(args.config))
        rows = load_schedule(Path(args.schedule))
        planned = build_plan(rows, settings)
        if not planned:
            print("커밋할 항목이 없습니다.", file=sys.stderr)
            return 0
        repo = ensure_repo(Path(args.repo))
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
    except ApplyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
