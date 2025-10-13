"""
AIBerry API Server
Enterprise-grade FastAPI application with LangChain, Redis, and Guardrails
"""
import os
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response

from .config import Settings
from .services.llm_service import LLMService
from .services.vector_service import VectorService
from .services.memory_service import MemoryService
from .services.guardrails_service import GuardrailsService
from .services.document_service import DocumentService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Prometheus metrics
REQUEST_COUNT = Counter('aiberry_api_requests_total', 'Total API requests', ['method', 'endpoint', 'status'])
REQUEST_DURATION = Histogram('aiberry_api_request_duration_seconds', 'Request duration', ['method', 'endpoint'])
QUERY_COUNT = Counter('aiberry_queries_total', 'Total queries processed', ['type'])
DOCUMENT_COUNT = Counter('aiberry_documents_total', 'Total documents processed', ['operation'])

# Global services
services = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting AIBerry API Server...")

    # Initialize settings
    settings = Settings()

    # Initialize services
    try:
        services['llm'] = LLMService(settings)
        services['vector'] = VectorService(settings)
        services['memory'] = MemoryService(settings)
        services['guardrails'] = GuardrailsService(settings)
        services['document'] = DocumentService(settings, services['vector'])

        await services['vector'].initialize()
        await services['memory'].initialize()

        logger.info("All services initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        raise

    yield

    # Cleanup
    logger.info("Shutting down AIBerry API Server...")
    await services['vector'].close()
    await services['memory'].close()

# Create FastAPI application
app = FastAPI(
    title="AIBerry API",
    description="Enterprise AI Agent API with LangChain, Redis Vector DB, and Guardrails",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://fend.aisolution.com", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models
class QueryRequest(BaseModel):
    """Request model for query endpoint"""
    query: str = Field(..., min_length=1, max_length=2000, description="User query")
    session_id: str = Field(..., description="Session ID for conversation continuity")
    use_context: bool = Field(default=True, description="Use document context from vector DB")
    temperature: float = Field(default=0.7, ge=0.0, le=1.0, description="LLM temperature")

class QueryResponse(BaseModel):
    """Response model for query endpoint"""
    response: str
    session_id: str
    sources: Optional[List[dict]] = None
    guardrails_passed: bool
    tokens_used: Optional[int] = None

class DocumentUploadResponse(BaseModel):
    """Response model for document upload"""
    document_id: str
    filename: str
    chunks_created: int
    status: str

class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    services: dict

class MemoryResponse(BaseModel):
    """Memory retrieval response"""
    session_id: str
    short_term_memory: List[dict]
    long_term_memory: Optional[List[dict]] = None

# Dependency injection
def get_llm_service() -> LLMService:
    return services['llm']

def get_vector_service() -> VectorService:
    return services['vector']

def get_memory_service() -> MemoryService:
    return services['memory']

def get_guardrails_service() -> GuardrailsService:
    return services['guardrails']

def get_document_service() -> DocumentService:
    return services['document']

# API Endpoints

@app.get("/", response_model=dict)
async def root():
    """Root endpoint"""
    return {
        "service": "AIBerry API",
        "version": "1.0.0",
        "status": "running"
    }

@app.get("/health", response_model=HealthResponse)
async def health_check(
    vector_service: VectorService = Depends(get_vector_service),
    memory_service: MemoryService = Depends(get_memory_service)
):
    """Health check endpoint"""
    REQUEST_COUNT.labels(method='GET', endpoint='/health', status='200').inc()

    services_status = {
        "redis_vector": await vector_service.health_check(),
        "redis_memory": await memory_service.health_check(),
    }

    all_healthy = all(services_status.values())

    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        services=services_status
    )

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.post("/api/v1/query", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    llm_service: LLMService = Depends(get_llm_service),
    vector_service: VectorService = Depends(get_vector_service),
    memory_service: MemoryService = Depends(get_memory_service),
    guardrails_service: GuardrailsService = Depends(get_guardrails_service)
):
    """
    Process user query with LangChain agent
    Applies guardrails, retrieves context from vector DB, and manages conversation memory
    """
    try:
        REQUEST_COUNT.labels(method='POST', endpoint='/api/v1/query', status='200').inc()
        QUERY_COUNT.labels(type='user_query').inc()

        # Apply input guardrails
        guardrails_result = await guardrails_service.validate_input(request.query)
        if not guardrails_result['passed']:
            return QueryResponse(
                response=guardrails_result['message'],
                session_id=request.session_id,
                guardrails_passed=False
            )

        # Retrieve conversation memory
        conversation_history = await memory_service.get_short_term_memory(request.session_id)

        # Retrieve relevant context from vector DB
        context_docs = []
        if request.use_context:
            context_docs = await vector_service.similarity_search(request.query, k=5)

        # Generate response using LLM
        response_data = await llm_service.generate_response(
            query=request.query,
            context=context_docs,
            conversation_history=conversation_history,
            temperature=request.temperature
        )

        # Apply output guardrails
        output_guardrails = await guardrails_service.validate_output(response_data['response'])
        if not output_guardrails['passed']:
            response_data['response'] = output_guardrails['message']

        # Store in memory
        await memory_service.add_to_short_term_memory(
            session_id=request.session_id,
            user_message=request.query,
            ai_message=response_data['response']
        )

        return QueryResponse(
            response=response_data['response'],
            session_id=request.session_id,
            sources=[doc.metadata for doc in context_docs] if context_docs else None,
            guardrails_passed=output_guardrails['passed'],
            tokens_used=response_data.get('tokens_used')
        )

    except Exception as e:
        logger.error(f"Error processing query: {e}")
        REQUEST_COUNT.labels(method='POST', endpoint='/api/v1/query', status='500').inc()
        raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")

@app.post("/api/v1/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    document_service: DocumentService = Depends(get_document_service)
):
    """
    Upload and process document for vector storage
    Supports PDF, DOCX, TXT formats
    """
    try:
        REQUEST_COUNT.labels(method='POST', endpoint='/api/v1/documents/upload', status='200').inc()
        DOCUMENT_COUNT.labels(operation='upload').inc()

        # Validate file type
        allowed_extensions = ['.pdf', '.docx', '.txt']
        file_extension = os.path.splitext(file.filename)[1].lower()
        if file_extension not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"File type not supported. Allowed: {', '.join(allowed_extensions)}"
            )

        # Read file content
        content = await file.read()

        # Process document
        result = await document_service.process_document(
            filename=file.filename,
            content=content,
            file_type=file_extension
        )

        return DocumentUploadResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading document: {e}")
        REQUEST_COUNT.labels(method='POST', endpoint='/api/v1/documents/upload', status='500').inc()
        raise HTTPException(status_code=500, detail=f"Error processing document: {str(e)}")

