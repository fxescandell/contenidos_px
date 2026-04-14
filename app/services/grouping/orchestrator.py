from abc import ABC, abstractmethod
from typing import List, Dict, Any
from app.db.models import SourceBatch, SourceFile
from app.schemas.all_schemas import GroupingResult
from app.core.enums import CandidateGroupingStrategy

class BaseGroupingStrategy(ABC):
    @property
    @abstractmethod
    def name(self) -> CandidateGroupingStrategy:
        pass

    @abstractmethod
    def group(self, batch: SourceBatch, files: List[SourceFile]) -> List[GroupingResult]:
        pass

class FolderGroupingStrategy(BaseGroupingStrategy):
    @property
    def name(self) -> CandidateGroupingStrategy:
        return CandidateGroupingStrategy.DIRECTORY_BASED

    def group(self, batch: SourceBatch, files: List[SourceFile]) -> List[GroupingResult]:
        # Implementation for grouping by folder
        # If files share the same relative directory inside the batch
        groups = {}
        for f in files:
            parts = f.relative_path.split('/')
            dir_key = parts[0] if len(parts) > 1 else "root"
            if dir_key not in groups:
                groups[dir_key] = []
            groups[dir_key].append(f)
            
        results = []
        for key, group_files in groups.items():
            if not group_files: continue
            
            assigned = []
            for idx, f in enumerate(group_files):
                assigned.append({
                    "id": f.id,
                    "role": "PRIMARY_DOCUMENT" if f.extension.lower() in [".docx", ".pdf", ".md", ".markdown", ".txt"] else "PRIMARY_IMAGE",
                    "sort_order": idx,
                    "confidence": 0.9 if key != "root" else 0.5
                })
                
            results.append(GroupingResult(
                candidate_key=f"{batch.id}_{key}",
                strategy=self.name,
                confidence=0.9 if key != "root" else 0.5,
                assigned_files=assigned
            ))
            
        return results

class GroupingOrchestrator:
    def __init__(self):
        self.strategies: List[BaseGroupingStrategy] = [
            FolderGroupingStrategy(),
            # Add DocumentPlusImagesGroupingStrategy, LooseFilesHeuristicGroupingStrategy, SinglePosterGroupingStrategy here
        ]
        
    def group_batch(self, batch: SourceBatch, files: List[SourceFile]) -> List[GroupingResult]:
        # A simple approach: Try the first strategy that yields high confidence
        # For this base implementation, we'll just run the folder strategy
        for strategy in self.strategies:
            results = strategy.group(batch, files)
            # If we found groups with reasonable confidence, return them
            if any(r.confidence > 0.7 for r in results):
                return results
                
        # Fallback to the last strategy or a default logic
        return self.strategies[0].group(batch, files) if self.strategies else []
