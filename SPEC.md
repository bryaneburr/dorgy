# dorgy

Dorgy is a python-based CLI app that automatically organizes your files.

## 1. Executive Summary

An automated file organization system that leverages LLMs to intelligently categorize, rename, and structure files across various formats. The system processes documents, images, and other file types using advanced document understanding, metadata extraction, and semantic analysis.

### Primary Use Cases
- Organize scanned physical documents automatically
- Continuous monitoring and organization of new files (e.g., Downloads folder)
- Batch organization of existing file collections
- Smart cleanup and deduplication

## 2. System Architecture

### 2.1 Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                     CLI Interface (Click/Rich)              │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────────┐
│                  Configuration Manager                      │
│  (User settings, LLM config, watched dirs, rules)           │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │                             │
┌───────▼────────┐           ┌────────▼────────┐
│ File Watcher   │           │ Batch Processor │
│  (watchdog)    │           │  (one-time run) │
└───────┬────────┘           └────────┬────────┘
        │                             │
        └──────────────┬──────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                    File Queue Manager                       │
│            (Async processing, batch optimization)           │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                  Metadata Extractor                         │
│  • EXIF (Pillow)                                            │
│  • Document metadata (via Docling)                          │
│  • File system metadata                                     │
│  • Hash computation                                         │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                  Content Extractor                          │
│  • Docling (PDF, DOCX, PPTX, XLSX, images w/ OCR)           │
│  • Vision models for images (optional)                      │
│  • Audio transcription (optional)                           │
│  • Fallback to filename analysis                            │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                    DSPy LLM Processor                       │
│  • Category classification                                  │
│  • Tag generation                                           │
│  • Smart renaming                                           │
│  • Folder structure proposal                                │
│  • Confidence scoring                                       │
│  • Duplicate detection (semantic)                           │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                    Decision Engine                          │
│  • Apply user rules                                         │
│  • Resolve conflicts                                        │
│  • Flag ambiguous cases                                     │
│  • Generate organization plan                               │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                    Action Engine                            │
│  • Dry-run simulation                                       │
│  • File operations (move, rename, copy)                     │
│  • Undo/rollback support (.trash)                           │
│  • Transaction logging                                      │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                    Metadata Store                           │
│  • SQLite                                                   │
│  • File metadata, tags, categories                          │
│  • Processing history, confidence scores                    │
│  • Vector embeddings (optional)                             │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Data Flow

```
1. File Detection → 2. Metadata Extraction → 3. Content Extraction →
4. LLM Analysis → 5. Decision Making → 6. Action Execution → 7. Metadata Storage
```

## 3. Technical Stack

### 3.1 Core Dependencies

```python
# File Processing
docling>=1.0.0              # Document understanding
watchdog>=3.0.0             # File system monitoring
Pillow>=10.0.0              # Image processing & EXIF

# LLM & AI
dspy>=2.0.0                 # LLM operations
sentence-transformers       # Local embeddings (optional)
ollama                      # Local LLM runtime (optional)

# Database
sqlalchemy>=2.0.0           # ORM
alembic                     # Migrations
chromadb                    # Vector store (optional)

# CLI & UI
click>=8.0.0                # CLI framework
rich>=13.0.0                # Terminal formatting
tqdm                        # Progress bars

# Utilities
pyyaml                      # Config files
python-magic                # File type detection
xxhash                      # Fast hashing
```

### 3.2 Platform Support
- **OS:** macOS, Linux (primary), Windows (future)
- **Python:** 3.10+
- **Architecture:** x86_64, arm64 (Apple Silicon optimized)

## 4. Configuration Schema

### 4.1 Main Configuration File (`~/.dorgy/config.yaml`)

