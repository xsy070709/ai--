from __future__ import annotations

from datetime import datetime


WEEKDAYS_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def current_time_context(now: datetime | None = None) -> dict[str, str]:
    current = now.astimezone() if now else datetime.now().astimezone()
    weekday = WEEKDAYS_ZH[current.weekday()]
    return {
        "iso": current.isoformat(timespec="seconds"),
        "date": current.date().isoformat(),
        "weekday": weekday,
        "timezone": current.tzname() or str(current.utcoffset()),
        "prompt_text": (
            f"当前真实时间：{current.isoformat(timespec='seconds')}，今天是"
            f"{current.date().isoformat()} {weekday}。"
            "所有相对时间词（今天、明天、昨天、今晚、下周）都必须以这个服务器时间为准；"
            "如果用户问现在日期或时间，不要凭模型训练记忆猜测。"
        ),
    }
