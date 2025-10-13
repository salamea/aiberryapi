"""
Guardrails Service for input/output validation and safety
"""
import logging
import re
from typing import Dict, Any

from ..config import Settings

logger = logging.getLogger(__name__)


class GuardrailsService:
    """Service for applying guardrails to inputs and outputs"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.enabled = settings.guardrails_enabled

        # Patterns for content filtering
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

    async def validate_input(self, text: str) -> Dict[str, Any]:
        """
        Validate user input against guardrails

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

            # Check for blocked content
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
        Validate model output against guardrails

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

            # Check for blocked content in output
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
