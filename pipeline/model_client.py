"""
统一 LLM 客户端 — 工厂模式封装多模型调用

支持 Anthropic(Claude)、DeepSeek、Qwen、OpenAI，通过环境变量切换。
返回统一格式：LLMResponse(content, usage)

环境变量：
    LLM_PROVIDER        选择提供商（anthropic/deepseek/qwen/openai），默认 anthropic
    ANTHROPIC_API_KEY   Claude API Key
    DEEPSEEK_API_KEY    DeepSeek API Key
    QWEN_API_KEY        Qwen API Key
    OPENAI_API_KEY      OpenAI API Key
"""

from __future__ import annotations

import os
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ── 数据结构 ──────────────────────────────────────────────────────────────

@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class LLMResponse:
    content: str
    usage: Usage = field(default_factory=Usage)
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "usage": self.usage.to_dict(),
            "model": self.model,
        }


# ── 成本估算（每 1K tokens，单位 USD） ────────────────────────────────────

PRICING: dict[str, dict[str, float]] = {
    # Anthropic Claude（直连 & gateway）
    "claude-haiku-4-5-20251001":       {"input": 0.00080, "output": 0.00400},
    "anthropic/claude-haiku-4.5":      {"input": 0.00080, "output": 0.00400},
    "claude-sonnet-4-6":               {"input": 0.00300, "output": 0.01500},
    "anthropic/claude-sonnet-4.5":     {"input": 0.00300, "output": 0.01500},
    "anthropic/claude-sonnet-4.6":     {"input": 0.00300, "output": 0.01500},
    "claude-opus-4-7":                 {"input": 0.01500, "output": 0.07500},
    # DeepSeek
    "deepseek-chat":                   {"input": 0.00014, "output": 0.00028},
    "deepseek/deepseek-v3.2":          {"input": 0.00014, "output": 0.00028},
    "deepseek-reasoner":               {"input": 0.00055, "output": 0.00219},
    "deepseek/deepseek-v4-pro":        {"input": 0.00055, "output": 0.00219},
    # Qwen
    "qwen-plus":                       {"input": 0.00040, "output": 0.00120},
    "qwen/qwen3-coder-next":           {"input": 0.00040, "output": 0.00120},
    "qwen3.6-plus":                    {"input": 0.00040, "output": 0.00120},
    "qwen-turbo":                      {"input": 0.00005, "output": 0.00010},
    # OpenAI
    "gpt-4o-mini":                     {"input": 0.00015, "output": 0.00060},
    "openai/gpt-5.3-codex":            {"input": 0.00015, "output": 0.00060},
    "gpt-4o":                          {"input": 0.00500, "output": 0.01500},
    "openai/gpt-5.4":                  {"input": 0.00500, "output": 0.01500},
    # Gateway 专属模型
    "google/gemini-3.1-pro-preview":   {"input": 0.00125, "output": 0.00500},
    "moonshotai/kimi-k2.5":            {"input": 0.00060, "output": 0.00240},
    "moonshotai/kimi-k2.6":            {"input": 0.00060, "output": 0.00240},
    "minimax/minimax-m2.5":            {"input": 0.00030, "output": 0.00120},
    "minimax/minimax-m2.7":            {"input": 0.00030, "output": 0.00120},
    "z-ai/glm-5":                      {"input": 0.00020, "output": 0.00080},
    "z-ai/glm-5.1":                    {"input": 0.00020, "output": 0.00080},
}


def estimate_cost(model: str, usage: Usage) -> float:
    prices = PRICING.get(model, {"input": 0.002, "output": 0.006})
    return (
        usage.prompt_tokens / 1000 * prices["input"]
        + usage.completion_tokens / 1000 * prices["output"]
    )


# ── Provider 抽象基类 ─────────────────────────────────────────────────────

