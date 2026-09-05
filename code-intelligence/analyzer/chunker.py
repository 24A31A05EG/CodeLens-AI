def chunk_code(source: str, max_lines: int = 80):
    lines = source.splitlines()

    chunks = []

    for start in range(0, len(lines), max_lines):
        end = min(start + max_lines, len(lines))

        chunk = "\n".join(lines[start:end])

        chunks.append({
            "start_line": start + 1,
            "end_line": end,
            "content": chunk
        })

    return chunks