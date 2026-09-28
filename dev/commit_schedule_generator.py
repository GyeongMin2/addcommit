#!/usr/bin/env python3
# 가중치 기반 Git 커밋 활동일 스케줄 생성기 (stdlib only)
# - 가중치, 주말/휴일 on/off, 평일 gap, 연도별/개인 휴무는 schedule_config.json
# - 평일/주말/공휴일/명절별 활동일 확률 + 커밋 수 분포
# - --seed 로 모든 난수 결정(재현 가능)
# - 활동일만 JSON 출력 (한글 day_type)

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# 고정 공휴일: 매년 같은 월일 (대체공휴일 미포함)
# 설날, 추석, 부처님오신날, 개인 휴무는 schedule_config.json 의 dated_holidays
# ---------------------------------------------------------------------------

FIXED_HOLIDAYS: Dict[Tuple[int, int], str] = {
    (1, 1): "신정",
    (3, 1): "삼일절",
    (5, 1): "근로자의날",
    (5, 5): "어린이날",
    (6, 6): "현충일",
    (8, 15): "광복절",
    (10, 3): "개천절",
    (10, 9): "한글날",
    (12, 25): "크리스마스",
}

def app_dir() -> Path:
    # exe로 실행하면 설정 파일은 실행 파일과 같은 폴더에 둔다.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


DEFAULT_CONFIG_PATH = app_dir() / "schedule_config.json"


DayType = str  # "평일" | "주말" | "공휴일" | "명절"


@dataclass
class DayWeights:
    weekday: float = 0.72
    weekend: float = 0.18
    holiday: float = 0.22
    major_holiday: float = 0.03
    weekend_enabled: bool = True
    holiday_enabled: bool = True


@dataclass(frozen=True)
class DatedHoliday:
    start: date
    end: date
    name: str
    day_type: DayType


@dataclass
class DayInfo:
    day_type: DayType
    holiday_name: Optional[str] = None


@dataclass
class ActiveDay:
    date: date
    commits: int
    day_type: DayType
    holiday_name: Optional[str] = None

    def to_dict(self) -> dict:
        out = {
            "date": self.date.isoformat(),
            "commits": self.commits,
            "day_type": self.day_type,
        }
        if self.holiday_name:
            out["holiday_name"] = self.holiday_name
        return out


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def classify_day(d: date, dated_holidays: Sequence[DatedHoliday]) -> DayInfo:
    # 명절 구간이 있으면 그 날 유형은 명절이다.
    major_names = [
        h.name for h in dated_holidays if h.day_type == "명절" and h.start <= d <= h.end
    ]
    if major_names:
        return DayInfo("명절", "/".join(dict.fromkeys(major_names)))

    names: List[str] = []
    fixed = FIXED_HOLIDAYS.get((d.month, d.day))
    if fixed:
        names.append(fixed)

    for holiday in dated_holidays:
        if holiday.day_type != "공휴일" or not (holiday.start <= d <= holiday.end):
            continue
        if holiday.name not in names:
            names.append(holiday.name)

    if names:
        # 같은 날 겹치면 "어린이날/부처님오신날" 형태
        return DayInfo("공휴일", "/".join(names))

    if d.weekday() >= 5:  # 토=5, 일=6
        return DayInfo("주말")
    return DayInfo("평일")


def activity_weight(day_type: DayType, weights: DayWeights) -> float:
    # OFF 인 주말/휴일(공휴일, 명절)은 활성 확률 0. 강제 활성은 평일만 해당한다.
    if day_type == "주말" and not weights.weekend_enabled:
        return 0.0
    if day_type in ("공휴일", "명절") and not weights.holiday_enabled:
        return 0.0
    return {
        "평일": weights.weekday,
        "주말": weights.weekend,
        "공휴일": weights.holiday,
        "명절": weights.major_holiday,
    }[day_type]


class ConfigError(Exception):
    pass


def _parse_config_date(value: object, label: str) -> date:
    if not isinstance(value, str):
        raise ConfigError(f"error: {label} must be YYYY-MM-DD")
    try:
        return parse_date(value)
    except ValueError as exc:
        raise ConfigError(f"error: {label} must be YYYY-MM-DD") from exc


def _parse_dated_holidays(data: dict) -> List[DatedHoliday]:
    if "dated_holidays" not in data:
        raise ConfigError("error: missing config key: dated_holidays")
    raw = data["dated_holidays"]
    if not isinstance(raw, list):
        raise ConfigError("error: dated_holidays must be a list")

    holidays: List[DatedHoliday] = []
    for index, item in enumerate(raw):
        label = f"dated_holidays[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f"error: {label} must be an object")

        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"error: {label}.name must be a non-empty string")

        day_type = item.get("day_type", "공휴일")
        if day_type not in ("공휴일", "명절"):
            raise ConfigError(f"error: {label}.day_type must be 공휴일 or 명절")

        has_date = "date" in item
        has_range = "start" in item or "end" in item
        if has_date and has_range:
            raise ConfigError(f"error: {label} uses date or start/end, not both")
        if has_date:
            start = _parse_config_date(item.get("date"), f"{label}.date")
            end = start
        elif "start" in item:
            start = _parse_config_date(item.get("start"), f"{label}.start")
            if "end" in item:
                end = _parse_config_date(item.get("end"), f"{label}.end")
            else:
                end = start
        else:
            raise ConfigError(f"error: {label} needs date or start")

        if end < start:
            raise ConfigError(f"error: {label} end must be >= start")
        holidays.append(DatedHoliday(start, end, name.strip(), day_type))
    return holidays


