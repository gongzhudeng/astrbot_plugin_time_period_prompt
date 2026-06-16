from datetime import datetime, date, time, timedelta

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.provider.entities import ProviderRequest


@register(
    "灵犀 · 陪伴节律助手",
    "灵犀",
    "让 AI 根据工作、休息、日期时间和生活节律调整陪伴方式",
    "2.9.0",
    "https://github.com/gongzhudeng/astrbot_plugin_time_period_prompt",
)
class CompanionRhythmPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    def debug_log(self, message: str):
        if self.config.get("debug_enabled", False):
            logger.info(f"[陪伴节律助手] {message}")

    def compact_text(self, text: str) -> str:
        text = str(text or "").strip()
        replacements = {
            "当前日期时间：": "时间：",
            "当前日期：": "日期：",
            "当前月份：": "月份：",
            "当前日期范围：": "日期：",
            "今日附加提示：": "今日：",
            "时段交接提示：": "交接：",
            "当前时段：": "时段：",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        while "时段：时段：" in text:
            text = text.replace("时段：时段：", "时段：")
        text = text.replace(" - ", "-")
        text = text.replace(" 到 ", "-")
        text = text.replace("次日 ", "次日")
        return text.strip()

    def parse_time(self, text: str):
        try:
            hour, minute = str(text).strip().split(":")
            return time(int(hour), int(minute))
        except Exception:
            return None

    def parse_time_range(self, text: str):
        try:
            text = str(text).strip()
            text = text.replace("－", "-").replace("—", "-")
            text = text.replace("~", "-").replace("～", "-").replace("到", "-")
            if "-" not in text:
                return None, None
            start_text, end_text = text.split("-", 1)
            return self.parse_time(start_text), self.parse_time(end_text)
        except Exception:
            return None, None

    def time_to_minutes(self, value: time) -> int:
        return value.hour * 60 + value.minute

    def is_now_in_range(self, now_time: time, start_time: time, end_time: time) -> bool:
        if start_time is None or end_time is None:
            return False
        if start_time <= end_time:
            return start_time <= now_time < end_time
        return now_time >= start_time or now_time < end_time

    def get_range_progress(self, now_time: time, start_time: time, end_time: time):
        if start_time is None or end_time is None:
            return None, None
        now_minutes = self.time_to_minutes(now_time)
        start_minutes = self.time_to_minutes(start_time)
        end_minutes = self.time_to_minutes(end_time)
        duration = (end_minutes - start_minutes) % 1440
        if duration == 0:
            duration = 1440
        elapsed = (now_minutes - start_minutes) % 1440
        remaining = duration - elapsed
        return elapsed, remaining

    def parse_days(self, text: str):
        try:
            text = str(text).strip()
            if not text or text == "*":
                return set(range(1, 8))
            text = text.replace("，", ",")
            result = set()
            for part in text.split(","):
                part = part.strip()
                if not part:
                    continue
                if "-" in part:
                    start_text, end_text = part.split("-", 1)
                    start = int(start_text.strip())
                    end = int(end_text.strip())
                    if start <= end:
                        day_range = range(start, end + 1)
                    else:
                        day_range = list(range(start, 8)) + list(range(1, end + 1))
                    for day in day_range:
                        if 1 <= day <= 7:
                            result.add(day)
                else:
                    day = int(part)
                    if 1 <= day <= 7:
                        result.add(day)
            return result
        except Exception:
            return set()

    def parse_date(self, text: str):
        try:
            return datetime.strptime(str(text).strip(), "%Y-%m-%d").date()
        except Exception:
            return None

    def normalize_date_list(self, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = value.replace("，", ",")
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    def is_date_in_list(self, today: date, value) -> bool:
        for item in self.normalize_date_list(value):
            if self.parse_date(item) == today:
                return True
        return False

    def get_saturday_of_week(self, today: date) -> date:
        return today + timedelta(days=(5 - today.weekday()))

    def is_big_week_saturday_work(self, target_date: date) -> bool:
        base_date = self.parse_date(self.config.get("big_week_base_saturday", ""))
        base_type = self.config.get("big_week_base_type", "基准周六上班")
        if base_date is None:
            logger.warning("大小周基准周六日期格式错误，请填写 YYYY-MM-DD")
            return False
        diff_days = (target_date - base_date).days
        week_offset = diff_days // 7
        same_as_base = week_offset % 2 == 0
        base_is_work = base_type in ["基准周六上班", "work"]
        return same_as_base if base_is_work else not same_as_base

    def get_big_small_week_text(self, today: date) -> str:
        saturday = self.get_saturday_of_week(today)
        is_work = self.is_big_week_saturday_work(saturday)
        return "大周，本周六上班" if is_work else "小周，本周六休息"

    def get_auto_day_type(self, now: datetime) -> str:
        today = now.date()
        weekday = now.weekday() + 1

        if self.is_date_in_list(today, self.config.get("temp_rest_dates", [])):
            return "rest"
        if self.is_date_in_list(today, self.config.get("temp_work_dates", [])):
            return "work"

        work_mode = self.config.get("work_mode", "单休")

        if work_mode in ["双休", "double_rest"]:
            return "work" if weekday in range(1, 6) else "rest"
        if work_mode in ["单休", "single_rest"]:
            return "work" if weekday in range(1, 7) else "rest"
        if work_mode in ["无休", "no_rest"]:
            return "work"
        if work_mode in ["自定义", "custom"]:
            custom_days = self.parse_days(self.config.get("custom_work_days", "1-5"))
            return "work" if weekday in custom_days else "rest"
        if work_mode in ["大小周", "big_small_week"]:
            if weekday in range(1, 6):
                return "work"
            if weekday == 7:
                return "rest"
            return "work" if self.is_big_week_saturday_work(today) else "rest"

        return "work"

    def get_day_type(self, now: datetime) -> str:
        override = self.config.get("today_override", "自动判断")
        if override in ["强制工作日", "force_work"]:
            return "work"
        if override in ["强制休息日", "force_rest"]:
            return "rest"
        return self.get_auto_day_type(now)

    def get_status_prompt(self, day_type: str) -> str:
        if day_type == "rest":
            return self.compact_text(self.config.get("rest_day_status_prompt", ""))
        return self.compact_text(self.config.get("work_day_status_prompt", ""))

    def get_datetime_prompt(self, now: datetime) -> str:
        mode = self.config.get("datetime_prompt_mode", "")
        if not mode:
            mode = self.config.get("date_prompt_mode", "关闭")

        if mode in ["关闭", "off", ""]:
            return ""

        year = now.year
        month = now.month
        day = now.day
        hour = now.hour
        minute = now.minute

        if mode in ["年月日", "date"]:
            return f"日期：{year}-{month:02d}-{day:02d}"
        if mode in ["年月", "month"]:
            return f"月份：{year}-{month:02d}"
        if mode in ["月初中下旬", "month_period"]:
            if day <= 10:
                period = "上旬"
            elif day <= 20:
                period = "中旬"
            else:
                period = "下旬"
            return f"日期：{year}-{month:02d}{period}"
        if mode in ["仅时间", "time"]:
            return f"时间：{hour:02d}:{minute:02d}"
        if mode in ["日期和时间", "datetime"]:
            return f"时间：{year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}"

        return ""

    def is_extra_prompt_active(self, now: datetime) -> bool:
        if not self.config.get("extra_prompt_enabled", False):
            return False
        extra_prompt = str(self.config.get("extra_prompt", "")).strip()
        if not extra_prompt:
            return False
        expire_date_text = str(self.config.get("extra_prompt_expire_date", "")).strip()
        if not expire_date_text:
            return True
        expire_date = self.parse_date(expire_date_text)
        if expire_date is None:
            logger.warning("今日附加提示到期日期格式错误，请填写 YYYY-MM-DD")
            return True
        return now.date() <= expire_date

    def get_extra_prompt(self, now: datetime) -> str:
        if not self.is_extra_prompt_active(now):
            return ""
        return self.compact_text(self.config.get("extra_prompt", ""))

    def render_text(self, text: str, day_type: str, status_prompt: str) -> str:
        day_type_text = "工作日" if day_type == "work" else "休息日"
        result = str(text or "").replace("{day_type}", day_type_text)
        result = result.replace("{day_status}", status_prompt)
        return self.compact_text(result)

    def get_transition_prompt(self, rule, elapsed: int, remaining: int) -> str:
        if not self.config.get("transition_enabled", True):
            return ""
        try:
            transition_minutes = int(self.config.get("transition_minutes", 10))
        except Exception:
            transition_minutes = 10
        if transition_minutes <= 0:
            return ""

        shared_prompt = str(rule.get("transition_prompt", "")).strip()
        enter_prompt = str(rule.get("enter_transition_prompt", "")).strip()
        leave_prompt = str(rule.get("leave_transition_prompt", "")).strip()

        if elapsed is not None and elapsed < transition_minutes:
            return enter_prompt or shared_prompt
        if remaining is not None and 0 < remaining <= transition_minutes:
            return leave_prompt or shared_prompt
        return ""

    def find_prompt_from_rules(self, rules, now_time: time):
        for index, rule in enumerate(rules, start=1):
            try:
                time_range = str(rule.get("time_range", "")).strip()
                prompt = str(rule.get("prompt", "")).strip()

                if not time_range or not prompt:
                    continue

                start_time, end_time = self.parse_time_range(time_range)
                if start_time is None or end_time is None:
                    logger.warning(f"时间段格式错误：{time_range}")
                    continue

                if self.is_now_in_range(now_time, start_time, end_time):
                    elapsed, remaining = self.get_range_progress(now_time, start_time, end_time)
                    transition_prompt = self.get_transition_prompt(rule, elapsed, remaining)
                    return prompt, time_range, index, transition_prompt
            except Exception as e:
                logger.error(f"处理时间段规则失败：{e}")

        return "", "", 0, ""

    def get_order_names(self):
        order_text = str(self.config.get("inject_order", "")).strip()
        if not order_text:
            order_text = "状态提示,今日附加提示,日期时间提示,交接提示,时段提示词"
        order_text = order_text.replace("，", ",")
        return [item.strip() for item in order_text.split(",") if item.strip()]

    def build_final_prompt(self, components):
        alias_map = {
            "状态提示": "status",
            "工作状态": "status",
            "工作日休息日提示": "status",
            "今日附加提示": "extra",
            "今日提示": "extra",
            "今日": "extra",
            "附加提示": "extra",
            "临时提示": "extra",
            "日期时间提示": "datetime",
            "日期提示": "datetime",
            "时间提示": "datetime",
            "日期时间": "datetime",
            "当前时间": "datetime",
            "交接提示": "transition",
            "交接": "transition",
            "模糊区间提示": "transition",
            "切换提示": "transition",
            "时段提示词": "period",
            "时段提示": "period",
            "时段": "period",
            "时间段提示": "period",
        }

        parts = []
        used_keys = set()

        for name in self.get_order_names():
            key = alias_map.get(name)
            if not key:
                continue
            value = components.get(key, "")
            if value:
                parts.append(value)
                used_keys.add(key)

        for key in ["status", "extra", "datetime", "transition", "period"]:
            if key not in used_keys and components.get(key):
                parts.append(components[key])

        return "\n".join(parts).strip()

    def get_current_context(self):
        now = datetime.now()
        now_time = now.time()

        day_type = self.get_day_type(now)
        status_prompt = self.get_status_prompt(day_type)
        datetime_prompt = self.get_datetime_prompt(now)
        extra_prompt = self.get_extra_prompt(now)

        if day_type == "rest":
            rules = self.config.get("rest_time_rules", [])
            default_prompt = str(self.config.get("rest_default_prompt", "")).strip()
            rule_group = "休息日时间段规则"
        else:
            rules = self.config.get("work_time_rules", [])
            default_prompt = str(self.config.get("work_default_prompt", "")).strip()
            rule_group = "工作日时间段规则"

        prompt, matched_range, matched_index, transition_prompt = self.find_prompt_from_rules(
            rules, now_time
        )

        used_default = False
        if not prompt:
            prompt = default_prompt
            used_default = bool(default_prompt)
            transition_prompt = ""

        period_prompt = self.render_text(prompt, day_type, status_prompt) if prompt else ""
        transition_prompt = self.render_text(transition_prompt, day_type, status_prompt) if transition_prompt else ""

        components = {
            "status": status_prompt,
            "extra": f"今日：{extra_prompt}" if extra_prompt else "",
            "datetime": datetime_prompt,
            "transition": f"交接：{transition_prompt}" if transition_prompt else "",
            "period": period_prompt,
        }

        final_prompt = self.build_final_prompt(components)

        return {
            "now": now,
            "day_type": day_type,
            "status_prompt": status_prompt,
            "datetime_prompt": datetime_prompt,
            "extra_prompt": extra_prompt,
            "transition_prompt": transition_prompt,
            "rule_group": rule_group,
            "matched_range": matched_range,
            "matched_index": matched_index,
            "used_default": used_default,
            "final_prompt": final_prompt,
        }

    def get_current_prompt(self) -> str:
        return self.get_current_context()["final_prompt"]

    @filter.on_llm_request(priority=-1)
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        if not self.config.get("enabled", True):
            return

        try:
            context = self.get_current_context()
            current_prompt = context["final_prompt"]

            if not current_prompt:
                self.debug_log("未匹配到提示词，本次不注入。")
                return

            today_schedule = getattr(self.context, "_busy_schedule_today_schedule", "")
            if today_schedule:
                current_prompt = current_prompt.replace("{today_schedule}", today_schedule)

            inject_text = f"[节律：{current_prompt}]"
            old_prompt = (req.prompt or "").strip()
            req.prompt = f"{old_prompt}\n\n{inject_text}".strip()

            day_type_text = "工作日" if context["day_type"] == "work" else "休息日"
            matched_text = (
                f"第 {context['matched_index']} 条，{context['matched_range']}"
                if context["matched_index"]
                else "默认提示词"
            )
            self.debug_log(
                f"今日判断：{day_type_text}；规则组：{context['rule_group']}；"
                f"命中：{matched_text}；日期时间提示：{context['datetime_prompt'] or '无'}；"
                f"交接提示：{context['transition_prompt'] or '无'}；"
                f"注入内容：{current_prompt}"
            )
        except Exception as e:
            logger.error(f"陪伴节律助手注入失败：{e}")

    @filter.command("节律状态")
    async def rhythm_status(self, event: AstrMessageEvent):
        """查看当前节律状态：今日判断、命中规则、注入内容等完整信息。"""
        context = self.get_current_context()
        now = context["now"]

        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday_text = weekday_names[now.weekday()]

        work_mode = self.config.get("work_mode", "单休")
        override = self.config.get("today_override", "自动判断")
        day_type_text = "工作日" if context["day_type"] == "work" else "休息日"

        lines = [
            "节律状态",
            f"日期：{now.strftime('%Y-%m-%d')} {weekday_text}",
            f"时间：{now.strftime('%H:%M')}",
            f"工作制度：{work_mode}",
            f"今日锁定：{override}",
            f"今日判断：{day_type_text}",
        ]

        if work_mode in ["大小周", "big_small_week"]:
            lines.append(f"大小周：{self.get_big_small_week_text(now.date())}")
            lines.append(f"基准周六：{self.config.get('big_week_base_saturday', '') or '未填写'}")
            lines.append(f"基准类型：{self.config.get('big_week_base_type', '基准周六上班')}")

        if self.is_date_in_list(now.date(), self.config.get("temp_rest_dates", [])):
            lines.append("临时日期：今天在临时休息日列表中")
        if self.is_date_in_list(now.date(), self.config.get("temp_work_dates", [])):
            lines.append("临时日期：今天在临时工作日列表中")

        lines.append(f"规则组：{context['rule_group']}")

        if context["matched_index"]:
            lines.append(f"命中规则：第 {context['matched_index']} 条")
            lines.append(f"命中时段：{context['matched_range']}")
        elif context["used_default"]:
            lines.append("命中规则：默认提示词")
        else:
            lines.append("命中规则：无")

        lines.append(f"状态：{context['status_prompt'] or '空，不注入'}")
        lines.append(f"日期时间：{context['datetime_prompt'] or '关闭'}")
        lines.append(f"交接：{context['transition_prompt'] or '当前未触发'}")
        lines.append(f"今日：{context['extra_prompt'] or '未启用或为空'}")
        lines.append(f"注入顺序：{self.config.get('inject_order', '状态提示,今日附加提示,日期时间提示,交接提示,时段提示词')}")

        lines.append("")
        if context["final_prompt"]:
            lines.append("当前会注入：")
            lines.append(f"[节律：{context['final_prompt']}]")
        else:
            lines.append("当前会注入：无")

        yield event.plain_result("\n".join(lines))

    def get_message_text(self, event: AstrMessageEvent) -> str:
        for attr in ["message_str", "message_text", "raw_message"]:
            value = getattr(event, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for method in ["get_message_str", "get_plain_text"]:
            if hasattr(event, method):
                try:
                    value = getattr(event, method)()
                    if isinstance(value, str) and value.strip():
                        return value.strip()
                except Exception:
                    pass

        return ""

    def get_command_arg(self, event: AstrMessageEvent, command_name: str) -> str:
        text = self.get_message_text(event).strip()
        prefixes = [f"/{command_name}", command_name]
        for prefix in prefixes:
            if text.startswith(prefix):
                return text[len(prefix):].strip()
        return text.strip()

    def save_runtime_config(self):
        for method_name in ["save", "save_config", "save_plugin_config"]:
            method = getattr(self.config, method_name, None)
            if callable(method):
                try:
                    method()
                    return
                except Exception:
                    pass

    def set_config_values(self, values: dict):
        for key, value in values.items():
            try:
                self.config[key] = value
            except Exception:
                try:
                    self.config.set(key, value)
                except Exception:
                    logger.warning(f"配置写入失败：{key}={value}")
        self.save_runtime_config()

    def get_current_rule_list_key(self, day_type: str) -> str:
        if day_type == "rest":
            return "rest_time_rules"
        return "work_time_rules"

    def update_current_period_prompt(self, new_prompt: str):
        now = datetime.now()
        now_time = now.time()
        day_type = self.get_day_type(now)
        rule_key = self.get_current_rule_list_key(day_type)
        rules = self.config.get(rule_key, [])

        for index, rule in enumerate(rules):
            try:
                time_range = str(rule.get("time_range", "")).strip()
                if not time_range:
                    continue
                start_time, end_time = self.parse_time_range(time_range)
                if start_time is None or end_time is None:
                    continue
                if self.is_now_in_range(now_time, start_time, end_time):
                    rule["prompt"] = new_prompt
                    self.set_config_values({rule_key: rules})
                    return True, rule_key, index + 1, time_range
            except Exception as e:
                logger.error(f"修改当前时间段提示词失败：{e}")

        return False, rule_key, 0, ""

    @filter.command("节律帮助")
    async def rhythm_help(self, event: AstrMessageEvent):
        """显示所有节律命令的帮助信息。"""
        text = """节律命令：
/节律状态
查看当前判断和注入内容

/节律今日 内容
设置今日附加提示，默认今天到期

/节律风格 内容
同 /节律今日，适合临时调整今天说话风格

/节律今日清空
清空今日附加提示

/节律今日到期 2026-06-12
设置今日附加提示到期日期

/节律锁定 自动
/节律锁定 工作日
/节律锁定 休息日

/节律状态提示 工作日 内容
/节律状态提示 休息日 内容

/节律状态提示清空 工作日
/节律状态提示清空 休息日

/节律时间 关闭
/节律时间 年月日
/节律时间 年月
/节律时间 月初中下旬
/节律时间 仅时间
/节律时间 日期和时间

/节律调试 开
/节律调试 关

/节律改时段 内容
直接修改当前命中的时间段提示词"""
        yield event.plain_result(text)

    @filter.command("节律今日")
    async def set_today_extra_prompt(self, event: AstrMessageEvent):
        """设置今日附加提示，今天到期。适合临时调整，如居家办公、外出等。"""
        content = self.get_command_arg(event, "节律今日")
        if not content:
            yield event.plain_result("用法：/节律今日 今天用户居家办公，语气可以更松弛一点。")
            return
        today = datetime.now().strftime("%Y-%m-%d")
        self.set_config_values({
            "extra_prompt_enabled": True,
            "extra_prompt": content,
            "extra_prompt_expire_date": today,
        })
        yield event.plain_result(f"已设置今日附加提示，今天到期：\n{content}")

    @filter.command("节律风格")
    async def set_today_style_prompt(self, event: AstrMessageEvent):
        """设置今日风格提示（同节律今日），今天到期。适合临时调整说话风格。"""
        content = self.get_command_arg(event, "节律风格")
        if not content:
            yield event.plain_result("用法：/节律风格 今天语气更温柔一点，少催促，多陪伴。")
            return
        today = datetime.now().strftime("%Y-%m-%d")
        self.set_config_values({
            "extra_prompt_enabled": True,
            "extra_prompt": content,
            "extra_prompt_expire_date": today,
        })
        yield event.plain_result(f"已设置今日风格提示，今天到期：\n{content}")

    @filter.command("节律今日清空")
    async def clear_today_extra_prompt(self, event: AstrMessageEvent):
        """清空今日附加提示，恢复为无附加状态。"""
        self.set_config_values({
            "extra_prompt_enabled": False,
            "extra_prompt": "",
            "extra_prompt_expire_date": "",
        })
        yield event.plain_result("已清空今日附加提示。")

    @filter.command("节律今日到期")
    async def set_today_extra_expire(self, event: AstrMessageEvent):
        """设置今日附加提示的到期日期，格式：2026-06-12。"""
        content = self.get_command_arg(event, "节律今日到期")
        if not self.parse_date(content):
            yield event.plain_result("用法：/节律今日到期 2026-06-12")
            return
        self.set_config_values({"extra_prompt_expire_date": content})
        yield event.plain_result(f"已设置今日附加提示到期日期：{content}")

    @filter.command("节律锁定")
    async def set_today_override(self, event: AstrMessageEvent):
        """锁定今日状态：自动判断、强制工作日或强制休息日。"""
        content = self.get_command_arg(event, "节律锁定")
        mapping = {
            "自动": "自动判断",
            "自动判断": "自动判断",
            "工作日": "强制工作日",
            "强制工作日": "强制工作日",
            "休息日": "强制休息日",
            "强制休息日": "强制休息日",
        }
        value = mapping.get(content)
        if not value:
            yield event.plain_result("用法：/节律锁定 自动\n或：/节律锁定 工作日\n或：/节律锁定 休息日")
            return
        self.set_config_values({"today_override": value})
        yield event.plain_result(f"今日状态锁定已改为：{value}")

    @filter.command("节律状态提示")
    async def set_day_status_prompt(self, event: AstrMessageEvent):
        """设置工作日或休息日的状态提示内容。"""
        content = self.get_command_arg(event, "节律状态提示")
        if not content:
            yield event.plain_result("用法：/节律状态提示 工作日 今天用户工作压力较大，关心要轻一点。")
            return

        parts = content.split(maxsplit=1)
        if len(parts) < 2:
            yield event.plain_result("用法：/节律状态提示 工作日 内容\n或：/节律状态提示 休息日 内容")
            return

        day_type, prompt = parts[0].strip(), parts[1].strip()
        if day_type == "工作日":
            self.set_config_values({"work_day_status_prompt": prompt})
            yield event.plain_result(f"已更新工作日状态提示：\n{prompt}")
            return
        if day_type == "休息日":
            self.set_config_values({"rest_day_status_prompt": prompt})
            yield event.plain_result(f"已更新休息日状态提示：\n{prompt}")
            return

        yield event.plain_result("第一段请写：工作日 或 休息日")

    @filter.command("节律状态提示清空")
    async def clear_day_status_prompt(self, event: AstrMessageEvent):
        """清空工作日或休息日的状态提示内容。"""
        content = self.get_command_arg(event, "节律状态提示清空")
        if content == "工作日":
            self.set_config_values({"work_day_status_prompt": ""})
            yield event.plain_result("已清空工作日状态提示。")
            return
        if content == "休息日":
            self.set_config_values({"rest_day_status_prompt": ""})
            yield event.plain_result("已清空休息日状态提示。")
            return
        yield event.plain_result("用法：/节律状态提示清空 工作日\n或：/节律状态提示清空 休息日")

    @filter.command("节律时间")
    async def set_datetime_prompt_mode(self, event: AstrMessageEvent):
        """设置日期时间提示模式：关闭、年月日、年月、月初中下旬、仅时间、日期和时间。"""
        content = self.get_command_arg(event, "节律时间")
        allowed = ["关闭", "年月日", "年月", "月初中下旬", "仅时间", "日期和时间"]
        if content not in allowed:
            yield event.plain_result("用法：/节律时间 关闭\n可选：年月日、年月、月初中下旬、仅时间、日期和时间")
            return
        self.set_config_values({"datetime_prompt_mode": content})
        yield event.plain_result(f"日期时间提示模式已改为：{content}")

    @filter.command("节律调试")
    async def set_debug_enabled(self, event: AstrMessageEvent):
        """开启或关闭调试日志，方便排查配置问题。"""
        content = self.get_command_arg(event, "节律调试")
        if content in ["开", "开启", "true", "True"]:
            self.set_config_values({"debug_enabled": True})
            yield event.plain_result("调试日志已开启。")
            return
        if content in ["关", "关闭", "false", "False"]:
            self.set_config_values({"debug_enabled": False})
            yield event.plain_result("调试日志已关闭。")
            return
        yield event.plain_result("用法：/节律调试 开\n或：/节律调试 关")

    @filter.command("节律改时段")
    async def update_current_period_prompt_command(self, event: AstrMessageEvent):
        """直接修改当前正在生效的时间段提示词，立即生效。"""
        content = self.get_command_arg(event, "节律改时段")
        if not content:
            yield event.plain_result("用法：/节律改时段 时段：下班到家 19:30-21:29，用户已经回到家，语气放松自然。")
            return

        ok, rule_key, index, time_range = self.update_current_period_prompt(content)
        if not ok:
            yield event.plain_result("没有找到当前正在生效的时间段规则。\n你可以先发 /节律状态 看看当前有没有命中时间段。")
            return

        group_name = "休息日时间段规则" if rule_key == "rest_time_rules" else "工作日时间段规则"
        yield event.plain_result(
            f"已修改当前时段提示词。\n"
            f"规则组：{group_name}\n"
            f"命中规则：第 {index} 条\n"
            f"时间段：{time_range}\n"
            f"新提示词：\n{content}"
        )

    async def terminate(self):
        pass
