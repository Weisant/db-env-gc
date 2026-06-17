# Direct Output Contract

Return only one ProjectArtifacts JSON object:

```json
{
  "project_name": "string",
  "cve_id": "CVE-YYYY-NNNN or empty string",
  "files": [
    {
      "path": "relative/path",
      "purpose": "string",
      "content": "complete file content"
    }
  ],
  "run_instructions": ["string"],
  "summary": "string"
}
```

Do not wrap the project in an `action` or `project` field.
