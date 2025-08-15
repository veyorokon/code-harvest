# code-harvest

Harvest codebases into portable JSON + chunks for search, RAG, and tooling.

## Install
```bash
pipx install harvest-code
```

## Quick start
```bash
harvest reap . -o out.harvest.json
harvest query out.harvest.json --entity chunks --public true --path-glob 'src/**'
harvest serve out.harvest.json
```

Visit http://localhost:8787 to browse your harvested codebase.