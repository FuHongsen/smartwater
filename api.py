"""
api.py - 商业智能喷灌控制器云 API 封装

本模块提供 SmartIrrigatorAPI 类，用于与商业闭源喷灌设备的云端服务进行通信。
通过逆向工程或官方适配的方式实现了基本的登录、状态查询和阀门控制功能。

注意：
- 本代码仅供个人农场自动化使用，需遵守设备厂商的服务条款。
- 请勿将凭据硬编码，应通过 HomeAssistant 的 secrets 或环境变量管理。
- 生产环境中建议增加请求重试、速率限制和缓存机制，避免触发云 API 的风控策略。

依赖：
- requests
"""

import logging
import time
from typing import Optional, Dict, Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class SmartIrrigatorAPIError(Exception):
    """自定义异常，用于表示 API 调用中的业务错误或网络问题。"""
    pass


class SmartIrrigatorAPI:
    """
    封装商业智能喷灌控制器的云 API。

    典型使用流程:
        api = SmartIrrigatorAPI("user@example.com", "password123")
        if api.login():
            status = api.get_device_status("field_1")
            if status:
                print(f"阀门当前状态: {'开' if status else '关'}")
            api.set_valve("field_1", True)   # 打开阀门
            api.logout()
    """

    # 默认 API 基地址
    BASE_URL = "https://api.irrigator-pro.com/v2"

    # 请求超时设置（秒）
    CONNECT_TIMEOUT = 10
    READ_TIMEOUT = 30

    def __init__(self, username: str, password: str, base_url: Optional[str] = None):
        """
        初始化 API 客户端。

        Args:
            username: 设备厂商账户（邮箱或手机号）
            password: 账户密码
            base_url: 可选，自定义 API 基地址（用于测试或本地代理）
        """
        self.username = username
        self.password = password
        self.base_url = base_url or self.BASE_URL

        # 创建一个带有重试机制的 requests 会话
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,                      # 最大重试次数
            backoff_factor=1,            # 重试间隔: 1s, 2s, 4s...
            status_forcelist=[429, 500, 502, 503, 504],  # 这些状态码触发重试
            allowed_methods=["HEAD", "GET", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # 登录后保存的令牌，由 login() 方法设置
        self.access_token: Optional[str] = None

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------
    def login(self) -> bool:
        """
        登录到云服务并获取访问令牌。

        Returns:
            bool: 登录是否成功
        """
        url = f"{self.base_url}/login"
        payload = {
            "user": self.username,
            "pass": self.password
        }
        try:
            logger.info("正在登录到设备云服务...")
            resp = self.session.post(
                url,
                json=payload,
                timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT)
            )
            resp.raise_for_status()
            data = resp.json()

            # 假设响应中包含 access_token 字段
            self.access_token = data.get("access_token")
            if not self.access_token:
                raise SmartIrrigatorAPIError("登录响应中缺少 access_token")

            # 更新后续请求的认证头
            self.session.headers.update({
                "Authorization": f"Bearer {self.access_token}"
            })
            logger.info("登录成功")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"登录请求失败: {e}")
            return False
        except SmartIrrigatorAPIError as e:
            logger.error(f"登录业务错误: {e}")
            return False

    def logout(self) -> bool:
        """
        登出并销毁当前会话令牌。

        Returns:
            bool: 是否成功登出
        """
        if not self.access_token:
            return True

        url = f"{self.base_url}/logout"
        try:
            resp = self.session.post(url, timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT))
            resp.raise_for_status()
            self.access_token = None
            self.session.headers.pop("Authorization", None)
            logger.info("已登出")
            return True
        except requests.exceptions.RequestException as e:
            logger.warning(f"登出请求失败，可能令牌已失效: {e}")
            self.access_token = None
            return False

    def _ensure_authenticated(self) -> None:
        """确保已登录，否则抛出异常。"""
        if not self.access_token:
            # 尝试自动登录
            if not self.login():
                raise SmartIrrigatorAPIError("未登录且自动登录失败，无法调用 API")

    # ------------------------------------------------------------------
    # 设备状态查询
    # ------------------------------------------------------------------
    def get_device_status(self, device_id: str) -> Optional[bool]:
        """
        获取指定设备的阀门状态。

        Args:
            device_id: 设备唯一标识，如 "field_1"

        Returns:
            bool 或 None: True 表示阀门打开，False 表示关闭，None 表示获取失败
        """
        self._ensure_authenticated()
        url = f"{self.base_url}/device/{device_id}/status"

        try:
            resp = self.session.get(url, timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT))
            resp.raise_for_status()
            data = resp.json()

            # 假设响应格式：{"valve_open": true} 或 {"valve_open": false}
            valve_open = data.get("valve_open")
            if valve_open is None:
                logger.warning(f"设备状态响应中缺少 valve_open 字段，原始数据: {data}")
                return None

            logger.debug(f"设备 {device_id} 阀门状态: {'开' if valve_open else '关'}")
            return valve_open

        except requests.exceptions.RequestException as e:
            logger.error(f"获取设备状态失败: {e}")
            return None

    def get_device_info(self, device_id: str) -> Optional[Dict[str, Any]]:
        """
        获取设备的完整信息（包括电池电量、信号强度、故障码等）。

        Args:
            device_id: 设备 ID

        Returns:
            dict 或 None: 包含设备详细信息的字典，获取失败返回 None
        """
        self._ensure_authenticated()
        url = f"{self.base_url}/device/{device_id}/info"

        try:
            resp = self.session.get(url, timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT))
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"获取设备信息失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 阀门控制
    # ------------------------------------------------------------------
    def set_valve(self, device_id: str, state: bool) -> bool:
        """
        设置指定设备的阀门开关状态。

        Args:
            device_id: 设备唯一标识
            state: True 开启喷灌，False 关闭喷灌

        Returns:
            bool: 命令是否执行成功
        """
        self._ensure_authenticated()
        url = f"{self.base_url}/device/{device_id}/control"
        payload = {
            "valve": 1 if state else 0
        }

        try:
            resp = self.session.post(
                url,
                json=payload,
                timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT)
            )
            resp.raise_for_status()
            logger.info(f"阀门控制成功: device={device_id}, state={'开' if state else '关'}")
            return True

        except requests.exceptions.RequestException as e:
            logger.error(f"阀门控制请求失败: {e}")
            return False

    # ------------------------------------------------------------------
    # 其他辅助功能 (示例)
    # ------------------------------------------------------------------
    def get_device_list(self) -> Optional[list]:
        """
        获取账户下所有设备列表。

        Returns:
            list: 设备 ID 列表，获取失败返回 None
        """
        self._ensure_authenticated()
        url = f"{self.base_url}/devices"

        try:
            resp = self.session.get(url, timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT))
            resp.raise_for_status()
            data = resp.json()
            # 假设返回格式：{"devices": [{"id": "field_1", "name": "番茄地喷灌"}, ...]}
            return [device["id"] for device in data.get("devices", [])]
        except requests.exceptions.RequestException as e:
            logger.error(f"获取设备列表失败: {e}")
            return None

    def send_raw_command(self, device_id: str, command: Dict[str, Any]) -> bool:
        """
        发送原始命令给设备，用于厂商未公开的高级功能。

        Args:
            device_id: 设备 ID
            command: 原始命令字典，如 {"valve": 1, "duration": 300}

        Returns:
            bool: 命令是否发送成功
        """
        self._ensure_authenticated()
        url = f"{self.base_url}/device/{device_id}/control"

        try:
            resp = self.session.post(url, json=command,
                                     timeout=(self.CONNECT_TIMEOUT, self.READ_TIMEOUT))
            resp.raise_for_status()
            logger.info(f"原始命令发送成功: {command}")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"发送原始命令失败: {e}")
            return False
