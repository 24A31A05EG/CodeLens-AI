def create_mermaid_diagram(components):
    lines = ["graph TD"]

    for component in components:
        name = component["name"]

        for dependency in component.get("depends_on", []):
            lines.append(
                f'    {name} --> {dependency}'
            )

    return "\n".join(lines)