def load_config(path: Path) -> Tuple[DayWeights, int, List[DatedHoliday]]:
    if not path.is_file():
        raise ConfigError(f"error: config file not found: {path}")

    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"error: invalid JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError("error: config root must be an object")

    weight_values: Dict[str, float] = {}
    for key in ("weekday", "weekend", "holiday", "major_holiday"):
        if key not in data:
            raise ConfigError(f"error: missing config key: {key}")
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"error: {key} must be a number between 0 and 1")
        number = float(value)
        if not 0.0 <= number <= 1.0:
            raise ConfigError(f"error: {key} must be between 0 and 1")
        weight_values[key] = number

    enabled: Dict[str, bool] = {}
    for key in ("weekend_enabled", "holiday_enabled"):
        if key not in data:
            raise ConfigError(f"error: missing config key: {key}")
        flag = data[key]
        if not isinstance(flag, bool):
            raise ConfigError(f"error: {key} must be true or false")
        enabled[key] = flag

    if "max_weekday_gap" not in data:
        raise ConfigError("error: missing config key: max_weekday_gap")
    gap = data["max_weekday_gap"]
    if isinstance(gap, bool) or not isinstance(gap, int) or gap < 0:
        raise ConfigError("error: max_weekday_gap must be an integer >= 0")

    weights = DayWeights(
        weekday=weight_values["weekday"],
        weekend=weight_values["weekend"],
        holiday=weight_values["holiday"],
        major_holiday=weight_values["major_holiday"],
        weekend_enabled=enabled["weekend_enabled"],
        holiday_enabled=enabled["holiday_enabled"],
    )
    return weights, gap, _parse_dated_holidays(data)


def commit_cap(day_type: DayType) -> int:
    return {
        "명절": 1,
        "주말": 2,
        "공휴일": 3,
        "평일": 7,
    }[day_type]


def sample_commit_count(rng: random.Random, day_type: DayType) -> int:
    # 명절: 최대 1
    # 주말: 1–2
    # 공휴일: 1–2 위주, 드물게 3
    # 평일: 1–3 위주, 가끔 4–5, 드물게 최대 7
    if day_type == "명절":
        return 1
    if day_type == "주말":
        return rng.randint(1, 2)
    if day_type == "공휴일":
        roll = rng.random()
        if roll < 0.70:
            return 1
        if roll < 0.95:
            return 2
        return 3
    # 평일
    roll = rng.random()
    if roll < 0.28:
        return 1
    if roll < 0.55:
        return 2
    if roll < 0.78:
        return 3
    if roll < 0.90:
        return 4
    if roll < 0.97:
        return 5
    if roll < 0.995:
        return 6
    return 7


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def generate_schedule(
    start: date,
    end: date,
    seed: int,
    weights: DayWeights,
    max_weekday_gap: int,
    dated_holidays: Sequence[DatedHoliday],
    target_commits: Optional[int] = None,
    target_active_days: Optional[int] = None,
    soft_retries: int = 8,
) -> List[ActiveDay]:
    """활동일 스케줄 생성.

    매일(평일 포함) 가중치 확률로 활성/휴식을 결정한다.
    --seed 가 활성 여부 + 커밋 수 난수를 모두 결정한다.
    target_* 는 soft(가벼운 스케일/재시도)로만 맞춘다.
    """
    best: List[ActiveDay] = []
    best_score = float("inf")

    for attempt in range(max(1, soft_retries)):
        rng = random.Random(seed + attempt * 9973)
        active = _generate_once(
            start, end, rng, weights, max_weekday_gap, dated_holidays
        )

        if target_active_days is not None and active:
            active = _scale_active_days(active, target_active_days, rng)
        if target_commits is not None and active:
            active = _scale_commits(active, target_commits, rng)

        score = _target_score(active, target_commits, target_active_days)
        if score < best_score:
            best_score = score
            best = active
        if score == 0:
            break

    return best


def _generate_once(
    start: date,
    end: date,
    rng: random.Random,
    weights: DayWeights,
    max_weekday_gap: int,
    dated_holidays: Sequence[DatedHoliday],
) -> List[ActiveDay]:
    active: List[ActiveDay] = []
    inactive_weekday_streak = 0

    for d in daterange(start, end):
        info = classify_day(d, dated_holidays)
        day_type = info.day_type
        w = max(0.0, min(1.0, activity_weight(day_type, weights)))

        # 평일도 가중치로 쉬는 날이 정상. gap 초과 시에만 가벼운 강제 활성.
        force = False
        if day_type == "평일" and max_weekday_gap > 0:
            if inactive_weekday_streak >= max_weekday_gap:
                force = True

        is_active = force or (rng.random() < w)

        if is_active:
            if force and day_type == "평일":
                commits = rng.randint(1, 2)
            else:
                commits = sample_commit_count(rng, day_type)
            active.append(
                ActiveDay(d, commits, day_type, holiday_name=info.holiday_name)
            )
            if day_type == "평일":
                inactive_weekday_streak = 0
        else:
            if day_type == "평일":
                inactive_weekday_streak += 1

    return active


