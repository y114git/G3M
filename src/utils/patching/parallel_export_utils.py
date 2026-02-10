"""Parallel export and filtering operations for mod patching."""
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Any
from utils.patching import resource_filter_utils as resource_filter
from utils.patching import mod_content_utils as mod_content
from utils.progress_throttler import ProgressThrottler
from services.mod_patching_service import ModPatcher


def perform_parallel_export(patcher, mods_to_export: List[Any], mods_to_apply: List[Any], mod_patched_files: Dict[int, str], mod_types: Dict[int, Dict], vanilla_data_win: str, patch_root: str, cache_running_dir: str, chapter_str: str, chapter_id: int, progress_base: int, export_progress: int, progress_callback) -> bool:
    if not mods_to_export:
        return True
    log_lock = threading.Lock()
    completed_count = [0]
    total_mods = len(mods_to_export)
    max_workers = max(1, min(os.cpu_count() - 1, total_mods, 8))
    patcher.patching_logger.info(f'[PARALLEL_EXPORT] Starting parallel export for {total_mods} mod(s) using {max_workers} worker(s)')
    throttler = ProgressThrottler(progress_callback, throttle_ms=150, parent=patcher)

    def export_single_mod(mod_info):
        mod_data, idx, original_idx, mod_number = mod_info
        mod_name = getattr(mod_data, 'name', 'Unknown')
        thread_id = threading.current_thread().ident
        try:
            with log_lock:
                patcher.patching_logger.info(f'[Mod-{mod_number}] [{thread_id}] Starting export for {mod_name}')
            mod_data_win = mod_patched_files.get(mod_number)
            if not mod_data_win or not os.path.exists(mod_data_win):
                with log_lock:
                    patcher.patching_logger.warning(f'[Mod-{mod_number}] [{thread_id}] data.win not found, skipping export')
                return (mod_number, False, mod_name, 'data.win not found')
            mod_dir = os.path.dirname(mod_data_win)
            mod_asset_types = mod_content.detect_mod_asset_types(mod_dir, logger=patcher.patching_logger)
            mod_type = mod_types.get(mod_number, {})
            has_previous_mod = mod_number > 1 and mod_number - 1 in mod_patched_files
            scripts, comparison_file = patcher._select_export_strategy(mod_type, mod_asset_types, mod_number, has_previous_mod)
            if not scripts and comparison_file is None:
                with log_lock:
                    patcher.patching_logger.info(f'[Mod-{mod_number}] [{thread_id}] Skipping export - already exported')
                return (mod_number, True, mod_name, 'already exported')
            with log_lock:
                patcher.patching_logger.info(f'[Mod-{mod_number}] [{thread_id}] Exporting using strategy: {scripts}, comparison: {comparison_file}')
            success = patcher._export_mod_assets_optimized(mod_data_win, mod_number, scripts, comparison_file, vanilla_data_win, patch_root, cache_running_dir, chapter_str)
            if success:
                objects_dir = os.path.join(mod_dir, 'Objects')
                if os.path.exists(objects_dir):
                    with log_lock:
                        patcher._log_resource_counts(objects_dir, f'[Mod-{mod_number}] [{thread_id}] Export completed')
                return (mod_number, True, mod_name, None)
            with log_lock:
                patcher.patching_logger.warning(f'[Mod-{mod_number}] [{thread_id}] Export failed for {mod_name}')
            return (mod_number, False, mod_name, 'export failed')
        except Exception as e:
            with log_lock:
                patcher.patching_logger.error(f'[Mod-{mod_number}] [{thread_id}] Exception during export: {e}', exc_info=True)
            return (mod_number, False, mod_name, str(e))
    export_tasks = []
    for idx, mod_data in enumerate(mods_to_export):
        original_idx = mods_to_apply.index(mod_data) if mod_data in mods_to_apply else idx
        mod_number = original_idx + 1
        export_tasks.append((mod_data, idx, original_idx, mod_number))
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_mod = {executor.submit(export_single_mod, task): task for task in export_tasks}
        for future in as_completed(future_to_mod):
            if patcher._cancelled:
                executor.shutdown(wait=False, cancel_futures=True)
                return False
            try:
                mod_number, success, mod_name, error = future.result()
                results[mod_number] = (success, mod_name, error)
                completed_count[0] += 1
                progress = progress_base + int(completed_count[0] / total_mods * export_progress)
                export_msg = ModPatcher._safe_tr('status.exporting_assets', f'Exporting assets from {mod_name} ({completed_count[0]}/{total_mods})...', mod=mod_name, current=completed_count[0], total=total_mods)
                throttler.update_progress(min(progress, 95), export_msg)
                if not success:
                    patcher.patching_logger.error(f'[PARALLEL_EXPORT] Export failed for mod {mod_number} ({mod_name}): {error}')
                    executor.shutdown(wait=True, cancel_futures=False)
                    return False
            except Exception as e:
                patcher.patching_logger.error(f'[PARALLEL_EXPORT] Exception in export task: {e}', exc_info=True)
                executor.shutdown(wait=True, cancel_futures=False)
                return False
    throttler.flush()
    patcher.patching_logger.info(f'[PARALLEL_EXPORT] All {total_mods} mod(s) exported successfully')
    return True