class LLMProvider(ABC):
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    @abstractmethod
    def chat(
        self,
        messages: list[dict[str, str]],
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        ...

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# ── Anthropic Provider ────────────────────────────────────────────────────

class AnthropicProvider(LLMProvider):
    """使用官方 anthropic SDK 调用 Claude 系列模型。"""

    def __init__(self, api_key: str, model: str):
        super().__init__(api_key, model)
        try:
            import anthropic as _anthropic
            self._client = _anthropic.Anthropic(api_key=api_key)
        except ImportError:
            raise RuntimeError("请安装 anthropic SDK: pip install anthropic")

    def chat(
        self,
        messages: list[dict[str, str]],
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        resp = self._client.messages.create(**kwargs)
        content = resp.content[0].text
        usage = Usage(
            prompt_tokens=resp.usage.input_tokens,
            completion_tokens=resp.usage.output_tokens,
        )
        return LLMResponse(content=content, usage=usage, model=self.model)

    def close(self) -> None:
        pass


# ── Gateway Provider ─────────────────────────────────────────────────────

class GatewayProvider(LLMProvider):
    """
    统一 Gateway Provider。
    端点声称 OpenAI-compatible，但实际返回 Anthropic Messages 格式：
      {"content": [{"text": "..."}], "usage": {"input_tokens": N, "output_tokens": N}}
    """

    def __init__(self, api_key: str, base_url: str, model: str):
        super().__init__(api_key, model)
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(timeout=60.0)

    def chat(
        self,
        messages: list[dict[str, str]],
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        resp = self._http.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": all_messages,
                  "temperature": temperature, "max_tokens": max_tokens},
        )
        resp.raise_for_status()
        data = resp.json()

        # 兼容两种响应格式
        if "choices" in data:
            # 标准 OpenAI 格式
            content = data["choices"][0]["message"]["content"]
            u = data.get("usage", {})
            usage = Usage(
                prompt_tokens=u.get("prompt_tokens", 0),
                completion_tokens=u.get("completion_tokens", 0),
            )
        else:
            # Anthropic Messages 格式（gateway 实际返回）
            content = data["content"][0]["text"]
            u = data.get("usage", {})
            usage = Usage(
                prompt_tokens=u.get("input_tokens", 0),
                completion_tokens=u.get("output_tokens", 0),
            )

        return LLMResponse(content=content, usage=usage, model=self.model)

    def close(self) -> None:
        self._http.close()


# ── OpenAI 兼容 Provider（DeepSeek / Qwen / OpenAI）─────────────────────

class OpenAICompatibleProvider(LLMProvider):
    """兼容 OpenAI Chat Completions API 的提供商。"""

    def __init__(self, api_key: str, base_url: str, model: str):
        super().__init__(api_key, model)
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(timeout=60.0)

    def chat(
        self,
        messages: list[dict[str, str]],
        system: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        resp = self._http.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model, "messages": all_messages,
                  "temperature": temperature, "max_tokens": max_tokens},
        )
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"]
        u = data.get("usage", {})
        usage = Usage(
            prompt_tokens=u.get("prompt_tokens", 0),
            completion_tokens=u.get("completion_tokens", 0),
        )
        return LLMResponse(content=content, usage=usage, model=self.model)

    def close(self) -> None:
        self._http.close()


# ── 工厂配置 ──────────────────────────────────────────────────────────────

PROVIDER_CONFIG: dict[str, dict[str, str]] = {
    "anthropic": {
        "api_key_env":    "ANTHROPIC_API_KEY",
        "default_model":  "claude-haiku-4-5-20251001",
    },
    # 统一 Gateway（OpenAI-compatible，单 Key 访问所有模型）
    # 支持: anthropic/claude-*, deepseek/deepseek-v*, qwen/qwen3-*,
    #        google/gemini-*, moonshotai/kimi-*, minimax/*, openai/gpt-*, z-ai/glm-*
    "gateway": {
        "api_key_env":       "GATEWAY_API_KEY",
        "base_url_env":      "GATEWAY_BASE_URL",
        "model_env":         "GATEWAY_MODEL",
        "default_base_url":  "https://ai-service-multimodal-gateway-pre.fulltrust.link/vibecoding-openai/v1",
        "default_model":     "anthropic/claude-haiku-4.5",
    },
    "deepseek": {
        "api_key_env":       "DEEPSEEK_API_KEY",
        "base_url_env":      "DEEPSEEK_BASE_URL",
        "model_env":         "DEEPSEEK_MODEL",
        "default_base_url":  "https://api.deepseek.com",
        "default_model":     "deepseek-chat",
    },
    "qwen": {
        "api_key_env":       "QWEN_API_KEY",
        "base_url_env":      "QWEN_BASE_URL",
        "model_env":         "QWEN_MODEL",
        "default_base_url":  "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model":     "qwen-plus",
    },
    "openai": {
        "api_key_env":       "OPENAI_API_KEY",
        "base_url_env":      "OPENAI_BASE_URL",
        "model_env":         "OPENAI_MODEL",
        "default_base_url":  "https://api.openai.com/v1",
        "default_model":     "gpt-4o-mini",
    },
}


