# smartwater
一套用于小花园、小菜园可手机远程操控的灌溉系统
# 🌱 AgriBrain - 基于 HomeAssistant + LLM 的智能喷灌联动系统

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![HomeAssistant](https://img.shields.io/badge/Home%20Assistant-2024.5-blue)](https://www.home-assistant.io/)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-green)](https://www.python.org/)

**AgriBrain** 将原本封闭的商业智能喷灌设备接入 HomeAssistant 生态，并引入大语言模型（LLM）作为决策大脑，实现 **跨设备联动、多源农业数据融合** 与 **自然语言交互控制** 的下一代精准灌溉系统。

> 本项目为黑客松大赛概念验证原型，重点展示 **开放生态集成** 与 **LLM驱动决策** 的技术路径。

---

## 📌 背景与问题

市面上现有的智能喷灌系统（如某品牌的 `SmartIrrigator Pro`）已经拥有：

- ☀️ 太阳能供电 + 4G 远程遥控开关
- 📱 手机端控制浇水，定时任务
- 🔒 **但：系统完全闭源，无法与气象站、土壤传感器、智能家居联动**
- 🧠 **不具备基于多源数据的智能决策能力**

农户如果同时拥有土壤湿度计、小型气象站、虫情灯等设备，它们只能各自为政，无法形成闭环的自动化管理。

**AgriBrain 的目标**：  
将这种商业设备“撬开一条缝”，通过 HomeAssistant 的统一平台，让 LLM 能够像人类管家一样阅读传感器数值、天气预报，甚至接收你的自然语言指令，最终精准地拧开或关闭喷灌开关。

---

## 🧱 系统架构
