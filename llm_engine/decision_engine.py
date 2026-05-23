"""
decision_engine.py - 大语言模型灌溉决策引擎

核心流程：
1. 通过 HAActionClient 采集传感器当前状态与上下文信息
2. 组装结构化 Prompt，注入作物知识、阈值规则和当前环境数据
3. 调用 LLM 获取决策（JSON 格式）
4. 校验决策安全性后执行阀门控制、模式调整、日志记录等动作

依赖：
- llm_engine.prompts (Prompt 模板)
- llm_engine.actions.HAActionClient (硬件动作执行)
- 外部 LLM API 客户端 (需实现 LLMClient 接口)
"""

import json
import logging
import time
from typing import Dict, Any, Optional, List
from .prompts import build_irrigation_prompt  # 从 prompts.py 引入模板构建函数
from .actions import HAActionClient

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# LLM 客户端抽象接口 (示例，可替换为 Ollama、OpenAI 等)
# ----------------------------------------------------------------------
class LLMClient:
    """
    大语言模型调用的抽象基类 / 简单示例。
    实际使用中可替换为 Ollama、OpenAI API 等的具体实现。
    """
    def complete(self, prompt: str) -> str:
        """
        向 LLM 发送提示词并返回原始文本响应。

        Args:
            prompt: 完整的提示词字符串

        Returns:
            模型返回的文本
        """
        # 示例伪实现，实际应替换为真实的 API 调用
        raise NotImplementedError("请实现具体的 LLM 调用逻辑")


class OllamaClient(LLMClient):
    """基于本地 Ollama 的 LLM 客户端示例。"""
    def __init__(self, model: str = "qwen2.5:7b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    def complete(self, prompt: str) -> str:
        import requests
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",       # 要求返回 JSON 格式
        }
        try:
            resp = requests.post(url, json=payload, timeout=60)
            resp.raise_for_status()
            result = resp.json()
            return result.get("response", "")
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            return "{}"