def create_provider(provider_name: str | None = None) -> LLMProvider:
    """
    工厂函数：根据提供商名称创建 LLM 客户端。

    默认读取环境变量 LLM_PROVIDER（未设置时使用 anthropic）。
    """
    name = (provider_name or os.getenv("LLM_PROVIDER", "anthropic")).lower()

    if name not in PROVIDER_CONFIG:
        raise ValueError(
            f"未知提供商: {name}，支持: {', '.join(PROVIDER_CONFIG)}"
        )

    config = PROVIDER_CONFIG[name]
    api_key = os.getenv(config["api_key_env"], "")
    if not api_key:
        raise RuntimeError(f"缺少 API Key，请设置: {config['api_key_env']}")

    if name == "anthropic":
        model = os.getenv("ANTHROPIC_MODEL", config["default_model"])
        logger.info("LLM provider=anthropic model=%s", model)
        return AnthropicProvider(api_key=api_key, model=model)

    base_url = os.getenv(config.get("base_url_env", ""), config["default_base_url"])
    model = os.getenv(config.get("model_env", ""), config["default_model"])
    logger.info("LLM provider=%s model=%s", name, model)

    if name == "gateway":
        return GatewayProvider(api_key=api_key, base_url=base_url, model=model)

    return OpenAICompatibleProvider(api_key=api_key, base_url=base_url, model=model)


# ── 带重试的调用封装 ──────────────────────────────────────────────────────

def chat_with_retry(
    provider: LLMProvider,
    messages: list[dict[str, str]],
    system: str = "",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    max_retries: int = 3,
    backoff_base: float = 2.0,
) -> LLMResponse:
    """带指数退避重试的聊天调用。"""
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            resp = provider.chat(
                messages=messages,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if attempt > 0:
                logger.info("第 %d 次重试成功", attempt)
            return resp
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = backoff_base ** attempt
                logger.warning("调用失败（%d/%d），%.1fs 后重试: %s", attempt + 1, max_retries, wait, e)
                time.sleep(wait)
            else:
                logger.error("已达最大重试次数: %s", e)

    raise last_error  # type: ignore[misc]


# ── 便捷函数 ──────────────────────────────────────────────────────────────

def chat(
    prompt: str,
    system: str = "你是一个 AI 技术分析助手。",
    provider: str | None = None,
    max_retries: int = 3,
) -> dict[str, Any]:
    """
    便捷调用，返回 {"content": str, "usage": {...}, "model": str}。
    """
    messages = [{"role": "user", "content": prompt}]
    llm = create_provider(provider)
    try:
        resp = chat_with_retry(llm, messages, system=system, max_retries=max_retries)
        cost = estimate_cost(llm.model, resp.usage)
        logger.info(
            "用量: %d+%d=%d tokens，估算成本: $%.6f",
            resp.usage.prompt_tokens, resp.usage.completion_tokens,
            resp.usage.total_tokens, cost,
        )
        return resp.to_dict()
    finally:
        llm.close()


def quick_chat(prompt: str, **kwargs: Any) -> str:
    """只返回文本内容的便捷函数。"""
    return chat(prompt, **kwargs)["content"]


# ── CLI 测试入口 ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    provider_name = os.getenv("LLM_PROVIDER", "anthropic")
    print(f"=== LLM 客户端测试 (provider={provider_name}) ===\n")

    try:
        result = chat("用一句话介绍什么是 AI Agent。")
        print(f"回复: {result['content']}")
        print(f"模型: {result['model']}")
        print(f"用量: {result['usage']}")
    except Exception as e:
        print(f"错误: {e}")
        print("请检查 .env 文件中的 API Key 配置。")
