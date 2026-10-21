from backend.llm_engine.engine.tools.code_diagrams import CodeDiagramArgs, traverse

REV_C = {
    "nodes": [
        {"id": "1", "tag": "TK-1", "label": "Tank", "type": "tank"},
        {"id": "2", "tag": "F-101", "label": "Filter", "type": "filter"},
        {"id": "3", "tag": "SV-1", "label": "Solenoid valve", "type": "valve"},
        {"id": "4", "tag": "INJ-14", "label": "Injector", "type": "injector"},
        {"id": "5", "tag": "PSU-2", "label": "Power supply", "type": "power_supply"},
        {"id": "6", "tag": "PT-101", "label": "Chamber pressure", "type": "sensor"},
    ],
    "edges": [
        {"source": "1", "target": "2", "medium": "propellant"},
        {"source": "2", "target": "3", "medium": "propellant"},
        {"source": "3", "target": "4", "medium": "propellant"},
        {"source": "5", "target": "3", "medium": "electrical"},
        {"source": "4", "target": "6", "medium": "signal", "directed": False},
    ],
}


def run(**kw):
    return traverse(REV_C, CodeDiagramArgs(**kw))


def test_upstream_of_the_injector_linearized():
    result, display, warnings = run(mode="diagram_path", from_tag="INJ-14", direction="upstream")
    assert ["TK-1", "F-101", "SV-1", "INJ-14"] in result["upstream"]
    assert "Upstream: TK-1 → F-101 → SV-1 → INJ-14" in display and warnings == []


def test_shortest_path_between_two_tags():
    result, display, _ = run(mode="diagram_path", from_tag="tk-1", to_tag="INJ-14")
    assert result["path"] == ["TK-1", "F-101", "SV-1", "INJ-14"]
    assert display == "Path: TK-1 → F-101 → SV-1 → INJ-14"


def test_neighbors_name_media():
    result, display, _ = run(mode="diagram_neighbors", from_tag="SV-1")
    assert result["upstream"] == ["F-101 [propellant]", "PSU-2 [electrical]"]
    assert result["downstream"] == ["INJ-14 [propellant]"]
    assert display.startswith("SV-1: upstream F-101 [propellant], PSU-2 [electrical]")


def test_undirected_edges_go_both_ways_and_unknown_tags_are_reported():
    result, _, _ = run(mode="diagram_neighbors", from_tag="PT-101")
    assert result["upstream"] == ["INJ-14 [signal]"] and result["downstream"] == ["INJ-14 [signal]"]
    _, display, warnings = run(mode="diagram_path", from_tag="XV-9")
    assert warnings == ["unknown tag XV-9"] and "not in this diagram" in display
