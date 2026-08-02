# Changelog

本项目的重要变更将记录在此文件中。

## [Unreleased]

### Added

- 创建初始项目目录结构。
- 添加项目任务书、开发计划、协作说明和 README。
- 添加 Docker Compose、环境变量示例及空目录跟踪文件。

## [0.1.1] - 2026-08-02

### Added

- 增加可插拔意图识别模块。
- 增加 LLMIntentClassifier 和 FakeIntentClassifier。
- 增加 qwen-flash 结构化输出支持。
- 增加意图评测数据集和真实模型验证脚本。
- 增加意图识别代码快速入门文档。

### Changed

- LangGraph 使用 IntentRecognitionService 替换关键词分类器。
- 查询、创建、状态更新、澄清和普通对话按 IntentResult 路由。
- 模型客户端通过统一工厂创建。

### Known Limitations

- 查询节点尚未充分使用 IntentResult.task_reference。
- GENERAL_CHAT 当前只返回固定能力提示。
- UPDATE_TASK 和 DECOMPOSE_TASK 业务功能尚未开放。
