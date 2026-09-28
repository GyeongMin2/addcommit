# addcommit

기간을 정하면 평일, 주말, 공휴일, 명절 가중치로 활동일을 뽑고, 그 날짜의 시간 구간에 맞춰 더미 파일을 `git add`와 `git commit`하는 도구입니다. push는 하지 않습니다.

## 폴더

| 폴더 | 내용 |
| --- | --- |
| `app` | Python 없이 실행하는 파일. `addcommit.exe`와 `schedule_config.json` |
| `dev` | 개발용 파이썬 소스와 설정 원본, 실행 파일을 다시 만드는 `build_exe.bat` |

exe는 `app\schedule_config.json`을 읽습니다. 휴일이나 시간 구간을 바꿀 때는 이 파일을 수정합니다. `dev\build_exe.bat`는 빌드할 때 `dev\schedule_config.json`을 `app` 쪽으로 덮어씁니다. 설정을 유지하려면 `dev` 쪽 설정을 먼저 고치고 빌드하거나, 빌드 뒤에 `app` 설정을 다시 맞춥니다.

## 필요한 것

- 커밋할 폴더는 이미 git 저장소여야 합니다. 이 도구는 `git init`을 하지 않습니다.
- Git 사용자 이름과 이메일이 그 PC에 설정되어 있어야 커밋이 됩니다.
- 작업 트리에 커밋되지 않은 변경이 있으면 중단합니다. 다른 수정과 더미 커밋이 섞이지 않게 하기 위해서입니다.
- `app\addcommit.exe`는 Python이 없어도 실행됩니다. Git은 설치되어 있어야 합니다.
- `dev` 스크립트를 직접 실행할 때만 Python 3이 필요합니다.

## exe 사용법

`app\addcommit.exe`를 실행합니다.

1. 대상 폴더 경로를 입력합니다. 저장소 폴더를 exe 위로 끌어다 놓아도 경로가 들어갑니다.
2. 시작일과 종료일을 `YYYY-MM-DD`로 입력합니다. 엔터만 누르면 기본값은 `2025-07-14`, `2025-10-08`입니다.
3. 활동일 수와 총 커밋 수 요약을 확인합니다.
4. `y`를 입력하면 커밋합니다. 그 외 입력은 취소입니다.

커밋은 이른 날짜부터 현재 브랜치 끝에 쌓입니다. 작성 시각만 스케줄 시각으로 들어갑니다. 끝나면 직접 push하면 됩니다.

명령으로 실행할 수도 있습니다.

```text
app\addcommit.exe --target C:\path\to\repo --start 2025-07-14 --end 2025-10-08 --dry-run
app\addcommit.exe --target C:\path\to\repo --start 2025-07-14 --end 2025-10-08 --yes
```

| 옵션 | 설명 |
| --- | --- |
| `대상 폴더` 또는 `--target` | 커밋을 넣을 git 저장소 |
| `--start`, `--end` | 기간. 없으면 실행 중 질문합니다. |
| `--seed` | 활동일 난수 시드. 기본값 `42`. 같은 시드와 설정이면 같은 스케줄이 나옵니다. |
| `--config` | 설정 JSON 경로. 없으면 exe 옆 `schedule_config.json` |
| `--dry-run` | 커밋하지 않고 날짜, 시각, 메시지만 출력 |
| `--yes` | 확인 질문 없이 커밋 |

## 커밋이 만들어지는 방식

같은 날 커밋은 `commit.window_start`와 `commit.window_end` 사이에 두고, 앞 커밋이 뒤 커밋보다 항상 이릅니다. 커밋이 1개면 시작 시각입니다. 2개 이상이면 시작 시각부터 끝 시각까지 균등하게 나눕니다.

예: `18:00`에서 `23:00`까지 커밋 3개면 `18:00:00`, `20:30:00`, `23:00:00`입니다.

더미 파일은 저장소 안의 `commit.dummy_file` 하나입니다. 기본값은 `activity.log`입니다. 커밋마다 아래 한 줄을 추가합니다.

```text
2025-07-14 18:00:00 1
```

마지막 숫자는 그 날짜 안에서의 순번입니다. 파일이 없으면 만들고, 상위 폴더도 만듭니다.

## 설정 파일

`schedule_config.json` 예:

```json
{
  "weekday": 0.72,
  "weekend": 0.18,
  "holiday": 0.22,
  "major_holiday": 0.03,
  "weekend_enabled": true,
  "holiday_enabled": true,
  "max_weekday_gap": 4,
  "dated_holidays": [],
  "commit": {
    "window_start": "18:00",
    "window_end": "23:00",
    "timezone": "+09:00",
    "dummy_file": "activity.log",
    "message": "chore: activity {date} {time}"
  }
}
```

### 활동일 확률

값은 `0` 이상 `1` 이하입니다. 그 날 유형이 활동일로 뽑힐 확률입니다.

| 키 | 기본값 | 의미 |
| --- | --- | --- |
| `weekday` | `0.72` | 평일 |
| `weekend` | `0.18` | 토요일, 일요일 |
| `holiday` | `0.22` | 공휴일과 `dated_holidays`의 공휴일 |
| `major_holiday` | `0.03` | 설날, 추석처럼 `day_type`이 명절인 날 |

