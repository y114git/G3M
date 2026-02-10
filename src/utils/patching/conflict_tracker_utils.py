"""Conflict tracking for multi-mod merging."""
import re
import time
from typing import Dict, List, Any
from config.patching_config import COMPILATION_ERROR_PATTERNS
from services.patching_log_service import get_conflicts_logger, rotate_conflicts_log


class PatchingConflictTracker:
    """Tracks resource modification history and detected conflicts during merge."""

    def __init__(self, patching_logger):
        self.patching_logger = patching_logger
        self.conflicts_logger = get_conflicts_logger()
        self.detected_conflicts: List[Dict[str, Any]] = []
        self.resource_modification_history: Dict[str, List[Dict[str, Any]]] = {}
        self._conflicts_log_rotated_this_session: bool = False

    def reset(self, patching_logger=None):
        """Reset state for a new merge session."""
        if patching_logger:
            self.patching_logger = patching_logger
        self.conflicts_logger = get_conflicts_logger()
        self.detected_conflicts = []

    def track_mod_history(self, resource_name: str, resource_type: str, mod_name: str, action: str = 'merged') -> None:
        if mod_name in ('0', 'vanilla', 'unknown_mod'):
            return
        if resource_name not in self.resource_modification_history:
            self.resource_modification_history[resource_name] = []
        existing_mods = [h['mod'] for h in self.resource_modification_history[resource_name]]
        if mod_name not in existing_mods:
            self.resource_modification_history[resource_name].append({'type': resource_type, 'mod': mod_name, 'action': action, 'timestamp': time.time()})

    def log_conflict(self, resource_type: str, resource_name: str, prev_mods: List[str], current_mod: str) -> None:
        prev_filtered = [m for m in prev_mods if m not in ('0', 'vanilla', 'unknown_mod', 'merged_mods', current_mod)]
        prev_unique = list(dict.fromkeys(prev_filtered))
        if not prev_unique:
            return
        conflict_msg = f'''{resource_type.capitalize()} "{resource_name}" was modified by: {', '.join(prev_unique)} before "{current_mod}". Higher priority mod ({current_mod}) will be used.'''
        self.patching_logger.warning(f'[CONFLICT] {conflict_msg}')
        self._rotate_conflicts_log_if_needed()
        self.conflicts_logger.info(f'''Resource: {resource_type.capitalize()} "{resource_name}" | Conflict between: {', '.join(prev_unique)} vs "{current_mod}" | Resolution: Using "{current_mod}" (higher priority)''')
        self.detected_conflicts.append({'resource_type': resource_type, 'resource_name': resource_name, 'mods': prev_unique + [current_mod], 'resolution': current_mod})

    def _rotate_conflicts_log_if_needed(self):
        if not self._conflicts_log_rotated_this_session:
            rotate_conflicts_log()
            self._conflicts_log_rotated_this_session = True
            self.conflicts_logger = get_conflicts_logger()

    def analyze_compilation_errors(self, stdout: str, stderr: str, script_name: str, mod_name: str) -> List[Dict[str, Any]]:
        errors_found = []
        combined_output = (stdout or '') + '\n' + (stderr or '')
        error_patterns = COMPILATION_ERROR_PATTERNS
        for pattern, error_type in error_patterns:
            matches = re.finditer(pattern, combined_output, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                error_context = match.group(0)
                variable_name = match.group(1) if len(match.groups()) > 0 else None
                object_name = match.group(2) if len(match.groups()) > 1 else None
                error_start = match.start()
                error_end = min(error_start + 500, len(combined_output))
                context = combined_output[error_start:error_end].split('\n')[:5]
                context_str = '\n'.join(context)
                error_info = {'type': error_type, 'script': script_name, 'mod': mod_name, 'error_message': error_context, 'context': context_str, 'variable_name': variable_name, 'object_name': object_name}
                errors_found.append(error_info)
                error_desc = f'Code Error: {error_type}'
                if variable_name:
                    error_desc += f' (variable: {variable_name})'
                if object_name:
                    error_desc += f' (object: {object_name})'
                self._rotate_conflicts_log_if_needed()
                self.conflicts_logger.info(f'Resource: GML Code | Error Type: {error_desc} | Script: {script_name} | Mod: {mod_name} | Error: {error_context[:200]}')
                self.detected_conflicts.append({'resource_type': 'code_error', 'resource_name': variable_name or object_name or 'unknown', 'mods': [mod_name], 'error_type': error_type, 'error_message': error_context[:300], 'script': script_name})
        return errors_found

    def get_conflicts_summary(self) -> Dict[str, Any]:
        if not self.detected_conflicts:
            return {'has_conflicts': False, 'conflicting_mods': set(), 'conflicts': []}
        all_mods = set()
        mod_pairs = set()
        unique_resources = set()
        for conflict in self.detected_conflicts:
            mods = conflict['mods']
            seen = set()
            unique_mods = [m for m in mods if not (m in seen or seen.add(m))]
            if len(unique_mods) < 2:
                continue
            all_mods.update(unique_mods)
            for i in range(len(unique_mods)):
                for j in range(i + 1, len(unique_mods)):
                    if unique_mods[i] != unique_mods[j]:
                        mod_pairs.add(tuple(sorted([unique_mods[i], unique_mods[j]])))
            resource_key = (conflict.get('resource_type'), conflict.get('resource_name'))
            unique_resources.add(resource_key)
        total_unique_conflicts = len(unique_resources)
        return {'has_conflicts': True, 'conflicting_mods': sorted(all_mods), 'mod_pairs': [list(pair) for pair in sorted(mod_pairs)], 'conflicts': self.detected_conflicts, 'total_conflicts': total_unique_conflicts}
