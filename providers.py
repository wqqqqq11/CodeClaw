"""
CodeClaw — 统一 LLM 提供商
单一类路由至 OpenAI、xAI、Claude、Gemini、DeepSeek 或 Z-AI。
统一 LLM 提供商接口。
"""

import asyncio
import logging
from config import Config

log = logging.getLogger("CodeClaw.providers")
OFFICIAL_ANTHROPIC_BASE_URL = "https://api.anthropic.com"


class LLMClient:
    """
    统一 LLM 接口。根据提供商名称路由至正确的 SDK。

    支持的提供商：
      - openai  → OpenAI ChatGPT（通过 openai SDK）
      - xai     → xAI Grok（通过 openai SDK 及自定义 base_url）
      - claude  → Anthropic Claude（通过 anthropic SDK）
      - gemini  → Google Gemini（通过 google-generativeai SDK）
      - deepseek → DeepSeek（通过 openai SDK 及自定义 base_url）
      - zai     → Z-AI / 智谱 GLM（通过 openai SDK 及自定义 base_url）
    """

    def __init__(self, config: Config):
        self.config = config
        self.provider_name = config.llm_provider
        self.model = config.llm_model
        self.max_output_tokens = max(512, int(getattr(config, "max_output_tokens", 4096) or 4096))
        if self.provider_name == "deepseek" and self.max_output_tokens > 4096:
            # DeepSeek 的聊天端点通常会拒绝较大的 max_tokens 值。
            self.max_output_tokens = 4096
        self._client = None
        self._claude_api_key = ""
        self._claude_auth_token = ""
        self._claude_base_url = OFFICIAL_ANTHROPIC_BASE_URL
        self._claude_custom_base = False

        self._init_client()
        log.info(f"LLM output budget: {self.max_output_tokens} tokens")

    def _init_client(self):
        """初始化相应的 SDK 客户端。"""
        if self.provider_name in ("openai", "xai", "deepseek", "zai"):
            import openai

            if self.provider_name == "xai":
                if not self.config.xai_api_key:
                    raise ValueError("XAI_API_KEY is required when LLM_PROVIDER=xai")
                self._client = openai.OpenAI(
                    api_key=self.config.xai_api_key,
                    base_url="https://api.x.ai/v1",
                    max_retries=0,
                )
            elif self.provider_name == "deepseek":
                if not self.config.deepseek_api_key:
                    raise ValueError("DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek")
                self._client = openai.OpenAI(
                    api_key=self.config.deepseek_api_key,
                    base_url="https://api.deepseek.com",
                    max_retries=0,
                )
            elif self.provider_name == "zai":
                if not self.config.zai_api_key:
                    raise ValueError("ZAI_API_KEY is required when LLM_PROVIDER=zai")
                self._client = openai.OpenAI(
                    api_key=self.config.zai_api_key,
                    base_url="https://open.bigmodel.cn/api/paas/v4",
                    max_retries=0,
                )
            else:
                if not self.config.openai_api_key:
                    raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
                self._client = openai.OpenAI(
                    api_key=self.config.openai_api_key,
                    max_retries=0,
                )
            log.info(f"Initialized {self.provider_name} provider (model: {self.model})")

        elif self.provider_name == "claude":
            import anthropic

            api_key = (self.config.anthropic_api_key or "").strip()
            auth_token = (self.config.anthropic_auth_token or "").strip()
            base_url = (self.config.anthropic_base_url or "").strip()
            normalized_base = base_url.rstrip("/")

            if not api_key and not auth_token:
                raise ValueError(
                    "ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN is required when LLM_PROVIDER=claude"
                )

            auth_mode = "api_key"
            kwargs: dict[str, object] = {"base_url": base_url}
            if auth_token:
                if api_key:
                    log.warning(
                        "同时设置了 ANTHROPIC_API_KEY 和 ANTHROPIC_AUTH_TOKEN；"
                        "优先使用 ANTHROPIC_AUTH_TOKEN。"
                    )
                kwargs["auth_token"] = auth_token
                auth_mode = "auth_token"
            else:
                kwargs["api_key"] = api_key

            self._claude_api_key = api_key
            self._claude_auth_token = auth_token
            self._claude_base_url = normalized_base
            self._claude_custom_base = normalized_base != OFFICIAL_ANTHROPIC_BASE_URL
            self._client = anthropic.Anthropic(**kwargs)
            log.info(f"Initialized Claude provider (model: {self.model})")
            log.info(f"Claude auth mode: {auth_mode}")

        elif self.provider_name == "gemini":
            import google.generativeai as genai

            if not self.config.gemini_api_key:
                raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
            genai.configure(api_key=self.config.gemini_api_key)
            self._client = genai.GenerativeModel(self.model)
            log.info(f"Initialized Gemini provider (model: {self.model})")

        else:
            raise ValueError(
                f"Unknown provider: {self.provider_name!r}. "
                f"Supported: openai, xai, claude, gemini, deepseek, zai"
            )

    async def chat(
        self,
        messages: list[dict],
        system_prompt: str = "",
        max_output_tokens: int | None = None,
    ) -> str:
        """
        向 LLM 发送消息并以纯字符串形式返回响应。

        参数：
            messages: {"role": "user"|"assistant", "content": "..."} 字典列表。
            system_prompt: 在开头注入的系统提示。
            max_output_tokens: 输出 Token 预算的可选覆盖值。

        返回：
            助手的响应文本。
        """
        try:
            if self.provider_name in ("openai", "xai", "deepseek", "zai"):
                return await self._chat_openai(messages, system_prompt, max_output_tokens)
            elif self.provider_name == "claude":
                return await self._chat_claude(messages, system_prompt, max_output_tokens)
            elif self.provider_name == "gemini":
                return await self._chat_gemini(messages, system_prompt, max_output_tokens)
        except Exception as e:
            err_text = str(e)
            lower_err = err_text.lower()
            if self.provider_name == "zai" and (
                "1113" in err_text
                or "余额不足" in err_text
                or "无可用资源包" in err_text
            ):
                log.error(f"LLM call failed ({self.provider_name}): {e}")
                return (
                    "⚠️ Error communicating with zai: account balance/package is exhausted "
                    "(provider code 1113). Recharge your ZAI account or switch provider."
                )
            if "429" in lower_err and "too many requests" in lower_err:
                log.error(f"LLM call failed ({self.provider_name}): {e}")
                return (
                    f"⚠️ Error communicating with {self.provider_name}: rate limit hit (429). "
                    "Please retry in a moment."
                )
            log.error(f"LLM call failed ({self.provider_name}): {e}")
            return f"⚠️ Error communicating with {self.provider_name}: {e}"

    # ── OpenAI / xAI ──────────────────────────────────────────

    async def _chat_openai(
        self,
        messages: list[dict],
        system_prompt: str,
        max_output_tokens: int | None = None,
    ) -> str:
        """通过 OpenAI 兼容 API 聊天（ChatGPT/xAI/DeepSeek/Z-AI）。"""
        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.extend(messages)

        output_tokens = max(256, int(max_output_tokens or self.max_output_tokens))
        try:
            response = await asyncio.to_thread(
                self._client.chat.completions.create,
                model=self.model,
                messages=api_messages,
                max_tokens=output_tokens,
                temperature=0.7,
            )
        except Exception as e:
            err_text = str(e).lower()
            limit_related = any(
                marker in err_text
                for marker in (
                    "max_tokens",
                    "max token",
                    "max output",
                    "out of range",
                    "too large",
                    "exceed",
                    "greater than",
                    "must be less",
                )
            )
            if output_tokens > 4096 and limit_related:
                log.warning(
                    f"{self.provider_name} rejected max_tokens={output_tokens}; retrying with 4096"
                )
                response = await asyncio.to_thread(
                    self._client.chat.completions.create,
                    model=self.model,
                    messages=api_messages,
                    max_tokens=4096,
                    temperature=0.7,
                )
            else:
                raise
        return response.choices[0].message.content or ""

    # ── Claude ────────────────────────────────────────────────

    async def _chat_claude(
        self,
        messages: list[dict],
        system_prompt: str,
        max_output_tokens: int | None = None,
    ) -> str:
        """通过 Anthropic 的 Messages API 聊天（系统提示为独立参数）。"""
        # Claude 要求用户/助手消息交替出现
        # 从列表中过滤掉所有系统消息
        api_messages = [m for m in messages if m.get("role") in ("user", "assistant")]

        # 确保消息以用户消息开头
        if not api_messages or api_messages[0]["role"] != "user":
            api_messages.insert(0, {"role": "user", "content": "Hello!"})

        output_tokens = max(256, int(max_output_tokens or self.max_output_tokens))
        kwargs = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": output_tokens,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        if self._claude_custom_base:
            return await self._chat_claude_http_compat(
                messages=api_messages,
                system_prompt=system_prompt,
                max_tokens=output_tokens,
            )

        connection_markers = (
            "connection error",
            "timed out",
            "timeout",
            "network",
            "temporary failure",
            "name or service not known",
        )

        last_error: Exception | None = None
        response = None
        for attempt in range(3):
            try:
                response = await asyncio.to_thread(self._client.messages.create, **kwargs)
                break
            except Exception as e:
                last_error = e
                err_text = str(e).lower()
                if output_tokens > 4096 and "max_tokens" in err_text:
                    log.warning(f"claude rejected max_tokens={output_tokens}; retrying with 4096")
                    kwargs["max_tokens"] = 4096
                    output_tokens = 4096
                    continue

                if any(marker in err_text for marker in connection_markers) and attempt < 2:
                    await asyncio.sleep(0.35 * (attempt + 1))
                    continue
                break

        if response is None:
            raise last_error if last_error is not None else RuntimeError("Claude request failed")

        # Extract text from content blocks
        text_parts = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
        return "\n".join(text_parts)

    async def _chat_claude_http_compat(
        self,
        messages: list[dict],
        system_prompt: str,
        max_tokens: int,
    ) -> str:
        """针对 SDK 传输间歇性失败的 Anthropic 兼容代理的回退方案。"""
        import httpx

        url = f"{self._claude_base_url}/v1/messages"
        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self._claude_auth_token:
            headers["authorization"] = f"Bearer {self._claude_auth_token}"
        elif self._claude_api_key:
            headers["x-api-key"] = self._claude_api_key
        else:
            raise RuntimeError("Missing Claude credentials for HTTP compatibility fallback.")

        payload: dict[str, object] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if system_prompt:
            payload["system"] = system_prompt

        def _post() -> tuple[int, str]:
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                resp = client.post(url, headers=headers, json=payload)
            return resp.status_code, resp.text

        status_code = 0
        body_text = ""
        for attempt in range(3):
            try:
                status_code, body_text = await asyncio.to_thread(_post)
                break
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(0.35 * (attempt + 1))
                    continue
                raise RuntimeError(f"Claude compatibility HTTP connection error: {e}") from e
        if status_code >= 400:
            detail = (body_text or "").strip().replace("\n", " ")[:240]
            raise RuntimeError(
                f"Claude compatibility HTTP error {status_code}: {detail or 'empty response'}"
            )

        try:
            import json

            data = json.loads(body_text)
        except Exception as e:
            raise RuntimeError(f"Claude compatibility HTTP parse error: {e}") from e

        content = data.get("content")
        if not isinstance(content, list):
            raise RuntimeError("Claude compatibility HTTP response missing content blocks.")
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "\n".join(parts)
        return ""

    # ── Gemini ────────────────────────────────────────────────

    async def _chat_gemini(
        self,
        messages: list[dict],
        system_prompt: str,
        max_output_tokens: int | None = None,
    ) -> str:
        """通过 Google Gemini 的 GenerativeModel API 聊天。"""
        import google.generativeai as genai

        # 如果提供了系统指令，则重新构建模型
        if system_prompt:
            model = genai.GenerativeModel(
                self.model,
                system_instruction=system_prompt,
            )
        else:
            model = self._client

        # 将消息转换为 Gemini 的格式
        gemini_history = []
        for msg in messages[:-1]:  # 除最后一条外全部包含（最后一条是当前提示）
            role = "user" if msg["role"] == "user" else "model"
            gemini_history.append({"role": role, "parts": [msg["content"]]})

        chat = model.start_chat(history=gemini_history)

        # 发送最后一条消息
        last_msg = messages[-1]["content"] if messages else "Hello!"
        response = await asyncio.to_thread(chat.send_message, last_msg)

        return response.text or ""
