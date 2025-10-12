# src/main.py
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import os
import uuid
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.memory import RedisChatMessageHistory
from langchain.chains import ConversationChain
from langchain.prompts import PromptTemplate
from sentence_transformers import SentenceTransformer
from redisvl.index import SearchIndex
from redisvl.query import VectorQuery
import textwrap
import io
from PyPDF2 import PdfReader

app = FastAPI(title="aiberry API", description="AI Agent with Memory & Documents")

# Allow frontend origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://fend.aisolution.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Config
REDIS_URL = os.getenv("REDIS_URL", "redis://redis-master.aiberry-dev.svc.cluster.local:6379")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# Initialize
embedding_model = SentenceTransformer(EMBEDDING_MODEL)
llm = ChatGoogleGenerativeAI(model="gemini-pro", google_api_key=GOOGLE_API_KEY)

# RedisVL Index
index_schema = {
    "index": "documents",
    "fields": [
        {"name": "id", "type": "TAG"},
        {"name": "content", "type": "TEXT"},
        {"name": "embedding", "type": "VECTOR", "dims": 384, "algorithm": "FLAT", "distance_metric": "COSINE"}
    ]
}
index = SearchIndex.from_dict(index_schema)
index.connect(url=REDIS_URL)
if not index.exists():
    index.create()

class QueryRequest(BaseModel):
    session_id: str
    query: str

class UploadResponse(BaseModel):
    message: str
    doc_id: str

def extract_text_from_pdf(file_bytes: bytes) -> str:
    pdf = PdfReader(io.BytesIO(file_bytes))
    text = ""
    for page in pdf.pages:
        text += page.extract_text() or ""
    return text

def chunk_text(text: str, max_length=500) -> List[str]:
    return textwrap.wrap(text, max_length)

@app.post("/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Only PDF supported")
    
    contents = await file.read()
    text = extract_text_from_pdf(contents)
    chunks = chunk_text(text)
    
    doc_id = str(uuid.uuid4())
    for i, chunk in enumerate(chunks):
        embedding = embedding_model.encode(chunk).tolist()
        index.load(
            data=[
                {
                    "id": f"{doc_id}_{i}",
                    "content": chunk,
                    "embedding": embedding
                }
            ]
        )
    
    return UploadResponse(message="Document stored", doc_id=doc_id)

@app.post("/query")
async def query_agent(req: QueryRequest):
    # Guardrail: block harmful prompts
    if any(word in req.query.lower() for word in ["hack", "exploit", "bypass"]):
        return {"answer": "I cannot assist with that request."}
    
    # Vector search
    query_embedding = embedding_model.encode(req.query).tolist()
    vq = VectorQuery(
        vector=query_embedding,
        vector_field_name="embedding",
        return_fields=["content"],
        num_results=3
    )
    results = index.query(vq)
    context = "\n".join([r["content"] for r in results])
    
    # LangChain with memory
    history = RedisChatMessageHistory(
        session_id=req.session_id,
        url=REDIS_URL
    )
    
    template = """
    You are a helpful AI assistant. Use the following context to answer the question.
    If you don't know, say "I don't know".
    
    Context: {context}
    
    Chat History: {history}
    
    Human: {input}
    AI:
    """
    prompt = PromptTemplate(input_variables=["context", "history", "input"], template=template)
    chain = ConversationChain(
        llm=llm,
        memory=history,
        prompt=prompt,
        verbose=False
    )
    
    response = chain.run(context=context, input=req.query)
    return {"answer": response}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/ready")
def ready():
    try:
        index.client.ping()
        return {"status": "ready"}
    except:
        raise HTTPException(status_code=503, detail="Redis not ready")