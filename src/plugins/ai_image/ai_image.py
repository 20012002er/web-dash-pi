"""AI Image plugin — generates an image via OpenAI, Gemini, or SiliconFlow.

Ported from the original OpenClaw-DashPi project. The original implementation
generated an image via the configured provider, resized it via the adaptive
image loader, added a title overlay with PIL, and returned a rendered image.
This web version keeps all of the generation logic (provider routing, prompt
randomization, news-feed prompt source) but returns a URL the frontend can
render directly:

* DALL-E and SiliconFlow return image URLs — passed through verbatim.
* Gemini (Imagen and native image models) return raw image bytes — saved to
  ``static/images/saved/ai_image_current.png`` and served from there.

The PIL title overlay and the ``image_loader`` have been removed; the frontend
``dashboard.html`` overlays the title via CSS.
"""

import base64
import html
import logging
import os
import random
from io import BytesIO

from plugins.base_plugin.base_plugin import BasePlugin
from utils.http_client import get_http_session

logger = logging.getLogger(__name__)

# Preset RSS news feeds
NEWS_FEEDS = {
    "bbc": ("BBC World News", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    "reuters": ("Reuters Top News", "https://www.rss-bridge.org/bridge01/?action=display&bridge=Reuters&feed=home%2Ftopnews&format=Atom"),
    "ap": ("AP Top News", "https://rsshub.app/apnews/topics/apf-topnews"),
    "npr": ("NPR News", "https://feeds.npr.org/1001/rss.xml"),
    "nyt": ("NY Times Headlines", "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"),
    "tech": ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
    "verge": ("The Verge", "https://www.theverge.com/rss/index.xml"),
}

# OpenAI models
OPENAI_IMAGE_MODELS = ["dall-e-3", "dall-e-2", "gpt-image-1"]
DEFAULT_OPENAI_MODEL = "dall-e-3"

# Gemini models
GEMINI_IMAGEN_MODELS = ["imagen-4.0-generate-001", "imagen-4.0-fast-generate-001", "imagen-4.0-ultra-generate-001"]
GEMINI_NATIVE_MODELS = ["gemini-2.5-flash-image", "gemini-3-pro-image-preview", "gemini-3.1-flash-image-preview"]
GEMINI_IMAGE_MODELS = GEMINI_IMAGEN_MODELS + GEMINI_NATIVE_MODELS
DEFAULT_GEMINI_MODEL = "imagen-4.0-generate-001"

# SiliconFlow models (Kwai-Kolors/Kolors via SiliconFlow)
SILICONFLOW_IMAGE_MODELS = ["Kwai-Kolors/Kolors"]
DEFAULT_SILICONFLOW_MODEL = "Kwai-Kolors/Kolors"
SILICONFLOW_TEXT_MODEL = "Qwen/Qwen3-32B"
SILICONFLOW_IMAGE_API = "https://api.siliconflow.cn/v1/images/generations"
SILICONFLOW_CHAT_API = "https://api.siliconflow.cn/v1/chat/completions"

# Stable filename for the saved Gemini image (served to the browser)
_SAVED_IMAGE_FILENAME = "ai_image_current.png"


class AIImage(BasePlugin):
    """Generates an AI image and returns a URL plus title for the frontend."""

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        # Don't require a specific key - user chooses provider
        template_params['api_key'] = {
            "required": False,
            "service": "OpenAI, Google Gemini, or SiliconFlow",
            "expected_key": "OPEN_AI_SECRET, GOOGLE_GEMINI_SECRET, or SILICONFLOW_SECRET"
        }
        return template_params

    def get_data(self, settings, device_config):
        """Generate an image via the configured provider and return a URL.

        Args:
            settings: Plugin settings dict containing ``provider``,
                ``textPrompt``, ``randomizePrompt``, ``promptSource``,
                ``imageModel``/``geminiImageModel``/``siliconflowImageModel``,
                ``quality``, ``fitMode``, ``showTitle``, ``newsFeeds``, and
                ``customFeedUrl``.
            device_config: Device configuration object, used to load the
                provider API keys and the display orientation.

        Returns:
            dict: ``{image_url: str, title: str}`` for the frontend.
        """
        logger.info("=== AI Image Plugin: Starting image generation ===")

        provider = settings.get("provider", "openai")
        text_prompt = settings.get("textPrompt", "")
        randomize_prompt = settings.get('randomizePrompt') == 'true'
        prompt_source = settings.get("promptSource", "manual")
        orientation = device_config.get_config("orientation")

        logger.info(f"Provider: {provider}, orientation: {orientation}, promptSource: {prompt_source}")

        # If news headlines mode, fetch a headline and use it as the prompt
        original_headline = None
        if prompt_source == "news":
            feed_urls = self._get_selected_feed_urls(settings)
            original_headline = self._fetch_news_headline(feed_urls)
            text_prompt = original_headline
            randomize_prompt = True  # Always randomize for news headlines
            logger.info(f"News headline selected: '{original_headline}'")

        logger.debug(f"Original prompt: '{text_prompt}'")
        logger.debug(f"Randomize prompt: {randomize_prompt}")

        image_url = None
        final_prompt = text_prompt  # Track the actual prompt used

        is_news = prompt_source == "news"
        if provider == "gemini":
            image_url, final_prompt = self._generate_with_gemini(settings, device_config, text_prompt, randomize_prompt, orientation, is_news)
        elif provider == "siliconflow":
            image_url, final_prompt = self._generate_with_siliconflow(settings, device_config, text_prompt, randomize_prompt, orientation, is_news)
        else:
            image_url, final_prompt = self._generate_with_openai(settings, device_config, text_prompt, randomize_prompt, orientation, is_news)

        if image_url:
            logger.info(f"AI image URL ready: {image_url}")

        # Title overlay: use original headline for news, final prompt otherwise
        show_title = settings.get("showTitle", "true") != "false"
        title = original_headline if original_headline else final_prompt
        if title:
            title = title.strip()
            words = title.split()
            if len(words) > 10:
                title = ' '.join(words[:10]) + '...'

        logger.info("=== AI Image Plugin: Image generation complete ===")
        return {
            "image_url": image_url or "",
            "title": title if show_title else "",
        }

    # ------------------------------------------------------------------
    # News feed helpers
    # ------------------------------------------------------------------
    def _get_selected_feed_urls(self, settings):
        """Build list of feed URLs from selected presets and custom URL."""
        feed_urls = []
        selected_feeds = settings.get("newsFeeds", "")
        if selected_feeds:
            for key in selected_feeds.split(","):
                key = key.strip()
                if key in NEWS_FEEDS:
                    feed_urls.append(NEWS_FEEDS[key][1])
        custom_url = settings.get("customFeedUrl", "").strip()
        if custom_url:
            feed_urls.append(custom_url)
        if not feed_urls:
            feed_urls.append(NEWS_FEEDS["bbc"][1])
            logger.warning("No news feeds selected, defaulting to BBC")
        return feed_urls

    def _fetch_news_headline(self, feed_urls):
        """Fetch headlines from RSS feeds and return a random one."""
        import feedparser

        session = get_http_session()
        all_headlines = []

        for url in feed_urls:
            try:
                resp = session.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                feed = feedparser.parse(resp.content)
                for entry in feed.entries:
                    title = entry.get("title", "").strip()
                    if title:
                        all_headlines.append(html.unescape(title))
            except Exception as e:
                logger.warning(f"Failed to fetch RSS feed {url}: {e}")
                continue

        if not all_headlines:
            raise RuntimeError("Could not fetch any news headlines. Check feed URLs and network connectivity.")

        headline = random.choice(all_headlines)
        logger.info(f"Selected headline from {len(all_headlines)} total: '{headline}'")
        return headline

    # ------------------------------------------------------------------
    # Provider: OpenAI (DALL-E)
    # ------------------------------------------------------------------
    def _generate_with_openai(self, settings, device_config, text_prompt, randomize_prompt, orientation, is_news=False):
        """Generate image using OpenAI DALL-E. Returns (image_url, prompt)."""
        from openai import OpenAI

        api_key = device_config.load_env_key("OPEN_AI_SECRET")
        if not api_key:
            logger.error("OpenAI API Key not configured")
            raise RuntimeError("OpenAI API Key not configured. Add OPEN_AI_SECRET in Settings > API Keys.")

        api_key = api_key.encode('ascii', errors='ignore').decode('ascii').strip()

        image_model = settings.get('imageModel', DEFAULT_OPENAI_MODEL)
        if image_model not in OPENAI_IMAGE_MODELS:
            logger.error(f"Invalid OpenAI image model: {image_model}")
            raise RuntimeError("Invalid Image Model provided.")

        image_quality = settings.get('quality', "medium" if image_model == "gpt-image-1" else "standard")

        logger.info(f"OpenAI Settings: model={image_model}, quality={image_quality}")

        try:
            ai_client = OpenAI(api_key=api_key)

            if randomize_prompt:
                logger.debug("Generating randomized prompt using GPT-4...")
                text_prompt = self._fetch_openai_prompt(ai_client, text_prompt, is_news)
                text_prompt = text_prompt.encode('ascii', errors='ignore').decode('ascii')
                logger.info(f"Randomized prompt: '{text_prompt}'")

            logger.info(f"Generating image with {image_model}...")
            image_url = self._fetch_openai_image_url(ai_client, text_prompt, image_model, image_quality, orientation)
            return image_url, text_prompt

        except Exception as e:
            logger.error(f"Failed to make OpenAI request: {str(e)}")
            raise RuntimeError("OpenAI request failure, please check logs.")

    def _fetch_openai_image_url(self, ai_client, prompt, model, quality, orientation):
        """Fetch image from OpenAI API and return a URL.

        DALL-E 2/3 return a hosted URL directly (pass-through).
        gpt-image-1 returns base64-encoded bytes; we save them to disk and
        return the served URL.
        """
        prompt = prompt.encode('ascii', errors='ignore').decode('ascii')

        logger.info(f"Generating image for prompt: {prompt}, model: {model}, quality: {quality}")
        prompt += (
            ". The image should fully occupy the entire canvas without any frames, "
            "borders, or cropped areas. No blank spaces or artificial framing."
        )

        args = {
            "model": model,
            "prompt": prompt,
            "size": "1024x1024",
        }
        if model == "dall-e-3":
            args["size"] = "1792x1024" if orientation == "horizontal" else "1024x1792"
            args["quality"] = quality
        elif model == "gpt-image-1":
            args["size"] = "1536x1024" if orientation == "horizontal" else "1024x1536"
            args["quality"] = quality

        response = ai_client.images.generate(**args)
        if model in ["dall-e-3", "dall-e-2"]:
            # DALL-E returns a hosted URL — pass it through directly.
            image_url = response.data[0].url
            return image_url
        elif model == "gpt-image-1":
            # gpt-image-1 returns base64-encoded image bytes.
            image_b64 = response.data[0].b64_json
            image_bytes = base64.b64decode(image_b64)
            return self._save_image_bytes(image_bytes)

    def _fetch_openai_prompt(self, ai_client, from_prompt=None, is_news=False):
        """Generate a creative prompt using OpenAI."""
        logger.info("Getting random image prompt from OpenAI...")

        system_content = (
            "Generate a single image prompt (20 words max). Each prompt must use a DIFFERENT "
            "visual style randomly chosen from: photorealistic photography, watercolor painting, "
            "pencil sketch, oil painting, cartoon/comic, pixel art, vector illustration, "
            "charcoal drawing, anime, retro poster, infrared photography, ink wash, pastel, "
            "3D render, woodcut print, collage, or stained glass.\n"
            "Subjects should span: people, animals, landscapes, cityscapes, food, sports, "
            "historical scenes, sci-fi, fantasy, everyday moments, architecture, underwater, "
            "space, weather, vehicles, and more.\n"
            "Do NOT default to surrealism or abstract art. Most prompts should depict "
            "recognizable scenes and subjects. Just output the prompt, nothing else."
        )
        user_content = "Generate a random image prompt."
        if from_prompt and from_prompt.strip() and is_news:
            system_content = (
                "You are a creative editorial illustrator. Given a news headline, generate "
                "a vivid image prompt that illustrates the story. Think bold editorial "
                "illustration style — dramatic, evocative, symbolic imagery. Keep it 20 words "
                "or less. Do not include any text or words in the image. Just provide the "
                "prompt, no explanation."
            )
            user_content = (
                f"News headline: \"{from_prompt}\"\n"
                "Create a vivid editorial illustration prompt for this headline."
            )
        elif from_prompt and from_prompt.strip():
            system_content = (
                "Rewrite the given image description into a more vivid, detailed version "
                "(20 words max). Keep the original subject but reimagine it in a randomly "
                "chosen visual style: photorealistic, watercolor, oil painting, pencil sketch, "
                "cartoon, pixel art, anime, retro poster, charcoal, ink wash, 3D render, etc. "
                "Add specific details like lighting, mood, time of day, or setting. "
                "Do NOT default to surrealism. Just output the rewritten prompt, nothing else."
            )
            user_content = (
                f"Original prompt: \"{from_prompt}\"\n"
                "Rewrite with more detail and a random visual style."
            )

        response = ai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content}
            ],
            temperature=1
        )

        prompt = response.choices[0].message.content.strip()
        logger.info(f"Generated random image prompt: {prompt}")
        return prompt

    # ------------------------------------------------------------------
    # Provider: Google Gemini (Imagen + native image models)
    # ------------------------------------------------------------------
    def _generate_with_gemini(self, settings, device_config, text_prompt, randomize_prompt, orientation, is_news=False):
        """Generate image using Google Gemini. Returns (served_url, prompt).

        Both Imagen (generate_images) and native Gemini image models
        (generate_content with response_modalities=["IMAGE"]) return raw image
        bytes; we save them to ``static/images/saved/ai_image_current.png``
        and return the served URL.
        """
        api_key = device_config.load_env_key("GOOGLE_GEMINI_SECRET")
        if not api_key:
            logger.error("Google Gemini API Key not configured")
            raise RuntimeError("Google Gemini API Key not configured. Add GOOGLE_GEMINI_SECRET in Settings > API Keys.")

        api_key = api_key.encode('ascii', errors='ignore').decode('ascii').strip()

        image_model = settings.get('geminiImageModel', DEFAULT_GEMINI_MODEL)

        logger.info(f"Gemini Settings: model={image_model}")

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)

            if randomize_prompt:
                logger.debug("Generating randomized prompt using Gemini...")
                text_prompt = self._fetch_gemini_prompt(client, text_prompt, is_news)
                logger.info(f"Randomized prompt: '{text_prompt}'")

            enhanced_prompt = text_prompt + (
                ". The image should fully occupy the entire canvas without any frames, "
                "borders, or cropped areas. No blank spaces or artificial framing."
            )

            logger.info(f"Generating image with Gemini {image_model}...")

            if orientation == "horizontal":
                aspect_ratio = "16:9"
            else:
                aspect_ratio = "9:16"

            if image_model in GEMINI_NATIVE_MODELS:
                response = client.models.generate_content(
                    model=image_model,
                    contents=enhanced_prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE"],
                        image_config=types.ImageConfig(
                            aspect_ratio=aspect_ratio,
                        ),
                    ),
                )
                for part in response.parts:
                    if part.inline_data is not None:
                        image_url = self._save_image_bytes(part.inline_data.data)
                        return image_url, text_prompt
                raise RuntimeError("Gemini returned no image in response")
            else:
                # Imagen image generation
                result = client.models.generate_images(
                    model=image_model,
                    prompt=enhanced_prompt,
                    config={
                        "number_of_images": 1,
                        "aspect_ratio": aspect_ratio,
                    }
                )

                if result.generated_images:
                    img_data = result.generated_images[0].image
                    image_url = self._save_image_bytes(img_data.image_bytes)
                    return image_url, text_prompt
                else:
                    raise RuntimeError("Gemini returned no images")

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

    def _fetch_gemini_prompt(self, client, from_prompt=None, is_news=False):
        """Generate a creative image prompt using Gemini 2.0 Flash as a text model."""
        logger.info("Getting random image prompt from Gemini...")

        if from_prompt and from_prompt.strip() and is_news:
            prompt_request = (
                f"News headline: \"{from_prompt}\"\n"
                "Create a vivid editorial illustration prompt for this headline. "
                "Think bold, dramatic, evocative, symbolic imagery in editorial illustration style. "
                "Focus on the emotion or human impact rather than politics or violence. "
                "Use rich, vibrant colors. "
                "Avoid cliche metaphors like scales of justice, broken chains, or chess pieces. "
                "Design for a single strong focal point with minimal background clutter. "
                "Do not include any text or words in the image. Keep it 20 words or less. "
                "Just provide the prompt, no explanation."
            )
        elif from_prompt and from_prompt.strip():
            prompt_request = (
                f"Take this image description: \"{from_prompt}\"\n"
                "Rewrite it with more vivid detail (20 words max). Keep the original subject "
                "but reimagine it in a randomly chosen visual style: photorealistic, watercolor, "
                "oil painting, pencil sketch, cartoon, pixel art, anime, retro poster, charcoal, "
                "ink wash, 3D render, etc. Add specific details like lighting, mood, or setting. "
                "Do NOT default to surrealism. Just provide the prompt, no explanation."
            )
        else:
            prompt_request = (
                "Generate a single image prompt (20 words max). Randomly pick a visual style "
                "from: photorealistic photo, watercolor, pencil sketch, oil painting, cartoon, "
                "pixel art, vector art, charcoal, anime, retro poster, infrared photo, ink wash, "
                "pastel, 3D render, woodcut, collage, stained glass, or crayon drawing.\n"
                "Randomly pick a subject from: people, animals, landscapes, cityscapes, food, "
                "sports, historical scenes, sci-fi, fantasy, everyday moments, architecture, "
                "underwater, space, weather, vehicles, portraits, still life, or wildlife.\n"
                "Do NOT default to surrealism, abstract, or Dali. Most prompts should depict "
                "recognizable real-world or fictional scenes. Vary wildly each time.\n"
                "Just output the prompt, nothing else."
            )

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt_request,
            config={"temperature": 2.0}
        )
        prompt = response.text.strip()
        words = prompt.split()
        if len(words) > 25:
            prompt = ' '.join(words[:25])
            logger.info(f"Truncated prompt from {len(words)} to 25 words")
        logger.info(f"Generated random image prompt: {prompt}")
        return prompt

    # ------------------------------------------------------------------
    # Provider: SiliconFlow (Kwai-Kolors/Kolors)
    # ------------------------------------------------------------------
    def _generate_with_siliconflow(self, settings, device_config, text_prompt, randomize_prompt, orientation, is_news=False):
        """Generate image using SiliconFlow (Kwai-Kolors/Kolors).

        SiliconFlow's image API returns a hosted URL, which we pass through
        directly to the frontend.
        """
        api_key = device_config.load_env_key("SILICONFLOW_SECRET")
        if not api_key:
            logger.error("SiliconFlow API Key not configured")
            raise RuntimeError("SiliconFlow API Key not configured. Add SILICONFLOW_SECRET in Settings > API Keys.")

        api_key = api_key.encode('ascii', errors='ignore').decode('ascii').strip()

        image_model = settings.get('siliconflowImageModel', DEFAULT_SILICONFLOW_MODEL)
        if image_model not in SILICONFLOW_IMAGE_MODELS:
            logger.error(f"Invalid SiliconFlow image model: {image_model}")
            raise RuntimeError("Invalid Image Model provided.")

        logger.info(f"SiliconFlow Settings: model={image_model}")

        session = get_http_session()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            if randomize_prompt:
                logger.debug("Generating randomized prompt using SiliconFlow chat...")
                text_prompt = self._fetch_siliconflow_prompt(session, headers, text_prompt, is_news)
                logger.info(f"Randomized prompt: '{text_prompt}'")

            enhanced_prompt = text_prompt + (
                ". The image should fully occupy the entire canvas without any frames, "
                "borders, or cropped areas. No blank spaces or artificial framing."
            )

            if orientation == "horizontal":
                image_size = "1280x720"
            else:
                image_size = "720x1280"

            logger.info(f"Generating image with SiliconFlow {image_model} (size={image_size})...")

            payload = {
                "model": image_model,
                "prompt": enhanced_prompt,
                "image_size": image_size,
                "batch_size": 1,
                "num_inference_steps": 20,
                "guidance_scale": 7.5,
            }

            resp = session.post(SILICONFLOW_IMAGE_API, json=payload, headers=headers, timeout=60)
            if resp.status_code != 200:
                error_msg = resp.text[:200]
                logger.error(f"SiliconFlow API error: {resp.status_code} - {error_msg}")
                if resp.status_code == 401:
                    raise RuntimeError("SiliconFlow API key is invalid. Check SILICONFLOW_SECRET in Settings > API Keys.")
                elif resp.status_code == 429:
                    raise RuntimeError("SiliconFlow rate limit reached. Please wait a minute and try again.")
                else:
                    raise RuntimeError(f"SiliconFlow request failed: {error_msg}")

            data = resp.json()
            images = data.get("images", [])
            if not images:
                raise RuntimeError("SiliconFlow returned no images")

            image_url = images[0].get("url")
            if not image_url:
                raise RuntimeError("SiliconFlow returned no image URL")

            # SiliconFlow returns a hosted URL — pass it through directly.
            return image_url, text_prompt

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"Failed to make SiliconFlow request: {str(e)}")
            raise RuntimeError(f"SiliconFlow request failure, please check logs.")

    def _fetch_siliconflow_prompt(self, session, headers, from_prompt=None, is_news=False):
        """Generate a creative image prompt using SiliconFlow chat completions."""
        logger.info("Getting random image prompt from SiliconFlow...")

        if from_prompt and from_prompt.strip() and is_news:
            user_content = (
                f'News headline: "{from_prompt}"\n'
                "Create a vivid editorial illustration prompt for this headline. "
                "Think bold, dramatic, evocative, symbolic imagery in editorial illustration style. "
                "Focus on the emotion or human impact rather than politics or violence. "
                "Use rich, vibrant colors. Avoid cliches like scales of justice or chess pieces. "
                "Design for a single strong focal point with minimal background clutter. "
                "Do not include any text or words in the image. Keep it 20 words or less. "
                "Just provide the prompt, no explanation."
            )
        elif from_prompt and from_prompt.strip():
            user_content = (
                f'Take this image description: "{from_prompt}"\n'
                "Rewrite it with more vivid detail (20 words max). Keep the original subject "
                "but reimagine it in a randomly chosen visual style: photorealistic, watercolor, "
                "oil painting, pencil sketch, cartoon, pixel art, anime, retro poster, charcoal, "
                "ink wash, 3D render, etc. Add specific details like lighting, mood, or setting. "
                "Do NOT default to surrealism. Just provide the prompt, no explanation."
            )
        else:
            user_content = (
                "Generate a single image prompt (20 words max). Randomly pick a visual style "
                "from: photorealistic photo, watercolor, pencil sketch, oil painting, cartoon, "
                "pixel art, vector art, charcoal, anime, retro poster, infrared photo, ink wash, "
                "pastel, 3D render, woodcut, collage, stained glass, or crayon drawing.\n"
                "Randomly pick a subject from: people, animals, landscapes, cityscapes, food, "
                "sports, historical scenes, sci-fi, fantasy, everyday moments, architecture, "
                "underwater, space, weather, vehicles, portraits, still life, or wildlife.\n"
                "Do NOT default to surrealism, abstract, or Dali. Most prompts should depict "
                "recognizable real-world or fictional scenes. Vary wildly each time.\n"
                "Just output the prompt, nothing else."
            )

        payload = {
            "model": SILICONFLOW_TEXT_MODEL,
            "messages": [{"role": "user", "content": user_content}],
            "temperature": 2.0,
            "max_tokens": 100,
        }

        try:
            resp = session.post(SILICONFLOW_CHAT_API, json=payload, headers=headers, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"SiliconFlow prompt generation failed ({resp.status_code}), using original prompt")
                return from_prompt or ""
            data = resp.json()
            prompt = data["choices"][0]["message"]["content"].strip()
            words = prompt.split()
            if len(words) > 25:
                prompt = ' '.join(words[:25])
                logger.info(f"Truncated prompt from {len(words)} to 25 words")
            logger.info(f"Generated random image prompt: {prompt}")
            return prompt
        except Exception as e:
            logger.warning(f"SiliconFlow prompt generation error: {e}, using original prompt")
            return from_prompt or ""

    # ------------------------------------------------------------------
    # Image persistence helper
    # ------------------------------------------------------------------
    def _save_image_bytes(self, image_bytes):
        """Save raw image bytes to the served static directory.

        Gemini and gpt-image-1 return image bytes rather than a hosted URL.
        We persist them to ``static/images/saved/ai_image_current.png`` so the
        browser can load them, and return the served URL path.
        """
        saved_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "static", "images", "saved"
        )
        try:
            os.makedirs(saved_dir, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create saved directory: {e}")
            raise RuntimeError("Failed to prepare image output directory.")

        dest_path = os.path.join(saved_dir, _SAVED_IMAGE_FILENAME)

        try:
            with open(dest_path, 'wb') as f:
                f.write(image_bytes)
            logger.debug(f"Saved AI image to: {dest_path}")
        except Exception as e:
            logger.error(f"Error saving AI image to {dest_path}: {e}")
            raise RuntimeError("Failed to save generated image, please check logs.")

        return f"/static/images/saved/{_SAVED_IMAGE_FILENAME}"
