# ReadBrief 文章摘要插件

## 简介

ReadBrief是一款专注于文章内容摘要生成的微信插件，旨在帮助用户快速获取文章核心内容，提高阅读效率。用户只需分享链接，插件将自动生成结构化摘要，并以精美卡片形式呈现。

## 功能特点

- **链接摘要**: 支持微信公众号、知乎、头条等常见平台文章链接
- **结构化输出**: 包含标题洞察、一句话总结、核心要点、AI点评、智能标签等
- **美观卡片**: 生成精美可视化摘要卡片，阅读体验更佳
- **智能追问**: 支持对摘要内容进行多轮提问
- **多模型支持**: 支持OpenAI、Gemini、Azure等多种大模型

## 示例效果

**卡片示例**:

![卡片示例](https://example.com/readbrief_card.jpg)

**文本摘要示例**:

```
📖 标题洞察：OpenAI推出GPT-4o：首个视频、图像、音频全面支持的多模态模型

📌 一句话总结：OpenAI推出新一代多模态模型GPT-4o，支持实时处理视频、图像和音频，并将提供免费使用渠道。

✨ 核心要点：
1️⃣ GPT-4o支持文本、图像、视频和音频的实时处理，响应速度比GPT-4 Turbo快2倍
2️⃣ GPT-4o将首先在ChatGPT中推出，免费版支持音频/视频/图像输入、文本输出，ChatGPT Plus将全面支持
3️⃣ GPT-4o即将在API中提供，开发者可以创建具有视觉和语音处理能力的应用
4️⃣ 该模型将改变AI互动方式，使人机交互更加自然，创建可能性更广阔

🤖 AI辣评：GPT-4o的推出标志着AI技术的重要里程碑，将人机交互推向更自然、更多模态的方向。OpenAI通过提供免费版本展示了对普及AI的决心，同时为付费用户提供更全面的功能。这种分层策略既扩大用户群，又维持商业可行性。对开发者而言，这是创新的契机；对用户而言，这意味着更直观、更便捷的AI体验。

🏷️ 智能标签：AI技术、OpenAI、GPT-4o、多模态模型、人工智能

⏱️ 预计阅读：3分钟

📰 文章来源：OpenAI官方博客
```

## 安装

使用管理员口令在线安装，管理员认证方法见：[管理员认证](https://github.com/zhayujie/chatgpt-on-wechat/tree/master/plugins/godcmd)

```
#installp https://github.com/username/readbrief.git
```

安装成功后，使用`#scanp`命令扫描新插件

## 配置

复制插件目录中的`config.json.template`文件，重命名为`config.json`，配置所需参数：

```json
{
  "readbrief": {
    "enabled": true,
    "service": "gpt-3.5-turbo",
    "group": true,
    "qa_enabled": true,
    "qa_prefix": "问",
    "prompt": "你是一个专业的文章分析师，请为以下文章生成结构化摘要，使用JSON格式返回，包含以下字段：title（标题洞察）, summary（一句话总结）, key_points（3-5个核心要点）, comment（AI评论）, tags（智能标签）, read_time（预计阅读时间）, source（文章来源）",
    "card_enabled": true,
    "card_api_url": "https://fireflycard-api.302ai.cn/api/saveImg"
  },
  "keys": {
    "open_ai_api_key": "",
    "model": "gpt-3.5-turbo",
    "open_ai_api_base": "https://api.openai.com/v1",
    "gemini_key": "",
    "azure_deployment_id": "",
    "azure_api_key": "",
    "azure_api_base": ""
  }
}
```

### 配置说明

#### readbrief部分
- `enabled`: 插件总开关
- `service`: 摘要服务，可选"gpt-3.5-turbo"(OpenAI)、"gemini"、"azure"
- `group`: 是否在群聊中启用，true/false
- `qa_enabled`: 是否启用追问功能，true/false
- `qa_prefix`: 追问前缀词
- `prompt`: 摘要生成提示词
- `card_enabled`: 是否启用卡片生成，true/false
- `card_api_url`: 卡片API地址

#### keys部分
- `open_ai_api_key`: OpenAI API密钥
- `model`: OpenAI模型名称
- `open_ai_api_base`: OpenAI API基础URL
- `gemini_key`: Google Gemini API密钥
- `azure_deployment_id`: Azure OpenAI部署ID
- `azure_api_key`: Azure API密钥
- `azure_api_base`: Azure API基础URL

## 使用方法

1. **分享链接**: 直接在聊天中发送或分享文章链接
2. **查看摘要**: 自动获取摘要，并以卡片或文本形式返回
3. **追问内容**: 在获取摘要后5分钟内，发送"问+问题"进行追问

## 依赖项

- requests
- jina
- beautifulsoup4
- json5
- pillow

## 常见问题

1. **卡片无法生成**: 请检查网络连接和卡片API是否可用
2. **链接无法解析**: 可能是不支持的链接格式或网站
3. **摘要内容混乱**: 尝试调整prompt配置或更换服务提供商

## 联系与反馈

如有问题或建议，请提交issue或联系开发者。

## 开源协议

本项目采用MIT许可证开源。 