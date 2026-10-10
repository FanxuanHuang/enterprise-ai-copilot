import os
import tempfile
import unittest
from pathlib import Path
from typing import Sequence

from app.services.knowledge_service import (
    Document,
    KnowledgeService,
    chunk_documents,
    load_markdown_documents,
)


class KeywordEmbeddingModel:
    model_name = "test-keyword-model"

    @staticmethod
    def _embed(text: str) -> list[float]:
        keyword_groups = (
            ("远程", "新员工", "90", "居家"),
            ("差旅", "出差", "住宿", "高铁"),
            ("报销", "发票", "不可报销"),
            ("年假", "病假", "员工手册"),
        )
        return [
            float(sum(text.count(keyword) for keyword in keywords))
            for keywords in keyword_groups
        ]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class KnowledgeServiceTests(unittest.TestCase):
    def setUp(self):
        descriptor, path = tempfile.mkstemp(suffix="-knowledge-index.json")
        os.close(descriptor)
        self.index_path = Path(path)
        self.knowledge_base_dir = Path(__file__).resolve().parents[1] / "knowledge_base"
        self.service = KnowledgeService(
            knowledge_base_dir=self.knowledge_base_dir,
            index_path=self.index_path,
            model_name="test-keyword-model",
            embedding_model=KeywordEmbeddingModel(),
        )

    def tearDown(self):
        if self.index_path.exists():
            self.index_path.unlink()

    def test_documents_are_loaded_and_chunked_with_source_metadata(self):
        documents = load_markdown_documents(self.knowledge_base_dir)
        chunks = chunk_documents(documents, chunk_size=180, overlap=30)

        self.assertEqual(len(documents), 4)
        self.assertGreater(len(chunks), len(documents))
        self.assertTrue(all(chunk.source.endswith(".md") for chunk in chunks))
        self.assertTrue(all(chunk.section for chunk in chunks))
        self.assertTrue(
            any(
                chunk.source == "remote_work_policy.md"
                and chunk.section == "申请资格"
                for chunk in chunks
            )
        )

    def test_index_builds_and_retriever_returns_expected_source_and_top_k(self):
        chunk_count = self.service.build_index(chunk_size=300, overlap=50)

        self.assertGreater(chunk_count, 0)
        self.assertTrue(self.index_path.is_file())

        results = self.service.search(
            "新员工入职多久以后可以申请远程办公？",
            top_k=3,
        )

        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].source, "remote_work_policy.md")
        self.assertEqual(results[0].section, "申请资格")
        self.assertIsInstance(results[0].chunk_index, int)
        self.assertGreater(results[0].score, 0.0)

    def test_chunk_overlap_preserves_boundary_context(self):
        document = Document(content="# 标题\n" + "甲" * 90, source="demo.md")
        chunks = chunk_documents([document], chunk_size=50, overlap=10)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].content[-10:], chunks[1].content[:10])


if __name__ == "__main__":
    unittest.main()