```yaml
# LLM Configuration
llm:
  provider: "local"  # local, openai, anthropic
  model: "llama3"    # for ollama
  api_key: null      # for cloud providers
  temperature: 0.1
  max_tokens: 2000

# Processing Options
processing:
  use_vision_models: false
  process_audio: false
  follow_symlinks: false
  process_hidden_files: false
  max_file_size_mb: 100  # Sample files larger than this
  sample_size_mb: 10     # Size of sample for large files
  
  # Locked file handling
  locked_files:
    action: "copy"  # copy, skip, wait
    retry_attempts: 3
    retry_delay_seconds: 5
  
  # Corrupted file handling
  corrupted_files:
    action: "skip"  # skip, quarantine
    quarantine_folder: "~/.dorgy/quarantine"

# Organization Strategies
organization:
  mode: "move"  # move, in-place
  target_directory: null  # null = in-place, or specify path
  
  # Naming conflicts
  conflict_resolution: "append_number"  # append_number, timestamp, skip
  
  # Date-based organization
  use_dates: true
  date_format: "YYYY-MM"
  
  # Language handling
  preserve_language: false  # false = treat as English
  
  # Metadata preservation
  preserve_timestamps: true
  preserve_extended_attributes: true

# Ambiguity Handling
ambiguity:
  confidence_threshold: 0.80  # Flag for review if below this
  max_auto_categories: 3      # Max tags/categories per file
  review_folder: "~/.dorgy/needs-review"

# Performance
performance:
  batch_size: 10
  parallel_workers: 4
  enable_caching: true
  cache_embeddings: true

# Safety
safety:
  dry_run: false
  auto_backup: true
  backup_location: "~/.dorgy/backups"
  trash_location: "~/.dorgy/.trash"
  transaction_log: "~/.dorgy/transactions.log"
  rollback_on_error: true

# Logging
logging:
  level: "WARNING"  # DEBUG, INFO, WARNING, ERROR
  file: "~/.dorgy/dorgy.log"
  max_size_mb: 100
  backup_count: 5

# Watched Directories
watched_directories:
  - path: "~/Downloads"
    enabled: true
    recursive: false
    auto_organize: true
  - path: "~/Documents/Scans"
    enabled: true
    recursive: true
    auto_organize: true

# User-defined Rules (optional)
rules:
  # Example: Force certain patterns to specific categories
  - pattern: "invoice-*.pdf"
    category: "Finance/Invoices"
    priority: high
  - pattern: "*.tax"
    category: "Finance/Taxes"
    priority: high
```

### 4.2 Database Schema

```sql
-- Files table
CREATE TABLE files (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    original_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    file_type TEXT,
    file_size INTEGER,
    created_date TIMESTAMP,
    modified_date TIMESTAMP,
    processed_date TIMESTAMP,
    last_organized_date TIMESTAMP,
    status TEXT  -- pending, processed, needs_review, error
);

-- Metadata table
CREATE TABLE file_metadata (
    file_id INTEGER REFERENCES files(id),
    metadata_type TEXT,  -- exif, document, filesystem
    metadata_json TEXT,  -- JSON blob
    extracted_date TIMESTAMP,
    extracted_location TEXT,
    extracted_author TEXT,
    PRIMARY KEY (file_id, metadata_type)
);

-- Content table
CREATE TABLE file_content (
    file_id INTEGER PRIMARY KEY REFERENCES files(id),
    content_preview TEXT,  -- First N chars
    full_content_path TEXT,  -- Path to extracted text file
    extraction_method TEXT,  -- docling, ocr, vision, filename
    language TEXT,
    page_count INTEGER
);

-- Categories table
CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    parent_id INTEGER REFERENCES categories(id),
    description TEXT,
    created_date TIMESTAMP
);

-- File categories (many-to-many)
CREATE TABLE file_categories (
    file_id INTEGER REFERENCES files(id),
    category_id INTEGER REFERENCES categories(id),
    confidence REAL,
    is_primary BOOLEAN,
    PRIMARY KEY (file_id, category_id)
);

-- Tags table
CREATE TABLE tags (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

-- File tags (many-to-many)
CREATE TABLE file_tags (
    file_id INTEGER REFERENCES files(id),
    tag_id INTEGER REFERENCES tags(id),
    confidence REAL,
    PRIMARY KEY (file_id, tag_id)
);

-- Processing log
CREATE TABLE processing_log (
    id INTEGER PRIMARY KEY,
    file_id INTEGER REFERENCES files(id),
    timestamp TIMESTAMP,
    action TEXT,  -- extracted, classified, moved, renamed, etc.
    details TEXT,  -- JSON
    confidence REAL,
    needs_review BOOLEAN
);

-- Transactions (for rollback)
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP,
    operation_type TEXT,  -- organize_batch, watch_event
    files_affected INTEGER,
    status TEXT,  -- in_progress, completed, rolled_back
    details TEXT  -- JSON with file operations
);

-- Embeddings (optional, for semantic search)
CREATE TABLE embeddings (
    file_id INTEGER PRIMARY KEY REFERENCES files(id),
    embedding BLOB,
    model TEXT,
    created_date TIMESTAMP
);
```

