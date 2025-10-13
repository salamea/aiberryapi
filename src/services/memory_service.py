"""
Memory Service for short-term and long-term conversation memory using Redis
"""
import logging
import json
from typing import List, Dict, Any, Optional
from datetime import datetime

import redis.asyncio as redis

from ..config import Settings

logger = logging.getLogger(__name__)


class MemoryService:
    """Service for managing conversation memory in Redis"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.redis_client: Optional[redis.Redis] = None

    async def initialize(self):
        """Initialize Redis connection for memory"""
        try:
            self.redis_client = redis.Redis(
                host=self.settings.redis_memory_host,
                port=self.settings.redis_memory_port,
                password=self.settings.redis_password,
                db=self.settings.redis_memory_db,
                decode_responses=True
            )

            await self.redis_client.ping()
            logger.info("Connected to Redis memory service successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Redis memory service: {e}")
            raise

    async def add_to_short_term_memory(
        self,
        session_id: str,
        user_message: str,
        ai_message: str
    ):
        """
        Add conversation exchange to short-term memory

        Args:
            session_id: Unique session identifier
            user_message: User's message
            ai_message: AI's response
        """
        try:
            key = f"stm:{session_id}"

            # Create message pair
            message_pair = {
                'timestamp': datetime.utcnow().isoformat(),
                'user': user_message,
                'ai': ai_message
            }

            # Add to list (FIFO)
            await self.redis_client.lpush(key, json.dumps(message_pair))

            # Trim to max size
            await self.redis_client.ltrim(
                key,
                0,
                self.settings.max_short_term_messages - 1
            )

            # Set TTL
            await self.redis_client.expire(key, self.settings.short_term_memory_ttl)

            logger.debug(f"Added message to short-term memory for session {session_id}")

        except Exception as e:
            logger.error(f"Error adding to short-term memory: {e}")

    async def get_short_term_memory(self, session_id: str) -> List[Dict[str, str]]:
        """
        Retrieve short-term memory for a session

        Args:
            session_id: Session identifier

        Returns:
            List of conversation messages
        """
        try:
            key = f"stm:{session_id}"
            messages = await self.redis_client.lrange(key, 0, -1)

            result = []
            for msg in reversed(messages):  # Reverse to get chronological order
                data = json.loads(msg)
                result.append({
                    'role': 'user',
                    'content': data['user'],
                    'timestamp': data['timestamp']
                })
                result.append({
                    'role': 'assistant',
                    'content': data['ai'],
                    'timestamp': data['timestamp']
                })

            return result

        except Exception as e:
            logger.error(f"Error retrieving short-term memory: {e}")
            return []

    async def add_to_long_term_memory(
        self,
        session_id: str,
        summary: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Add important information to long-term memory

        Args:
            session_id: Session identifier
            summary: Summary of important conversation points
            metadata: Additional metadata
        """
        try:
            key = f"ltm:{session_id}"

            memory_entry = {
                'timestamp': datetime.utcnow().isoformat(),
                'summary': summary,
                'metadata': metadata or {}
            }

            await self.redis_client.lpush(key, json.dumps(memory_entry))
            await self.redis_client.expire(key, self.settings.long_term_memory_ttl)

            logger.debug(f"Added to long-term memory for session {session_id}")

        except Exception as e:
            logger.error(f"Error adding to long-term memory: {e}")

    async def get_long_term_memory(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve long-term memory for a session

        Args:
            session_id: Session identifier

        Returns:
            List of memory entries
        """
        try:
            key = f"ltm:{session_id}"
            entries = await self.redis_client.lrange(key, 0, -1)

            return [json.loads(entry) for entry in reversed(entries)]

        except Exception as e:
            logger.error(f"Error retrieving long-term memory: {e}")
            return []

    async def clear_session(self, session_id: str):
        """Clear all memory for a session"""
        try:
            await self.redis_client.delete(
                f"stm:{session_id}",
                f"ltm:{session_id}"
            )
            logger.info(f"Cleared memory for session {session_id}")

        except Exception as e:
            logger.error(f"Error clearing session memory: {e}")

    async def get_active_sessions(self) -> List[str]:
        """Get list of active session IDs"""
        try:
            sessions = set()

            # Scan for short-term memory keys
            async for key in self.redis_client.scan_iter(match="stm:*"):
                session_id = key.split(":", 1)[1]
                sessions.add(session_id)

            return list(sessions)

        except Exception as e:
            logger.error(f"Error getting active sessions: {e}")
            return []

    async def health_check(self) -> bool:
        """Check Redis memory service health"""
        try:
            await self.redis_client.ping()
            return True
        except:
            return False

    async def close(self):
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.close()
        logger.info("Closed Redis memory service connection")