`weekend_enabled`가 `false`이면 주말은 커밋하지 않습니다. `holiday_enabled`가 `false`이면 공휴일과 명절을 모두 커밋하지 않습니다.

`max_weekday_gap`은 연속으로 쉬는 평일 상한입니다. 기본값 `4`이면 평일을 4일 연속 쉰 다음 평일은 커밋 1개 또는 2개로 넣습니다. `0`이면 이 강제 활성을 쓰지 않습니다. 주말과 휴일에는 적용하지 않습니다.

활동일의 커밋 개수는 대략 다음 범위입니다.

- 평일: 대부분 1개에서 3개, 가끔 더 많고 최대 7개
- 주말: 1개 또는 2개
- 공휴일: 대부분 1개 또는 2개, 드물게 3개
- 명절: 1개

### 날짜별 휴일

쉬고 싶은 날, 설날, 추석, 부처님오신날은 `dated_holidays`에 추가합니다. 목록에 없는 해는 아래 고정 공휴일과 주말, 평일만 계산합니다.

매년 같은 날로 코드에 들어 있는 고정 공휴일:

- 1월 1일 신정
- 3월 1일 삼일절
- 5월 1일 근로자의날
- 5월 5일 어린이날
- 6월 6일 현충일
- 8월 15일 광복절
- 10월 3일 개천절
- 10월 9일 한글날
- 12월 25일 크리스마스

하루만 쉴 때:

```json
{"date": "2027-04-01", "name": "개인휴무"}
```

`day_type`을 생략하면 공휴일입니다. 공휴일 확률(`holiday`)을 사용합니다.

여러 날:

```json
{"start": "2027-08-02", "end": "2027-08-06", "name": "여름휴가"}
```

명절로 두고 활동 확률을 더 낮출 때:

```json
{"start": "2027-02-06", "end": "2027-02-08", "name": "설날", "day_type": "명절"}
```

`day_type`은 `공휴일` 또는 `명절`만 가능합니다. `date`와 `start`, `end`를 한 항목에 같이 적으면 오류입니다. `end`는 `start`와 같거나 그 이후여야 합니다.

같은 날이 고정 공휴일과 겹치면 이름이 `어린이날/부처님오신날`처럼 붙습니다. 명절 구간으로 지정한 날은 공휴일보다 우선합니다.

### 커밋 시간

| 키 | 기본값 | 의미 |
| --- | --- | --- |
| `window_start` | `18:00` | 하루 커밋 시작. `HH:MM` |
| `window_end` | `23:00` | 하루 커밋 끝. 시작보다 뒤여야 합니다. |
| `timezone` | `+09:00` | 커밋 시각의 시간대 |
| `dummy_file` | `activity.log` | 저장소 안의 상대 경로. 상위 폴더(`..`)와 절대 경로는 사용할 수 없습니다. |
| `message` | `chore: activity {date} {time}` | 커밋 메시지. `{date}`, `{time}`, `{index}`를 넣을 수 있습니다. |

구간이 너무 짧아서 커밋 시각이 끝 시각을 넘어가면 커밋을 시작하지 않고 오류로 멈춥니다.

## 개발용 명령

`dev` 폴더에서 실행합니다.

스케줄만 JSON으로 저장:

```text
python commit_schedule_generator.py --start 2025-07-14 --end 2025-10-08 --seed 42 --json-out schedule.json --no-summary
```

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--start`, `--end` | `2025-07-14`, `2025-10-08` | 기간 |
| `--seed` | `42` | 난수 시드 |
| `--target-commits` | 없음 | 총 커밋 수에 맞추려는 느슨한 목표 |
| `--target-active-days` | 없음 | 활동일 수에 맞추려는 느슨한 목표 |
| `--config` | `dev\schedule_config.json` | 설정 파일 |
| `--json-out` | 없음 | 지정하면 그 파일에 JSON을 쓰고, 요약은 화면으로 출력 |
| `--no-summary` | 꺼짐 | 요약 생략 |

저장된 스케줄로 커밋:

```text
python commit_schedule_apply.py --schedule schedule.json --repo C:\path\to\repo --dry-run
python commit_schedule_apply.py --schedule schedule.json --repo C:\path\to\repo
```

| 옵션 | 기본값 | 설명 |
| --- | --- | --- |
| `--schedule` | 필수 | 생성기가 만든 JSON |
| `--repo` | 현재 폴더 | 대상 git 저장소 |
| `--config` | `dev\schedule_config.json` | 설정 파일 |
| `--dry-run` | 꺼짐 | 계획만 출력 |
| `--yes` | 꺼짐 | 확인 없이 커밋 |

생성과 커밋을 한 번에:

```text
python addcommit_app.py --target C:\path\to\repo --start 2025-07-14 --end 2025-10-08 --dry-run
```

소스를 고친 뒤 exe를 다시 만들 때:

```text
dev\build_exe.bat
```

Python과 PyInstaller가 필요합니다. 결과물은 `app\addcommit.exe`입니다.
