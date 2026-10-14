"""Copy the working cases from the raw PMo dataset into data/cases/ and summarise them.

For every case ID listed in config.yaml, this script copies:
  data/raw/pmo/descriptions/<id>.txt  ->  data/cases/<id>/description.txt
  data/raw/pmo/bpmn/<id>.bpmn         ->  data/cases/<id>/reference.bpmn

It then prints one row per case: the number of words in the description and the
number of tasks and gateways in the reference BPMN.

Run from the project root:  .venv\\Scripts\\python.exe -m src.load_cases
"""

import shutil
from pathlib import Path

from lxml import etree

from src.config import load_config, project_path


class CaseLoader:
    """Copies cases from the raw dataset and describes their size."""

    def __init__(self, config: dict):
        paths = config["paths"]
        self.case_ids = config["cases"]["ids"]
        self.raw_descriptions_dir = project_path(paths["pmo_descriptions"])
        self.raw_bpmn_dir = project_path(paths["pmo_bpmn"])
        self.cases_dir = project_path(paths["cases"])
        self.description_file = paths["case_description_file"]
        self.reference_file = paths["case_reference_file"]

    def copy_case(self, case_id: str) -> Path:
        """Copy the description and reference BPMN of one case into its own folder."""
        case_dir = self.cases_dir / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.raw_descriptions_dir / f"{case_id}.txt",
                        case_dir / self.description_file)
        shutil.copyfile(self.raw_bpmn_dir / f"{case_id}.bpmn",
                        case_dir / self.reference_file)
        return case_dir

    def copy_all(self) -> list[Path]:
        """Copy every case listed in config.yaml."""
        return [self.copy_case(case_id) for case_id in self.case_ids]

    def summarise_case(self, case_id: str) -> dict:
        """Count the words in the description and the tasks and gateways in the BPMN."""
        case_dir = self.cases_dir / case_id
        text = (case_dir / self.description_file).read_text(encoding="utf-8")
        tasks, gateways = count_tasks_and_gateways(case_dir / self.reference_file)
        return {"case_id": case_id, "words": len(text.split()),
                "tasks": tasks, "gateways": gateways}


def count_tasks_and_gateways(bpmn_path: Path) -> tuple[int, int]:
    """Count BPMN elements by tag name.

    Tasks: every element whose name ends in "task" (task, userTask, serviceTask, ...).
    Gateways: every element whose name ends in "Gateway" (exclusive, parallel, ...).
    The XML namespace is ignored by looking only at the local tag name.
    """
    tree = etree.parse(str(bpmn_path))
    tasks = gateways = 0
    for element in tree.iter():
        if not isinstance(element.tag, str):  # skip XML comments
            continue
        name = etree.QName(element).localname
        if name.lower().endswith("task"):
            tasks += 1
        elif name.endswith("Gateway"):
            gateways += 1
    return tasks, gateways


def print_table(rows: list[dict]) -> None:
    """Print the summary rows as a simple aligned table."""
    print(f"{'case':<6}{'words':>7}{'tasks':>7}{'gateways':>10}")
    for row in rows:
        print(f"{row['case_id']:<6}{row['words']:>7}{row['tasks']:>7}{row['gateways']:>10}")


def main() -> None:
    loader = CaseLoader(load_config())
    loader.copy_all()
    print(f"Copied {len(loader.case_ids)} cases to {loader.cases_dir}\n")
    print_table([loader.summarise_case(case_id) for case_id in loader.case_ids])


if __name__ == "__main__":
    main()
