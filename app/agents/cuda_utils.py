"""
CUDA-accelerated semantic re-ranking for web search snippets.

Goal:
Reduce noise before LLM synthesis by selecting top-K most relevant snippets
with multilingual sentence embeddings.

Model: paraphrase-multilingual-MiniLM-L12-v2
- supports Polish and English well
- lightweight and fast (384-d embeddings)
- runs on CUDA when available, CPU fallback otherwise
"""
from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

_EMBED_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


def get_device() -> str:
    """Return 'cuda' when GPU is available, otherwise 'cpu'."""
    try:
        import torch
        if torch.cuda.is_available():
            gpu = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
            logger.info(f"CUDA available: {gpu} ({vram:.1f} GB VRAM); running reranking on GPU")
            return "cuda"
    except ImportError:
        pass
    logger.warning("CUDA unavailable; running reranking on CPU")
    return "cpu"


def get_cuda_info() -> dict:
    """Return GPU diagnostics used by /health endpoint."""
    try:
        import torch
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            return {
                "cuda_available": True,
                "gpu_name": torch.cuda.get_device_name(0),
                "vram_total_gb": round(props.total_memory / 1024 ** 3, 1),
                "vram_free_gb": round(
                    (props.total_memory - torch.cuda.memory_allocated(0)) / 1024 ** 3, 1
                ),
                "cuda_version": torch.version.cuda,
                "torch_version": torch.__version__,
            }
        return {"cuda_available": False, "reason": "torch.cuda.is_available() = False"}
    except ImportError:
        return {"cuda_available": False, "reason": "torch not installed"}


class GPUReranker:
    """
    Semantic reranker backed by sentence embeddings.

    It computes cosine similarity between the query and each snippet,
    then returns top_k highest-scoring snippets.
    """

    def __init__(self):
        self.device = get_device()
        self._model = None

    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                logger.info(f"Loading embedding model: {_EMBED_MODEL} on {self.device}")
                self._model = SentenceTransformer(_EMBED_MODEL, device=self.device)
                logger.info("Embedding model ready")
            except ImportError:
                logger.error("sentence-transformers is not installed; reranking disabled")
                self._model = None

    def rerank(self, query: str, results: list[str], top_k: int = 3) -> list[str]:
        """Return top_k snippets sorted by semantic similarity to query."""
        if not results:
            return results

        self._load_model()
        if self._model is None:
            return results[:top_k]

        try:
            import torch.nn.functional as F

            texts = [query] + results
            embeddings = self._model.encode(
                texts,
                convert_to_tensor=True,
                device=self.device,
                batch_size=32,
                show_progress_bar=False,
            )

            query_emb = embeddings[0]
            result_embs = embeddings[1:]

            scores = F.cosine_similarity(
                query_emb.unsqueeze(0),
                result_embs,
            ).cpu().tolist()

            ranked = sorted(zip(scores, results), key=lambda x: x[0], reverse=True)
            top = [text for _, text in ranked[:top_k]]

            logger.info(
                f"Reranking done: {len(results)} -> top {top_k}; "
                f"scores={[round(s, 3) for s, _ in ranked[:top_k]]}"
            )
            return top

        except Exception as exc:
            logger.warning(f"Reranking failed: {exc}; returning original top_k results")
            return results[:top_k]


@lru_cache(maxsize=1)
def get_reranker() -> GPUReranker:
    """Return a singleton reranker instance."""
    return GPUReranker()
