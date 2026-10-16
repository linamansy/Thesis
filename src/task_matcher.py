"""TaskMatcher: pairs generated tasks with reference tasks by label meaning.

Steps:
  1. Embed every task label with a sentence-transformers model, so labels with a
     similar meaning ("Ship goods" / "Send products") get similar vectors.
  2. Compute the cosine similarity between every generated and every reference label.
  3. Find the best one-to-one pairing with the Hungarian algorithm (each task can be
     used at most once; the total similarity of the pairing is as high as possible).
  4. Keep only pairs whose similarity is at least the threshold from config.yaml.
"""

import numpy as np
from scipy.optimize import linear_sum_assignment
from sentence_transformers import SentenceTransformer


class TaskMatcher:
    """Matches task labels one-to-one using embeddings and the Hungarian algorithm."""

    def __init__(self, model_name: str, threshold: float):
        self.model_name = model_name
        self.threshold = threshold
        self.model = SentenceTransformer(model_name)

    def similarity_matrix(self, generated: list[str], reference: list[str]) -> np.ndarray:
        """Cosine similarity: rows = generated labels, columns = reference labels."""
        gen_vectors = self.model.encode(generated, normalize_embeddings=True)
        ref_vectors = self.model.encode(reference, normalize_embeddings=True)
        return gen_vectors @ ref_vectors.T  # with normalised vectors, dot product = cosine

    def match(self, generated: dict[str, str], reference: dict[str, str], threshold: float | None = None) -> dict:
        """Match {id: label} of the generated model against {id: label} of the reference.

        threshold: overrides the default threshold for this call (used by the threshold sweep).
        Returns the matched pairs plus the missing (reference only) and extra (generated only) tasks.
        """
        threshold = self.threshold if threshold is None else threshold
        gen_ids, ref_ids = list(generated), list(reference)
        matched = []
        if gen_ids and ref_ids:
            similarity = self.similarity_matrix([generated[i] for i in gen_ids], [reference[i] for i in ref_ids])
            # Pairs below the threshold count as 0, so the algorithm never gives up an
            # acceptable pair in exchange for unacceptable ones.
            usable = np.where(similarity >= threshold, similarity, 0.0)
            rows, cols = linear_sum_assignment(usable, maximize=True)
            for r, c in zip(rows, cols):
                if similarity[r, c] >= threshold:
                    matched.append({
                        "generated_id": gen_ids[r], "generated_label": generated[gen_ids[r]],
                        "reference_id": ref_ids[c], "reference_label": reference[ref_ids[c]],
                        "similarity": round(float(similarity[r, c]), 4),
                    })

        used_gen = {m["generated_id"] for m in matched}
        used_ref = {m["reference_id"] for m in matched}
        return {
            "matched": matched,
            "missing": [{"reference_id": i, "reference_label": reference[i]} for i in ref_ids if i not in used_ref],
            "extra": [{"generated_id": i, "generated_label": generated[i]} for i in gen_ids if i not in used_gen],
        }

    def best_similarity(self, labels: list[str], texts: list[str]) -> list[float]:
        """For every label, the highest cosine similarity to any of the texts (0.0 if there are no texts)."""
        if not labels:
            return []
        if not texts:
            return [0.0] * len(labels)
        return [float(row.max()) for row in self.similarity_matrix(labels, texts)]
