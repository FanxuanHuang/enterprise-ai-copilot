import json
import logging
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol, Sequence

from app.core.config import settings


logger = logging.getLogger(__name__)

INDEX_VERSION = 1
DEFAULT_CHUNK_SIZE = 600
DEFAULT_CHUNK_OVERLAP = 100


class KnowledgeServiceError(Exception):
    pass


@dataclass(frozen=True)
class Document:
    content: str
    source: str


@dataclass(frozen=True)
class Chunk:
    content: str
    source: str
    section: str
    chunk_index: int


@dataclass(frozen=True)
class SearchResult:
    content: str
    source: str
    section: str
    score: float


class EmbeddingModel(Protocol):
    model_name: str

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedModel:
    def __init__(self, model_name: str) -> None:
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name)

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.passage_embed(list(texts))]

    def embed_query(self, text: str) -> list[float]:
        return next(self._model.query_embed(text)).tolist()


def load_markdown_documents(knowledge_base_dir: Path) -> list[Document]:
    if not knowledge_base_dir.is_dir():
        raise KnowledgeServiceError(
            f"Knowledge base directory does not exist: {knowledge_base_dir}"
        )

    documents = [
        Document(content=path.read_text(encoding="utf-8"), source=path.name)
        for path in sorted(knowledge_base_dir.glob("*.md"))
    ]
    if not documents:
        raise KnowledgeServiceError(
            f"No Markdown documents found in: {knowledge_base_dir}"
        )
    return documents


def _split_markdown_sections(document: Document) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_heading = "Document"
    current_lines: list[str] = []

    def flush() -> None:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append((current_heading, content))

    for line in document.content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            current_lines = []
            current_heading = stripped.lstrip("#").strip() or "Document"
        else:
            current_lines.append(line)
    flush()
    return sections


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        hard_end = min(start + chunk_size, len(text))
        end = hard_end
        if hard_end < len(text):
            split_at = text.rfind("\n", start, hard_end)
            if split_at > start + chunk_size // 2:
                end = split_at

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)

    return chunks


def chunk_documents(
    documents: Sequence[Document],
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be between 0 and chunk_size - 1")

    chunks: list[Chunk] = []
    for document in documents:
        document_chunk_index = 0
        for section, section_text in _split_markdown_sections(document):
            for content in _split_text(section_text, chunk_size, overlap):
                chunks.append(
                    Chunk(
                        content=content,
                        source=document.source,
                        section=section,
                        chunk_index=document_chunk_index,
                    )
                )
                document_chunk_index += 1
    return chunks


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise KnowledgeServiceError("Query and document vector dimensions differ.")
    dot_product = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot_product / (left_norm * right_norm)


class KnowledgeService:
    def __init__(
        self,
        *,
        knowledge_base_dir: Path | None = None,
        index_path: Path | None = None,
        model_name: str | None = None,
        embedding_model: EmbeddingModel | None = None,
    ) -> None:
        self.knowledge_base_dir = knowledge_base_dir or settings.knowledge_base_dir
        self.index_path = index_path or settings.knowledge_index_path
        self.model_name = model_name or settings.embedding_model
        self._embedding_model = embedding_model
        self._index: dict[str, object] | None = None

    @property
    def embedding_model(self) -> EmbeddingModel:
        if self._embedding_model is None:
            self._embedding_model = FastEmbedModel(self.model_name)
        return self._embedding_model

    def build_index(
        self,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> int:
        documents = load_markdown_documents(self.knowledge_base_dir)
        chunks = chunk_documents(
            documents,
            chunk_size=chunk_size,
            overlap=overlap,
        )
        vectors = self.embedding_model.embed_passages(
            [chunk.content for chunk in chunks]
        )
        if len(vectors) != len(chunks):
            raise KnowledgeServiceError("Embedding count does not match chunk count.")

        index: dict[str, object] = {
            "version": INDEX_VERSION,
            "embedding_model": self.model_name,
            "chunk_size": chunk_size,
            "chunk_overlap": overlap,
            "items": [
                {"chunk": asdict(chunk), "embedding": vector}
                for chunk, vector in zip(chunks, vectors, strict=True)
            ],
        }
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._index = index
        logger.info(
            "Knowledge index built: documents=%d chunks=%d path=%s",
            len(documents),
            len(chunks),
            self.index_path,
        )
        return len(chunks)

    def _load_index(self) -> dict[str, object]:
        if self._index is not None:
            return self._index
        if not self.index_path.is_file():
            raise KnowledgeServiceError(
                "Knowledge index is missing. Build it with "
                "`python -m app.scripts.build_knowledge_index`."
            )

        try:
            index = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise KnowledgeServiceError("Knowledge index could not be loaded.") from exc

        if index.get("version") != INDEX_VERSION:
            raise KnowledgeServiceError("Knowledge index version is not supported.")
        if index.get("embedding_model") != self.model_name:
            raise KnowledgeServiceError(
                "Knowledge index uses a different embedding model. Rebuild the index."
            )
        self._index = index
        return index

    def search(self, query: str, top_k: int) -> list[SearchResult]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if top_k < 1:
            raise ValueError("top_k must be positive")

        index = self._load_index()
        items = index.get("items")
        if not isinstance(items, list):
            raise KnowledgeServiceError("Knowledge index items are invalid.")

        query_vector = self.embedding_model.embed_query(query)
        scored_results: list[SearchResult] = []
        for item in items:
            chunk = item["chunk"]
            score = _cosine_similarity(query_vector, item["embedding"])
            scored_results.append(
                SearchResult(
                    content=chunk["content"],
                    source=chunk["source"],
                    section=chunk["section"],
                    score=score,
                )
            )

        scored_results.sort(key=lambda result: result.score, reverse=True)
        return scored_results[:top_k]


knowledge_service = KnowledgeService()