## 5. DSPy Integration Strategy

### 5.1 DSPy Signatures

```python
import dspy

class FileClassification(dspy.Signature):
    """Classify a file into categories and generate relevant tags."""
    
    # Inputs
    filename: str = dspy.InputField(desc="The filename")
    file_type: str = dspy.InputField(desc="File type (pdf, jpg, etc)")
    content_preview: str = dspy.InputField(desc="Preview of file content")
    metadata: str = dspy.InputField(desc="Extracted metadata (JSON)")
    
    # Outputs
    primary_category: str = dspy.OutputField(desc="Main category for organization")
    secondary_categories: list[str] = dspy.OutputField(desc="Additional relevant categories")
    tags: list[str] = dspy.OutputField(desc="Descriptive tags")
    confidence: float = dspy.OutputField(desc="Confidence score 0-1")
    reasoning: str = dspy.OutputField(desc="Brief explanation of classification")


class FileRenaming(dspy.Signature):
    """Generate a descriptive filename for a file."""
    
    filename: str = dspy.InputField()
    file_type: str = dspy.InputField()
    content_preview: str = dspy.InputField()
    metadata: str = dspy.InputField()
    category: str = dspy.InputField(desc="Assigned category")
    
    suggested_name: str = dspy.OutputField(desc="Descriptive filename without extension")
    reasoning: str = dspy.OutputField(desc="Why this name")


class FolderStructureProposal(dspy.Signature):
    """Propose an optimal folder structure for organizing files."""
    
    file_list: str = dspy.InputField(desc="List of files with their classifications")
    existing_structure: str = dspy.InputField(desc="Current folder structure if any")
    
    proposed_structure: str = dspy.OutputField(desc="Hierarchical folder structure (JSON)")
    reasoning: str = dspy.OutputField(desc="Explanation of structure")


class DuplicateDetection(dspy.Signature):
    """Determine if two files are semantic duplicates."""
    
    file1_info: str = dspy.InputField()
    file2_info: str = dspy.InputField()
    
    is_duplicate: bool = dspy.OutputField()
    similarity_score: float = dspy.OutputField()
    reasoning: str = dspy.OutputField()
```

### 5.2 DSPy Module Example

```python
class dorgyanizer(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classifier = dspy.ChainOfThought(FileClassification)
        self.renamer = dspy.ChainOfThought(FileRenaming)
        self.structure_proposer = dspy.ChainOfThought(FolderStructureProposal)
    
    def forward(self, file_info):
        # Classify the file
        classification = self.classifier(
            filename=file_info['filename'],
            file_type=file_info['type'],
            content_preview=file_info['content'][:1000],
            metadata=json.dumps(file_info['metadata'])
        )
        
        # Generate new name if needed
        if classification.confidence >= 0.8:
            new_name = self.renamer(
                filename=file_info['filename'],
                file_type=file_info['type'],
                content_preview=file_info['content'][:1000],
                metadata=json.dumps(file_info['metadata']),
                category=classification.primary_category
            )
        else:
            new_name = None
        
        return {
            'classification': classification,
            'suggested_name': new_name,
            'needs_review': classification.confidence < 0.8
        }
```

### 5.3 LLM Configuration

```python
# Local LLM via Ollama
import dspy
from dspy import OllamaLocal

lm = OllamaLocal(model='llama3', base_url='http://localhost:11434')
dspy.settings.configure(lm=lm)

# Cloud LLM (optional)
# from dspy import OpenAI, Anthropic
# lm = OpenAI(model='gpt-4', api_key='...')
# lm = Anthropic(model='claude-3-5-sonnet-20241022', api_key='...')
```

## 6. Implementation Phases

