"""
switch.py - 智能喷灌阀门开关实体

本模块为 SmartIrrigator 集成创建一个可控制的开关实体，
代表田地里的物理喷灌阀门。用户通过 HomeAssistant 面板或自动化
即可远程开关阀门，所有底层云 API 调用均由 api.py 处理。

实体特性：
- 支持轮询状态（cloud_polling），定期向设备云同步真实阀门开/关
- 可通过 HomeAssistant 的 switch.turn_on / switch.turn_off 服务控制
- 自动记录操作日志，便于回溯
"""

import logging
from datetime import timedelta

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.helpers.event import async_track_time_interval

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

# 状态同步间隔：每 60 秒向云端查询一次阀门真实状态
SCAN_INTERVAL = timedelta(seconds=60)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """
    异步初始化开关平台。

    此函数由 HomeAssistant 在加载 smart_irrigator 集成时自动调用，
    负责创建 SmartIrrigatorSwitch 实体并将其添加到 HA 中。

    Args:
        hass: HomeAssistant 核心对象
        config: 平台配置（此处未使用）
        async_add_entities: 回调函数，用于向 HA 注册实体列表
        discovery_info: 发现信息（此处未使用）
    """
    # 从集成共享数据中获取 API 客户端和设备 ID
    if DOMAIN not in hass.data:
        _LOGGER.error("集成数据未初始化，无法创建开关实体")
        return

    api = hass.data[DOMAIN]["api"]
    device_id = hass.data[DOMAIN]["device_id"]

    # 创建开关实体并注册
    async_add_entities([SmartIrrigatorSwitch(api, device_id)], True)
    _LOGGER.debug("SmartIrrigator 开关实体已创建 (设备: %s)", device_id)


class SmartIrrigatorSwitch(SwitchEntity):
    """
    代表一个智能喷灌阀门的开关实体。
    """

    def __init__(self, api, device_id):
        """
        初始化阀门开关实体。

        Args:
            api: SmartIrrigatorAPI 实例，用于与设备云通信
            device_id: 设备唯一标识符
        """
        self._api = api
        self._device_id = device_id

        # 内部状态缓存
        self._is_on = False         # 当前阀门是否开启
        self._available = True      # 实体是否可用（通信正常）

        # 实体基本属性
        self._attr_name = f"喷灌阀门 {device_id}"
        self._attr_unique_id = f"smart_irrigator_{device_id}_valve"
        self._attr_icon = "mdi:water-pump"

        # 标记设备类型（用于 HomeAssistant 设备注册，非必须但推荐）
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
            "name": f"智能喷灌控制器 {device_id}",
            "manufacturer": "SmartIrrigator",
            "model": "Pro",
        }

    # ------------------------------------------------------------------
    # 实体属性
    # ------------------------------------------------------------------
    @property
    def is_on(self) -> bool:
        """返回阀门是否处于开启状态。"""
        return self._is_on

    @property
    def available(self) -> bool:
        """返回实体当前是否可用（能够正常通信）。"""
        return self._available

    # ------------------------------------------------------------------
    # 控制方法
    # ------------------------------------------------------------------
    async def async_turn_on(self, **kwargs):
        """通过云端 API 打开喷灌阀门。"""
        try:
            success = await self.hass.async_add_executor_job(
                self._api.set_valve, self._device_id, True
            )
            if success:
                self._is_on = True
                self._available = True
                self.async_write_ha_state()
                _LOGGER.info("阀门已开启 (设备: %s)", self._device_id)
            else:
                _LOGGER.error("开启阀门失败")
                self._available = False
        except Exception as e:
            _LOGGER.exception("开启阀门时发生异常: %s", e)
            self._available = False

    async def async_turn_off(self, **kwargs):
        """通过云端 API 关闭喷灌阀门。"""
        try:
            success = await self.hass.async_add_executor_job(
                self._api.set_valve, self._device_id, False
            )
            if success:
                self._is_on = False
                self._available = True
                self.async_write_ha_state()
                _LOGGER.info("阀门已关闭 (设备: %s)", self._device_id)
            else:
                _LOGGER.error("关闭阀门失败")
                self._available = False
        except Exception as e:
            _LOGGER.exception("关闭阀门时发生异常: %s", e)
            self._available = False

    # ------------------------------------------------------------------
    # 状态更新
    # ------------------------------------------------------------------
    async def async_update(self):
        """
        从设备云端拉取阀门真实状态，更新实体缓存。

        该方法由 HomeAssistant 按照 SCAN_INTERVAL 间隔自动调用。
        如果通信失败，则标记实体为不可用。
        """
        try:
            status = await self.hass.async_add_executor_job(
                self._api.get_device_status, self._device_id
            )
            if status is not None:
                self._is_on = status
                self._available = True
                _LOGGER.debug("状态已更新: %s", "开" if status else "关")
            else:
                _LOGGER.warning("获取设备状态失败，设备可能离线")
                self._available = False
        except Exception as e:
            _LOGGER.exception("更新状态时发生异常: %s", e)
            self._available = False

    @property
    def should_poll(self) -> bool:
        """此实体需要主动轮询状态。"""
        return True

    @property
    def scan_interval(self) -> timedelta:
        """状态轮询间隔。"""
        return SCAN_INTERVAL
