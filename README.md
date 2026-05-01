# xWiki

A standalone knowledge management and wiki generation system using LLMs and SQLite.

## Features
- **Ingestor**: Processes raw documents and stores them in SQLite.
- **Searcher**: Provides semantic and FTS5 search capabilities.
- **Compiler**: Uses LLMs to synthesize knowledge from documents into wiki entities.
- **Agent**: Iterative agent for deep knowledge extraction and verification.
- **Viewer**: Formatted display of wiki content.
- **Health Check**: Identifies gaps and contradictions in the wiki.

## Setup
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```
2. Configure environment:
   Copy `.env.example` to `.env` and fill in your API keys. (Currently `.env` is already created with placeholders).

## Usage
- **Ingestion**: `python ingestor.py`
- **Searching**: `python searcher.py`
- **Agent/Compiling**: `python agent.py`
- **Viewing**: `python viewer.py`
- **Health Check**: `python health_check.py`
