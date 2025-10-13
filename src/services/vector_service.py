"""
Vector Database Service using Redis with RediSearch
"""
import logging
import json
import httpx
from typing import List, Dict, Any, Optional

import redis.asyncio as redis
from redis.commands.search.field import TextField, VectorField, NumericField
from redis.commands.search.indexDefinition import IndexDefinition, IndexType
from redis.commands.search.query import Query
from langchain.schema import Document

from ..config import Settings

logger = logging.getLogger(__name__)


class VectorService:
    """Service for vector storage and retrieval using Redis"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.redis_client: Optional[redis.Redis] = None
        self.index_name = settings.redis_vector_index
        self.embedding_dimension = settings.embedding_dimension
        self.http_client = httpx.AsyncClient(timeout=30.0)

    async def initialize(self):
        """Initialize Redis connection and create vector index"""
        try:
            # Connect to Redis
            self.redis_client = redis.Redis(
                host=self.settings.redis_host,
                port=self.settings.redis_port,
                password=self.settings.redis_password,
                db=self.settings.redis_db,
                decode_responses=False,
                encoding='utf-8'
            )

            # Test connection
            await self.redis_client.ping()
            logger.info("Connected to Redis successfully")

            # Create vector index if it doesn't exist
            await self._create_index()

        except Exception as e:
            logger.error(f"Failed to initialize Redis vector service: {e}")
            raise

    async def _create_index(self):
        """Create vector search index in Redis"""
        try:
            # Check if index exists
            try:
                await self.redis_client.ft(self.index_name).info()
                logger.info(f"Vector index '{self.index_name}' already exists")
                return
            except:
                pass  # Index doesn't exist, create it

            # Define schema
            schema = (
                TextField("$.content", as_name="content"),
                TextField("$.filename", as_name="filename"),
                TextField("$.document_id", as_name="document_id"),
                NumericField("$.chunk_index", as_name="chunk_index"),
                VectorField(
                    "$.embedding",
                    "FLAT",
                    {
                        "TYPE": "FLOAT32",
                        "DIM": self.embedding_dimension,
                        "DISTANCE_METRIC": "COSINE",
                    },
                    as_name="embedding"
                ),
            )

            # Create index
            await self.redis_client.ft(self.index_name).create_index(
                fields=schema,
                definition=IndexDefinition(
                    prefix=[f"doc:"],
                    index_type=IndexType.JSON
                )
            )

            logger.info(f"Created vector index '{self.index_name}'")

        except Exception as e:
            logger.error(f"Error creating vector index: {e}")
            # Don't raise, index might already exist

    async def _get_embedding(self, text: str) -> List[float]:
        """Get embedding from embedding service"""
        try:
            response = await self.http_client.post(
                f"{self.settings.embedding_service_url}/embed",
                json={"text": text}
            )
            response.raise_for_status()
            data = response.json()
            return data['embedding']

        except Exception as e:
            logger.error(f"Error getting embedding: {e}")
            raise

    async def add_documents(
        self,
        documents: List[Document],
        document_id: str
    ) -> int:
        """
        Add documents to vector store

        Args:
            documents: List of document chunks
            document_id: Unique document identifier

        Returns:
            Number of documents added
        """
        try:
            pipeline = self.redis_client.pipeline()

            for idx, doc in enumerate(documents):
                # Get embedding
                embedding = await self._get_embedding(doc.page_content)

                # Prepare document data
                doc_data = {
                    "content": doc.page_content,
                    "filename": doc.metadata.get('filename', ''),
                    "document_id": document_id,
                    "chunk_index": idx,
                    "embedding": embedding,
                    "metadata": json.dumps(doc.metadata)
                }

                # Store in Redis
                key = f"doc:{document_id}:{idx}"
                pipeline.json().set(key, "$", doc_data)

            await pipeline.execute()
            logger.info(f"Added {len(documents)} document chunks to vector store")

            return len(documents)

        except Exception as e:
            logger.error(f"Error adding documents to vector store: {e}")
            raise

    async def similarity_search(
        self,
        query: str,
        k: int = 5,
        score_threshold: Optional[float] = None
    ) -> List[Document]:
        """
        Perform similarity search

        Args:
            query: Search query
            k: Number of results to return
            score_threshold: Minimum similarity score

        Returns:
            List of relevant documents
        """
        try:
            # Get query embedding
            query_embedding = await self._get_embedding(query)

            # Prepare KNN query
            query_vector = [float(x) for x in query_embedding]

            # Create query
            base_query = f"*=>[KNN {k} @embedding $vec AS score]"
            q = Query(base_query).return_fields("content", "filename", "document_id", "score").dialect(2)

            # Execute search
            params = {
                "vec": query_vector
            }

            results = await self.redis_client.ft(self.index_name).search(q, query_params=params)

            # Process results
            documents = []
            for doc in results.docs:
                score = 1 - float(doc.score)  # Convert distance to similarity

                # Apply score threshold
                if score_threshold and score < score_threshold:
                    continue

                documents.append(Document(
                    page_content=doc.content,
                    metadata={
                        'filename': doc.filename,
                        'document_id': doc.document_id,
                        'score': score
                    }
                ))

            logger.info(f"Found {len(documents)} similar documents")
            return documents

        except Exception as e:
            logger.error(f"Error performing similarity search: {e}")
            return []

    async def delete_document(self, document_id: str) -> bool:
        """Delete all chunks of a document"""
        try:
            # Find all keys for this document
            pattern = f"doc:{document_id}:*"
            keys = []
            async for key in self.redis_client.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                await self.redis_client.delete(*keys)
                logger.info(f"Deleted {len(keys)} chunks for document {document_id}")

            return True

        except Exception as e:
            logger.error(f"Error deleting document: {e}")
            return False

    async def list_documents(self) -> List[Dict[str, Any]]:
        """List all documents in vector store"""
        try:
            documents = {}
            pattern = "doc:*"

            async for key in self.redis_client.scan_iter(match=pattern):
                data = await self.redis_client.json().get(key)
                doc_id = data.get('document_id')

                if doc_id not in documents:
                    documents[doc_id] = {
                        'document_id': doc_id,
                        'filename': data.get('filename'),
                        'chunks': 0
                    }
                documents[doc_id]['chunks'] += 1

            return list(documents.values())

        except Exception as e:
            logger.error(f"Error listing documents: {e}")
            return []

    async def health_check(self) -> bool:
        """Check Redis connection health"""
        try:
            await self.redis_client.ping()
            return True
        except:
            return False

    async def close(self):
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.close()
        await self.http_client.aclose()
        logger.info("Closed Redis vector service connection")
