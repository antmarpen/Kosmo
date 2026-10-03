from app.domain.workflows.validation import validate_output_validation_catalogue


def test_catalogue_reports_unknown_options_with_node_output_and_section():
    issues = validate_output_validation_catalogue({"nodes": [{
        "id": "writer", "type": "ai", "outputs": ["report"],
        "output_validation": {"report": {"levels": [
            {"name": "syntax", "message_key": "x", "params_schema": {"format": "xml"}},
            {"name": "format", "message_key": "x", "params_schema": {}},
            {"name": "rules", "message_key": "x", "params_schema": {}},
        ]}},
    }]})
    assert [(issue.params["node_id"], issue.params["output"], issue.params["section"])
            for issue in issues] == [("writer", "report", "syntax")]
