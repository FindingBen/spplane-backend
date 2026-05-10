import json
import logging
from abc import ABC, abstractmethod

import requests
from django.conf import settings
from pydantic import BaseModel, Field, ValidationError as PydanticValidationError

logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """Raised when the configured LLM client fails to return valid content."""


class ProductCopyPayload(BaseModel):
    hero_title: str = ""
    hero_subtitle: str = ""
    pain_point: str = ""
    benefit_bullets: list[str] = Field(default_factory=list)
    cta_label: str = "Shop now"
    urgency_message: str | None = None
    bundle_headline: str | None = None
    bundle_items: list[str] = Field(default_factory=list)
    price_caption: str | None = None
    tag_line: str | None = None


class LLMClient(ABC):
    provider_name = "base"

    @abstractmethod
    def generate_product_copy(
        self,
        *,
        product_data: dict,
        rule_analysis: dict,
        template_structure: dict,
    ) -> ProductCopyPayload:
        raise NotImplementedError


class OpenAIWrapper:
    """Thin wrapper around the OpenAI chat completions HTTP API."""

    def __init__(self, *, api_key: str, model: str, api_base_url: str, timeout: int):
        self._api_key = api_key
        self._model = model
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout = timeout

    def create_json_completion(self, *, system_prompt: str, user_prompt: str) -> dict:
        if not self._api_key:
            raise LLMClientError("OPENAI_API_KEY is not configured.")

        try:
            response = requests.post(
                f"{self._api_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "temperature": 0.4,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise LLMClientError("OpenAI request failed.") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise LLMClientError("OpenAI returned an invalid JSON response.") from exc

        if response.status_code >= 400:
            raise LLMClientError(f"OpenAI HTTP error: {response.status_code} {body}")

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMClientError(f"OpenAI response was missing message content: {body}") from exc

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMClientError("OpenAI returned non-JSON content in JSON mode.") from exc


class OpenAILLMClient(LLMClient):
    provider_name = "openai"

    def __init__(self, wrapper: OpenAIWrapper):
        self._wrapper = wrapper

    def generate_product_copy(
        self,
        *,
        product_data: dict,
        rule_analysis: dict,
        template_structure: dict,
    ) -> ProductCopyPayload:
        template_summary = []
        components = template_structure.get("components") or template_structure.get("blocks") or []
        for component in components:
            if not isinstance(component, dict):
                continue

            props = component.get("props") or {}
            template_summary.append(
                {
                    "id": component.get("id"),
                    "type": component.get("type"),
                    "prop_keys": sorted(props.keys()) if isinstance(props, dict) else [],
                }
            )

        system_prompt = (
            "You generate concise ecommerce landing page copy from factual product data. "
            "Never invent product features, certifications, or medical claims. "
            "Use only the provided facts and return a JSON object matching the requested keys. "
            "If a field is unsupported by the data, return an empty string or empty list."
        )
        user_prompt = json.dumps(
            {
                "task": "Generate constrained landing page copy for the supplied template structure.",
                "expected_keys": ProductCopyPayload.model_json_schema()["properties"],
                "product": product_data,
                "rules": rule_analysis,
                "template": template_summary,
            },
            ensure_ascii=True,
        )

        payload = self._wrapper.create_json_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        try:
            return ProductCopyPayload.model_validate(payload)
        except PydanticValidationError as exc:
            raise LLMClientError(f"OpenAI returned invalid product copy payload: {exc}") from exc


class DeterministicLLMClient(LLMClient):
    provider_name = "deterministic"

    def generate_product_copy(
        self,
        *,
        product_data: dict,
        rule_analysis: dict,
        template_structure: dict,
    ) -> ProductCopyPayload:
        del template_structure

        title = (product_data.get("title") or "Discover this product").strip()
        description = (
            product_data.get("seo_description")
            or product_data.get("description_text")
            or product_data.get("seo_title")
            or title
        ).strip()
        tags = product_data.get("tags") or []
        variant_titles = [
            item.get("title")
            for item in rule_analysis.get("variant_items", [])
            if item.get("title")
        ]
        benefits = []
        if description:
            benefits.append(description)
        if tags:
            benefits.append(f"Best for {', '.join(tags[:3])}")
        if product_data.get("has_out_of_stock_variants") is False:
            benefits.append("Available now")

        hero_title = self._headline_from_product(title)
        return ProductCopyPayload(
            hero_title=hero_title,
            hero_subtitle=description,
            pain_point=hero_title,
            benefit_bullets=benefits[:3],
            cta_label="Shop now",
            urgency_message=rule_analysis.get("urgency_message"),
            bundle_headline=("Choose your preferred option" if len(variant_titles) > 1 else None),
            bundle_items=variant_titles,
            price_caption=rule_analysis.get("price_label"),
            tag_line=(", ".join(tags[:3]) if tags else None),
        )

    @staticmethod
    def _headline_from_product(title: str) -> str:
        lowered = title.lower()
        if "shoulder" in lowered and "massager" in lowered:
            return "Relieve shoulder tension fast"
        if "menstrual" in lowered or "heating pad" in lowered:
            return "Comfort when you need it most"
        if "massager" in lowered:
            return "Relax sore muscles on your schedule"
        if "portable" in lowered:
            return "Relief that moves with you"
        return title


def build_llm_client() -> LLMClient:
    api_key = getattr(settings, "OPENAI_API_KEY", "")
    if not api_key:
        logger.info("Product content generation: OPENAI_API_KEY missing, using deterministic fallback.")
        return DeterministicLLMClient()

    wrapper = OpenAIWrapper(
        api_key=api_key,
        model=getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"),
        api_base_url=getattr(settings, "OPENAI_API_BASE_URL", "https://api.openai.com/v1"),
        timeout=getattr(settings, "OPENAI_TIMEOUT_SECONDS", 30),
    )
    return OpenAILLMClient(wrapper)