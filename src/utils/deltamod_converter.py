import os
import json
import re
import shutil
import uuid
import logging
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any
from managers.localization_manager import tr


class DeltamodConverter:

    def __init__(self, source_path: str, mods_dir: str):
        self.source_path = source_path
        self.mods_dir = mods_dir
        self.deltamod_info: Dict[str, Any] = {}
        self.modding_xml: Optional[ET.Element] = None

    def convert(self) -> Optional[str]:
        try:
            if not self._validate_source():
                return None
            config_data = self._generate_config_json()
            if not config_data:
                return None
            mod_key = config_data['mod_key']
            target_mod_dir = os.path.join(self.mods_dir, mod_key)
            if os.path.exists(target_mod_dir):
                shutil.rmtree(target_mod_dir)
            os.makedirs(target_mod_dir)
            self._process_files(target_mod_dir)
            config_path = os.path.join(target_mod_dir, 'config.json')
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=4, ensure_ascii=False)
            logging.info(f"Deltamod converted: {config_data.get('name')} → {target_mod_dir}")
            return target_mod_dir
        except Exception as e:
            logging.error(f'Deltamod conversion failed: {e}')
            return None

    def _validate_source(self) -> bool:
        info_path = os.path.join(self.source_path, '_deltamodInfo.json')
        xml_path = os.path.join(self.source_path, 'modding.xml')
        if not os.path.exists(info_path):
            return False
        if not os.path.exists(xml_path):
            return False
        try:
            with open(info_path, 'r', encoding='utf-8') as f:
                self.deltamod_info = json.load(f)
        except Exception:
            return False
        try:
            self.modding_xml = ET.parse(xml_path).getroot()
        except ET.ParseError:
            try:
                with open(xml_path, 'r', encoding='utf-8') as f:
                    xml_content = f.read().strip()
                if not xml_content.startswith('<?xml'):
                    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n<patches>\n' + xml_content + '\n</patches>'
                else:
                    xml_lines = xml_content.split('\n', 1)
                    xml_content = xml_lines[0] + '\n<patches>\n' + xml_lines[1] + '\n</patches>'
                self.modding_xml = ET.fromstring(xml_content)
            except Exception:
                self.modding_xml = None
        except Exception:
            self.modding_xml = None
        return True

    def _generate_config_json(self) -> Optional[Dict[str, Any]]:
        if not self.deltamod_info or self.modding_xml is None:
            return None
        patches = []
        if self.modding_xml.tag == 'patch':
            patches.append(self.modding_xml)
        else:
            patches.extend(self.modding_xml.findall('patch'))
        meta = self.deltamod_info.get('metadata', {})
        package_id = meta.get('packageID', '')
        if package_id and package_id != 'und.und.und':
            mod_key = package_id.replace('.', '_')
        else:
            mod_key = f"local_{meta.get('name', 'unnamed')}_{uuid.uuid4().hex[:8]}"
        from datetime import datetime
        created_date = datetime.now().strftime('%d.%m.%y %H:%M')
        has_xdelta = any((p.get('type') == 'xdelta' for p in patches))
        config = {'is_local_mod': True, 'mod_key': mod_key, 'created_date': created_date, 'is_available_on_server': False, 'name': meta.get('name', tr('defaults.local_mod')), 'version': meta.get('version', '1.0.0'), 'author': ', '.join(meta.get('author', [tr('defaults.unknown')])), 'tagline': meta.get('description', tr('defaults.no_description')), 'external_url': meta.get('url', ''), 'game_version': self.deltamod_info.get('deltaruneTargetVersion', tr('defaults.not_specified')), 'modgame': 'deltarunedemo' if meta.get('demoMod') else 'deltarune', 'is_xdelta': has_xdelta, 'files': self._generate_files_structure(patches), 'tags': meta.get('tags', [])}
        return config

    def _generate_files_structure(self, patches: list) -> Dict[str, Any]:
        files_structure = {}
        if self.modding_xml is None:
            return {}
        for patch in patches:
            to_path = patch.get('to', '')
            patch_file = patch.get('patch', '')
            patch_type = patch.get('type', '')
            chapter_key = None
            if 'demo' in to_path:
                chapter_key = 'demo'
            else:
                match = re.search('chapter(\\d+)', to_path, re.IGNORECASE)
                if match:
                    chapter_num = int(match.group(1))
                    if chapter_num > 0:
                        chapter_key = str(chapter_num)
            if not chapter_key:
                continue
            if chapter_key not in files_structure:
                files_structure[chapter_key] = {}
            if patch_type == 'xdelta':
                files_structure[chapter_key]['data_file_url'] = os.path.basename(patch_file)
                files_structure[chapter_key]['data_file_version'] = self.deltamod_info.get('metadata', {}).get('version', '1.0.0')
            elif patch_type == 'override':
                if 'extra_files' not in files_structure[chapter_key]:
                    files_structure[chapter_key]['extra_files'] = {}
                group_key = os.path.splitext(os.path.basename(patch_file))[0]
                if group_key not in files_structure[chapter_key]['extra_files']:
                    files_structure[chapter_key]['extra_files'][group_key] = []
                files_structure[chapter_key]['extra_files'][group_key].append(os.path.basename(patch_file))
        return files_structure

    def _process_files(self, target_mod_dir: str) -> None:
        if self.modding_xml is None:
            return
        patches = []
        if self.modding_xml.tag == 'patch':
            patches.append(self.modding_xml)
        else:
            patches.extend(self.modding_xml.findall('patch'))
        icon_path = os.path.join(self.source_path, '_icon.png')
        if os.path.exists(icon_path):
            shutil.copy2(icon_path, os.path.join(target_mod_dir, '_icon.png'))
        for patch in patches:
            to_path = patch.get('to', '')
            patch_file_rel = patch.get('patch', '').lstrip('./')
            patch_file_abs = os.path.join(self.source_path, patch_file_rel)
            if not os.path.exists(patch_file_abs):
                continue
            chapter_key = None
            if 'demo' in to_path:
                chapter_key = 'demo'
            else:
                match = re.search('chapter(\\d+)', to_path, re.IGNORECASE)
                if match:
                    chapter_num = int(match.group(1))
                    if chapter_num > 0:
                        chapter_key = f'chapter_{chapter_num}'
            if not chapter_key:
                continue
            target_chapter_dir = os.path.join(target_mod_dir, chapter_key)
            os.makedirs(target_chapter_dir, exist_ok=True)
            shutil.copy2(patch_file_abs, os.path.join(target_chapter_dir, os.path.basename(patch_file_abs)))