### Phase 1: Core Foundation (Weeks 1-2)
**Deliverables:**
- Project structure and dependencies
- Configuration management
- Database schema and migrations
- Basic CLI with Click + Rich
- Metadata extractor (EXIF, filesystem)
- Content extractor (Docling integration)
- DSPy setup with basic signatures
- File operations (copy, move, rename) with safety checks

**Milestone:** Can extract content from files and store in database

### Phase 2: LLM Integration (Weeks 3-4)
**Deliverables:**
- DSPy modules for classification and renaming
- Local LLM integration (Ollama)
- Cloud LLM support (optional)
- Confidence scoring
- Basic rule engine
- Dry-run mode implementation
- Transaction logging

**Milestone:** Can classify and rename files with LLM

### Phase 3: Organization Logic (Weeks 5-6)
**Deliverables:**
- Folder structure proposal system
- In-place vs move modes
- Conflict resolution
- Batch processing
- Ambiguity detection and flagging
- Multi-page document handling
- Duplicate detection (hash + semantic)

**Milestone:** Can organize a directory end-to-end

### Phase 4: Automation (Weeks 7-8)
**Deliverables:**
- File watcher implementation
- Queue management
- Async processing
- Performance optimization (parallel, batching)
- Progress indicators
- Error recovery and rollback
- Undo mechanism with .trash

**Milestone:** Can continuously monitor and organize folders

### Phase 5: Polish & Enhancement (Weeks 9-10)
**Deliverables:**
- Vision model support for images
- Vector embeddings for semantic search
- Enhanced logging and debugging
- Performance profiling and optimization
- Comprehensive test suite
- Documentation
- macOS app packaging exploration

**Milestone:** Production-ready system

## 7. CLI Design

### 7.1 Command Structure

```bash
# Main command
dorgy [OPTIONS] COMMAND [ARGS]

# Commands
dorgy init                    # Initialize configuration
dorgy organize PATH           # Organize files in directory
dorgy watch [PATH...]         # Start watching directories
dorgy status                  # Show current operations
dorgy undo [TRANSACTION_ID]   # Undo last operation
dorgy review                  # Review flagged files
dorgy config [edit|show]      # Manage configuration
dorgy search QUERY            # Search organized files
dorgy stats [PATH]            # Show statistics
```

### 7.2 Command Examples

```bash
# First time setup
dorgy init
# Creates ~/.dorgy/config.yaml with defaults
# Initializes database

# Dry run to preview organization
dorgy organize ~/Documents/Scans --dry-run
# Shows proposed structure with Rich tree visualization
# Prompts for approval before proceeding

# Organize files (move to target directory)
dorgy organize ~/Downloads --target ~/Documents/Organized

# Organize files in-place
dorgy organize ~/Documents --in-place

# Start watching directories (from config)
dorgy watch --daemon

# Watch specific directory
dorgy watch ~/Downloads --interval 5

# Review ambiguous files
dorgy review
# Interactive CLI to manually categorize flagged files

# Undo last operation
dorgy undo
dorgy undo --transaction 42

# Search organized files
dorgy search "tax documents 2024"
dorgy search --category Finance --after 2024-01-01

# Statistics
dorgy stats
dorgy stats ~/Documents/Organized

# Configuration
dorgy config edit
dorgy config show
dorgy config set llm.model llama3.1
```

### 7.3 Interactive Dry-Run UI (Rich)

```python
from rich.console import Console
from rich.tree import Tree
from rich.prompt import Confirm
from rich.table import Table

def show_dry_run_results(organization_plan):
    console = Console()
    
    # Show proposed structure as tree
    tree = Tree("📁 Proposed Organization")
    for folder, files in organization_plan.items():
        folder_node = tree.add(f"📂 {folder}")
        for file in files:
            confidence = file['confidence']
            icon = "✅" if confidence >= 0.8 else "⚠️"
            folder_node.add(
                f"{icon} {file['new_name']} "
                f"(confidence: {confidence:.2%})"
            )
    
    console.print(tree)
    
    # Show statistics
    table = Table(title="Organization Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Total Files", str(len(organization_plan)))
    table.add_row("High Confidence", str(high_confidence_count))
    table.add_row("Needs Review", str(needs_review_count))
    table.add_row("New Folders", str(len(organization_plan)))
    
    console.print(table)
    
    # Prompt for approval
    if Confirm.ask("\nProceed with organization?"):
        return True
    return False
```