def _scale_active_days(
    days: List[ActiveDay], target: int, rng: random.Random
) -> List[ActiveDay]:
    if target <= 0:
        return []
    if len(days) == target:
        return days
    if len(days) > target:
        return sorted(rng.sample(days, target), key=lambda x: x.date)
    return days


def _scale_commits(
    days: List[ActiveDay], target: int, rng: random.Random
) -> List[ActiveDay]:
    if not days or target <= 0:
        return days
    total = sum(d.commits for d in days)
    if total == 0 or total == target:
        return days

    ratio = target / total
    scaled: List[ActiveDay] = []
    for d in days:
        c = max(1, int(round(d.commits * ratio)))
        c = min(c, commit_cap(d.day_type))
        scaled.append(ActiveDay(d.date, c, d.day_type, d.holiday_name))

    cur = sum(d.commits for d in scaled)
    guard = 0
    while cur < target and guard < 500:
        candidates = [d for d in scaled if d.commits < commit_cap(d.day_type)]
        if not candidates:
            break
        pick = rng.choice(candidates)
        pick.commits += 1
        cur += 1
        guard += 1
    while cur > target and guard < 1000:
        candidates = [d for d in scaled if d.commits > 1]
        if not candidates:
            break
        pick = rng.choice(candidates)
        pick.commits -= 1
        cur -= 1
        guard += 1

    return scaled


def _target_score(
    days: List[ActiveDay],
    target_commits: Optional[int],
    target_active_days: Optional[int],
) -> float:
    score = 0.0
    if target_commits is not None:
        score += abs(sum(d.commits for d in days) - target_commits)
    if target_active_days is not None:
        score += abs(len(days) - target_active_days) * 2.0
    return score


def summarize(days: List[ActiveDay]) -> dict:
    by_type: Dict[str, dict] = {}
    for dt in ("평일", "주말", "공휴일", "명절"):
        subset = [d for d in days if d.day_type == dt]
        by_type[dt] = {
            "active_days": len(subset),
            "commits": sum(d.commits for d in subset),
        }
    return {
        "total_commits": sum(d.commits for d in days),
        "active_days": len(days),
        "by_day_type": by_type,
        "date_range": {
            "first": days[0].date.isoformat() if days else None,
            "last": days[-1].date.isoformat() if days else None,
        },
    }


def print_summary(summary: dict, file=sys.stderr) -> None:
    print("=== Commit Schedule Summary ===", file=file)
    print(f"total_commits : {summary['total_commits']}", file=file)
    print(f"active_days   : {summary['active_days']}", file=file)
    dr = summary["date_range"]
    print(f"first / last  : {dr['first']} / {dr['last']}", file=file)
    print("breakdown:", file=file)
    for dt, info in summary["by_day_type"].items():
        print(
            f"  {dt:6s} days={info['active_days']:3d}  commits={info['commits']:4d}",
            file=file,
        )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="가중치 랜덤 Git 커밋 활동일 스케줄 생성기 (한국 공휴일 반영)"
    )
    p.add_argument("--start", default="2025-07-14", help="시작일 YYYY-MM-DD")
    p.add_argument("--end", default="2025-10-08", help="종료일 YYYY-MM-DD")
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="난수 시드(활성 여부 + 커밋 수 모두 이 시드로 결정)",
    )
    p.add_argument("--target-commits", type=int, default=None, help="총 커밋 soft target")
    p.add_argument(
        "--target-active-days", type=int, default=None, help="활동일 soft target"
    )
    p.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="가중치 설정 JSON 경로 (기본: 실행 파일 또는 스크립트 옆 schedule_config.json)",
    )
    p.add_argument(
        "--json-out",
        default=None,
        help="JSON 파일 경로 (미지정 시 stdout에 JSON)",
    )
    p.add_argument(
        "--no-summary",
        action="store_true",
        help="요약 출력 생략",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    start = parse_date(args.start)
    end = parse_date(args.end)
    if end < start:
        print("error: --end must be >= --start", file=sys.stderr)
        return 2

    try:
        weights, max_weekday_gap, dated_holidays = load_config(Path(args.config))
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    schedule = generate_schedule(
        start=start,
        end=end,
        seed=args.seed,
        weights=weights,
        max_weekday_gap=max_weekday_gap,
        dated_holidays=dated_holidays,
        target_commits=args.target_commits,
        target_active_days=args.target_active_days,
    )

    payload = [d.to_dict() for d in schedule]
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)

    if not args.no_summary:
        summary = summarize(schedule)
        out = sys.stdout if args.json_out else sys.stderr
        print_summary(summary, file=out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
