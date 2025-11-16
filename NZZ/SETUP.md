# Setup Guide

## Installation

1. **Install dependencies:**
   ```bash
   pip install -r ../requirements.txt
   pip install -r requirements_llm.txt
   ```

## Ollama Setup (for LLM-based Author Classification)

The scraper uses [Ollama](https://ollama.com/) to run a language model for accurately distinguishing between locations and author names.

### 1. Install Ollama

Download and install Ollama from: https://ollama.com/download

- **Windows**: Download the installer and run it
- **macOS**: Download the app or use Homebrew: `brew install ollama`
- **Linux**: Run: `curl -fsSL https://ollama.com/install.sh | sh`

### 2. Install the Python Library

```bash
pip install ollama
```

Or install from requirements:
```bash
pip install -r requirements_llm.txt
```

### 3. Pull the Model

The default model is `gemma3:270m` (small and fast). You can change it via the `OLLAMA_MODEL` environment variable.

```bash
ollama pull gemma3:270m
```

### 4. Run Ollama

Ollama needs to be running for the LLM classifier to work.

**Windows/macOS**: Ollama runs automatically after installation.

**Linux/Background**: Run Ollama in the background:
```bash
ollama serve
```

Or use nohup:
```bash
nohup ollama serve > ollama.log 2>&1 &
```

### 5. Verify Installation

```bash
ollama list
```

You should see `gemma3:270m` (or your chosen model) in the list.

## Database

Articles are stored in `nzz_scraped_articles.db` SQLite database in the NZZ folder.

## Logs

Log files are saved in the `log/` subfolder:
- `nzz_scraper_YYYYMMDD_HHMMSS.log` - Main operation logs
- `nzz_scraper_errors_YYYYMMDD_HHMMSS.log` - Error logs only



