"""Pydantic models for the JSON process structure the generator LLM must return.

The LLM never writes BPMN XML. It returns JSON in this format, Pydantic checks
it, and BPMNBuilder turns it into BPMN XML.
"""

from pydantic import BaseModel, Field, model_validator

# Ids must be valid XML ids: start with a letter or underscore, no spaces.
ID_PATTERN = r"^[A-Za-z_][A-Za-z0-9_.-]*$"


class Element(BaseModel):
    """Anything with an id and a name."""

    id: str = Field(pattern=ID_PATTERN, description="Unique id that starts with a letter, e.g. task_1")
    name: str = Field(description="Short label shown in the diagram")


class StartEvent(Element):
    """Where the process begins."""


class EndEvent(Element):
    """Where the process ends."""


class Task(Element):
    """One activity performed in the process."""


class Gateway(Element):
    """A point where paths split or join."""


class SequenceFlow(BaseModel):
    """An arrow from one element to the next."""

    id: str = Field(pattern=ID_PATTERN, description="Unique id, e.g. flow_1")
    source: str = Field(description="id of the element the flow starts from")
    target: str = Field(description="id of the element the flow goes to")
    condition: str | None = Field(
        default=None,
        description="Decision outcome label (e.g. 'yes'), only on flows leaving an exclusive gateway",
    )


class Lane(Element):
    """A role or department, with the tasks it performs."""

    task_ids: list[str] = Field(description="ids of the tasks performed in this lane")


class ProcessModel(BaseModel):
    """A complete process: all elements and the flows that connect them."""

    start_events: list[StartEvent] = Field(min_length=1)
    end_events: list[EndEvent] = Field(min_length=1)
    tasks: list[Task]
    exclusive_gateways: list[Gateway] = Field(
        default_factory=list, description="Decisions: exactly one outgoing path is taken")
    parallel_gateways: list[Gateway] = Field(
        default_factory=list, description="All outgoing paths are taken at the same time")
    sequence_flows: list[SequenceFlow]
    lanes: list[Lane] = Field(default_factory=list, description="Optional; only if the description names who does what")

    def flow_nodes(self) -> list[tuple[str, Element]]:
        """All elements that flows can connect, paired with their BPMN tag name."""
        return ([("startEvent", e) for e in self.start_events]
                + [("task", t) for t in self.tasks]
                + [("exclusiveGateway", g) for g in self.exclusive_gateways]
                + [("parallelGateway", g) for g in self.parallel_gateways]
                + [("endEvent", e) for e in self.end_events])

    @model_validator(mode="after")
    def check_ids_and_lanes(self):
        """Ids must be unique; lanes may only list existing tasks, each task in one lane at most."""
        ids = ([element.id for _, element in self.flow_nodes()]
               + [flow.id for flow in self.sequence_flows]
               + [lane.id for lane in self.lanes])
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate ids: {duplicates}")

        task_ids = {task.id for task in self.tasks}
        assigned = []
        for lane in self.lanes:
            unknown = [t for t in lane.task_ids if t not in task_ids]
            if unknown:
                raise ValueError(f"lane {lane.id} lists unknown tasks: {unknown}")
            assigned += lane.task_ids
        in_two_lanes = sorted({t for t in assigned if assigned.count(t) > 1})
        if in_two_lanes:
            raise ValueError(f"tasks assigned to more than one lane: {in_two_lanes}")
        return self