@app.get("/api/v1/documents", response_model=List[dict])
async def list_documents(
    document_service: DocumentService = Depends(get_document_service)
):
    """List all uploaded documents"""
    try:
        documents = await document_service.list_documents()
        return documents
    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(status_code=500, detail=f"Error listing documents: {str(e)}")

@app.get("/api/v1/memory/{session_id}", response_model=MemoryResponse)
async def get_memory(
    session_id: str,
    memory_service: MemoryService = Depends(get_memory_service)
):
    """Retrieve conversation memory for a session"""
    try:
        short_term = await memory_service.get_short_term_memory(session_id)
        long_term = await memory_service.get_long_term_memory(session_id)

        return MemoryResponse(
            session_id=session_id,
            short_term_memory=short_term,
            long_term_memory=long_term
        )
    except Exception as e:
        logger.error(f"Error retrieving memory: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving memory: {str(e)}")

@app.delete("/api/v1/memory/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def clear_memory(
    session_id: str,
    memory_service: MemoryService = Depends(get_memory_service)
):
    """Clear conversation memory for a session"""
    try:
        await memory_service.clear_session(session_id)
        return None
    except Exception as e:
        logger.error(f"Error clearing memory: {e}")
        raise HTTPException(status_code=500, detail=f"Error clearing memory: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
