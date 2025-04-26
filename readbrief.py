import requests
import json
import re
import os
import plugins
from bridge.reply import Reply, ReplyType
from bridge.context import ContextType
from channel.chat_message import ChatMessage
from plugins import *
from common.log import logger
from common.expired_dict import ExpiredDict
from bs4 import BeautifulSoup
from PIL import Image
import base64
import html
from io import BytesIO
import jina

@plugins.register(
    name="readbrief",
    desire_priority=2,
    desc="一个专注于生成文章摘要的插件",
    version="0.1.0",
    author="readbrief",
)
class ReadBrief(Plugin):
    """
    ReadBrief插件：生成文章摘要
    
    用户分享链接后，插件将：
    1. 使用jina读取链接内容
    2. 调用大模型API生成JSON格式摘要
    3. 通过流光卡片API生成可视化摘要
    """
    def __init__(self):
        super().__init__()
        try:
            # 加载配置
            curdir = os.path.dirname(__file__)
            config_path = os.path.join(curdir, "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            else:
                # 使用父类的方法来加载配置
                self.config = super().load_config()
                if not self.config:
                    raise Exception("config.json not found")
                    
            # 设置事件处理函数
            self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
            self.params_cache = ExpiredDict(300)  # 设置5分钟过期的缓存
            
            # 从配置中提取所需的设置
            self.readbrief = self.config.get("readbrief", {})
            self.keys = self.config.get("keys", {})
            
            # ReadBrief相关配置
            self.enabled = self.readbrief.get("enabled", False)
            self.service = self.readbrief.get("service", "gpt-3.5-turbo")
            self.group = self.readbrief.get("group", True)
            self.qa_enabled = self.readbrief.get("qa_enabled", True)
            self.qa_prefix = self.readbrief.get("qa_prefix", "问")
            self.prompt = self.readbrief.get("prompt", "")
            self.card_enabled = self.readbrief.get("card_enabled", True)
            self.card_api_url = self.readbrief.get("card_api_url", "https://fireflycard-api.302ai.cn/api/saveImg")
            
            # API密钥配置
            self.open_ai_api_key = self.keys.get("open_ai_api_key", "")
            self.model = self.keys.get("model", "gpt-3.5-turbo")
            self.open_ai_api_base = self.keys.get("open_ai_api_base", "https://api.openai.com/v1")
            self.gemini_key = self.keys.get("gemini_key", "")
            self.azure_deployment_id = self.keys.get("azure_deployment_id", "")
            self.azure_api_key = self.keys.get("azure_api_key", "")
            self.azure_api_base = self.keys.get("azure_api_base", "")
            
            # 初始化成功日志
            logger.info("[ReadBrief] 初始化成功。")
        except Exception as e:
            # 初始化失败日志
            logger.warn(f"ReadBrief初始化失败: {e}")
            
    def on_handle_context(self, e_context: EventContext):
        """处理上下文事件的主函数"""
        context = e_context["context"]
        
        # 只处理文本和链接分享
        if context.type not in [ContextType.TEXT, ContextType.SHARING]:
            return
            
        # 如果插件未启用，直接返回
        if not self.enabled:
            return
            
        msg: ChatMessage = e_context["context"]["msg"]
        user_id = msg.from_user_id
        content = context.content
        isgroup = e_context["context"].get("isgroup", False)
        
        # 处理群聊和私聊的配置
        if isgroup and not self.group:
            return
            
        # 更新URL匹配逻辑，支持完整的URL
        url_match = re.match(r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*', content)
        unsupported_urls = re.search(r'.*finder\.video\.qq\.com.*|.*support\.weixin\.qq\.com/update.*|.*support\.weixin\.qq\.com/security.*|.*mp\.weixin\.qq\.com/mp/waerrpage.*', content)
        
        # 处理用户追问
        if user_id in self.params_cache and 'last_url' in self.params_cache[user_id]:
            # 用户发送追问
            if content.startswith(self.qa_prefix) and self.qa_enabled:
                logger.info('内容以qa_prefix开头，处理追问')
                # 去除关键词前缀
                new_content = content[len(self.qa_prefix):]
                self.params_cache[user_id]['prompt'] = new_content
                logger.info('已更新用户提问')
                self.handle_url(self.params_cache[user_id]['last_url'], e_context)
                return
                
        # 处理链接分享
        if context.type == ContextType.SHARING:
            content = html.unescape(content)
            if unsupported_urls:  # 不支持的URL类型
                if not isgroup:  # 私聊回复不支持
                    logger.info("[ReadBrief] 不支持的URL : %s", content)
                    reply = Reply(type=ReplyType.TEXT, content="不支持小程序和视频号")
                    e_context["reply"] = reply
                    e_context.action = EventAction.BREAK_PASS
            else:  # 支持的URL类型
                # 更新params_cache中的last_url
                self.params_cache[user_id] = {}
                self.params_cache[user_id]['last_url'] = content
                self.params_cache[user_id]['prompt'] = self.prompt
                logger.info('[ReadBrief] 已更新last_url至params_cache')
                self.handle_url(content, e_context)
        
        # 处理文本中可能包含的URL
        elif url_match and not unsupported_urls:
            url = url_match.group(0)
            # 更新params_cache中的last_url
            self.params_cache[user_id] = {}
            self.params_cache[user_id]['last_url'] = url
            self.params_cache[user_id]['prompt'] = self.prompt
            logger.info('[ReadBrief] 已从文本中提取URL并更新至params_cache')
            self.handle_url(url, e_context)
            
    def handle_url(self, url, e_context):
        """处理URL链接，获取内容并生成摘要"""
        try:
            logger.info(f"[ReadBrief] 处理URL: {url}")
            
            # 根据选择的服务调用不同的API
            if self.service == "gemini":
                self.handle_gemini(url, e_context)
            elif self.service == "azure":
                self.handle_azure(url, e_context)
            else:  # 默认使用OpenAI
                self.handle_openai(url, e_context)
                
        except Exception as e:
            logger.error(f"处理URL时出错: {str(e)}")
            reply = Reply(ReplyType.ERROR, "处理URL时发生错误")
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            
    def fetch_url_content(self, url):
        """使用jina获取URL内容"""
        try:
            # 使用jina提取网页内容
            from jina import Document
            doc = Document(uri=url).load_uri_to_text()
            
            # 获取网页正文内容
            content = doc.text
            
            # 解析网页元数据
            soup = BeautifulSoup(content, 'html.parser')
            
            # 提取标题
            title = soup.title.string if soup.title else ""
            
            # 提取来源（可能需要根据实际网站结构调整）
            source = ""
            meta_site = soup.find('meta', {'property': 'og:site_name'})
            if meta_site:
                source = meta_site.get('content', '')
                
            return {
                "content": content,
                "title": title,
                "source": source
            }
        except Exception as e:
            logger.error(f"获取URL内容失败: {str(e)}")
            return None
            
    def handle_openai(self, url, e_context):
        """使用OpenAI处理URL内容"""
        try:
            # 获取用户ID和参数
            msg: ChatMessage = e_context["context"]["msg"]
            user_id = msg.from_user_id
            user_params = self.params_cache.get(user_id, {})
            isgroup = e_context["context"].get("isgroup", False)
            prompt = user_params.get('prompt', self.prompt)
            
            # 获取网页内容
            url_data = self.fetch_url_content(url)
            if not url_data:
                reply = Reply(ReplyType.ERROR, "无法获取网页内容")
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
                
            # 构建API请求
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.open_ai_api_key}'
            }
            
            # 构建消息
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"链接：{url}\n\n内容：{url_data['content'][:5000]}"}  # 限制内容长度
            ]
            
            # API调用参数
            data = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 1000
            }
            
            logger.info(f"[OpenAI API请求] URL: {url}")
            logger.info(f"[OpenAI API请求] 提示词: {prompt}")
            
            # 发送API请求
            response = requests.post(f"{self.open_ai_api_base}/chat/completions", 
                                    headers=headers, json=data)
            response.raise_for_status()
            response_data = response.json()
            
            # 提取生成的摘要
            summary_json = response_data["choices"][0]["message"]["content"]
            
            # 尝试解析JSON
            try:
                summary_data = json.loads(summary_json)
                
                # 构建格式化摘要文本
                summary_text = self.format_summary(summary_data, url_data)
                
                # 保存内容到用户缓存
                self.params_cache[user_id]['content'] = summary_text
                self.params_cache[user_id]['title'] = summary_data.get('title', url_data.get('title', ''))
                self.params_cache[user_id]['source'] = summary_data.get('source', url_data.get('source', ''))
                
                # 处理生成的摘要
                self.process_summary_response(summary_text, e_context)
                
            except json.JSONDecodeError:
                # JSON解析失败，直接使用文本
                logger.warning("JSON解析失败，使用原始文本")
                summary_text = summary_json
                
                # 添加交互提示
                if self.qa_enabled:
                    final_text = f"{summary_text}\n\n💬5分钟内输入{self.qa_prefix}+问题，可继续追问"
                else:
                    final_text = summary_text
                    
                # 创建文本回复
                reply = Reply(ReplyType.TEXT, final_text)
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                
        except Exception as e:
            logger.error(f"OpenAI处理错误: {str(e)}")
            reply = Reply(ReplyType.ERROR, "摘要生成失败")
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            
    def handle_gemini(self, url, e_context):
        """使用Gemini处理URL内容"""
        try:
            # 获取用户ID和参数
            msg: ChatMessage = e_context["context"]["msg"]
            user_id = msg.from_user_id
            user_params = self.params_cache.get(user_id, {})
            isgroup = e_context["context"].get("isgroup", False)
            prompt = user_params.get('prompt', self.prompt)
            
            # 获取网页内容
            url_data = self.fetch_url_content(url)
            if not url_data:
                reply = Reply(ReplyType.ERROR, "无法获取网页内容")
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
                
            # Gemini API配置
            api_key = self.gemini_key
            api_base = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
            
            # 构建请求
            headers = {
                'Content-Type': 'application/json'
            }
            
            # 构建消息
            data = {
                "contents": [
                    {
                        "parts": [
                            {"text": prompt},
                            {"text": f"链接：{url}\n\n内容：{url_data['content'][:5000]}"}  # 限制内容长度
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.7,
                    "maxOutputTokens": 1000
                }
            }
            
            logger.info(f"[Gemini API请求] URL: {url}")
            logger.info(f"[Gemini API请求] 提示词: {prompt}")
            
            # 发送API请求
            response = requests.post(f"{api_base}?key={api_key}", 
                                    headers=headers, json=data)
            response.raise_for_status()
            response_data = response.json()
            
            # 提取生成的摘要
            summary_json = response_data["candidates"][0]["content"]["parts"][0]["text"]
            
            # 尝试解析JSON
            try:
                summary_data = json.loads(summary_json)
                
                # 构建格式化摘要文本
                summary_text = self.format_summary(summary_data, url_data)
                
                # 保存内容到用户缓存
                self.params_cache[user_id]['content'] = summary_text
                self.params_cache[user_id]['title'] = summary_data.get('title', url_data.get('title', ''))
                self.params_cache[user_id]['source'] = summary_data.get('source', url_data.get('source', ''))
                
                # 处理生成的摘要
                self.process_summary_response(summary_text, e_context)
                
            except json.JSONDecodeError:
                # JSON解析失败，直接使用文本
                logger.warning("JSON解析失败，使用原始文本")
                summary_text = summary_json
                
                # 添加交互提示
                if self.qa_enabled:
                    final_text = f"{summary_text}\n\n💬5分钟内输入{self.qa_prefix}+问题，可继续追问"
                else:
                    final_text = summary_text
                    
                # 创建文本回复
                reply = Reply(ReplyType.TEXT, final_text)
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                
        except Exception as e:
            logger.error(f"Gemini处理错误: {str(e)}")
            reply = Reply(ReplyType.ERROR, "摘要生成失败")
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            
    def handle_azure(self, url, e_context):
        """使用Azure OpenAI处理URL内容"""
        try:
            # 获取用户ID和参数
            msg: ChatMessage = e_context["context"]["msg"]
            user_id = msg.from_user_id
            user_params = self.params_cache.get(user_id, {})
            isgroup = e_context["context"].get("isgroup", False)
            prompt = user_params.get('prompt', self.prompt)
            
            # 获取网页内容
            url_data = self.fetch_url_content(url)
            if not url_data:
                reply = Reply(ReplyType.ERROR, "无法获取网页内容")
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                return
                
            # Azure API配置
            headers = {
                'Content-Type': 'application/json',
                'api-key': self.azure_api_key
            }
            
            # 构建消息
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"链接：{url}\n\n内容：{url_data['content'][:5000]}"}  # 限制内容长度
            ]
            
            # API调用参数
            data = {
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 1000
            }
            
            logger.info(f"[Azure API请求] URL: {url}")
            logger.info(f"[Azure API请求] 提示词: {prompt}")
            
            # 发送API请求
            endpoint = f"{self.azure_api_base}/openai/deployments/{self.azure_deployment_id}/chat/completions?api-version=2023-05-15"
            response = requests.post(endpoint, headers=headers, json=data)
            response.raise_for_status()
            response_data = response.json()
            
            # 提取生成的摘要
            summary_json = response_data["choices"][0]["message"]["content"]
            
            # 尝试解析JSON
            try:
                summary_data = json.loads(summary_json)
                
                # 构建格式化摘要文本
                summary_text = self.format_summary(summary_data, url_data)
                
                # 保存内容到用户缓存
                self.params_cache[user_id]['content'] = summary_text
                self.params_cache[user_id]['title'] = summary_data.get('title', url_data.get('title', ''))
                self.params_cache[user_id]['source'] = summary_data.get('source', url_data.get('source', ''))
                
                # 处理生成的摘要
                self.process_summary_response(summary_text, e_context)
                
            except json.JSONDecodeError:
                # JSON解析失败，直接使用文本
                logger.warning("JSON解析失败，使用原始文本")
                summary_text = summary_json
                
                # 添加交互提示
                if self.qa_enabled:
                    final_text = f"{summary_text}\n\n💬5分钟内输入{self.qa_prefix}+问题，可继续追问"
                else:
                    final_text = summary_text
                    
                # 创建文本回复
                reply = Reply(ReplyType.TEXT, final_text)
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS
                
        except Exception as e:
            logger.error(f"Azure处理错误: {str(e)}")
            reply = Reply(ReplyType.ERROR, "摘要生成失败")
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            
    def format_summary(self, summary_data, url_data):
        """格式化摘要数据为文本形式"""
        title = summary_data.get('title', url_data.get('title', '未知标题'))
        summary = summary_data.get('summary', '无摘要')
        key_points = summary_data.get('key_points', [])
        comment = summary_data.get('comment', '无评论')
        tags = summary_data.get('tags', '')
        read_time = summary_data.get('read_time', '未知')
        source = summary_data.get('source', url_data.get('source', '未知来源'))
        
        # 格式化关键点
        formatted_points = ""
        for i, point in enumerate(key_points):
            if isinstance(point, str):
                formatted_points += f"{i+1}️⃣ {point}\n"
                
        # 构建最终摘要文本
        summary_text = f"📖 标题洞察：{title}\n\n"
        summary_text += f"📌 一句话总结：{summary}\n\n"
        summary_text += f"✨ 核心要点：\n{formatted_points}\n"
        summary_text += f"🤖 AI辣评：{comment}\n\n"
        summary_text += f"🏷️ 智能标签：{tags}\n\n"
        summary_text += f"⏱️ 预计阅读：{read_time}\n\n"
        summary_text += f"📰 文章来源：{source}"
        
        return summary_text
        
    def process_summary_response(self, summary_text, e_context):
        """处理摘要响应并生成卡片（如果启用）"""
        try:
            # 获取用户信息
            msg: ChatMessage = e_context["context"]["msg"]
            user_id = msg.from_user_id
            isgroup = e_context["context"].get("isgroup", False)
            
            # 如果启用了卡片生成
            if summary_text and self.card_enabled:
                logger.info(f"[卡片生成] 处理摘要文本...")
                
                # 获取标题和来源
                title = self.params_cache[user_id].get('title', '')
                source = self.params_cache[user_id].get('source', '')
                original_url = self.params_cache[user_id].get('last_url', '')
                
                # 提取摘要各部分
                one_line_match = re.search(r'📌 一句话总结[：:]\s*(.*?)(?=\n\n|$)', summary_text)
                summary = one_line_match.group(1).strip() if one_line_match else ""
                
                # 提取核心要点
                deep_analysis_match = re.search(r'✨ 核心要点[：:]?\n(.*?)(?=\n\n(?:🤖|🏷️|⏱️)|$)', summary_text, re.DOTALL)
                points = []
                if deep_analysis_match:
                    analysis_text = deep_analysis_match.group(1).strip()
                    for point in analysis_text.split('\n'):
                        point = point.strip()
                        if point and not point.startswith('✨'):
                            # 移除markdown和编号
                            point = re.sub(r'\*\*(.*?)\*\*', r'\1', point)
                            point = re.sub(r'^[1-5]️⃣\s*', '', point)
                            points.append(point)
                
                # 提取AI评论
                thinking_match = re.search(r'🤖 AI辣评[：:]\s*(.*?)(?=\n\n(?:🏷️|⏱️)|$)', summary_text, re.DOTALL)
                thinking = thinking_match.group(1).strip() if thinking_match else ""
                
                # 提取标签
                tags_match = re.search(r'🏷️ 智能标签[：:]\s*(.*?)(?=\n\n(?:⏱️)|$)', summary_text, re.DOTALL)
                tags = tags_match.group(1).strip() if tags_match else ""
                
                # 提取预计阅读时间
                time_match = re.search(r'⏱️ 预计阅读[：:]\s*(.*?)(?=\n|$)', summary_text)
                reading_time = time_match.group(1).strip() if time_match else ""
                
                # 格式化卡片内容
                formatted_sections = []
                
                # 添加一句话总结
                if summary:
                    formatted_sections.append(f'<p><span style="background-color: transparent; color: inherit; font-size: calc(1.1rem);"><b>📌 一句话总结</b></span></p><p><span style="font-size: 14px;">{summary}</span></p>')
                
                # 添加核心要点
                if points:
                    formatted_points = '<br>'.join(points)
                    formatted_sections.append(f'<p><b><span style="font-size: 16px;">✨ 核心要点</span></b></p><p><span style="font-size: 14px;">{formatted_points}</span></p>')
                
                # 添加AI评论
                if thinking:
                    formatted_sections.append(f'<p><b><span style="font-size: 16px;">🤖 AI辣评</span></b></p><p><span style="font-size: 14px;">{thinking}</span></p>')
                
                # 添加智能标签
                if tags:
                    formatted_sections.append(f'<p><b><span style="font-size: 14px;">🏷️ 智能标签</span></b></p><p><span style="color: rgb(35, 90, 217); font-size: 14px;">{tags}</span></p>')
                
                # 添加预计阅读时间
                if reading_time:
                    formatted_sections.append(f'<p><span style="color: rgb(217, 118, 2); font-size: 12px;">⏱️ 预计阅读：{reading_time}</span></p>')
                
                # 组合所有部分
                content = '<p><br></p>'.join([section for section in formatted_sections if section.strip()])
                
                if not content:
                    logger.error("[卡片生成] 无内容生成!")
                    content = "<p>内容处理失败，请重试</p>"
                
                logger.info(f"[卡片生成] 标题: {title}")
                logger.info(f"[卡片生成] 内容部分: {len(formatted_sections)}")
                
                # 生成卡片
                card_image = self.generate_card(title, content, original_url, source)
                
                if card_image:
                    # 创建图片回复
                    image_io = BytesIO(card_image)
                    reply = Reply(ReplyType.IMAGE, image_io)
                    logger.info("[卡片生成] 成功生成卡片图片")
                else:
                    # 如果卡片生成失败，回退到文本回复
                    # 添加交互提示
                    if self.qa_enabled:
                        final_text = f"{summary_text}\n\n💬5分钟内输入{self.qa_prefix}+问题，可继续追问"
                    else:
                        final_text = summary_text
                        
                    reply = Reply(ReplyType.TEXT, final_text)
                    logger.warning("[卡片生成] 卡片生成失败，回退到文本")
            else:
                # 默认文本回复
                # 添加交互提示
                if self.qa_enabled:
                    final_text = f"{summary_text}\n\n💬5分钟内输入{self.qa_prefix}+问题，可继续追问"
                else:
                    final_text = summary_text
                    
                reply = Reply(ReplyType.TEXT, final_text)
                
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
            
        except Exception as e:
            logger.error(f"处理摘要响应时出错: {str(e)}")
            logger.error(f"导致错误的摘要文本: {summary_text}")
            reply = Reply(ReplyType.ERROR, "处理摘要时出错")
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS
        
    def generate_card(self, title, content, qr_code_url=None, source=""):
        """生成卡片图片"""
        try:
            # 默认值
            qr_code_title = "阅读简报"
            
            # 格式化来源
            formatted_source = f'<p>{source}</p>' if source else "<p>未知来源</p>"
            
            # 构建请求数据
            payload = {
                "form": {
                    "icon": "https://thirdwx.qlogo.cn/mmopen/vi_32/PiajxSqBRaELBfzmtibIGDLIMh25xMibQib7bOzufM1CYPRz0yMxpe7eVDf6iarE0jWXsmicswRPyldE5ibCcBQTLhgBHeF1oWLJU5WklyBpvsDdubahZmeMknmDQ/132",
                    "date": "",
                    "title": f"<p>{title}</p>",
                    "content": f"<p>{content}</p>",
                    "author": formatted_source,
                    "textCount": "字数",
                    "qrCodeTitle": qr_code_title,
                    "qrCodeText": "长按识别二维码 · 阅读原文",
                    "pagination": "01",
                    "qrCode": qr_code_url if qr_code_url else "https://u.wechat.com/EEFtTHlxdhQGmGofv3SHszQ",
                    "textCountNum": len(content)
                },
                "style": {
                    "align": "left",
                    "backgroundName": "light-color-41",
                    "backShadow": "",
                    "font": "LXGW WenKai Light",
                    "width": 540,
                    "ratio": "",
                    "height": 0,
                    "fontScale": 0.8,
                    "padding": "10px",
                    "borderRadius": "20px",
                    "backgroundAngle": "150deg",
                    "lineHeights": {
                        "date": "",
                        "content": ""
                    },
                    "letterSpacings": {
                        "date": "",
                        "content": ""
                    }
                },
                "switchConfig": {
                    "showIcon": False,
                    "showDate": False,
                    "showTitle": True,
                    "showContent": True,
                    "showAuthor": True,
                    "showTextCount": False,
                    "showQRCode": True,
                    "showPageNum": False,
                    "showWatermark": False,
                    "showTGradual": True
                },
                "temp": "tempEasy",
                "imgScale": 3,
                "language": "zh"
            }
            
            logger.info(f"[卡片API请求] 发送请求")
            
            headers = {
                'Content-Type': 'application/json'
            }
            
            response = requests.post(self.card_api_url, headers=headers, 
                                    data=json.dumps(payload), verify=False)
            
            if response.status_code == 200:
                logger.info("[卡片API响应] 成功接收图片数据")
                return response.content
            else:
                logger.error(f"[卡片API响应] 失败: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"[卡片API错误] {str(e)}")
            return None
            
    def get_help_text(self, verbose=False, **kwargs):
        """返回插件帮助信息"""
        help_text = "ReadBrief插件：\n"
        if not verbose:
            help_text += "生成文章摘要，发送链接即可。支持追问功能。"
        else:
            help_text += "一款专注于文章内容摘要生成的插件，帮助用户快速获取文章核心内容。\n"
            help_text += "- 发送链接即可获取文章摘要\n"
            help_text += f"- 发送{self.qa_prefix}+问题，可针对文章内容提问\n"
            
        return help_text 