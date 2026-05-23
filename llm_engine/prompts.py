"""
prompts.py - 灌溉决策 Prompt 模板与构建工具

本模块提供 build_irrigation_prompt() 函数，用于将传感器上下文、
用户策略和作物信息组合成结构化的自然语言提示（Prompt），
引导 LLM 以 JSON 格式输出灌溉控制指令。

设计原则：
- 明确的角色设定（农业灌溉专家）与任务说明
- 结构化输入（传感器数据、作物阶段、阈值规则）
- 严格的 JSON 输出约束，便于程序解析
- 安全边界提醒（最大时长、极端天气）
- 可选的紧急模式，调整决策激进程度
"""

from typing import Dict, Any


# ----------------------------------------------------------------------
# 作物需水特征知识库（内置规则，补充 LLM 的农业知识）
# ----------------------------------------------------------------------
CROP_WATER_GUIDE = {
    "seedling": "幼苗期需水量较低，保持土壤湿润即可，避免积水。",
    "vegetative": "营养生长期需水量逐渐增加，建议保持土壤湿度 60-80%。",
    "flowering": "开花期对水分敏感，需稳定供水，湿度维持在 65-75%，避免剧烈波动。",
    "fruiting": "结果期需水量大，但需防止过湿导致裂果或病害，湿度目标 70-85%。",
    "ripening": "成熟期适当控水，促进糖分积累，湿度可降至 55-65%。",
}


def _crop_stage_hint(stage: str) -> str:
    """根据作物生长阶段返回需水知识提示文本"""
    return CROP_WATER_GUIDE.get(
        stage.lower(),
        "通用蔬菜需水规律：保持土壤湿度 60-80%，避免长时间干旱或积水。"
    )


# ----------------------------------------------------------------------
# Prompt 构建核心函数
# ----------------------------------------------------------------------
def build_irrigation_prompt(
    area: str,
    context: Dict[str, Any],
    urgency: str = "normal",
    max_duration: int = 30
) -> str:
    """
    构建发送给 LLM 的完整 Prompt。

    参数:
        area: 地块标识字符串，如 "tomato_field"
        context: 上下文字典，由 decision_engine 采集，必须包含：
            - "states": {entity_id: state_value} 传感器状态映射
            - "crop_stage": 当前作物生长阶段（如 "seedling", "vegetative"）
            - "is_hold": 布尔值，表示是否处于暂停状态
            - "valve_currently_on": 布尔值，阀门当前开/关
        urgency: 紧急程度 "normal" 或 "high"
            - "high" 时会提示 LLM 优先保障作物存活，允许放宽降雨等待策略
        max_duration: 单次灌溉最大允许时长（分钟）

    返回:
        完整的 prompt 字符串，可直接发送给 LLM
    """
    # 解析上下文
    sensor_states = context.get("states", {})
    crop_stage = context.get("crop_stage", "unknown")
    is_hold = context.get("is_hold", False)
    valve_currently_on = context.get("valve_currently_on", False)

    # 将传感器状态转化为可读的列表
    sensor_lines = "\n".join(
        f"  - {entity_id}: {state_value}" 
        for entity_id, state_value in sensor_states.items()
    ) if sensor_states else "  无传感器数据"

    # 作物阶段提示
    crop_hint = _crop_stage_hint(crop_stage)

    # 当前设备状态描述
    valve_status = "开启中" if valve_currently_on else "已关闭"
    hold_status = "是（请勿输出开启阀门指令）" if is_hold else "否"

    # 根据紧急程度调整决策指引
    if urgency == "high":
        urgency_note = (
            "当前为紧急干旱状态，请优先保障作物存活。可以忽略短时降雨预报，"
            "立即开启灌溉并建议较短时长快速补水。"
        )
    else:
        urgency_note = (
            "正常模式，请综合考虑未来降雨概率，如果降雨可能性>70%可延后灌溉，"
            "优先采用节水策略。"
        )

    # 组装完整的 Prompt
    prompt = f"""你是一位资深农业灌溉专家，负责控制一个智能喷灌系统。

【当前任务】
根据下面的实时传感器数据、作物生长阶段和设备状态，决定是否需要进行灌溉。
请以严格的 JSON 格式输出你的决策，不要包含任何多余的解释文字。

【地块信息】
- 地块名称: {area}
- 作物生长阶段: {crop_stage}
- 该阶段需水特征: {crop_hint}

【实时传感器数据】
{sensor_lines}

【设备状态】
- 喷灌阀门: {valve_status}
- 灌溉暂停标记: {hold_status}
- 决策策略: {urgency_note}

【灌溉约束】
- 单次灌溉最短 {5} 分钟，最长不超过 {max_duration} 分钟。
- 如果阀门当前已开启，请根据时长需要决定是继续还是关闭。
- 如果灌溉暂停标记为“是”，则 action 必须为 "off"。

【输出格式】
严格输出一个 JSON 对象，包含以下字段：
{{
  "action": "on" 或 "off",
  "duration_minutes": 整数，建议灌溉时长（仅在 action="on" 时有效），
  "reason": "简短中文理由，不超过50字",
  "mode": "normal" 或 "eco"（可选）
}}
- 如果你认为应该灌溉，action 为 "on" 并提供合理的 duration_minutes。
- 如果不需要灌溉，action 为 "off"，duration_minutes 可设为 0。
- 在 energy saving 场景或水量充足但想节水时，可将 mode 设为 "eco"。

现在请直接输出 JSON："""

    return prompt
