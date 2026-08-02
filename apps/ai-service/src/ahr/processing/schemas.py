"""Validated contract for LLM enrichment output.

AHR-SPEC-000 §8: LLM output must pass schema validation before it can be
stored. AHR-ROADMAP-800 forbids writing free text into structured columns when
parsing fails — a failure becomes a dead letter instead.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

ContentType = Literal[
    "model_release",
    "product_release",
    "api_update",
    "research",
    "open_source",
    "business",
    "policy",
    "security",
    "opinion",
    "tutorial",
]

# ADR-0014: aligned with config/taxonomy.yaml. The extra three matter because
# a university is not a company, MCP is not a product, and LangChain is not a
# technology — collapsing them writes a wrong fact at the data layer.
EntityType = Literal[
    "company",
    "organization",
    "product",
    "model",
    "technology",
    "protocol",
    "framework",
    "person",
]
EntityRole = Literal["subject", "object", "mention"]


class ExtractedEntity(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: EntityType
    role: EntityRole = "mention"
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class ExtractedTopic(BaseModel):
    slug: str = Field(min_length=1, max_length=80)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class QualityFactors(BaseModel):
    relevance: int = Field(ge=0, le=100, default=50)
    information_gain: int = Field(ge=0, le=100, default=50)
    technical_depth: int = Field(ge=0, le=100, default=50)
    spam_penalty: int = Field(ge=0, le=100, default=0)


class EnrichmentResult(BaseModel):
    """The structured view of one article."""

    summary_zh: str = Field(min_length=1, max_length=1200)
    zh_title: str = Field(min_length=1, max_length=300)
    content_type: ContentType
    entities: list[ExtractedEntity] = Field(default_factory=list, max_length=25)
    topics: list[ExtractedTopic] = Field(default_factory=list, max_length=10)
    quality_factors: QualityFactors = Field(default_factory=QualityFactors)

    @field_validator("entities")
    @classmethod
    def drop_blank_entities(cls, value: list[ExtractedEntity]) -> list[ExtractedEntity]:
        return [entity for entity in value if entity.name.strip()]

    def quality_score(self, *, source_authority: int) -> float:
        """Weighted 0-100 score.

        Follows AHR-PRD-100 §4 for the factors available at this stage. The
        evidence and editorial terms need Story context, so they arrive in M3;
        the weights here are renormalised over what exists rather than silently
        scoring the missing terms as zero.
        """
        factors = self.quality_factors
        weighted = (
            0.30 * source_authority
            + 0.25 * factors.relevance
            + 0.25 * factors.information_gain
            + 0.20 * factors.technical_depth
        )
        return round(max(0.0, min(weighted - factors.spam_penalty, 100.0)), 2)


# Kept in the repository so a prompt change is reviewable and versioned
# (AHR-SPEC-000 §8 requires prompt and model versions to be recorded).
PROMPT_VERSION = "enrich-v2"

SYSTEM_PROMPT = """你是 AI 行业情报分析助手。请阅读给定的资讯正文，输出结构化 JSON。

严格要求：
1. 只输出 JSON，不要输出任何解释、markdown 代码块或额外文字。
2. summary_zh：用中文写 2-4 句摘要，覆盖「谁、做了什么、影响是什么」。只能基于正文事实，禁止推测或补充正文没有的信息。
3. zh_title：中文标题，不超过 40 字，忠实于原标题含义。
4. content_type 必须是以下之一：model_release, product_release, api_update, research, open_source, business, policy, security, opinion, tutorial。
5. entities：正文中出现的实体。type 必须是以下之一：
   - company：商业公司（OpenAI、字节跳动）
   - organization：大学、标准组织、非营利机构（Stanford、Linux Foundation）
   - product：产品或平台（ChatGPT、Claude Code）
   - model：具体模型（GPT-5.6、DeepSeek-V4）
   - technology：技术方法（RAG、量化、蒸馏）
   - protocol：协议或规范（MCP、OpenAI 兼容 API）
   - framework：框架或库（LangChain、vLLM、PyTorch）
   - person：人物
   role 用 subject（主角）|object（被涉及）|mention（提及）。
6. topics：用小写英文 slug，如 agent、rag、multimodal、inference、training、safety。
7. quality_factors 各项 0-100：relevance（与 AI 行业相关度）、information_gain（相比常识的新增信息量）、technical_depth（技术深度）、spam_penalty（营销水分，越高越差）。

输出格式：
{"summary_zh":"...","zh_title":"...","content_type":"...","entities":[{"name":"OpenAI","type":"company","role":"subject","confidence":0.9}],"topics":[{"slug":"agent","confidence":0.8}],"quality_factors":{"relevance":90,"information_gain":70,"technical_depth":60,"spam_penalty":0}}"""

REPAIR_PROMPT = """上一次输出不是合法 JSON 或不符合字段要求。错误信息：

{error}

请只输出修正后的 JSON，不要任何其他文字。"""