## 8. Performance Considerations

### 8.1 Batch Processing Strategy

```python
class BatchProcessor:
    def __init__(self, batch_size=10, max_workers=4):
        self.batch_size = batch_size
        self.max_workers = max_workers
    
    async def process_files(self, files):
        # Group files into batches
        batches = self.create_batches(files, self.batch_size)
        
        # Process batches in parallel
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:
            futures = [
                executor.submit(self.process_batch, batch)
                for batch in batches
            ]
            
            # Show progress with Rich
            with Progress() as progress:
                task = progress.add_task(
                    "Processing files...",
                    total=len(files)
                )
                
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    progress.update(task, advance=len(result))
```

### 8.2 Caching Strategy

```python
# Cache embeddings to avoid recomputation
@lru_cache(maxsize=1000)
def get_file_embedding(file_hash: str) -> np.ndarray:
    # Check database first
    cached = db.get_embedding(file_hash)
    if cached:
        return cached
    
    # Compute and store
    embedding = compute_embedding(file_content)
    db.store_embedding(file_hash, embedding)
    return embedding

# Cache LLM responses for identical inputs
@lru_cache(maxsize=500)
def classify_content(content_hash: str, metadata_hash: str):
    # DSPy call cached automatically
    pass
```

### 8.3 Large File Handling

```python
def process_large_file(file_path: Path, max_size_mb: int = 100):
    file_size_mb = file_path.stat().st_size / (1024 * 1024)
    
    if file_size_mb > max_size_mb:
        # Sample the file
        return sample_file_content(
            file_path,
            sample_size_mb=10
        )
    else:
        return extract_full_content(file_path)
```

## 9. Safety & Error Handling

### 9.1 Transaction Management

```python
class Transaction:
    def __init__(self, db_session):
        self.session = db_session
        self.operations = []
        self.start_time = datetime.now()
    
    def add_operation(self, operation_type, source, destination):
        self.operations.append({
            'type': operation_type,
            'source': source,
            'destination': destination,
            'timestamp': datetime.now()
        })
    
    def commit(self):
        # All operations successful
        self.session.commit()
        self.log_transaction('completed')
    
    def rollback(self):
        # Undo all operations
        for op in reversed(self.operations):
            if op['type'] == 'move':
                shutil.move(op['destination'], op['source'])
            elif op['type'] == 'rename':
                os.rename(op['destination'], op['source'])
        
        self.session.rollback()
        self.log_transaction('rolled_back')
```

### 9.2 Undo Mechanism

```python
def move_to_trash(file_path: Path, trash_dir: Path):
    """Move file to trash instead of deleting."""
    trash_path = trash_dir / file_path.name
    
    # Handle naming conflicts in trash
    counter = 1
    while trash_path.exists():
        trash_path = trash_dir / f"{file_path.stem}_{counter}{file_path.suffix}"
        counter += 1
    
    shutil.move(file_path, trash_path)
    return trash_path

def undo_transaction(transaction_id: int):
    """Restore files from last transaction."""
    transaction = db.get_transaction(transaction_id)
    
    for operation in reversed(transaction.operations):
        if operation['type'] == 'move':
            # Restore from trash or original location
            restore_file(operation)
```

### 9.3 Error Recovery

```python
def process_file_with_retry(file_path, max_retries=3):
    for attempt in range(max_retries):
        try:
            result = process_file(file_path)
            return result
        except FileLockedError:
            if attempt < max_retries - 1:
                time.sleep(config.retry_delay_seconds)
                continue
            else:
                # Handle per config: copy, skip, or fail
                return handle_locked_file(file_path)
        except CorruptedFileError:
            if config.corrupted_files.action == 'quarantine':
                move_to_quarantine(file_path)
            return None
        except Exception as e:
            log.error(f"Error processing {file_path}: {e}")
            if config.rollback_on_error:
                raise
            return None
```

## 10. Testing Strategy

### 10.1 Test Structure

