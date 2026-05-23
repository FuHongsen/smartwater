"""
SmartIrrigator 集成入口

本模块将商业闭源的智能喷灌控制器接入 HomeAssistant，通过封装其云 API，
在 HA 中暴露出 switch 实体以实现远程开关阀门的功能。

功能：
- 从 configuration.yaml 读取设备账号、密码和设备 ID
- 创建 SmartIrrigatorAPI 实例并存储到 hass.data 中，供各平台共享
- 注册 forward 到 switch 平台，由 switch.py 创建阀门开关实体
- （可选）注册自定义服务，如 force_refresh、diagnostic_report 等

使用方式：
  在 configuration.yaml 中添加：
    smart_irrigator:
      username: !secret irrigator_username
      password: !secret irrigator_password
      device_id: "field_1"
"""

import logging
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD, CONF_DEVICE_ID
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .api import SmartIrrigatorAPI

DOMAIN = "smart_irrigator"
_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 配置校验 Schema
# ---------------------------------------------------------------------------
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Required(CONF_DEVICE_ID): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


def setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """
    同步方式初始化集成（兼容旧版本 HA，也可改为 async_setup）。

    主要任务：
    1. 读取配置
    2. 创建 API 客户端并登录
    3. 将客户端存储到 hass.data[DOMAIN] 中
    4. 加载 switch 平台
    5. （可选）注册自定义服务

    Args:
        hass: HomeAssistant 核心实例
        config: 全局配置字典

    Returns:
        bool: True 表示初始化成功，False 表示失败
    """
    conf = config[DOMAIN]

    username = conf[CONF_USERNAME]
    password = conf[CONF_PASSWORD]
    device_id = conf[CONF_DEVICE_ID]

    _LOGGER.info("正在初始化 SmartIrrigator 集成 (设备: %s)", device_id)

    # 1. 创建 API 客户端并登录
    api = SmartIrrigatorAPI(username, password)
    if not api.login():
        _LOGGER.error("无法登录到喷灌设备云服务，请检查用户名和密码")
        return False

    # 2. 将 API 客户端和设备 ID 存储到 hass.data，供 switch 平台使用
    hass.data[DOMAIN] = {
        "api": api,
        "device_id": device_id,
    }

    # 3. 加载 switch 平台（由 switch.py 创建实体）
    hass.helpers.discovery.load_platform("switch", DOMAIN, {}, config)

    # 4. 注册自定义服务（示例：强制刷新状态）
    def handle_force_refresh(call):
        """处理 smart_irrigator.force_refresh 服务调用"""
        api_client = hass.data[DOMAIN]["api"]
        dev_id = hass.data[DOMAIN]["device_id"]
        try:
            status = api_client.get_device_status(dev_id)
            if status is not None:
                # 更新对应实体的状态（需通过 switch 平台提供的方法）
                _LOGGER.info("强制刷新成功：阀门状态 %s", "开" if status else "关")
            else:
                _LOGGER.warning("强制刷新失败：无法获取设备状态")
        except Exception as e:
            _LOGGER.error("强制刷新异常: %s", e)

    hass.services.register(DOMAIN, "force_refresh", handle_force_refresh)

    # 5. 注册一个服务：发送原始命令（用于调试）
    def handle_raw_command(call):
        """处理 smart_irrigator.raw_command 服务，用于高级调试"""
        api_client = hass.data[DOMAIN]["api"]
        dev_id = hass.data[DOMAIN]["device_id"]
        command = call.data.get("command", {})
        try:
            success = api_client.send_raw_command(dev_id, command)
            if success:
                _LOGGER.info("原始命令已发送: %s", command)
            else:
                _LOGGER.error("原始命令发送失败")
        except Exception as e:
            _LOGGER.error("发送原始命令异常: %s", e)

    hass.services.register(
        DOMAIN,
        "raw_command",
        handle_raw_command,
        schema=vol.Schema(
            {
                vol.Required("command"): dict,
            }
        ),
    )

    _LOGGER.info("SmartIrrigator 集成初始化完成")
    return True


def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """
    异步初始化（推荐用于较新版本的 HA）。
    为简单起见，当前实现直接调用同步 setup 函数。
    在真正的异步版本中，应使用 aiohttp 或异步库改造 API 调用。
    """
    return setup(hass, config)