def perform_parallel_filtering(patcher, vanilla_hashes: Dict[str, Dict[str, str]], mods_dirs_info: List[tuple], progress_base: int, filter_progress: int, progress_callback) -> Dict[int, Optional[str]]:
    if not mods_dirs_info:
        return {}
    log_lock = threading.Lock()
    completed_count = [0]
    total_mods = len(mods_dirs_info)
    max_workers = max(1, min(os.cpu_count() - 1, total_mods, 8))
    patcher.patching_logger.info(f'[PARALLEL_FILTER] Starting parallel filtering for {total_mods} mod(s) using {max_workers} worker(s)')
    throttler = ProgressThrottler(progress_callback, throttle_ms=150, parent=patcher)

    def filter_single_mod(mod_info):
        mod_number, mod_objects_dir, mod_name = mod_info
        thread_id = threading.current_thread().ident
        try:
            with log_lock:
                patcher.patching_logger.info(f'[Mod-{mod_number}] [{thread_id}] Starting filtering for {mod_name}')
            filtered_dir = resource_filter.filter_vanilla_identical_resources(vanilla_hashes, mod_objects_dir, mod_number, mod_name, logger=patcher.patching_logger)
            with log_lock:
                if filtered_dir:
                    patcher.patching_logger.info(f'[Mod-{mod_number}] [{thread_id}] Filtering completed, unique resources in {filtered_dir}')
                else:
                    patcher.patching_logger.info(f'[Mod-{mod_number}] [{thread_id}] Filtering completed, no unique resources')
            return (mod_number, filtered_dir, mod_name, None)
        except Exception as e:
            with log_lock:
                patcher.patching_logger.error(f'[Mod-{mod_number}] [{thread_id}] Exception during filtering: {e}', exc_info=True)
            return (mod_number, None, mod_name, str(e))
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_mod = {executor.submit(filter_single_mod, mod_info): mod_info for mod_info in mods_dirs_info}
        for future in as_completed(future_to_mod):
            if patcher._cancelled:
                executor.shutdown(wait=False, cancel_futures=True)
                return {}
            try:
                mod_number, filtered_dir, mod_name, error = future.result()
                results[mod_number] = filtered_dir
                completed_count[0] += 1
                progress = progress_base + int(completed_count[0] / total_mods * filter_progress)
                filter_msg = ModPatcher._safe_tr('status.filtering_resources', f'Filtering resources from {mod_name} ({completed_count[0]}/{total_mods})...', mod=mod_name, current=completed_count[0], total=total_mods)
                throttler.update_progress(min(progress, 95), filter_msg)
                if error:
                    patcher.patching_logger.warning(f'[PARALLEL_FILTER] Filtering warning for mod {mod_number} ({mod_name}): {error}')
            except Exception as e:
                patcher.patching_logger.error(f'[PARALLEL_FILTER] Exception in filtering task: {e}', exc_info=True)
                executor.shutdown(wait=True, cancel_futures=False)
                return {}
    throttler.flush()
    patcher.patching_logger.info(f'[PARALLEL_FILTER] All {total_mods} mod(s) filtered successfully')
    return results
