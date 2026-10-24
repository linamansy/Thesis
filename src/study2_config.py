"""Study 2 config view: a copy of config.yaml in which the shared settings point to the GDPR setup.

Study 1's code (run_experiment.ExperimentRunner, the Orchestrator, the Evaluator) reads its paths and cases from the
config. Instead of changing that code or the Study 1 defaults, Study 2 gives it a deep copy in which:
  paths.passages          -> study2_gdpr.passages_restricted   (GDPR Chapters I-V; passage titles for the C3 block)
  paths.dense_index_dir   -> study2_gdpr.dense_index_dir_restricted
  paths.frozen_retrieval  -> study2_gdpr.frozen_retrieval      (the chosen version: rerank, decided 24 Oct 2026)
  cases.ids               -> study2_gdpr.development_ids
  reranker.enabled        -> study2_gdpr.reranker_enabled      (true; the Study 1 default stays false)
The config itself is never changed, so Study 1 keeps reading data/retrieval/frozen_retrieval.json.
"""

from src.freeze_retrieval_gdpr import gdpr_view


def study2_view(config: dict) -> dict:
    """A copy of the config for Study 2 runs on the GDPR development cases."""
    view = gdpr_view(config)
    gdpr = config["study2_gdpr"]
    view["paths"]["frozen_retrieval"] = gdpr["frozen_retrieval"]
    view["reranker"]["enabled"] = gdpr["reranker_enabled"]
    return view