```
tests/
├── unit/
│   ├── test_metadata_extractor.py
│   ├── test_content_extractor.py
│   ├── test_dspy_modules.py
│   └── test_file_operations.py
├── integration/
│   ├── test_full_pipeline.py
│   ├── test_watch_mode.py
│   └── test_database.py
├── fixtures/
│   ├── sample_files/
│   │   ├── documents/
│   │   ├── images/
│   │   └── mixed/
│   └── expected_results/
└── conftest.py
```

### 10.2 Key Test Cases

- Metadata extraction from various file types
- Content extraction with Docling
- DSPy classification accuracy
- Folder structure generation
- Conflict resolution
- Transaction rollback
- Dry-run correctness
- Performance benchmarks

## 11. Future Enhancements

### 11.1 Phase 6+ Features

- **Web UI:** Browser-based interface for remote access
- **Advanced Search:** Full-text search with semantic queries
- **ML Optimization:** DSPy optimization with user feedback
- **Cloud Sync:** Integration with cloud storage providers
- **Mobile App:** iOS/Android companion apps
- **Plugins:** Extension system for custom processors
- **AI Features:**
  - Auto-summarization of documents
  - Smart content recommendations
  - Predictive organization
- **Collaboration:** Multi-user support
- **Advanced Security:**
  - PII detection and redaction
  - Encryption for sensitive files
  - Access control

### 11.2 Scalability Path

- **100K+ files:** PostgreSQL + connection pooling
- **1M+ files:** Distributed processing with Celery
- **10M+ files:** Separate microservices architecture

## 12. Success Metrics

- **Accuracy:** >90% classification confidence on typical documents
- **Performance:** Process 100 files in <5 minutes (including LLM calls)
- **User Satisfaction:** <5% manual review rate
- **Reliability:** 99% successful file operations without data loss
- **Usability:** First-time users can organize folder in <5 minutes

## 13. Project Timeline

**Total Duration:** 10 weeks

- **Weeks 1-2:** Core foundation
- **Weeks 3-4:** LLM integration
- **Weeks 5-6:** Organization logic
- **Weeks 7-8:** Automation
- **Weeks 9-10:** Polish and enhancement

**Milestones:**
1. End Week 2: Can extract and store file information
2. End Week 4: Can classify files with LLM
3. End Week 6: Can organize directories end-to-end
4. End Week 8: Can monitor and auto-organize
5. End Week 10: Production-ready with documentation

---

## Appendix A: Example Workflows

### A.1 First-Time User Workflow

```bash
# 1. Install
pip install dorgy

# 2. Initialize
dorgy init

# 3. Organize Downloads folder (dry-run)
dorgy organize ~/Downloads --dry-run

# 4. Review proposed structure, approve

# 5. Execute organization
dorgy organize ~/Downloads --target ~/Documents/Organized

# 6. Set up continuous monitoring
dorgy config set watched_directories[0].path ~/Downloads
dorgy config set watched_directories[0].enabled true
dorgy watch --daemon
```

### A.2 Scanned Documents Workflow

```bash
# 1. Set up scan output folder monitoring
dorgy config set watched_directories[1].path ~/Documents/Scans
dorgy config set watched_directories[1].auto_organize true

# 2. Start watching
dorgy watch --daemon

# 3. Scan documents → automatically processed and organized

# 4. Review flagged items periodically
dorgy review
```

### A.3 Batch Cleanup Workflow

```bash
# 1. Organize with statistics
dorgy organize ~/OldFiles --stats

# 2. Review what needs attention
dorgy review

# 3. Search organized files
dorgy search "2023 receipts"

# 4. If needed, undo
dorgy undo
```

### A.4 Development environment
- Use `uv` to manage the python environment and add this directive to the main AGENTS.md file.
- Always create and update AGENTS.md files for any modules that require them and add this directive to the main AGENTS.md file.
- Configure pre-commit hooks that run auto-formatting, liniting, import sorting, and run tests (if python files have changed).
- Use feature branches for all new work and commit early and often, merging feature branches with `main` if and only if all linters and tests pass. Add this directive to the main AGENTS.md file.
---

*Document Version: 1.0*
*Last Updated: 2025-10-09*