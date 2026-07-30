"""AI Text plugin — generates and displays text from OpenAI, Gemini, or DeepSeek.

Ported from the original OpenClaw-DashPi project. The original implementation
generated text via the configured provider, then rendered it on a PIL image
with a centered title (with underline) and a quoted, centered body block. This
web version keeps all of the generation logic (provider routing, joke special
handling, DeepSeek reasoning fallback) and returns the generated text plus the
configured colors for the frontend ``dashboard.html`` fragment to render. The
PIL rendering helpers and CJK font selection have been removed; the browser
handles font fallback natively.
"""

import logging
import random
from datetime import datetime

from plugins.base_plugin.base_plugin import BasePlugin

logger = logging.getLogger(__name__)

# OpenAI models
OPENAI_TEXT_MODELS = ["gpt-4o-mini", "gpt-4o", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "gpt-5", "gpt-5-mini", "gpt-5-nano"]
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

# Gemini models (use full model names for new API)
GEMINI_TEXT_MODELS = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash"]
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"

# DeepSeek models (OpenAI-compatible API at https://api.deepseek.com)
DEEPSEEK_TEXT_MODELS = ["deepseek-v4-flash", "deepseek-v4-pro"]
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class AIText(BasePlugin):
    """Sends a prompt to an AI model and returns the generated text for display."""

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['api_key'] = {
            "required": False,
            "service": "OpenAI, Google Gemini, or DeepSeek",
            "expected_key": "OPEN_AI_SECRET, GOOGLE_GEMINI_SECRET, or DEEPSEEK_SECRET"
        }
        template_params['style_settings'] = True
        return template_params

    def get_data(self, settings, device_config):
        """Generate text via the configured AI provider and return it for display.

        Args:
            settings: Plugin settings dict containing ``provider``,
                ``textPrompt``, ``title``, ``textModel``/``geminiTextModel``/
                ``deepseekTextModel``, ``backgroundColor``, and ``textColor``.
            device_config: Device configuration object (used by the provider
                methods to load API keys).

        Returns:
            dict: ``{title: str, text: str, background_color: str,
            text_color: str}`` for the frontend.
        """
        logger.info("=== AI Text Plugin: Starting text generation ===")

        provider = settings.get("provider", "openai")
        text_prompt = settings.get('textPrompt', '')

        # Use provided title, or auto-generate from prompt
        title = settings.get("title") or ""
        if not title and text_prompt:
            title = text_prompt.strip()
            if len(title) > 40:
                title = title[:37] + "..."

        if not text_prompt.strip():
            raise RuntimeError("Text Prompt is required.")

        logger.info(f"Provider: {provider}")
        logger.debug(f"Prompt: '{text_prompt}'")

        if provider == "gemini":
            prompt_response = self._generate_with_gemini(settings, device_config, text_prompt)
        elif provider == "deepseek":
            prompt_response = self._generate_with_deepseek(settings, device_config, text_prompt)
        else:
            prompt_response = self._generate_with_openai(settings, device_config, text_prompt)

        # Convert literal \n to actual newlines for the frontend
        formatted_response = prompt_response.replace('\\n', '\n')

        # Colors (default to light theme if unset)
        background_color = settings.get("backgroundColor", "#ffffff")
        text_color = settings.get("textColor", "#000000")

        logger.info("=== AI Text Plugin: Text generation complete ===")
        return {
            "title": title,
            "text": formatted_response,
            "background_color": background_color,
            "text_color": text_color,
        }

    # ------------------------------------------------------------------
    # Provider: OpenAI
    # ------------------------------------------------------------------
    def _generate_with_openai(self, settings, device_config, text_prompt):
        """Generate text using OpenAI."""
        from openai import OpenAI

        api_key = device_config.load_env_key("OPEN_AI_SECRET")
        if not api_key:
            raise RuntimeError("OpenAI API Key not configured. Add OPEN_AI_SECRET in Settings > API Keys.")

        api_key = api_key.encode('ascii', errors='ignore').decode('ascii').strip()

        text_model = settings.get('textModel', DEFAULT_OPENAI_MODEL)
        if text_model not in OPENAI_TEXT_MODELS:
            logger.warning(f"Unknown OpenAI model: {text_model}, using anyway")

        logger.info(f"OpenAI Settings: model={text_model}")

        try:
            ai_client = OpenAI(api_key=api_key)
            return self._fetch_openai_text(ai_client, text_model, text_prompt)
        except Exception as e:
            logger.error(f"Failed to make OpenAI request: {str(e)}")
            raise RuntimeError("OpenAI request failure, please check logs.")

    # ------------------------------------------------------------------
    # Provider: Google Gemini
    # ------------------------------------------------------------------
    def _generate_with_gemini(self, settings, device_config, text_prompt):
        """Generate text using Google Gemini."""
        api_key = device_config.load_env_key("GOOGLE_GEMINI_SECRET")
        if not api_key:
            raise RuntimeError("Google Gemini API Key not configured. Add GOOGLE_GEMINI_SECRET in Settings > API Keys.")

        api_key = api_key.encode('ascii', errors='ignore').decode('ascii').strip()

        text_model = settings.get('geminiTextModel', DEFAULT_GEMINI_MODEL)

        logger.info(f"Gemini Settings: model={text_model}")

        try:
            from google import genai

            client = genai.Client(api_key=api_key)

            # Add randomness to prevent cached/repeated responses
            random_seed = random.randint(1, 1000000)

            # Check if prompt is asking for a joke - use special handling
            prompt_lower = text_prompt.lower()
            is_joke_request = any(word in prompt_lower for word in ["joke", "funny", "humor", "laugh", "pun"])

            if is_joke_request:
                # Random variety injectors for joke prompts
                styles = ["witty", "clever", "silly", "dry", "absurd", "punny", "observational", "surreal", "dark", "wholesome"]
                topics = ["technology", "food", "animals", "work", "relationships", "science", "history", "sports", "music", "travel"]
                random_style = random.choice(styles)
                random_topic = random.choice(topics)

                system_prompt = (
                    f"You are a {random_style} comedian who never repeats jokes. "
                    "Keep responses under 70 words. Be creative and original. "
                    "Respond directly without introductions or explanations."
                )

                # For generic joke requests, inject variety
                if len(text_prompt.split()) < 6:
                    enhanced_prompt = f"{text_prompt} (make it {random_style}, maybe about {random_topic})"
                else:
                    enhanced_prompt = text_prompt
            else:
                # General-purpose text generation
                system_prompt = (
                    "You are a helpful and creative text generation assistant. "
                    "Keep responses under 70 words. Be concise and relevant. "
                    "Respond directly without introductions or explanations."
                )
                enhanced_prompt = text_prompt

            full_prompt = f"{system_prompt}\n\nUser request: {enhanced_prompt}"
            response = client.models.generate_content(
                model=text_model,
                contents=full_prompt,
                config={
                    "temperature": 2.0,
                    "seed": random_seed
                }
            )
            result = response.text.strip()

            logger.info(f"Generated text response: {result[:100]}...")
            return result

        except ImportError:
            logger.error("google-genai package not installed")
            raise RuntimeError("Google Gemini SDK not installed. Run: pip install google-genai")
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to make Gemini request: {error_msg}")

            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                raise RuntimeError("Gemini rate limit reached. Please wait a minute and try again, or try a different model.")
            elif "API_KEY" in error_msg.upper() or "401" in error_msg:
                raise RuntimeError("Gemini API key is invalid. Please check your GOOGLE_GEMINI_SECRET in Settings > API Keys.")
            elif "404" in error_msg:
                raise RuntimeError("Gemini model not found. Please select a different model.")
            else:
                raise RuntimeError(f"Gemini error: {error_msg[:100]}")

    # ------------------------------------------------------------------
    # Provider: DeepSeek (OpenAI-compatible API)
    # ------------------------------------------------------------------
    def _generate_with_deepseek(self, settings, device_config, text_prompt):
        """Generate text using DeepSeek via its OpenAI-compatible API."""
        from openai import OpenAI

        api_key = device_config.load_env_key("DEEPSEEK_SECRET")
        if not api_key:
            raise RuntimeError("DeepSeek API Key not configured. Add DEEPSEEK_SECRET in Settings > API Keys.")

        api_key = api_key.encode('ascii', errors='ignore').decode('ascii').strip()

        text_model = settings.get('deepseekTextModel', DEFAULT_DEEPSEEK_MODEL)
        if text_model not in DEEPSEEK_TEXT_MODELS:
            logger.warning(f"Unknown DeepSeek model: {text_model}, using anyway")

        logger.info(f"DeepSeek Settings: model={text_model}")

        try:
            # DeepSeek accepts the OpenAI SDK with a custom base_url.
            # Disable thinking mode for this short-text-generation use case:
            # V4 models default to thinking mode, which emits reasoning_content
            # and can leave `content` empty when the reasoning exhausts the
            # token budget. Non-thinking mode returns the answer directly in
            # `content` and is faster.
            ai_client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
            return self._fetch_openai_text(
                ai_client, text_model, text_prompt,
                extra_body={"thinking": {"type": "disabled"}},
            )
        except RuntimeError:
            raise
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to make DeepSeek request: {error_msg}")

            if "429" in error_msg:
                raise RuntimeError("DeepSeek rate limit reached. Please wait a minute and try again.")
            elif "401" in error_msg or "API_KEY" in error_msg.upper():
                raise RuntimeError("DeepSeek API key is invalid. Please check your DEEPSEEK_SECRET in Settings > API Keys.")
            elif "404" in error_msg:
                raise RuntimeError("DeepSeek model not found. Please select a different model.")
            else:
                raise RuntimeError(f"DeepSeek error: {error_msg[:100]}")

    def _fetch_openai_text(self, ai_client, model, text_prompt, extra_body=None):
        """Fetch text response from an OpenAI-compatible chat completions API.

        Handles both OpenAI and DeepSeek. For DeepSeek V4 reasoning models the
        final answer lives in `content` while the chain-of-thought is exposed
        via `reasoning_content`; we fall back to the latter if `content` is
        empty so the display is never blank.
        """
        logger.info(f"Getting text response, model: {model}")

        system_content = (
            "You are a highly intelligent text generation assistant. Generate concise, "
            "relevant, and accurate responses tailored to the user's input. The response "
            "should be 70 words or less."
            "IMPORTANT: Do not rephrase, reword, or provide an introduction. Respond directly "
            "to the request without adding explanations or extra context "
            "IMPORTANT: If the response naturally requires a newline for formatting, provide "
            "the '\n' newline character explicitly for every new line. For regular sentences "
            "or paragraphs do not provide the new line character."
            f"For context, today is {datetime.today().strftime('%Y-%m-%d')}"
        )

        request_kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": text_prompt}
            ],
            "temperature": 1,
            # Reasoning models (e.g. DeepSeek V4 in thinking mode) can consume
            # the default token budget on chain-of-thought, leaving `content`
            # empty. 2048 comfortably covers the 70-word target plus reasoning.
            "max_tokens": 2048,
        }
        if extra_body:
            request_kwargs["extra_body"] = extra_body

        response = ai_client.chat.completions.create(**request_kwargs)

        message = response.choices[0].message
        result = (message.content or "").strip()

        if not result:
            # DeepSeek reasoning models expose the chain-of-thought via
            # reasoning_content; use it as a fallback so the display is
            # never blank.
            reasoning = getattr(message, "reasoning_content", None)
            if reasoning:
                logger.warning("Empty content, falling back to reasoning_content")
                result = reasoning.strip()

        if not result:
            raise RuntimeError("AI model returned an empty response.")

        logger.info(f"Generated text response: {result[:100]}...")
        return result
