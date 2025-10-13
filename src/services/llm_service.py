"""
LLM Service using Google Gemini via LangChain
"""
import logging
from typing import List, Dict, Any, Optional

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.chains import ConversationalRetrievalChain
from langchain.prompts import PromptTemplate
from langchain.schema import Document, HumanMessage, AIMessage

from ..config import Settings

logger = logging.getLogger(__name__)


class LLMService:
    """Service for LLM operations using Google Gemini"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = ChatGoogleGenerativeAI(
            model=settings.google_model,
            google_api_key=settings.google_api_key,
            temperature=settings.llm_temperature,
            max_output_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout
        )

        # System prompt for the AI agent
        self.system_prompt = PromptTemplate.from_template("""
You are AIBerry, an intelligent AI assistant designed to help users with their queries and documents.
You have access to a knowledge base of documents and can provide accurate, helpful responses.

Guidelines:
- Be helpful, accurate, and concise
- If you don't know something, admit it
- Use the provided context when available
- Maintain conversation continuity using chat history
- Be professional and respectful

Context from documents:
{context}

Chat History:
{chat_history}

User Question: {question}

Your response:
""")

    async def generate_response(
        self,
        query: str,
        context: Optional[List[Document]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        temperature: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Generate response using LLM with context and conversation history

        Args:
            query: User query
            context: List of relevant documents from vector search
            conversation_history: Previous conversation messages
            temperature: Override default temperature

        Returns:
            Dict with response and metadata
        """
        try:
            # Format context
            context_str = ""
            if context:
                context_str = "\n\n".join([
                    f"Document: {doc.metadata.get('filename', 'Unknown')}\n{doc.page_content}"
                    for doc in context
                ])

            # Format chat history
            chat_history_str = ""
            if conversation_history:
                for msg in conversation_history[-5:]:  # Last 5 messages
                    role = msg.get('role', 'user')
                    content = msg.get('content', '')
                    chat_history_str += f"{role.upper()}: {content}\n"

            # Create prompt
            prompt = self.system_prompt.format(
                context=context_str or "No additional context available.",
                chat_history=chat_history_str or "No previous conversation.",
                question=query
            )

            # Create temporary LLM with custom temperature if provided
            llm = self.llm
            if temperature is not None:
                llm = ChatGoogleGenerativeAI(
                    model=self.settings.google_model,
                    google_api_key=self.settings.google_api_key,
                    temperature=temperature,
                    max_output_tokens=self.settings.llm_max_tokens,
                    timeout=self.settings.llm_timeout
                )

            # Generate response
            response = await llm.ainvoke([HumanMessage(content=prompt)])

            return {
                'response': response.content,
                'tokens_used': response.response_metadata.get('token_count'),
                'model': self.settings.google_model
            }

        except Exception as e:
            logger.error(f"Error generating LLM response: {e}")
            raise

    async def summarize_document(self, text: str) -> str:
        """Summarize document text"""
        try:
            prompt = f"""Please provide a concise summary of the following text:

{text[:4000]}  # Limit to avoid token limits

Summary:"""

            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            return response.content

        except Exception as e:
            logger.error(f"Error summarizing document: {e}")
            raise
