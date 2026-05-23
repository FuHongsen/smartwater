"""
actions.py - 农业灌溉动作执行器

本模块封装了与 HomeAssistant 进行交互的具体动作，
使得 LLM 决策引擎可以像调用函数一样控制喷灌阀门、
设置灌溉模式、暂停灌溉并记录决策日志。

依赖：requests (通过 HomeAssistant REST API 通信)
使用前提：需在 HomeAssistant 中创建长期访问令牌，并配置对应实体。
"""

import logging
import requests
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class HAActionClient:
    """
    通过 HomeAssistant REST API 执行设备控制动作的客户端。

    实体命名约定（需在 HA 中预先创建）：
    - 喷灌阀门: switch.{area}_valve
    - 灌溉模式选择: input_select.{area}_mode
    - 灌溉暂停标记: input_boolean.{area}_irrigation_hold
    - 暂停计时器: timer.{area}_irrigation_hold_timer
    - 低功耗模式标记: input_boolean.low_power_mode
    - 4G 通讯开关: switch.irrigator_4g_module
    """

    def __init__(self, ha_url: str, ha_token: str, verify_ssl: bool = True):
        """
        初始化 HA 动作客户端。

        Args:
            ha_url: HomeAssistant 实例的基础地址，例如 'http://192.168.1.100:8123'
            ha_token: 长期访问令牌 (Long-Lived Access Token)
            verify_ssl: 是否验证 SSL 证书，本地测试可设为 False
        """
        self.base_url = ha_url.rstrip('/')
        self.headers = {
            "Authorization": f"Bearer {ha_token}",
            "Content-Type": "application/json",
        }
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    # ------------------------------------------------------------------
    # 底层 API 调用封装
    # ------------------------------------------------------------------
    def _call_service(self, domain: str, service: str, entity_id: str,
                      service_data: Optional[Dict[str, Any]] = None):
        """
        调用 HomeAssistant 的服务 API。

        Args:
            domain: 服务域，如 'switch', 'timer', 'input_boolean'
            service: 服务名称，如 'turn_on', 'start'
            entity_id: 目标实体 ID
            service_data: 额外的服务参数，例如持续时间
        """
        url = f"{self.base_url}/api/services/{domain}/{service}"
        payload = {"entity_id": entity_id}
        if service_data:
            payload.update(service_data)

        try:
            resp = self.session.post(url, json=payload, verify=self.verify_ssl)
            resp.raise_for_status()
            logger.info(f"HA 服务调用成功: {domain}.{service} -> {entity_id}")
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"调用 HA 服务失败: {e}")
            raise

    def get_state(self, entity_id: str) -> Optional[str]:
        """
        获取指定实体的当前状态。

        Args:
            entity_id: 实体 ID，如 'sensor.soil_moisture_tomato'

        Returns:
            实体状态值（字符串），失败返回 None
        """
        url = f"{self.base_url}/api/states/{entity_id}"
        try:
            resp = self.session.get(url, verify=self.verify_ssl)
            resp.raise_for_status()
            return resp.json().get("state")
        except requests.exceptions.RequestException as e:
            logger.error(f"获取状态失败 {entity_id}: {e}")
            return None

    # ------------------------------------------------------------------
    # 阀门直接控制
    # ------------------------------------------------------------------
    def turn_valve_on(self, area: str):
        """
        打开指定地块的喷灌阀门。

        Args:
            area: 地块标识，如 'tomato_field'
                  对应实体 switch.{area}_valve
        """
        entity_id = f"switch.{area}_valve"
        self._call_service("switch", "turn_on", entity_id)
        logger.info(f"灌溉阀门已开启: {area}")

    def turn_valve_off(self, area: str):
        """
        关闭指定地块的喷灌阀门。

        Args:
            area: 地块标识
        """
        entity_id = f"switch.{area}_valve"
        self._call_service("switch", "turn_off", entity_id)
        logger.info(f"灌溉阀门已关闭: {area}")

    # ------------------------------------------------------------------
    # 灌溉策略与模式管理
    # ------------------------------------------------------------------
    def set_irrigation_mode(self, area: str, mode: str):
        """
        切换灌溉模式（如 'normal', 'eco'）。

        通过 input_select 实体记录当前模式，供自动化规则读取。
        需在 HA 中预先创建 input_select.{area}_mode，并定义选项。

        Args:
            area: 地块标识
            mode: 模式名称，必须在 input_select 的选项列表中
        """
        entity_id = f"input_select.{area}_mode"
        self._call_service("input_select", "select_option", entity_id,
                           service_data={"option": mode})
        logger.info(f"灌溉模式已切换: {area} -> {mode}")

    def set_hold(self, area: str, hold_minutes: int, reason: str = ""):
        """
        暂停灌溉指定时长，通常用于虫情警报、施肥后等场景。

        动作：
        1. 强制关闭阀门
        2. 打开暂停标记布尔实体
        3. 启动一个计时器，到期后可通过自动化恢复灌溉
        4. 记录暂停原因

        Args:
            area: 地块标识
            hold_minutes: 暂停时长（分钟）
            reason: 暂停原因描述，用于日志
        """
        # 立即关闭阀门
        self.turn_valve_off(area)

        # 标记进入暂停状态
        self._call_service("input_boolean", "turn_on",
                           f"input_boolean.{area}_irrigation_hold")

        # 启动倒计时定时器
        self._call_service("timer", "start",
                           f"timer.{area}_irrigation_hold_timer",
                           service_data={
                               "duration": f"00:{hold_minutes:02d}:00"
                           })
        logger.info(f"{area} 灌溉暂停 {hold_minutes} 分钟，原因: {reason}")

    def release_hold(self, area: str):
        """
        手动解除灌溉暂停状态。

        注意：通常由自动化在计时器结束后自动调用，
        但也可由 LLM 决策主动解除。
        """
        self._call_service("input_boolean", "turn_off",
                           f"input_boolean.{area}_irrigation_hold")
        logger.info(f"{area} 灌溉暂停已解除")

    # ------------------------------------------------------------------
    # 能源管理相关
    # ------------------------------------------------------------------
    def enable_low_power_mode(self):
        """
        进入低功耗模式：打开低功耗标记、关闭 4G 数据模块。
        """
        self._call_service("input_boolean", "turn_on", "input_boolean.low_power_mode")
        self._call_service("switch", "turn_off", "switch.irrigator_4g_module")
        logger.info("已进入低功耗模式")

    def disable_low_power_mode(self):
        """
        退出低功耗模式：关闭低功耗标记、重新开启 4G 数据模块。
        """
        self._call_service("input_boolean", "turn_off", "input_boolean.low_power_mode")
        self._call_service("switch", "turn_on", "switch.irrigator_4g_module")
        logger.info("已退出低功耗模式，恢复正常运行")

    # ------------------------------------------------------------------
    # 日志与通知
    # ------------------------------------------------------------------
    def log_decision(self, area: str, message: str):
        """
        将 LLM 的决策理由记录到 HA 的持久化通知中，
        方便用户在 UI 中回溯灌溉决策历史。

        Args:
            area: 地块标识
            message: 决策理由或摘要
        """
        self._call_service("persistent_notification", "create", "irrigation_log",
                           service_data={
                               "title": f"LLM 灌溉决策 - {area}",
                               "message": message,
                           })
        logger.info(f"决策日志 [{area}]: {message}")

    # ------------------------------------------------------------------
    # 批量传感器数据采集
    # ------------------------------------------------------------------
    def get_sensor_context(self, sensors: list) -> Dict[str, Optional[str]]:
        """
        批量获取多个传感器的当前状态，用于喂给 LLM 作为上下文。

        Args:
            sensors: 实体 ID 列表，如 ['sensor.soil_moisture_tomato', 'weather.openweathermap']

        Returns:
            字典，键为实体 ID，值为状态字符串（失败为 None）
        """
        context = {}
        for entity in sensors:
            state = self.get_state(entity)
            context[entity] = state
        return context
