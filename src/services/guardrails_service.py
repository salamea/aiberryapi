"""
Guardrails Service for input/output validation and safety using NeMo Guardrails
"""
import logging
import re
from typing import Dict, Any, Optional

from nemoguardrails import RailsConfig, LLMRails
from nemoguardrails.rails.llm.config import Model

from ..config import Settings

logger = logging.getLogger(__name__)


class GuardrailsService:
    """Service for applying guardrails to inputs and outputs using NeMo Guardrails"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.enabled = settings.guardrails_enabled
        self.rails: Optional[LLMRails] = None

        # Fallback patterns for content filtering (used if NeMo fails)
        self.blocked_patterns = [
            r'(?i)(hack|exploit|vulnerability|malware|phishing)',
            r'(?i)(password|credential|api[_\s]?key|secret[_\s]?key)',
            r'(?i)(inject|sql|xss|csrf)',
            r'(?i)(bypass|circumvent|override)\s+(security|safety)',
        ]

        # PII patterns
        self.pii_patterns = [
            (r'\b\d{3}-\d{2}-\d{4}\b', 'SSN'),  # SSN
            (r'\b\d{16}\b', 'CC'),  # Credit card
            (r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', 'EMAIL', re.IGNORECASE),
        ]

    async def initialize(self):
        """Initialize NeMo Guardrails"""
        if not self.enabled:
            logger.info("Guardrails disabled")
            return

        try:
            # Create a basic configuration
            config = RailsConfig.from_content(
                colang_content="""
                define user ask about unsafe topics
                    "how to hack"
                    "how to exploit"
                    "bypass security"
                    "malware"
                    "phishing"

                define user share sensitive info
                    "my password is"
                    "my credit card"
                    "my ssn is"
                    "api key"
                    "secret key"

                define bot refuse unsafe request
                    "I cannot provide information on that topic as it may be unsafe or unethical."

                define bot refuse sensitive info
                    "I cannot process requests containing sensitive personal information. Please remove any passwords, credit card numbers, or other sensitive data."

                define flow handle unsafe topics
                    user ask about unsafe topics
                    bot refuse unsafe request

                define flow handle sensitive info
                    user share sensitive info
                    bot refuse sensitive info
                """,
                yaml_content=f"""
                models:
                  - type: main
                    engine: google
                    model: {self.settings.google_model}
                    parameters:
                      api_key: {self.settings.google_api_key}
                      temperature: 0.1

                rails:
                  input:
                    flows:
                      - handle unsafe topics
                      - handle sensitive info
                  output:
                    flows:
                      - handle unsafe topics
                      - handle sensitive info
                """
            )

            self.rails = LLMRails(config)
            logger.info("NeMo Guardrails initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize NeMo Guardrails: {e}")
            logger.warning("Falling back to regex-based guardrails")
            self.rails = None

    async def validate_input(self, text: str) -> Dict[str, Any]:
        """
        Validate user input against guardrails using NeMo

        Args:
            text: Input text to validate

        Returns:
            Dict with validation result
        """
        if not self.enabled:
            return {'passed': True}

        try:
            # Check input length
            if len(text) > self.settings.max_input_length:
                return {
                    'passed': False,
                    'message': f"Input exceeds maximum length of {self.settings.max_input_length} characters"
                }

            # Check for empty input
            if not text.strip():
                return {
                    'passed': False,
                    'message': "Input cannot be empty"
                }

            # Use NeMo Guardrails if available
            if self.rails:
                try:
                    response = await self.rails.generate_async(
                        messages=[{"role": "user", "content": text}]
                    )

                    # If NeMo blocked the input, it will return a refusal message
                    if response and "cannot" in response.get("content", "").lower():
                        logger.warning(f"Input blocked by NeMo Guardrails")
                        return {
                            'passed': False,
                            'message': response.get("content", "Input contains potentially unsafe content.")
                        }
                except Exception as nemo_error:
                    logger.error(f"NeMo Guardrails validation error: {nemo_error}")
                    # Fall through to regex-based validation

            # Fallback: Check for blocked content with regex
            for pattern in self.blocked_patterns:
                if re.search(pattern, text):
                    logger.warning(f"Input blocked by guardrail pattern: {pattern}")
                    return {
                        'passed': False,
                        'message': "Input contains potentially unsafe content. Please rephrase your query."
                    }

            # Check for PII (warning only, not blocking)
            pii_found = []
            for pattern_data in self.pii_patterns:
                pattern = pattern_data[0]
                pii_type = pattern_data[1]
                flags = pattern_data[2] if len(pattern_data) > 2 else 0

                if re.search(pattern, text, flags):
                    pii_found.append(pii_type)
                    logger.warning(f"PII detected in input: {pii_type}")

            if pii_found:
                return {
                    'passed': True,
                    'warning': f"Detected potential PII: {', '.join(pii_found)}. Please avoid sharing sensitive information.",
                    'pii_types': pii_found
                }

            return {'passed': True}

        except Exception as e:
            logger.error(f"Error validating input: {e}")
            return {'passed': True}  # Fail open

    async def validate_output(self, text: str) -> Dict[str, Any]:
        """
        Validate model output against guardrails using NeMo

        Args:
            text: Output text to validate

        Returns:
            Dict with validation result
        """
        if not self.enabled:
            return {'passed': True}

        try:
            # Check output length
            if len(text) > self.settings.max_output_length:
                logger.warning("Output exceeds maximum length")
                return {
                    'passed': False,
                    'message': "Response too long. Please try a more specific query."
                }

            # Use NeMo Guardrails if available for output validation
            if self.rails:
                try:
                    response = await self.rails.generate_async(
                        messages=[
                            {"role": "user", "content": "Check this response"},
                            {"role": "assistant", "content": text}
                        ]
                    )

                    # If NeMo flags the output, block it
                    if response and "cannot" in response.get("content", "").lower():
                        logger.warning(f"Output blocked by NeMo Guardrails")
                        return {
                            'passed': False,
                            'message': "I cannot provide that information. Please ask a different question."
                        }
                except Exception as nemo_error:
                    logger.error(f"NeMo Guardrails output validation error: {nemo_error}")
                    # Fall through to regex-based validation

            # Fallback: Check for blocked content in output
            for pattern in self.blocked_patterns:
                if re.search(pattern, text):
                    logger.warning(f"Output blocked by guardrail pattern: {pattern}")
                    return {
                        'passed': False,
                        'message': "I cannot provide that information. Please ask a different question."
                    }

            # Check for potential PII leakage
            pii_found = []
            for pattern_data in self.pii_patterns:
                pattern = pattern_data[0]
                pii_type = pattern_data[1]
                flags = pattern_data[2] if len(pattern_data) > 2 else 0

                if re.search(pattern, text, flags):
                    pii_found.append(pii_type)
                    logger.error(f"PII leaked in output: {pii_type}")

            if pii_found:
                return {
                    'passed': False,
                    'message': "I apologize, but I cannot provide that response for privacy reasons."
                }

            return {'passed': True}

        except Exception as e:
            logger.error(f"Error validating output: {e}")
            return {'passed': True}  # Fail open

    async def sanitize_text(self, text: str) -> str:
        """
        Sanitize text by removing or masking sensitive information

        Args:
            text: Text to sanitize

        Returns:
            Sanitized text
        """
        sanitized = text

        # Mask PII
        for pattern_data in self.pii_patterns:
            pattern = pattern_data[0]
            pii_type = pattern_data[1]
            flags = pattern_data[2] if len(pattern_data) > 2 else 0

            sanitized = re.sub(pattern, f"[{pii_type}_REDACTED]", sanitized, flags=flags)

        return sanitized

    async def check_rate_limit(self, user_id: str) -> bool:
        """
        Check if user has exceeded rate limit
        (Placeholder - implement with Redis if needed)

        Args:
            user_id: User identifier

        Returns:
            True if within rate limit, False otherwise
        """
        # TODO: Implement rate limiting with Redis
        return True