# ----------------------------------------------------------------------
# 决策引擎核心
# ----------------------------------------------------------------------
class AgriDecisionEngine:
    """
    农业灌溉智能决策引擎。

    职责：
    - 接受地块标识与传感器列表
    - 采集实时状态
    - 构建 Prompt 并调用 LLM
    - 解析 LLM 返回的决策 JSON
    - 执行相应的灌溉控制动作并记录日志

    使用示例：
        engine = AgriDecisionEngine(ha_client, llm_client)
        engine.analyze_and_act(
            area="tomato_field",
            context_sensors=["sensor.soil_moisture_tomato", "weather.openweathermap"],
            max_duration=30
        )
    """

    # 默认安全限制常量
    DEFAULT_MAX_DURATION_MINUTES = 30   # 单次灌溉最长 30 分钟
    MIN_DURATION_MINUTES = 5            # 最短灌溉时长，避免无效开关

    def __init__(self, ha_client: HAActionClient, llm_client: LLMClient):
        """
        Args:
            ha_client: HomeAssistant 动作客户端，用于设备控制与数据读取
            llm_client: 大语言模型客户端，需实现 complete 方法
        """
        self.ha = ha_client
        self.llm = llm_client

    def analyze_and_act(self,
                        area: str,
                        context_sensors: List[str],
                        urgency: str = "normal",
                        max_duration: int = None) -> bool:
        """
        执行一次完整的“感知-决策-执行”循环。

        Args:
            area: 地块标识 (如 'tomato_field')
            context_sensors: 需要采集状态的传感器实体 ID 列表
            urgency: 紧急程度标记 ('normal' / 'high')，影响 LLM 的决策风格
            max_duration: 允许的最大单次灌溉时长（分钟），为空则使用默认值

        Returns:
            bool: 是否成功执行了阀门动作
        """
        # 1. 采集上下文数据
        context = self._gather_context(area, context_sensors)

        # 2. 构建 Prompt
        prompt = build_irrigation_prompt(
            area=area,
            context=context,
            urgency=urgency,
            max_duration=max_duration or self.DEFAULT_MAX_DURATION_MINUTES
        )

        # 3. 调用 LLM 获取决策
        logger.info(f"正在向 LLM 请求灌溉决策，地块: {area}")
        raw_response = self.llm.complete(prompt)

        # 4. 解析决策
        decision = self._parse_decision(raw_response)
        if decision is None:
            logger.error(f"LLM 返回的决策无法解析，原始响应: {raw_response}")
            return False

        # 5. 安全校验
        decision = self._validate_decision(decision, max_duration or self.DEFAULT_MAX_DURATION_MINUTES)

        # 6. 执行动作
        return self._execute_decision(area, decision)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _gather_context(self, area: str, sensors: List[str]) -> Dict[str, Any]:
        """
        采集所有需要的传感器状态，并补充地块自定义属性。

        Returns:
            字典，包含：
            - 'area': 地块标识
            - 'states': {entity_id: state_value}
            - 'crop_stage': 作物生长阶段 (从 input_select 读取)
            - 'hold_status': 是否处于暂停状态
        """
        # 批量获取传感器状态
        sensor_states = self.ha.get_sensor_context(sensors)

        # 额外读取作物阶段 (如果存在)
        crop_stage = self.ha.get_state(f"input_select.{area}_crop_stage") or "unknown"

        # 读取灌溉暂停状态
        hold_state = self.ha.get_state(f"input_boolean.{area}_irrigation_hold")
        is_hold = hold_state == "on" if hold_state else False

        # 读取当前阀门状态
        valve_state = self.ha.get_state(f"switch.{area}_valve")

        return {
            "area": area,
            "states": sensor_states,
            "crop_stage": crop_stage,
            "is_hold": is_hold,
            "valve_currently_on": valve_state == "on",
        }

    def _parse_decision(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """
        从 LLM 原始响应中提取决策 JSON。

        预期格式：
        {
            "action": "on" | "off",
            "duration_minutes": 15,
            "reason": "简短解释",
            "mode": "normal" | "eco" (可选)
        }
        """
        # 尝试直接解析 JSON
        try:
            decision = json.loads(raw_text)
            if "action" in decision:
                return decision
        except json.JSONDecodeError:
            pass

        # 如果 LLM 在 JSON 前后添加了其他文本，尝试提取首个 JSON 对象
        try:
            import re
            # 匹配第一个 {} 包裹的文本
            json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
            if json_match:
                decision = json.loads(json_match.group(0))
                if "action" in decision:
                    return decision
        except Exception:
            pass

        logger.error(f"无法从响应中提取决策 JSON: {raw_text}")
        return None

    def _validate_decision(self,
                           decision: Dict[str, Any],
                           max_duration: int) -> Dict[str, Any]:
        """
        对 LLM 输出的决策进行硬性安全校验与默认值填充。

        规则：
        - action 仅允许 'on' 或 'off'，其余均视为 'off'
        - duration_minutes 限制在 [MIN_DURATION, max_duration] 范围内
        - 若阀门当前已开启且要求打开，则跳过重复操作
        - 紧急模式下可适当放宽一些逻辑（但仍遵守物理限制）
        """
        safe_decision = {
            "action": decision.get("action", "off").lower(),
            "duration_minutes": decision.get("duration_minutes", 10),
            "reason": decision.get("reason", "LLM 未提供理由"),
            "mode": decision.get("mode", "normal"),
        }

        # 动作白名单
        if safe_decision["action"] not in ("on", "off"):
            logger.warning(f"LLM 返回无效动作 {safe_decision['action']}，强制设为 'off'")
            safe_decision["action"] = "off"

        # 灌溉时长限幅
        try:
            duration = int(safe_decision["duration_minutes"])
            duration = max(self.MIN_DURATION_MINUTES, min(duration, max_duration))
            safe_decision["duration_minutes"] = duration
        except (ValueError, TypeError):
            safe_decision["duration_minutes"] = 10

        return safe_decision

    def _execute_decision(self, area: str, decision: Dict[str, Any]) -> bool:
        """
        根据安全校验后的决策执行具体动作。

        处理逻辑：
        - action == 'on': 打开阀门，启动定时关闭（非阻塞方式）
        - action == 'off': 关闭阀门
        - 如果提供了 mode，则调用 set_irrigation_mode
        - 最后记录决策日志
        """
        action = decision["action"]
        duration = decision["duration_minutes"]
        reason = decision["reason"]
        mode = decision.get("mode", "normal")

        try:
            if action == "on":
                # 打开阀门
                self.ha.turn_valve_on(area)
                logger.info(f"{area} 开始灌溉，计划时长 {duration} 分钟")

                # 启动延时关闭（此处使用 HomeAssistant 的 timer 实体更可靠，
                # 但为了演示本地控制逻辑，此处用简单的异步线程模拟）
                self._schedule_valve_off(area, duration)

            else:  # action == 'off'
                # 关闭阀门（如果当前是开启状态）
                self.ha.turn_valve_off(area)
                logger.info(f"{area} 停止灌溉，原因: {reason}")

            # 切换灌溉模式（如果决策中有指定且不同于当前模式）
            if mode:
                current_mode = self.ha.get_state(f"input_select.{area}_mode")
                if current_mode != mode:
                    self.ha.set_irrigation_mode(area, mode)

            # 记录决策日志
            log_msg = (
                f"动作: {action.upper()} | "
                f"时长: {duration}分钟 | "
                f"模式: {mode} | "
                f"理由: {reason}"
            )
            self.ha.log_decision(area, log_msg)

            return True

        except Exception as e:
            logger.exception(f"执行决策失败: {e}")
            return False

    def _schedule_valve_off(self, area: str, delay_minutes: int):
        """
        安排延迟关闭阀门。
        生产环境中建议使用 HomeAssistant 的 timer 集成，
        或 Celery 等任务队列。此处仅为演示概念的简单实现。
        """
        def delayed_off():
            time.sleep(delay_minutes * 60)
            try:
                # 再次检查是否仍然需要关闭（可能因其他条件被手动关闭）
                current_state = self.ha.get_state(f"switch.{area}_valve")
                if current_state == "on":
                    self.ha.turn_valve_off(area)
                    logger.info(f"{area} 定时灌溉结束，自动关闭阀门")
            except Exception as e:
                logger.error(f"延迟关闭阀门失败: {e}")

        import threading
        threading.Thread(target=delayed_off, daemon=True).start()
